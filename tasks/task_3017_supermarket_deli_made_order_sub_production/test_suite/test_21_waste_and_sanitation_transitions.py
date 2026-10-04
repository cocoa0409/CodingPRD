"""Waste-sequence enforcement and the sanitation-cycle threshold rules."""

from test_helpers import (
    get_success_data,
    ApiErrorId,
    api_client,
    clerk_headers,
    create_waste_record,
    manager_headers,
    open_sanitation_cycle,
    platform_admin_headers,
    produce_batch,
    set_clock,
    setup_deli_master_data,
    validate_error,
    validate_success,
)


def test_discard_is_refused_while_the_markdown_window_is_still_open():
    """PRD §3.3: "A record may be discarded directly from `DRAFT` when the parent
    batch's `hold_status` is `HOLDING` and either the item's
    `markdown_window_minutes` is zero or the half-open markdown window has
    already closed at the logical clock; if the markdown window is still open at
    that moment the direct discard is refused with
    `ERR_MARKDOWN_REQUIRED_BEFORE_DISCARD`."

    Design: Corner/state_machines/waste_record_discard_before_markdown_is_rejected
    """
    set_clock("2026-09-02T06:00:00Z")
    master = setup_deli_master_data(capacity=300, store_number="103", store_name="Store Three",
                                    slicer_count=1)
    batch = produce_batch(master.s, master.j4["id"], master.a1["id"], "B-W", 4, produced_lbs=4,
                          slicer_id=master.slicers[0]["id"])
    assert batch["hold_expires_at"].startswith("2026-09-02T08:00:00")

    set_clock("2026-09-02T07:59:00Z")
    record = create_waste_record(
        master.s, batch["id"], master.a2["id"], reason="QUALITY", acting_associate_id=master.a1["id"]
    )

    response = api_client.discard_waste_record(record["id"], 4, clerk_headers(master.a1["id"]))
    validate_error(response, ApiErrorId.ERR_MARKDOWN_REQUIRED_BEFORE_DISCARD)

    record_now = validate_success(api_client.get_waste_record(record["id"], platform_admin_headers()))
    assert record_now["status"] == "DRAFT", "the rejected transition wrote nothing"
    batch_now = validate_success(api_client.get_batch(batch["id"], platform_admin_headers()))
    assert batch_now["hold_status"] == "HOLDING", (
        "a zero-markdown item is not at issue here; the window is what blocked the discard"
    )


def test_the_producer_cannot_verify_their_own_discard():
    """PRD §3.3: "Verifying requires the `verifier_associate_id` supplied to differ
    both from the batch's `produced_by_associate_id` and from the record's
    `markdown_by_associate_id`; a verifier who was either the producer or the
    marker-down fails with `ERR_SEGREGATION_OF_DUTIES`."

    Design: Corner/state_machines/verification_by_producer_is_rejected_by_segregation
    """
    set_clock("2026-09-02T06:00:00Z")
    master = setup_deli_master_data(capacity=300, store_number="103", store_name="Store Three",
                                    slicer_count=1)
    batch = produce_batch(master.s, master.j4["id"], master.a1["id"], "B-V", 4, produced_lbs=4,
                          slicer_id=master.slicers[0]["id"])
    # j4's markdown window has closed by 06:30, which is what makes the direct
    # discard from DRAFT legal under PRD 3.3.
    set_clock("2026-09-02T08:30:00Z")
    record = create_waste_record(
        master.s, batch["id"], master.a2["id"], reason="QUALITY", acting_associate_id=master.a1["id"]
    )
    validate_success(api_client.discard_waste_record(record["id"], 4, clerk_headers(master.a1["id"])))
    batch_now = validate_success(api_client.get_batch(batch["id"], platform_admin_headers()))

    produced_by_producer = api_client.verify_waste_record(
        record["id"], master.a1["id"], master.c_a1_fh["id"], batch_now["version"],
        manager_headers(master.a2["id"]),
    )
    validate_error(produced_by_producer, ApiErrorId.ERR_SEGREGATION_OF_DUTIES)

    still_discarded = validate_success(
        api_client.get_waste_record(record["id"], platform_admin_headers())
    )
    assert still_discarded["status"] == "DISCARDED"


