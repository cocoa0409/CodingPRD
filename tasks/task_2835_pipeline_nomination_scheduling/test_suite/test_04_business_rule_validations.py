"""Business-rule validation boundaries for the pipeline nomination service.

Each test drives one PRD-declared refusal (or the accepted instant on the other
side of the same boundary) and then reads the affected rows back, because the PRD
requires a refused request to leave the book exactly as it found it.
"""

from datetime import datetime

from test_helpers import (
    ADMIN,
    OPERATOR,
    PUBLISHER_USER_ID,
    SCHEDULER,
    TEST_DEFAULTS,
    ApiErrorId,
    add_tariff,
    assert_millisecond_timestamp,
    close_cycle,
    create_cycle_payload,
    create_nomination_payload,
    create_terminal_payload,
    deliver_payload,
    get_success_data,
    inject_payload,
    inject_ticket,
    make_scheduler_headers,
    make_shipper_headers,
    nomination_key,
    plan_maintenance,
    refresh_cycle,
    reschedule_window_payload,
    resubmit_nomination_payload,
    settle_payload,
    setup_multi_shipper_cycle,
    setup_network,
    setup_open_cycle,
    setup_cycle_with_nomination,
    setup_prorated_cycle,
    setup_published_cycle,
    setup_scheduled_cycle,
    set_clock,
    validate_error,
    validate_paginated,
    validate_success,
)


def _instant(value):
    """Parse an ISO 8601 UTC instant so two renderings of the same moment compare
    equal regardless of how many fractional digits either one carries."""
    return datetime.fromisoformat(str(value).replace("Z", "+00:00"))


def _junction_terminal(api):
    """A third tank farm that the segment under test does not serve, used to nominate
    a destination that is off the segment's route."""
    return get_success_data(
        api.create_terminal(
            create_terminal_payload(
                terminal_code="MEM",
                name="Memphis Junction Terminal",
                role_kind="BOTH",
                shell_capacity_bbl=300000,
                min_operating_inventory_bbl=4000,
                injection_bays=1,
            ),
            ADMIN,
        )
    )


def test_nomination_at_the_window_open_instant_is_inside_the_window(api):
    """PRD 3.3: "The nomination window is half-open — `window_open_at` is inclusive and `window_close_at` is exclusive — and so is the shipping window, whose `ship_start_at` is inclusive and `ship_end_at` exclusive."

    PRD 3.3: "The new nomination itself starts with `status` of `SUBMITTED`, `revision_count` of 0, `allocated_bbl` of 0, `history_base_bbl` of 0, `allocation_class` of `NEW_SHIPPER`, `pinned_tariff_id` of null and `rejection_reason` of null."

    PRD 3.3: "The cycle's `version` increments by one — which is exactly why the next submission must re-read it — and the cycle's `nominated_total_bbl`, `allocated_total_bbl` and `unallocated_capacity_bbl` are recomputed."

    Design: Corner/validations/nomination_at_window_open_lower_bound_accepted
    """
    ctx = setup_open_cycle()
    cycle = ctx["cycle"]
    alpha = ctx["shippers"]["ALPHA"]
    assert _instant(cycle["window_open_at"]) == _instant(TEST_DEFAULTS["WINDOW_OPEN_AT"])

    set_clock(TEST_DEFAULTS["WINDOW_OPEN_AT"])
    nomination = validate_success(
        api.create_nomination(
            create_nomination_payload(
                cycle["id"],
                alpha["id"],
                ctx["grades"]["ULSD"]["id"],
                ctx["origin"]["id"],
                ctx["destination"]["id"],
                cycle["version"],
                nominated_bbl=30000,
            ),
            make_shipper_headers(alpha["id"]),
        ),
        201,
    )

    assert nomination["status"] == "SUBMITTED"
    assert int(nomination["revision_count"]) == 0
    assert float(nomination["allocated_bbl"]) == 0
    assert float(nomination["history_base_bbl"]) == 0
    assert nomination["allocation_class"] == "NEW_SHIPPER"
    assert nomination["pinned_tariff_id"] is None
    assert nomination["rejection_reason"] is None
    assert float(nomination["nominated_bbl"]) == 30000

    after = validate_success(api.get_cycle(cycle["id"], SCHEDULER))
    assert after["status"] == "OPEN"
    assert float(after["nominated_total_bbl"]) == 30000
    assert int(after["version"]) == 2


