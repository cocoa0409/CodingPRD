"""Computed reads and the production-day sweep."""

from test_helpers import (
    api_client,
    clerk_headers,
    create_catering_order_payload,
    create_sub_ticket_payload,
    get_success_data,
    manager_headers,
    platform_admin_headers,
    produce_batch,
    scale_operator_headers,
    set_clock,
    setup_deli_master_data,
    store_version,
    setup_price_file,
    store_version,
    validate_success,
)


def test_posture_report_agrees_with_the_store_row_it_summarises():
    """PRD §2.6: "it is computed from the store's own counters and flags, and it
    is recomputed on any change to the store's protection index,
    `certified_slicer_operator_count`, `case_on_hand_lbs`, `active_price_file_id`
    or `haccp_safety_flag`."

    Design: Corner/endpoints/posture_report_is_a_computed_read_consistent_with_store_row
    """
    set_clock("2026-09-02T06:00:00Z")
    master = setup_deli_master_data(capacity=300, store_number="103", store_name="Store Three",
                                    slicer_count=1)
    produce_batch(master.s, master.j2["id"], master.a1["id"], "B-C", 125, produced_lbs=125,
                  slicer_id=master.slicers[0]["id"])

    store = validate_success(api_client.get_store(master.s, platform_admin_headers()))
    report = validate_success(api_client.get_posture_report(master.s, platform_admin_headers()))
    assert report["posture"] == store["posture"]
    assert report["posture_reason"] == store["posture_reason"]
    # PRD §2.7: base 100 less 12 per ACTIVE associate holding no live
    # SLICER_OPERATION certification, less 6 per live waste record, less 4 per
    # slicer awaiting sanitation, clamped at a floor of zero.
    needs_sanitation = validate_success(
        api_client.list_slicers(
            platform_admin_headers(), {"store_id": master.s, "sanitation_status": "NEEDS_SANITATION"}
        )
    )
    associates = validate_success(
        api_client.list_associates(platform_admin_headers(), {"store_id": master.s})
    )
    live_slicer_holders = set()
    for associate in associates:
        certs = validate_success(
            api_client.list_certifications(
                platform_admin_headers(),
                {"associate_id": associate["id"], "cert_type": "SLICER_OPERATION", "status": "ACTIVE"},
            )
        )
        if certs:
            live_slicer_holders.add(associate["id"])
    lapsed = sum(1 for a in associates
                 if a["status"] == "ACTIVE" and a["id"] not in live_slicer_holders)
    live_waste = store["pending_waste_verification_count"]
    expected = max(0, 100 - 12 * lapsed - 6 * live_waste - 4 * len(needs_sanitation))
    assert report["protection_index"] == expected, (
        "the index sums PRD 2.7's three counted sets against the base of 100"
    )
    assert report["diffusion_index"] == 100 - report["protection_index"]
    assert report["certified_slicer_operator_count"] == store["certified_slicer_operator_count"]
    assert report["newest_completed_ticket_lateness_minutes"] == 0


def test_the_active_price_file_read_treats_the_upper_bound_as_exclusive():
    """PRD §3.6: "The candidate set is every price file belonging to the store
    whose status is `ACTIVE` and whose half-open interval contains the logical
    clock, with `effective_from` inclusive and `effective_to` exclusive."
    PRD §3.6: "When the candidate set is empty the store's `active_price_file_id`
    is null, every label-generating call returns `ERR_PRICE_FILE_STALE` at status
    409, and the store's posture reason becomes `NO_ACTIVE_PRICE_FILE`."

    Design: Corner/endpoints/active_price_file_read_resolves_by_half_open_interval
    """
    set_clock("2026-09-02T06:00:00Z")
    # This scenario manages its own half-open interval, so it opts out of the
    # fixture's default price file.
    master = setup_deli_master_data(capacity=240, store_number="102", store_name="Store Two",
                                    slicer_count=0, with_price_file=False)
    price_file = setup_price_file(
        master.s, file_label="PF-0901",
        effective_from="2026-09-01T00:00:00Z", effective_to="2026-09-15T00:00:00Z",
    )

    set_clock("2026-09-14T23:59:59Z")
    inside = validate_success(api_client.get_active_price_file(master.s, scale_operator_headers()))
    assert inside["id"] == price_file["id"]

    set_clock("2026-09-15T00:00:00Z")
    api_client.get_active_price_file(master.s, scale_operator_headers())
    store = validate_success(api_client.get_store(master.s, platform_admin_headers()))
    assert store["active_price_file_id"] is None, (
        "the clock at exactly effective_to sits outside the half-open interval"
    )
    report = validate_success(api_client.get_posture_report(master.s, platform_admin_headers()))
    assert report["posture_reason"] == "NO_ACTIVE_PRICE_FILE"


