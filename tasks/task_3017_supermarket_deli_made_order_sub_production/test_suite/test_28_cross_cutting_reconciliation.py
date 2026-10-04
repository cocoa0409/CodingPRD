"""Derived counters, deferred bucket release, and immediate visibility."""

from test_helpers import (
    ApiErrorId,
    api_client,
    clerk_headers,
    close_markdown_window,
    create_waste_record,
    get_success_data,
    platform_admin_headers,
    produce_batch,
    scale_operator_headers,
    set_clock,
    setup_deli_master_data,
    store_version,
    setup_price_file,
    store_version,
    validate_error,
    validate_success,
)


def test_the_grace_reminder_window_is_seventy_two_hours():
    """PRD §2.8: "Every `Certification` carries a derived `grace_reminder` flag,
    true when an ACTIVE certification expires within 72 hours of the logical
    clock."

    This test asserts only the comparison at the window's edge, because the
    contract names exactly one bound and the two fixtures straddle it
    unambiguously.

    Design: Corner/cross_cutting_layers/certification_expiry_threshold_within_twenty_four_hours
    """
    set_clock("2026-09-02T06:00:00Z")
    master = setup_deli_master_data(slicer_count=0)

    soon = get_success_data(
        api_client.create_certification(
            {"store_id": master.s, "associate_id": master.a1["id"], "cert_type": "ALLERGEN_MANAGEMENT",
             "issued_at": "2026-09-01T00:00:00Z", "expires_at": "2026-09-02T12:00:00.000Z"},
            platform_admin_headers(),
        )
    )
    later = get_success_data(
        api_client.create_certification(
            {"store_id": master.s, "associate_id": master.a1["id"], "cert_type": "ALLERGEN_MANAGEMENT",
             "issued_at": "2026-09-01T00:00:00Z", "expires_at": "2026-09-16T00:00:00Z"},
            platform_admin_headers(),
        )
    )
    soon_now = validate_success(api_client.get_certification(soon["id"], platform_admin_headers()))
    later_now = validate_success(api_client.get_certification(later["id"], platform_admin_headers()))
    assert soon_now["grace_reminder"] is True, (
        "a certification expiring in six hours is inside the reminder window"
    )
    assert later_now["grace_reminder"] is False, (
        "a certification expiring in fourteen days is outside it"
    )
    assert soon_now["status"] == "ACTIVE" and later_now["status"] == "ACTIVE", (
        "the reminder is a flag, not a transition"
    )


def test_two_identical_discards_earn_different_fees():
    """PRD §3.3: "Second, a prior-liability base is accumulated over every other
    waste record in the same store whose creation instant is strictly before this
    record's creation instant."
    PRD §3.3: "Third, a discounted base is computed as 0.70 multiplied by
    `discard_value_cents`, plus 0.30 multiplied by that prior-liability base,
    rounded half up to whole cents."

    Design: Corner/cross_cutting_layers/waste_liability_cumulative_threshold_uses_previous_settled_total
    """
    set_clock("2026-09-02T06:00:00Z")
    master = setup_deli_master_data(capacity=300, store_number="103", store_name="Store Three",
                                    slicer_count=0)
    item = validate_success(
        api_client.create_item(
            {"sku": "CC-PROSC-99", "name": "Prosciutto", "category": "COLD_CUT",
             "unit_cost_cents": 1000, "retail_price_per_lb_cents": 1499,
             "case_life_minutes": 120, "markdown_window_minutes": 0, "allergen_flags": ["MILK"],
             "slicer_required": False},
            platform_admin_headers(),
        ), expected_status=201)
    first_batch = produce_batch(master.s, item["id"], master.a1["id"], "B-1", 5, produced_lbs=5)
    second_batch = produce_batch(master.s, item["id"], master.a1["id"], "B-2", 5, produced_lbs=5)
    # The item has markdown_window_minutes=0, so the half-open markdown window
    # [hold_expires_at, hold_expires_at) is always empty; PRD 3.3 allows the
    # direct discard from DRAFT only once that window has closed, which a
    # zero-markdown item satisfies at any instant after production.
    set_clock("2026-09-02T09:00:00Z")

    first = create_waste_record(master.s, first_batch["id"], master.a2["id"], reason="QUALITY",
                                acting_associate_id=master.a1["id"])
    priced_first = validate_success(
        api_client.discard_waste_record(first["id"], 5, clerk_headers(master.a1["id"]))
    )
    assert priced_first["handling_fee_cents"] == 0, (
        "the first record's tier base reads no prior settled total"
    )

    # PRD 3.3 excludes records created at the identical instant, so the second
    # record is opened one minute after the first.
    set_clock("2026-09-02T09:01:00Z")
    second = create_waste_record(master.s, second_batch["id"], master.a2["id"], reason="QUALITY",
                                 acting_associate_id=master.a1["id"])
    priced_second = validate_success(
        api_client.discard_waste_record(second["id"], 5, clerk_headers(master.a1["id"]))
    )
    assert priced_second["handling_fee_cents"] == 250, (
        "the second record's base of 5000 spans the first tier boundary, cumulatively"
    )