def test_a_third_distinct_certified_associate_completes_the_verification():
    """PRD §3.3: "The `verified_by_certification_id` must additionally reference a
    `FOOD_HANDLING` certification that is ACTIVE and belongs to the stated
    verifier, or the request fails with `ERR_ASSOCIATE_NOT_CERTIFIED`."

    Design: Corner/state_machines/verification_by_producer_is_rejected_by_segregation
    """
    set_clock("2026-09-02T06:00:00Z")
    master = setup_deli_master_data(capacity=300, store_number="103", store_name="Store Three",
                                    slicer_count=1)
    batch = produce_batch(master.s, master.j4["id"], master.a1["id"], "B-V", 4, produced_lbs=4,
                          slicer_id=master.slicers[0]["id"])
    # j4's markdown window has closed by 06:30, which is what makes the direct
    # discard from DRAFT legal under PRD 3.3.
    set_clock("2026-09-02T08:30:00Z")
    record = create_waste_record(
        master.s, batch["id"], master.a2["id"], reason="QUALITY", acting_associate_id=master.a1["id"]
    )
    validate_success(api_client.discard_waste_record(record["id"], 4, clerk_headers(master.a1["id"])))
    batch_now = validate_success(api_client.get_batch(batch["id"], platform_admin_headers()))

    verified = validate_success(
        api_client.verify_waste_record(
            record["id"], master.a3["id"], master.c_a3_fh["id"], batch_now["version"],
            manager_headers(master.a2["id"]),
        )
    )
    assert verified["status"] == "VERIFIED"
    assert verified["verifier_associate_id"] == master.a3["id"]


def test_halting_the_store_rejects_fresh_work_and_abandons_live_tickets():
    """PRD §2.6: "A store in `HALT` accepts no fresh work at all: creating a sub
    ticket or a production batch is rejected with `ERR_POSTURE_HALT`."
    PRD §3.8: "When the flag is set true, every non-terminal sub ticket in the
    store moves to `ABANDONED` and each abandoned ticket releases its bread
    reserve, exactly as the certification-induced halt does."

    Design: Corner/state_machines/store_halt_blocks_new_production_and_abandons_queued_tickets
    """
    set_clock("2026-09-02T06:00:00Z")
    master = setup_deli_master_data(capacity=600, store_number="102", store_name="Store Two",
                                    slicer_count=2)
    produce_batch(master.s, master.j2["id"], master.a1["id"], "B-001", 30, produced_lbs=30,
                  slicer_id=master.slicers[0]["id"])
    ticket = validate_success(
        api_client.create_sub_ticket(
            {"store_id": master.s, "deli_item_id": master.j1["id"], "bread_deli_item_id": master.b1["id"],
             "order_channel": "DIGITAL",
             "lines": [{"deli_item_id": master.j2["id"], "half_lb_units": 4,
                        "line_sequence_number": 1}]},
            clerk_headers(master.a1["id"]),
        ), expected_status=201)
    validate_success(api_client.ticket_sub_ticket(ticket["id"], clerk_headers(master.a1["id"])))

    gated = validate_success(
        api_client.set_posture_gate(master.s, True, manager_headers(master.a2["id"]))
    )
    assert gated["posture"] == "HALT"
    assert gated["posture_reason"] == "POSTURE_GATE_TRIGGERED"

    fresh = api_client.create_sub_ticket(
        {"store_id": master.s, "deli_item_id": master.j1["id"], "bread_deli_item_id": master.b1["id"],
         "order_channel": "DIGITAL",
         "lines": [{"deli_item_id": master.j2["id"], "half_lb_units": 2, "line_sequence_number": 1}]},
        clerk_headers(master.a1["id"]),
    )
    validate_error(fresh, ApiErrorId.ERR_POSTURE_HALT)

    abandoned = validate_success(api_client.get_sub_ticket(ticket["id"], platform_admin_headers()))
    assert abandoned["status"] == "ABANDONED", "the halt cascade takes the store's live tickets"