def test_nomination_at_the_window_close_instant_is_outside_the_window(api):
    """PRD 3.3: "The nomination window is half-open — `window_open_at` is inclusive and `window_close_at` is exclusive — and so is the shipping window, whose `ship_start_at` is inclusive and `ship_end_at` exclusive."

    PRD 3.3: "the logical clock must be at or after `window_open_at` and strictly before `window_close_at`, or `ERR_NOMINATION_WINDOW_CLOSED`"

    Design: Corner/validations/nomination_at_window_close_instant_rejected
    """
    ctx = setup_open_cycle()
    cycle = ctx["cycle"]
    alpha = ctx["shippers"]["ALPHA"]
    assert _instant(cycle["window_close_at"]) == _instant(TEST_DEFAULTS["WINDOW_CLOSE_AT"])

    set_clock(TEST_DEFAULTS["WINDOW_CLOSE_AT"])
    response = api.create_nomination(
        create_nomination_payload(
            cycle["id"],
            alpha["id"],
            ctx["grades"]["ULSD"]["id"],
            ctx["origin"]["id"],
            ctx["destination"]["id"],
            cycle["version"],
            nominated_bbl=30000,
        ),
        make_shipper_headers(alpha["id"]),
    )
    validate_error(response, ApiErrorId.ERR_NOMINATION_WINDOW_CLOSED.value)

    after = validate_success(api.get_cycle(cycle["id"], SCHEDULER))
    assert after["status"] == "OPEN"
    assert float(after["nominated_total_bbl"]) == 0
    assert int(after["version"]) == 1

    rows, meta = validate_paginated(
        api.list_nominations(SCHEDULER, params={"cycle_id": cycle["id"], "limit": 10})
    )
    assert meta["total_count"] == 0
    assert rows == []


def test_nomination_to_a_terminal_off_the_segment_route_is_refused(api):
    """PRD 3.3: "the supplied `origin_terminal_id` must equal the cycle's segment's `origin_terminal_id` and the supplied `destination_terminal_id` must equal that segment's `destination_terminal_id`, or `ERR_ROUTE_NOT_SERVED`"

    PRD 2.5: "**Route serviceability.** The nominated origin and destination match the cycle's segment endpoints — otherwise `ERR_ROUTE_NOT_SERVED` (422)."

    Design: Corner/validations/nomination_off_route_destination_returns_route_not_served
    """
    ctx = setup_open_cycle()
    cycle = ctx["cycle"]
    alpha = ctx["shippers"]["ALPHA"]
    junction = _junction_terminal(api)

    response = api.create_nomination(
        create_nomination_payload(
            cycle["id"],
            alpha["id"],
            ctx["grades"]["ULSD"]["id"],
            ctx["origin"]["id"],
            junction["id"],
            cycle["version"],
            nominated_bbl=30000,
        ),
        make_shipper_headers(alpha["id"]),
    )
    validate_error(response, ApiErrorId.ERR_ROUTE_NOT_SERVED.value)

    after = validate_success(api.get_cycle(cycle["id"], SCHEDULER))
    assert after["status"] == "OPEN"
    assert float(after["nominated_total_bbl"]) == 0
    assert int(after["version"]) == 1

    rows, meta = validate_paginated(
        api.list_nominations(SCHEDULER, params={"cycle_id": cycle["id"], "limit": 10})
    )
    assert meta["total_count"] == 0
    assert rows == []


