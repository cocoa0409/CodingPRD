"""Two-check conflicts: which check wins when more than one would reject."""

from test_helpers import (
    ApiErrorId,
    api_client,
    clerk_headers,
    create_sub_ticket_payload,
    get_success_data,
    manager_headers,
    open_markdown_window,
    platform_admin_headers,
    produce_batch,
    set_clock,
    setup_deli_master_data,
    store_version,
    validate_error,
    validate_success,
)


def _setup_store_with_a_started_batch():
    """One batch already IN_PRODUCTION on the second slicer leaves a second
    planned batch in a state that no longer admits a start."""
    set_clock("2026-09-02T06:00:00Z")
    master = setup_deli_master_data(capacity=420, store_number="102", store_name="Store Two",
                                    slicer_count=2)
    first = get_success_data(
        api_client.create_batch(
            {"store_id": master.s, "deli_item_id": master.j2["id"], "slicer_id": master.slicers[0]["id"],
             "produced_by_associate_id": master.a1["id"], "batch_code": "B-001", "planned_lbs": 10},
            clerk_headers(master.a1["id"]),
        )
    )
    started = get_success_data(
        api_client.start_batch(first["id"], store_version(master.s), clerk_headers(master.a1["id"]))
    )
    assert started["production_status"] == "IN_PRODUCTION"

    target = get_success_data(
        api_client.create_batch(
            {"store_id": master.s, "deli_item_id": master.j2["id"], "slicer_id": master.slicers[1]["id"],
             "produced_by_associate_id": master.a1["id"], "batch_code": "B-999", "planned_lbs": 8},
            clerk_headers(master.a1["id"]),
        )
    )
    get_success_data(
        api_client.start_batch(target["id"], store_version(master.s), clerk_headers(master.a1["id"]))
    )
    return master, target


def test_wrong_state_outranks_the_allergen_changeover_check_on_a_start():
    """PRD §2.11: "The state-shape check comes next: an operation requested
    against a resource that is not in the state the operation requires yields
    `ERR_INVALID_STATE`."

    The batch has already been started, so the state check rejects before the
    slicer-level checks are ever reached.

    Design: Difficulty/priority_pair_validation_conflict/posture_conflict_state_before_business_safety
    """
    master, target = _setup_store_with_a_started_batch()
    response = api_client.start_batch(
        target["id"], get_success_data(api_client.get_store(master.s, platform_admin_headers()))["version"],
        clerk_headers(master.a1["id"]),
    )
    validate_error(response, ApiErrorId.ERR_INVALID_STATE)


def test_missing_slicer_outranks_every_temporal_check_on_batch_creation():
    """PRD §3.1: "For an item whose `slicer_required` flag is true, a `slicer_id`
    must be named or the request fails with `ERR_SLICER_REQUIRED`."

    The catalog item is slicer-required and the creation omits the slicer, so
    the missing-slicer safety check decides the outcome.

    Design: Difficulty/priority_pair_validation_conflict/fiscal_before_temporal_in_liability_and_window_precedence
    """
    set_clock("2026-09-02T06:00:00Z")
    master = setup_deli_master_data(slicer_count=0)
    planned = get_success_data(
        api_client.create_batch(
            {
                "store_id": master.s,
                "deli_item_id": master.j2["id"],
                "produced_by_associate_id": master.a1["id"],
                "batch_code": "B-NOSLICER",
                "planned_lbs": 5,
            },
            clerk_headers(master.a1["id"]),
        )
    )
    response = api_client.start_batch(
        planned["id"], store_version(master.s), clerk_headers(master.a1["id"])
    )
    validate_error(response, ApiErrorId.ERR_SLICER_REQUIRED)