def test_each_production_day_checkpoint_advances_the_counter_and_sweeps_lapses():
    """PRD §3.1: "Incrementing the store's `ops_run_index` production-day counter
    by one and stamping the current logical clock as the store's
    `logical_clock_at_last_run` are the two bookkeeping effects."
    PRD §2.8: "When the logical clock reaches a certification's `expires_at`, the
    certification moves from `ACTIVE` to `EXPIRED` on the next production-day
    sweep."

    Design: Corner/endpoints/run_production_day_advances_the_counter_and_sweeps_laggards
    """
    set_clock("2026-09-02T06:00:00Z")
    master = setup_deli_master_data(slicer_count=0)
    expiring = get_success_data(
        api_client.create_certification(
            {"store_id": master.s, "associate_id": master.a3["id"], "cert_type": "SLICER_OPERATION",
             "issued_at": "2026-09-01T00:00:00Z", "expires_at": "2026-09-02T00:00:00Z"},
            platform_admin_headers(),
        )
    )

    first = validate_success(
        api_client.run_production_day_for_store(master.s, manager_headers(master.a2["id"]))
    )
    assert first["ops_run_index"] == 1
    assert first["logical_clock_at_last_run"].startswith("2026-09-02T06:00:00"), (
        "the stamp is the logical clock, not wall-clock time"
    )
    lapsed = validate_success(api_client.get_certification(expiring["id"], platform_admin_headers()))
    assert lapsed["status"] == "EXPIRED"

    second = validate_success(
        api_client.run_production_day_for_store(master.s, manager_headers(master.a2["id"]))
    )
    assert second["ops_run_index"] == 2
    assert second["certified_slicer_operator_count"] == 1, "A1's certification is still valid"


def test_completing_a_batch_exposes_its_four_side_effects():
    """PRD §3.1: "On success the batch's `produced_at` is stamped from the logical
    clock and its `hold_expires_at` is computed as the produced instant plus the
    item's `case_life_minutes`."
    PRD §3.1: "The slicer is left needing attention: its `sanitation_status` moves
    to `NEEDS_SANITATION`, its `last_sliced_deli_item_id` records the item just
    sliced, and its `cuts_since_sanitation` counter is incremented by the produced
    weight in pounds divided by five, rounded up to a whole number of cuts."

    Design: Corner/endpoints/batch_completion_side_effects_are_observable_individually
    """
    set_clock("2026-09-02T06:00:00Z")
    master = setup_deli_master_data(slicer_count=1)
    slicer = master.slicers[0]
    batch = get_success_data(
        api_client.create_batch(
            {"store_id": master.s, "deli_item_id": master.j2["id"], "slicer_id": slicer["id"],
             "produced_by_associate_id": master.a1["id"], "batch_code": "B-C", "planned_lbs": 16},
            clerk_headers(master.a1["id"]),
        )
    )
    validate_success(api_client.start_batch(
        batch["id"], store_version(master.s), clerk_headers(master.a1["id"])
    ))
    completed = validate_success(api_client.complete_batch(batch["id"], 16, clerk_headers(master.a1["id"])))

    assert completed["hold_expires_at"].startswith("2026-09-02T09:00:00"), (
        "the 180 minute case life runs from the produced instant"
    )
    assert completed["case_yield_cost_provisional_cents"] == 8365, (
        "the labor load and one slicer fee unit for the 4 accumulated cuts enter the cost"
    )

    slicer_now = validate_success(api_client.get_slicer(slicer["id"], platform_admin_headers()))
    assert slicer_now["sanitation_status"] == "NEEDS_SANITATION"
    assert slicer_now["cuts_since_sanitation"] == 4
    assert slicer_now["last_sliced_deli_item_id"] == master.j2["id"]

    store = validate_success(api_client.get_store(master.s, platform_admin_headers()))
    assert store["case_on_hand_lbs"] == 16.0