def test_closing_a_cycle_whose_only_tariff_starts_after_the_ship_window_is_refused(api):
    """PRD 3.2: "Activation also has a cascade: every *other* tariff for the same `segment_id` and `grade_id` that is currently `EFFECTIVE` and whose effectivity interval overlaps the newly activated one moves `EFFECTIVE → SUPERSEDED`."

    PRD 3.2: "If the candidate set for any submitted nomination is empty, the entire close is refused with `ERR_NO_EFFECTIVE_TARIFF` (HTTP 422) and no nomination in the cycle is pinned, accepted or rejected."

    PRD 3.4: "if even one of them resolves an empty candidate set the whole close is refused with `ERR_NO_EFFECTIVE_TARIFF` and the cycle stays `OPEN`"

    Design: Corner/validations/cycle_close_without_effective_tariff_in_scope_rejected
    """
    ctx = setup_cycle_with_nomination()
    superseded_tariff = ctx["tariffs"]["ULSD"]
    later_tariff = add_tariff(
        ctx,
        "ULSD",
        effective_from="2026-09-01T00:00:00Z",
        base_rate_usd_per_bbl=2.100,
        tier1_rate_usd_per_bbl=1.950,
        tier2_rate_usd_per_bbl=1.800,
        imbalance_penalty_rate_usd_per_bbl=0.50,
    )

    response = api.close_cycle(ctx["cycle"]["id"], SCHEDULER)
    validate_error(response, ApiErrorId.ERR_NO_EFFECTIVE_TARIFF.value)

    cycle = validate_success(api.get_cycle(ctx["cycle"]["id"], SCHEDULER))
    assert cycle["status"] == "OPEN"

    nomination = validate_success(
        api.get_nomination(ctx["nominations"][nomination_key("ALPHA")]["id"], SCHEDULER)
    )
    assert nomination["status"] == "SUBMITTED"
    assert nomination["pinned_tariff_id"] is None
    assert nomination["rejection_reason"] is None

    old_row = validate_success(api.get_tariff(superseded_tariff["id"], SCHEDULER))
    assert old_row["status"] == "SUPERSEDED"
    new_row = validate_success(api.get_tariff(later_tariff["id"], SCHEDULER))
    assert new_row["status"] == "EFFECTIVE"


def test_maintenance_notice_inside_the_forty_eight_hour_lead_time_is_refused(api):
    """PRD 3.8: "the notice must be timely: the logical clock advanced by two full days — 48 hours — must be at or before the event's `window_start`, or the request is refused with `ERR_INSUFFICIENT_NOTICE` (HTTP 422)."

    PRD 3.8: "A new event's `status` is `PLANNED`, its `notified_at` is null and its `notified_shipper_count` is 0."

    PRD 3.4: "The segment's own `derate_pct` is always the largest `capacity_derate_pct` among the maintenance events on that segment whose `status` is `NOTIFIED` or `ACTIVE`, and is 0 when no such event exists."

    Design: Corner/validations/maintenance_notify_inside_48h_notice_rejected
    """
    ctx = setup_network()
    event = plan_maintenance(
        ctx,
        kind="VALVE_REPAIR",
        window_start="2026-08-02T00:00:00Z",
        window_end="2026-08-04T00:00:00Z",
        capacity_derate_pct=0.50,
        notes="mainline valve replacement",
    )
    assert event["status"] == "PLANNED"

    response = api.notify_maintenance_event(event["id"], SCHEDULER)
    validate_error(response, ApiErrorId.ERR_INSUFFICIENT_NOTICE.value)

    after = validate_success(api.get_maintenance_event(event["id"], SCHEDULER))
    assert after["status"] == "PLANNED"
    assert after["notified_at"] is None
    assert int(after["notified_shipper_count"]) == 0

    segment = validate_success(api.get_segment(ctx["segment"]["id"], SCHEDULER))
    assert float(segment["derate_pct"]) == 0
    assert segment["operational_status"] == "OPERATIONAL"