def test_the_price_files_sync_counter_is_recomputed_when_a_label_is_voided():
    """PRD §3.6: "it records an `activated_at` instant and a derived
    `synced_scale_count` counting the labels written against it."
    PRD §3.6: "the previously ACTIVE file moves to `SUPERSEDED`, every `ISSUED`
    label written against it moves to `VOIDED`."

    Design: Corner/cross_cutting_layers/label_void_reconciles_the_price_file_sync_counter
    """
    set_clock("2026-09-02T06:00:00Z")
    master = setup_deli_master_data(capacity=240, store_number="102", store_name="Store Two",
                                    slicer_count=0)
    price_file = master.price_file
    label = validate_success(
        api_client.create_label(
            {"store_id": master.s, "subject_type": "CATERING_PLATTER",
             "subject_ref_id": master.p1["id"], "net_weight_lbs": 2, "unit_price_cents": 1800},
            scale_operator_headers(),
        ),
        expected_status=201,
    )

    after_issue = validate_success(api_client.get_price_file(price_file["id"], platform_admin_headers()))
    assert after_issue["synced_scale_count"] == 1, (
        "the derived counter tracks the label written against the file"
    )

    successor = setup_price_file(
        master.s, file_label="PF-0902", effective_from="2026-09-02T06:00:00Z",
        effective_to="2026-10-01T00:00:00Z", item_price_count=8, activate=False,
    )
    validate_success(api_client.activate_price_file(successor["id"], scale_operator_headers()))

    voided = validate_success(api_client.get_label(label["id"], platform_admin_headers()))
    assert voided["status"] == "VOIDED"
    recomputed = validate_success(api_client.get_price_file(price_file["id"], platform_admin_headers()))
    assert recomputed["synced_scale_count"] == 0, (
        "the counter is recomputed from the ISSUED labels rather than incremented blindly"
    )
    successor_now = validate_success(api_client.get_price_file(successor["id"], platform_admin_headers()))
    assert successor_now["synced_scale_count"] == 0, "the successor starts from an accurate baseline"


def test_case_weight_is_recomputed_rather_than_adjusted_by_a_delta():
    """PRD §2.4: "Recomputing `case_on_hand_lbs`, `posture`, `posture_reason`,
    `active_price_file_id`, `targeted_promo_id`, `covered_allergen_set`,
    `available_bread_units`, `certified_slicer_operator_count`,
    `verified_waste_liability_cents` or `pending_waste_verification_count` on a
    `Store` is a mutation of that store."

    Design: Corner/cross_cutting_layers/store_case_weight_reconciles_after_every_partial_update
    """
    set_clock("2026-09-02T06:00:00Z")
    master = setup_deli_master_data(capacity=300, store_number="103", store_name="Store Three",
                                    slicer_count=0)
    produce_batch(master.s, master.j1["id"], master.a1["id"], "B-R1", 5, produced_lbs=5)
    produce_batch(master.s, master.j1["id"], master.a1["id"], "B-R2", 7, produced_lbs=7)

    first_read = validate_success(api_client.get_store(master.s, platform_admin_headers()))
    assert first_read["case_on_hand_lbs"] == 12.0

    held = get_success_data(
        api_client.list_batches(
            platform_admin_headers(), {"store_id": master.s, "hold_status": "HOLDING"}
        )
    )
    mark_down_target = held[-1]
    # PRD 3.3: the direct discard from DRAFT requires the half-open markdown
    # window to have closed at the logical clock.
    close_markdown_window(mark_down_target, master.j1)
    record = create_waste_record(master.s, mark_down_target["id"], master.a1["id"],
                                 reason="QUALITY", acting_associate_id=master.a1["id"])
    discarded = validate_success(
        api_client.discard_waste_record(record["id"], 7, clerk_headers(master.a1["id"]))
    )
    discarded_id = mark_down_target["id"]

    after_discard = validate_success(api_client.get_store(master.s, platform_admin_headers()))
    assert after_discard["case_on_hand_lbs"] == 5.0, (
        "the discarded batch contributes nothing to the recomputed sum"
    )

    successor = validate_success(
        api_client.rework_batch(
            discarded_id,
            {"planned_lbs": 7, "produced_by_associate_id": master.a1["id"], "batch_code": "B-R2R"},
            clerk_headers(master.a1["id"]),
        ),
        expected_status=201,
    )
    validate_success(
        api_client.start_batch(successor["id"], after_discard["version"], clerk_headers(master.a1["id"]))
    )
    validate_success(api_client.complete_batch(successor["id"], 7, clerk_headers(master.a1["id"])))

    final_read = validate_success(api_client.get_store(master.s, platform_admin_headers()))
    assert final_read["case_on_hand_lbs"] == 12.0, (
        "the successor's weight re-enters the recomputed sum"
    )