def test_cancelling_a_ready_catering_order_synthesizes_an_excluded_waste_record():
    """PRD §3.3: "Cancelling a catered platter after it has been marked ready
    synthesizes an unclaimed-platter waste record against the platter's batch;
    because that record's `reason` is `UNCLAIMED_PLATTER`, it is excluded from
    both store-level liability sums by construction."

    Design: Corner/endpoints/catering_cancel_from_ready_synthesizes_an_excluded_waste_record
    """
    set_clock("2026-09-02T06:00:00Z")
    master = setup_deli_master_data(capacity=240, store_number="102", store_name="Store Two",
                                    slicer_count=0)
    # PRD §3.7 synthesizes the unclaimed-platter record "against the platter's
    # batch", so the platter must have been produced.
    produce_batch(master.s, master.p1["id"], master.a1["id"], "B-PLAT", 2, produced_lbs=2)
    order = get_success_data(
        api_client.create_catering_order(
            create_catering_order_payload(
                store_id=master.s, platter_deli_item_id=master.p1["id"],
                customer_name="Ready Party", certified_planner_associate_id=master.a1["id"],
                request_id="REQ-READY",
            ),
            clerk_headers(master.a1["id"]),
        )
    )
    validate_success(api_client.confirm_catering_order(order["id"], clerk_headers(master.a1["id"])))
    validate_success(api_client.start_catering_production(order["id"], clerk_headers(master.a1["id"])))
    # PRD §3.7: marking ready requires the clock to sit within two hours of the
    # pickup window start.
    set_clock("2026-09-03T13:30:00Z")
    validate_success(api_client.mark_catering_ready(order["id"], clerk_headers(master.a1["id"])))

    cancelled = validate_success(
        api_client.cancel_catering_order(
            order["id"], "customer never collected", manager_headers(master.a2["id"])
        )
    )
    assert cancelled["status"] == "CANCELLED"

    records = api_client.list_waste_records(
        manager_headers(master.a2["id"]), {"store_id": master.s, "reason": "UNCLAIMED_PLATTER"}
    )
    rows = records.json()["data"]
    assert len(rows) == 1, "exactly one synthesized record was created by the cancellation"
    assert rows[0]["reason"] == "UNCLAIMED_PLATTER"

    store = validate_success(api_client.get_store(master.s, platform_admin_headers()))
    assert store["verified_waste_liability_cents"] == 0, (
        "the unclaimed-platter row cannot inflate the deli waste liability"
    )

    labels = api_client.list_labels(
        manager_headers(master.a2["id"]), {"store_id": master.s, "subject_type": "CATERING_PLATTER"}
    )
    assert len(labels.json()["data"]) == 1, (
        "marking the order ready issued the platter's weight label"
    )


def test_the_sub_queue_ranks_only_the_gate_eligible_set():
    """PRD §3.4: "The derived queue is the store's live workload view. A ticket is
    gate-eligible when its fulfillment status is `TICKETED` or `IN_PROGRESS` and
    its bread status is `QUEUED` simultaneously. The eligible set is ranked by
    `promised_at` ascending, with `creation_sequence` ascending as the tie-break."

    Design: Corner/endpoints/bulk_queue_read_ranks_the_eligible_set_only
    """
    set_clock("2026-09-02T06:00:00Z")
    master = setup_deli_master_data(capacity=600, store_number="102", store_name="Store Two",
                                    slicer_count=2, clerk_allergy_set=("MILK", "WHEAT"))
    price_file = master.price_file
    produce_batch(master.s, master.j2["id"], master.a1["id"], "B-001", 30, produced_lbs=30,
                  slicer_id=master.slicers[0]["id"])

    tickets = [
        get_success_data(
            api_client.create_sub_ticket(
                create_sub_ticket_payload(
                    store_id=master.s, deli_item_id=master.j1["id"],
                    bread_deli_item_id=master.b1["id"], order_channel="DIGITAL",
                    lines=[{"deli_item_id": master.j2["id"], "half_lb_units": units,
                            "line_sequence_number": 1}],
                ),
                clerk_headers(master.a1["id"]),
            )
        )
        for units in (2, 4, 6, 2)
    ]
    for ticket in tickets[:3]:
        validate_success(api_client.ticket_sub_ticket(ticket["id"], clerk_headers(master.a1["id"])))

    queue = validate_success(api_client.get_sub_queue(platform_admin_headers(), {"store_id": master.s}))
    assert queue["queue_depth"] == 3
    assert queue["ordered_total_count"] == 3, "the QUEUED ticket is excluded by the gate"

    first = validate_success(api_client.get_sub_ticket(tickets[0]["id"], platform_admin_headers()))
    queued = validate_success(api_client.get_sub_ticket(tickets[3]["id"], platform_admin_headers()))
    assert first["queue_position"] == 1
    assert queued["queue_position"] == 0