def test_cycle_whose_nomination_window_closes_after_shipping_starts_is_refused(api):
    """PRD 3.3: "Those four instants must be ordered so that `window_open_at` is strictly earlier than `window_close_at`, `window_close_at` is at or before `ship_start_at`, and `ship_start_at` is strictly earlier than `ship_end_at`; any other ordering is refused with `ERR_INVALID_WINDOW` (HTTP 422)."

    Design: Corner/validations/cycle_create_with_close_after_ship_start_returns_invalid_window
    """
    ctx = setup_network()

    response = api.create_cycle(
        create_cycle_payload(
            ctx["segment"]["id"],
            window_open_at="2026-08-01T00:00:00Z",
            window_close_at="2026-09-05T00:00:00Z",
            ship_start_at="2026-09-01T00:00:00Z",
            ship_end_at="2026-09-30T00:00:00Z",
        ),
        SCHEDULER,
    )
    validate_error(response, ApiErrorId.ERR_INVALID_WINDOW.value)

    rows, meta = validate_paginated(
        api.list_cycles(SCHEDULER, params={"segment_id": ctx["segment"]["id"], "limit": 10})
    )
    assert meta["total_count"] == 0
    assert rows == []


def test_rescheduling_a_batch_outside_the_shipping_window_leaves_the_slot_untouched(api):
    """PRD 3.6: "The ticket's `movement_status` must be `PLANNED`, or the request is refused with `ERR_TICKET_INVALID_STATE`; the requested window must lie inside the cycle's shipping window bounded by `ship_start_at` and `ship_end_at`, or `ERR_INVALID_WINDOW`; and the segment carrying the ticket must not be shut, or `ERR_SEGMENT_UNAVAILABLE`."

    PRD 3.6: "Each ticket's `injection_window_start` is the cycle's `ship_start_at` advanced by one 24-hour slot for every position ahead of it — that is, by `sequence_position` minus one whole days — and its `injection_window_end` is 24 hours after its own start."

    Design: Corner/validations/reschedule_window_outside_ship_window_returns_invalid_window
    """
    ctx = setup_scheduled_cycle()
    ticket = ctx["tickets"][0]
    assert int(ticket["sequence_position"]) == 1

    response = api.reschedule_window(
        ticket["id"],
        reschedule_window_payload("2026-10-05T00:00:00Z", "2026-10-06T00:00:00Z"),
        SCHEDULER,
    )
    validate_error(response, ApiErrorId.ERR_INVALID_WINDOW.value)

    after = validate_success(api.get_batch_ticket(ticket["id"], SCHEDULER))
    assert after["movement_status"] == "PLANNED"
    assert_millisecond_timestamp(after["injection_window_start"], "injection_window_start")
    assert_millisecond_timestamp(after["injection_window_end"], "injection_window_end")
    assert _instant(after["injection_window_start"]) == _instant("2026-09-01T00:00:00.000Z")
    assert _instant(after["injection_window_end"]) == _instant("2026-09-02T00:00:00.000Z")


def test_publishing_a_schedule_with_the_line_short_of_linefill_is_refused(api):
    """PRD 3.6: "it has one physical precondition: the segment's `linefill_bbl` must be at least its `linefill_requirement_bbl`."

    PRD 3.6: "A segment short of linefill cannot publish, is refused with `ERR_LINEFILL_REQUIREMENT_NOT_MET` (HTTP 422), and must be topped up through a linefill inventory adjustment first."

    PRD 3.6: "Building a schedule does not itself advance `schedule_version`; only publication does."

    PRD 3.4: "First, the **linefill make-up** is the amount by which the segment's `linefill_requirement_bbl` exceeds its current `linefill_bbl`, or zero when linefill is already at or above requirement — never a negative number."

    PRD 3.4: "Third, the linefill make-up is subtracted from that truncated figure, and then the segment's `transmix_reserve_bbl` is subtracted as well."

    Design: Corner/validations/publish_schedule_below_linefill_requirement_rejected
    """
    ctx = setup_scheduled_cycle(linefill_bbl=5000)
    segment = validate_success(api.get_segment(ctx["segment"]["id"], SCHEDULER))
    assert float(segment["linefill_bbl"]) == 5000
    assert float(segment["linefill_requirement_bbl"]) == 20000

    response = api.publish_schedule(
        ctx["cycle"]["id"], make_scheduler_headers(PUBLISHER_USER_ID)
    )
    validate_error(response, ApiErrorId.ERR_LINEFILL_REQUIREMENT_NOT_MET.value)

    cycle = validate_success(api.get_cycle(ctx["cycle"]["id"], SCHEDULER))
    assert cycle["status"] == "SCHEDULED"
    assert int(cycle["schedule_version"]) == 0
    assert cycle["schedule_published_at"] is None
    assert cycle["schedule_published_by_user_id"] is None
    assert int(cycle["effective_capacity_bbl"]) == 85000