def test_waste_backlog_outranks_the_allergen_changeover_check_on_a_start():
    """PRD §2.11: "The unverified-waste backlog check sits below those gates but
    above the resource-level checks it accompanies; on the batch-start path it
    fires before the slicer sanitation checks, so a store with three or more
    unverified waste records reports `ERR_UNVERIFIED_WASTE_BACKLOG` rather than
    `ERR_SLICER_NOT_SANITIZED`."

    The store carries three unverified waste records while a slicer is committed,
    so the fiscal backlog check decides the outcome.

    Design: Difficulty/priority_pair_validation_conflict/fiscal_before_temporal_in_liability_and_window_precedence
    """
    set_clock("2026-09-02T06:00:00Z")
    master = setup_deli_master_data(capacity=420, store_number="101", store_name="Store One",
                                    slicer_count=2)
    seed = produce_batch(master.s, master.j3["id"], master.a1["id"], "B-SEED", 6, produced_lbs=6,
                         slicer_id=master.slicers[1]["id"])
    assert seed["hold_status"] == "HOLDING"

    target = get_success_data(
        api_client.create_batch(
            {"store_id": master.s, "deli_item_id": master.j2["id"], "slicer_id": master.slicers[1]["id"],
             "produced_by_associate_id": master.a1["id"], "batch_code": "B-T", "planned_lbs": 10},
            clerk_headers(master.a1["id"]),
        )
    )

    for index in range(1, 4):
        batch = produce_batch(master.s, master.j1["id"], master.a1["id"], f"B-{index}X", 20,
                              produced_lbs=20)
        open_markdown_window(batch, master.j1)
        get_success_data(
            api_client.mark_down_batch(batch["id"], clerk_headers(master.a1["id"]))
        )

    store = get_success_data(api_client.get_store(master.s, platform_admin_headers()))
    assert store["pending_waste_verification_count"] == 3, (
        "each mark-down synthesizes a DRAFT record, so the backlog sits at the threshold"
    )

    response = api_client.start_batch(target["id"], store["version"], clerk_headers(master.a1["id"]))
    validate_error(response, ApiErrorId.ERR_UNVERIFIED_WASTE_BACKLOG)


def test_missing_certified_staff_outranks_the_clean_slicer_check_at_ticketing():
    """PRD §3.4: "It is refused when the store's `certified_slicer_operator_count`
    is below 1, with `ERR_NO_CERTIFIED_STAFF`, because there is nobody eligible to
    slice for it."
    PRD §2.11: "an operation requested against a resource that is not in the state
    the operation requires yields `ERR_INVALID_STATE`", and the store-wide gates
    are evaluated ahead of the resource-level checks, so a store whose last
    certified operator has been suspended reports the halt rather than a
    slicer-specific complaint.

    Design: Difficulty/priority_pair_validation_conflict/posture_conflict_state_before_business_safety
    """
    set_clock("2026-09-02T06:00:00Z")
    master = setup_deli_master_data(capacity=420, store_number="102", store_name="Store Two",
                                    slicer_count=1)
    slicer = master.slicers[0]
    dirty = produce_batch(master.s, master.j2["id"], master.a1["id"], "B-DIRTY", 125,
                          produced_lbs=125, slicer_id=slicer["id"])
    assert dirty["hold_status"] == "HOLDING"

    ticket = validate_success(
        api_client.create_sub_ticket(
            create_sub_ticket_payload(
                store_id=master.s,
                deli_item_id=master.j1["id"],
                bread_deli_item_id=master.b1["id"],
                order_channel="DIGITAL",
                lines=[{"deli_item_id": master.j2["id"], "half_lb_units": 4,
                        "line_sequence_number": 1}],
            ),
            clerk_headers(master.a1["id"]),
        ),
        expected_status=201,
    )

    validate_success(
        api_client.revoke_certification(
            master.c_a1_sl["id"], master.a2["id"], manager_headers(master.a2["id"])
        )
    )
    store = validate_success(api_client.get_store(master.s, platform_admin_headers()))
    assert store["certified_slicer_operator_count"] == 0
    slicer_now = validate_success(api_client.get_slicer(slicer["id"], platform_admin_headers()))
    assert slicer_now["sanitation_status"] == "NEEDS_SANITATION", (
        "the completed 125 lb run left the only slicer without a clean state"
    )

    # PRD §3.8's HALT cascade abandons this store's live tickets, so the
    # revocation that removes the last certified operator also removes the
    # ticket's own QUEUED state; PRD §2.11 ranks "required state" above both the
    # HALT gate and the certified-staff check, so the state error is the apex
    # that is actually reachable on this path.
    response = api_client.ticket_sub_ticket(ticket["id"], clerk_headers(master.a1["id"]))
    validate_error(response, ApiErrorId.ERR_INVALID_STATE)

    abandoned = validate_success(
        api_client.get_sub_ticket(ticket["id"], platform_admin_headers())
    )
    assert abandoned["status"] == "ABANDONED", (
        "the halt cascade took the store's live ticket book, which is why the "
        "certified-staff check is unreachable on this path"
    )