def test_discard_carries_the_batch_forward_and_rework_only_follows_a_discard():
    """PRD §3.1: "Reworking a batch is legal only when that batch's `hold_status`
    is already `DISCARDED`; any other state yields `ERR_INVALID_STATE`."
    PRD §3.1: "The discarded row keeps its `DISCARDED` status forever, which
    means the rework loop is an induced cycle running from a batch through its
    waste record and back to a new batch, never a state reversal."

    Design: Corner/state_machines/production_batch_initial_state_and_forward_only_discard
    """
    set_clock("2026-09-02T06:00:00Z")
    master = setup_deli_master_data(capacity=300, store_number="103", store_name="Store Three",
                                    slicer_count=1)
    batch = produce_batch(master.s, master.j4["id"], master.a1["id"], "B-D2", 4, produced_lbs=4,
                          slicer_id=master.slicers[0]["id"])

    premature = api_client.rework_batch(
        batch["id"],
        {"planned_lbs": 4, "produced_by_associate_id": master.a1["id"], "batch_code": "B-D2R"},
        clerk_headers(master.a1["id"]),
    )
    validate_error(premature, ApiErrorId.ERR_INVALID_STATE)

    set_clock("2026-09-02T08:30:00Z")
    record = create_waste_record(
        master.s, batch["id"], master.a2["id"], reason="HOLD_EXPIRED",
        acting_associate_id=master.a1["id"],
    )
    discarded = validate_success(
        api_client.discard_waste_record(record["id"], 4, clerk_headers(master.a1["id"]))
    )
    assert discarded["status"] == "DISCARDED"

    batch_now = validate_success(api_client.get_batch(batch["id"], platform_admin_headers()))
    assert batch_now["hold_status"] == "DISCARDED", (
        "the parent batch discards itself as a direct consequence of the record"
    )

    successor = validate_success(
        api_client.rework_batch(
            batch["id"],
            {"planned_lbs": 4, "produced_by_associate_id": master.a1["id"], "batch_code": "B-D2R"},
            clerk_headers(master.a1["id"]),
        ),
        expected_status=201,
    )
    assert successor["production_status"] == "PLANNED"
    assert successor["rework_of_batch_id"] == batch["id"]

    predecessor = validate_success(api_client.get_batch(batch["id"], platform_admin_headers()))
    assert predecessor["hold_status"] == "DISCARDED", "the predecessor is never restored"


def test_markdown_opens_at_the_inclusive_lower_bound_and_not_before():
    """PRD §3.2: "A `ROUTINE` cycle is due when the slicer's
    `cuts_since_sanitation` is greater than or equal to its
    `sanitation_cycle_limit` — the threshold is inclusive, so a slicer sitting at
    exactly its limit is due."

    The same threshold policy governs the markdown window: the batch enters it
    inclusively at the window's opening instant.

    Design: Corner/state_machines/markdown_window_lower_bound_is_inclusive
    """
    set_clock("2026-09-02T06:00:00Z")
    master = setup_deli_master_data(capacity=300, store_number="103", store_name="Store Three",
                                    slicer_count=1)
    batch = produce_batch(master.s, master.j2["id"], master.a1["id"], "B-M", 8, produced_lbs=8,
                          slicer_id=master.slicers[0]["id"])
    # PRD §3.1: the half-open window runs [hold_expires - markdown_window,
    # hold_expires), i.e. the opening instant itself is legal and one minute
    # earlier is not.
    from datetime import datetime, timedelta, timezone
    expiry = datetime.fromisoformat(batch["hold_expires_at"].replace("Z", "+00:00"))
    opens = expiry - timedelta(minutes=master.j2["markdown_window_minutes"])

    set_clock((opens - timedelta(minutes=1)).strftime("%Y-%m-%dT%H:%M:%SZ"))
    early = api_client.mark_down_batch(batch["id"], clerk_headers(master.a1["id"]))
    validate_error(early, ApiErrorId.ERR_MARKDOWN_WINDOW_CLOSED)

    set_clock(opens.strftime("%Y-%m-%dT%H:%M:%SZ"))
    on_time = validate_success(api_client.mark_down_batch(batch["id"], clerk_headers(master.a1["id"])))
    assert on_time["hold_status"] == "MARKED_DOWN"
    assert on_time["production_status"] == "ON_LINE", (
        "only the hold dimension moved; the production dimension never crosses over"
    )