def test_injection_that_would_break_the_origin_tank_floor_is_refused(api):
    """PRD 3.7: "A successful injection must not draw the origin tank below its floor: the origin terminal's `inventory_bbl` less the sum of the supplied `injected_bbl` and the ticket's own `transmix_bbl` must remain at or above that terminal's `min_operating_inventory_bbl`, and a shortfall is refused with `ERR_INSUFFICIENT_ORIGIN_INVENTORY` (HTTP 422)."

    PRD 3.7: "`quality_status` becomes `PASSED`, both measured values are stored, `injected_bbl` takes the supplied value, and `movement_status` moves `PLANNED → INJECTED`."

    PRD 3.7: "The segment's `in_transit_bbl` is increased by `injected_bbl` and its `transmix_inventory_bbl` is increased by `transmix_bbl`."

    Design: Corner/validations/inject_below_min_operating_inventory_rejected
    """
    ctx = setup_published_cycle(origin_stock_bbl=35000)
    ticket = ctx["tickets"][0]
    assert float(ticket["volume_bbl"]) == 30000
    assert float(ctx["origin"]["inventory_bbl"]) == 35000
    assert float(ctx["origin"]["min_operating_inventory_bbl"]) == 10000

    response = api.inject_batch(ticket["id"], inject_payload(30000, 9, 8), OPERATOR)
    validate_error(response, ApiErrorId.ERR_INSUFFICIENT_ORIGIN_INVENTORY.value)

    after = validate_success(api.get_batch_ticket(ticket["id"], SCHEDULER))
    assert after["movement_status"] == "PLANNED"
    assert after["quality_status"] == "PENDING"
    assert after["injected_bbl"] is None
    assert int(after["retest_count"]) == 0

    origin = validate_success(api.get_terminal(ctx["origin"]["id"], SCHEDULER))
    assert float(origin["inventory_bbl"]) == 35000

    segment = validate_success(api.get_segment(ctx["segment"]["id"], SCHEDULER))
    assert float(segment["in_transit_bbl"]) == 0
    assert float(segment["transmix_inventory_bbl"]) == 0

    shipper = validate_success(api.get_shipper(ctx["shippers"]["ALPHA"]["id"], SCHEDULER))
    assert float(shipper["exposure_usd"]) == 0


def test_delivery_beyond_the_destination_shell_capacity_is_refused(api):
    """PRD 3.7: "And the destination tank must have room: its `inventory_bbl` plus the supplied `delivered_bbl` must not exceed its `shell_capacity_bbl`, or the delivery is refused with `ERR_DESTINATION_CAPACITY_EXCEEDED` (HTTP 422)."

    PRD 3.7: "On success, `delivered_bbl` is stored and `movement_status` moves `INJECTED → DELIVERED`; the destination terminal's `inventory_bbl` increases by `delivered_bbl`; the segment's `in_transit_bbl` decreases by the ticket's `injected_bbl`; the segment's `system_loss_bbl` increases by the difference between `injected_bbl` and `delivered_bbl`, which is exactly where line shrinkage is booked; and the shipper's `exposure_usd` is recomputed."

    Design: Corner/validations/deliver_beyond_destination_shell_capacity_rejected
    """
    ctx = setup_published_cycle(destination_overrides={"shell_capacity_bbl": 20000})
    ticket = ctx["tickets"][0]
    inject_ticket(ctx, ticket["id"], 30000)

    response = api.deliver_batch(ticket["id"], deliver_payload(20500), OPERATOR)
    validate_error(response, ApiErrorId.ERR_DESTINATION_CAPACITY_EXCEEDED.value)

    after = validate_success(api.get_batch_ticket(ticket["id"], SCHEDULER))
    assert after["movement_status"] == "INJECTED"
    assert after["delivered_bbl"] is None
    assert float(after["injected_bbl"]) == 30000

    destination = validate_success(api.get_terminal(ctx["destination"]["id"], SCHEDULER))
    assert float(destination["inventory_bbl"]) == 0
    assert float(destination["shell_capacity_bbl"]) == 20000

    segment = validate_success(api.get_segment(ctx["segment"]["id"], SCHEDULER))
    assert float(segment["in_transit_bbl"]) == 30000
    assert float(segment["system_loss_bbl"]) == 0