def test_activating_a_price_file_remakes_exactly_the_affected_ticket():
    """PRD §2.12: "When a price file is superseded, every ISSUED label written
    against it is voided, and every sub ticket whose label was voided moves to
    `REMADE` — the reverse direction of the ordinary label life, expressed as a
    forward transition to a remake state rather than a reversion of the issued
    label."
    PRD §3.4: "This increments its `remake_count` by one, and the ticket returns to
    `QUEUED` through a fresh fulfillment cycle on the same row rather than as a
    new ticket."

    A second, label-less ticketed ticket in the same store is untouched by the
    cascade, so the remake counts exactly once per affected label.

    Design: Corner/endpoints/sub_ticket_remake_preserves_ticket_number_and_counts_once
    """
    set_clock("2026-09-02T06:00:00Z")
    master = setup_deli_master_data(capacity=600, store_number="102", store_name="Store Two",
                                    slicer_count=2, clerk_allergy_set=("MILK", "WHEAT"))
    first_file = master.price_file
    produce_batch(master.s, master.j2["id"], master.a1["id"], "B-001", 30, produced_lbs=30,
                  slicer_id=master.slicers[0]["id"])

    def make_ticket(pounds_units):
        ticket = get_success_data(
            api_client.create_sub_ticket(
                create_sub_ticket_payload(
                    store_id=master.s, deli_item_id=master.j1["id"],
                    bread_deli_item_id=master.b1["id"], order_channel="DIGITAL",
                    lines=[{"deli_item_id": master.j2["id"], "half_lb_units": pounds_units,
                            "line_sequence_number": 1}],
                ),
                clerk_headers(master.a1["id"]),
            )
        )
        return get_success_data(api_client.ticket_sub_ticket(ticket["id"], clerk_headers(master.a1["id"])))

    completed = make_ticket(2)
    untouched = make_ticket(4)
    completed = validate_success(
        api_client.complete_sub_ticket(completed["id"], 1, clerk_headers(master.a1["id"]))
    )
    label_id = completed["label_id"]
    original_number = completed["ticket_number"]

    successor = setup_price_file(
        master.s, file_label="PF-0902", effective_from="2026-09-02T06:00:00Z",
        effective_to="2026-10-01T00:00:00Z", item_price_count=8, activate=False,
    )
    validate_success(api_client.activate_price_file(successor["id"], scale_operator_headers()))

    label_now = validate_success(api_client.get_label(label_id, platform_admin_headers()))
    remade = validate_success(api_client.get_sub_ticket(completed["id"], platform_admin_headers()))
    assert label_now["status"] == "VOIDED"
    assert remade["status"] == "REMADE"
    assert remade["remake_count"] == 1
    assert remade["ticket_number"] == original_number

    untouched_now = validate_success(api_client.get_sub_ticket(untouched["id"], platform_admin_headers()))
    assert untouched_now["status"] == "TICKETED", (
        "a ticket with no issued label is untouched by the cascade"
    )

    assert validate_success(api_client.get_price_file(first_file["id"], platform_admin_headers()))["status"] == "SUPERSEDED"
    assert validate_success(api_client.get_price_file(successor["id"], platform_admin_headers()))["status"] == "ACTIVE"