def test_the_timed_sanitation_threshold_is_met_and_the_routine_one_is_inclusive():
    """PRD §3.2: "A `TIMED` cycle is due when the slicer's `in_use_minutes` is
    greater than or equal to three times its `sanitation_cycle_limit`."
    PRD §3.2: "Requesting a routine or timed cycle before it is due fails with
    `ERR_SANITATION_CYCLE_NOT_DUE`."

    PRD leaves the mapping from sliced pounds to in-use minutes open, so this
    case asserts only that the TIMED form is not yet due after one batch while
    the inclusive ROUTINE form is.

    Design: Corner/state_machines/sanitation_threshold_inclusive_but_timed_multiplier_not_met
    """
    set_clock("2026-09-02T06:00:00Z")
    master = setup_deli_master_data(capacity=300, store_number="103", store_name="Store Three",
                                    slicer_count=1)
    slicer = master.slicers[0]
    produce_batch(master.s, master.j2["id"], master.a1["id"], "B-C", 125, produced_lbs=125,
                  slicer_id=slicer["id"])
    slicer_now = validate_success(api_client.get_slicer(slicer["id"], platform_admin_headers()))
    assert slicer_now["cuts_since_sanitation"] == 25

    timed = api_client.create_sanitation_cycle(
        {"store_id": master.s, "slicer_id": slicer["id"], "cycle_type": "TIMED", "cycle_minutes": 10},
        clerk_headers(master.a1["id"]),
    )
    validate_error(timed, ApiErrorId.ERR_SANITATION_CYCLE_NOT_DUE)

    cycle = validate_success(
        api_client.create_sanitation_cycle(
            {"store_id": master.s, "slicer_id": slicer["id"], "cycle_type": "ROUTINE",
             "cycle_minutes": 10},
            clerk_headers(master.a1["id"]),
        ),
        expected_status=201,
    )
    assert cycle["status"] == "OPEN", "the ROUTINE threshold at exactly 25 cuts admits the cycle"
    slicer_after = validate_success(api_client.get_slicer(slicer["id"], platform_admin_headers()))
    assert slicer_after["sanitation_status"] == "SANITIZING"


def test_reopening_a_cycle_is_bounded_at_two_per_production_day():
    """PRD §3.2: "A slicer may be reopened at most twice per production day, and
    the third attempt fails with `ERR_REOPEN_LIMIT_EXCEEDED`."

    Design: Corner/state_machines/reopen_is_bounded_at_two_per_production_day
    """
    set_clock("2026-09-02T06:00:00Z")
    master = setup_deli_master_data(capacity=300, store_number="103", store_name="Store Three",
                                    slicer_count=0)
    slicer = get_success_data(
        api_client.create_slicer(
            {"store_id": master.s, "asset_tag": "SL-7", "sanitation_cycle_limit": 12,
             "assigned_operator_id": master.a1["id"]},
            platform_admin_headers(),
        )
    )
    # 150 lbs leaves the slicer at ceil(150/5)=30 cuts, above its 12-cut limit, so
    # every cycle opened on it is due (PRD 3.2).
    produce_batch(master.s, master.j2["id"], master.a1["id"], "B-C", 150, produced_lbs=150,
                  slicer_id=slicer["id"])

    minute = [6]

    def fresh_cycle():
        """Open, complete and reopen one cycle; returns the aborted cycle row."""
        minute[0] += 1
        set_clock("2026-09-02T%02d:11:00Z" % minute[0])
        opened = open_sanitation_cycle(master.s, slicer["id"], master.a1["id"])
        minute[0] += 1
        set_clock("2026-09-02T%02d:11:00Z" % minute[0])
        validate_success(
            api_client.complete_sanitation_cycle(opened["id"], master.a1["id"],
                                                 clerk_headers(master.a1["id"]))
        )
        return validate_success(
            api_client.reopen_sanitation_cycle(
                opened["id"], "cycle evidence invalidated by manager review",
                manager_headers(master.a2["id"]))
        )

    first = fresh_cycle()
    second = fresh_cycle()
    assert first["status"] == "ABORTED" and second["status"] == "ABORTED", (
        "two reopenings are permitted within the production day"
    )

    minute[0] += 1
    set_clock("2026-09-02T%02d:11:00Z" % minute[0])
    third_cycle = open_sanitation_cycle(master.s, slicer["id"], master.a1["id"])
    minute[0] += 1
    set_clock("2026-09-02T%02d:11:00Z" % minute[0])
    validate_success(
        api_client.complete_sanitation_cycle(third_cycle["id"], master.a1["id"],
                                             clerk_headers(master.a1["id"]))
    )
    third = api_client.reopen_sanitation_cycle(
        third_cycle["id"], "reopen three", manager_headers(master.a2["id"])
    )
    validate_error(third, ApiErrorId.ERR_REOPEN_LIMIT_EXCEEDED)