def test_resubmission_above_the_volume_held_at_revision_time_is_refused(api):
    """PRD 3.8: "it must not exceed the `nominated_bbl` the nomination held when revision was requested, or the resubmission is refused with `ERR_REVISION_VOLUME_INCREASE` (HTTP 422), and it must be at least the segment's `min_tender_bbl`, or `ERR_TENDER_MINIMUM_NOT_MET`."

    PRD 3.8: "On success the nomination moves to `REVISION_REQUESTED`, its `allocated_bbl` is set to 0, its `revision_count` increments by one, every batch ticket of that nomination still in `PLANNED` is cancelled, and the cycle's `allocated_total_bbl` and `unallocated_capacity_bbl` are recomputed."

    PRD 2.8: "A parallel identity governs allocation rather than volume: for every nomination cycle, `allocated_total_bbl` plus `unallocated_capacity_bbl` must equal `effective_capacity_bbl` exactly, in whole barrels, with zero drift."

    Design: Corner/validations/resubmit_above_revision_baseline_rejected
    """
    ctx = setup_prorated_cycle()
    nomination = ctx["nominations"][nomination_key("ALPHA")]
    alpha = ctx["shippers"]["ALPHA"]
    assert float(nomination["nominated_bbl"]) == 30000

    get_success_data(api.request_revision(nomination["id"], SCHEDULER))

    response = api.resubmit_nomination(
        nomination["id"],
        resubmit_nomination_payload(30001),
        make_shipper_headers(alpha["id"]),
    )
    validate_error(response, ApiErrorId.ERR_REVISION_VOLUME_INCREASE.value)

    after = validate_success(api.get_nomination(nomination["id"], SCHEDULER))
    assert after["status"] == "REVISION_REQUESTED"
    assert int(after["revision_count"]) == 1
    assert float(after["nominated_bbl"]) == 30000
    assert float(after["allocated_bbl"]) == 0

    cycle = validate_success(api.get_cycle(ctx["cycle"]["id"], SCHEDULER))
    assert int(cycle["allocated_total_bbl"]) == 0
    assert int(cycle["effective_capacity_bbl"]) == 100000
    assert int(cycle["unallocated_capacity_bbl"]) == 100000