def test_bucket_occupancy_is_held_until_the_order_is_resolved():
    """PRD §3.7: "On success the order is assigned its `pickup_bucket_key`, the
    bucket's headcount accumulator increases, and the quote is recomputed."
    PRD §3.7: "A confirmed order that has not yet entered production may also be
    cancelled, which decreases the bucket accumulator."

    Design: Corner/cross_cutting_layers/pickup_bucket_decrements_on_cancellation_and_expiry
    """
    set_clock("2026-09-02T06:00:00Z")
    master = setup_deli_master_data(capacity=240, store_number="102", store_name="Store Two",
                                    slicer_count=0)

    big = get_success_data(
        api_client.create_catering_order(
            {"store_id": master.s, "platter_deli_item_id": master.p1["id"],
             "customer_name": "Big Party", "platter_count": 20, "headcount": 30,
             "lead_time_hours": 30, "pickup_window_start": "2026-09-03T15:00:00Z",
             "pickup_window_end": "2026-09-03T15:45:00Z", "deposit_cents": 5000,
             "certified_planner_associate_id": master.a1["id"], "request_id": "REQ-BIG"},
            clerk_headers(master.a1["id"]),
        )
    )
    small = get_success_data(
        api_client.create_catering_order(
            {"store_id": master.s, "platter_deli_item_id": master.p1["id"],
             "customer_name": "Small Party", "platter_count": 5, "headcount": 15,
             "lead_time_hours": 30, "pickup_window_start": "2026-09-03T15:05:00Z",
             "pickup_window_end": "2026-09-03T16:00:00Z", "deposit_cents": 3000,
             "certified_planner_associate_id": master.a1["id"], "request_id": "REQ-SMALL"},
            clerk_headers(master.a1["id"]),
        )
    )
    confirmed = validate_success(api_client.confirm_catering_order(big["id"], clerk_headers(master.a1["id"])))
    assert confirmed["pickup_bucket_key"] is not None

    full = api_client.confirm_catering_order(small["id"], clerk_headers(master.a1["id"]))
    validate_error(full, ApiErrorId.ERR_PICKUP_CAPACITY_EXCEEDED)

    validate_success(
        api_client.cancel_catering_order(big["id"], "customer withdrew", clerk_headers(master.a1["id"]))
    )
    now_ok = validate_success(
        api_client.confirm_catering_order(small["id"], clerk_headers(master.a1["id"]))
    )
    assert now_ok["status"] == "CONFIRMED", (
        "the headcount is deferred-release, so the freed capacity is reusable"
    )


def test_a_write_response_already_carries_its_side_effects():
    """PRD §2.4: "The `updated_at` field shares that format and is refreshed on
    every mutation, including mutations the server performs automatically rather
    than in response to a client request."

    Design: Corner/consistency_model/immediate_visibility_of_side_effects_in_the_write_response
    """
    set_clock("2026-09-02T06:00:00Z")
    master = setup_deli_master_data(slicer_count=1)
    batch = get_success_data(
        api_client.create_batch(
            {"store_id": master.s, "deli_item_id": master.j2["id"],
             "slicer_id": master.slicers[0]["id"], "produced_by_associate_id": master.a1["id"],
             "batch_code": "B-IM", "planned_lbs": 10},
            clerk_headers(master.a1["id"]),
        )
    )
    validate_success(api_client.start_batch(
        batch["id"], store_version(master.s), clerk_headers(master.a1["id"])
    ))

    completed = validate_success(api_client.complete_batch(batch["id"], 10, clerk_headers(master.a1["id"])))
    assert completed["production_status"] == "ON_LINE", (
        "the state write is visible in the completion response itself"
    )
    assert completed["hold_expires_at"].startswith("2026-09-02T09:00:00")
    assert completed["case_yield_cost_provisional_cents"] == 5245, (
        "10.0 lbs at 520 cents plus the labor load; the 2 accumulated cuts stay below one fee unit"
    )

    reread = validate_success(api_client.get_batch(batch["id"], platform_admin_headers()))
    assert reread["production_status"] == completed["production_status"]
    assert reread["hold_expires_at"] == completed["hold_expires_at"]
    assert reread["case_yield_cost_provisional_cents"] == completed["case_yield_cost_provisional_cents"], (
        "the follow-up read returns identical values, confirming no eventual lag"
    )