def test_building_a_schedule_whose_interface_cuts_exceed_the_reserve_is_refused(api):
    """PRD 3.6: "The sum of the transmix cuts across the sequence the build would produce must not exceed the segment's `transmix_reserve_bbl`; when it would, the build is refused with `ERR_TRANSMIX_RESERVE_EXCEEDED` (HTTP 422) and no ticket is created."

    PRD 3.6: "The cycle's `total_transmix_bbl` is the sum of `transmix_bbl` across the cycle's tickets whose `movement_status` is anything other than `CANCELLED`."

    PRD 3.4: "Second, the segment's nameplate `capacity_bbl_per_cycle` is multiplied by one minus the segment's `derate_pct`, and that derated nameplate is truncated downward to the next lower whole barrel."

    PRD 3.4: "Third, the linefill make-up is subtracted from that truncated figure, and then the segment's `transmix_reserve_bbl` is subtracted as well."

    PRD 3.5: "Walking that order, each nomination receives the smaller of its own unmet demand and the leftover still available, the grant is added to its allocation and subtracted from the leftover."

    PRD 3.5: "Surviving nominations settle into `PRORATED` by one of three hops — `ACCEPTED → PRORATED` in the ordinary run, and `SUBMITTED → PRORATED` or `REVISION_REQUESTED → PRORATED` when the cycle was `RESEQUENCING` — and the cycle itself moves to `PRORATED`."

    Design: Corner/validations/build_schedule_over_transmix_reserve_rejected
    """
    ctx = setup_multi_shipper_cycle(
        [("ALPHA", "JET", 20000), ("BRAVO", "ULSD", 20000), ("CHARLIE", "CBOB", 20000)],
        grades=("JET", "ULSD", "CBOB"),
        prorate=True,
        segment_overrides={"transmix_reserve_bbl": 200},
    )
    assert float(ctx["segment"]["transmix_reserve_bbl"]) == 200

    response = api.build_schedule(ctx["cycle"]["id"], SCHEDULER)
    validate_error(response, ApiErrorId.ERR_TRANSMIX_RESERVE_EXCEEDED.value)

    rows, meta = validate_paginated(
        api.list_batch_tickets(
            SCHEDULER, params={"cycle_id": ctx["cycle"]["id"], "limit": 10}
        )
    )
    assert meta["total_count"] == 0
    assert rows == []

    cycle = validate_success(api.get_cycle(ctx["cycle"]["id"], SCHEDULER))
    assert cycle["status"] == "PRORATED"
    assert float(cycle["total_transmix_bbl"]) == 0
    assert int(cycle["effective_capacity_bbl"]) == 100800
    assert int(cycle["allocated_total_bbl"]) == 60000
    assert int(cycle["unallocated_capacity_bbl"]) == 40800

    for key in ("ALPHA:JET", "BRAVO:ULSD", "CHARLIE:CBOB"):
        row = validate_success(
            api.get_nomination(ctx["nominations"][key]["id"], SCHEDULER)
        )
        assert row["status"] == "PRORATED"
        assert int(row["allocated_bbl"]) == 20000


def test_settling_a_cycle_with_a_batch_still_planned_is_blocked(api):
    """PRD 3.9: "It has one physical precondition: every batch ticket of the cycle must have reached `DELIVERED` or `CANCELLED`."

    PRD 3.9: "A single ticket still in `PLANNED` or still in `INJECTED` blocks the whole settlement with `ERR_BATCHES_IN_TRANSIT` (HTTP 409), because a cycle cannot be billed while product is still in the line."

    PRD 3.6: "Publication drives the cycle `SCHEDULED → PUBLISHED`, increments the cycle's `schedule_version` by one, stamps `schedule_published_at` with the logical clock and records the publishing operator's `X-User-ID` in `schedule_published_by_user_id`, and moves every nomination of the cycle still in `PRORATED` to `SCHEDULED`."

    Design: Corner/validations/settle_with_planned_ticket_returns_batches_in_transit
    """
    ctx = setup_published_cycle()
    ticket = ctx["tickets"][0]
    assert ticket["movement_status"] == "PLANNED"

    response = api.settle_cycle(ctx["cycle"]["id"], settle_payload("DELIVERED"), SCHEDULER)
    validate_error(response, ApiErrorId.ERR_BATCHES_IN_TRANSIT.value)

    cycle = validate_success(api.get_cycle(ctx["cycle"]["id"], SCHEDULER))
    assert cycle["status"] == "PUBLISHED"
    assert cycle["settled_at"] is None

    rows, meta = validate_paginated(
        api.list_settlements(SCHEDULER, params={"cycle_id": ctx["cycle"]["id"], "limit": 10})
    )
    assert meta["total_count"] == 0
    assert rows == []

    nomination = validate_success(
        api.get_nomination(ctx["nominations"][nomination_key("ALPHA")]["id"], SCHEDULER)
    )
    assert nomination["status"] == "SCHEDULED"

    after = validate_success(api.get_batch_ticket(ticket["id"], SCHEDULER))
    assert after["movement_status"] == "PLANNED"


def test_injection_whose_line_value_exceeds_the_credit_limit_is_refused(api):
    """PRD 3.7: "The gate asks whether that exposure, plus the candidate ticket's own line value computed the same way from its `volume_bbl` and its pinned base rate, remains at or below the shipper's `credit_limit_usd`; if it does not, the injection is refused with `ERR_CREDIT_LIMIT_EXCEEDED` and HTTP 402."

    PRD 3.7: "`quality_status` becomes `PASSED`, both measured values are stored, `injected_bbl` takes the supplied value, and `movement_status` moves `PLANNED → INJECTED`."

    PRD 3.1: "A new shipper's `status` is `ACTIVE`, its `suspended_reason` is null and its `exposure_usd` is 0.00."

    Design: Corner/validations/inject_over_credit_limit_rejected
    """
    ctx = setup_published_cycle(shipper_overrides={"credit_limit_usd": 40000})
    ticket = ctx["tickets"][0]
    alpha = ctx["shippers"]["ALPHA"]
    assert float(ticket["volume_bbl"]) == 30000
    assert float(ctx["tariffs"]["ULSD"]["base_rate_usd_per_bbl"]) == 1.855

    response = api.inject_batch(ticket["id"], inject_payload(30000, 9, 8), OPERATOR)
    validate_error(response, ApiErrorId.ERR_CREDIT_LIMIT_EXCEEDED.value)

    after = validate_success(api.get_batch_ticket(ticket["id"], SCHEDULER))
    assert after["movement_status"] == "PLANNED"
    assert after["quality_status"] == "PENDING"
    assert after["injected_bbl"] is None

    shipper = validate_success(api.get_shipper(alpha["id"], SCHEDULER))
    assert float(shipper["exposure_usd"]) == 0
    assert float(shipper["credit_limit_usd"]) == 40000
    assert shipper["status"] == "ACTIVE"

    origin = validate_success(api.get_terminal(ctx["origin"]["id"], SCHEDULER))
    assert float(origin["inventory_bbl"]) == 100000


def test_a_closed_cycle_is_reported_before_an_unserved_route(api):
    """PRD 2.5: "More than one rule can be violated by the same request, and the service must always report the *first* violated rule in a fixed order of evaluation."

    PRD 2.5: "The ladder below is exhaustive and is evaluated from top to bottom; the first rank whose condition fails determines both the `error_id` and the HTTP status, and no later rank is consulted."

    PRD 2.5: "Nomination submission has its own code at this rank, `ERR_CYCLE_NOT_OPEN` (409), because the state being guarded is the cycle's rather than the nomination's."

    PRD 2.5: "**Route serviceability.** The nominated origin and destination match the cycle's segment endpoints — otherwise `ERR_ROUTE_NOT_SERVED` (422)."

    Design: Corner/validations/priority_cycle_not_open_beats_route_not_served
    """
    ctx = setup_open_cycle()
    close_cycle(ctx)
    junction = _junction_terminal(api)
    cycle = refresh_cycle(ctx)
    assert cycle["status"] == "CLOSED"
    alpha = ctx["shippers"]["ALPHA"]

    response = api.create_nomination(
        create_nomination_payload(
            cycle["id"],
            alpha["id"],
            ctx["grades"]["ULSD"]["id"],
            ctx["origin"]["id"],
            junction["id"],
            cycle["version"],
            nominated_bbl=30000,
        ),
        make_shipper_headers(alpha["id"]),
    )
    validate_error(response, ApiErrorId.ERR_CYCLE_NOT_OPEN.value)

    after = validate_success(api.get_cycle(cycle["id"], SCHEDULER))
    assert after["status"] == "CLOSED"
    assert float(after["nominated_total_bbl"]) == 0

    rows, meta = validate_paginated(
        api.list_nominations(SCHEDULER, params={"cycle_id": cycle["id"], "limit": 10})
    )
    assert meta["total_count"] == 0
    assert rows == []
