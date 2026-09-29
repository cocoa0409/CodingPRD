"""Gates that live on an entity the request only references, and gates that turn on
one window overlapping another.

The first pair refuses a write because of a field on a *different* row -- the
shipper's standing, the segment's operational status -- while everything on the
request itself is in order. The second pair contends for a resource over time: an
exclusive segment padded by a buffer, and a terminal whose bays are counted.
"""

from test_helpers import (
    OPERATOR,
    SCHEDULER,
    api_client,
    create_nomination_payload,
    inject_payload,
    make_shipper_headers,
    nomination_key,
    plan_maintenance,
    notify_maintenance,
    refresh_cycle,
    refresh_nomination,
    refresh_origin,
    refresh_segment,
    refresh_shipper,
    refresh_tickets,
    reschedule_window_payload,
    set_clock,
    setup_network,
    setup_open_cycle,
    setup_multi_shipper_cycle,
    setup_two_bay_terminal_schedule,
    suspend_shipper,
    ticket_at,
    validate_error,
    validate_success,
)

SUSPENSION_REASON = "credit review pending"


def _barrels(value) -> int:
    return int(round(float(value)))


def _volume(value) -> float:
    return round(float(value), 2)


def _money(value) -> float:
    return round(float(value), 2)


def _ratio(value) -> float:
    return round(float(value), 6)


def _at(value) -> str:
    """The second-resolution prefix of an ISO 8601 instant, which is what the
    literal windows in this file are stated to."""
    return str(value)[:19]


def _open_cycle_with_a_suspended_alpha():
    """Everything on the request is in order -- OPEN cycle, clock inside the window,
    volume clear of the tender minimum -- and only ALPHA's standing is not."""
    ctx = setup_open_cycle(shippers=("ALPHA",))
    suspend_shipper(ctx, "ALPHA", suspended_reason=SUSPENSION_REASON)
    set_clock("2026-08-05T00:00:00Z", SCHEDULER)
    refresh_cycle(ctx)
    return ctx


def _submit(ctx, shipper_code, nominated_bbl):
    shipper = ctx["shippers"][shipper_code]
    return api_client.create_nomination(
        create_nomination_payload(
            ctx["cycle"]["id"],
            shipper["id"],
            ctx["grades"]["ULSD"]["id"],
            ctx["origin"]["id"],
            ctx["destination"]["id"],
            ctx["cycle"]["version"],
            nominated_bbl=nominated_bbl,
        ),
        make_shipper_headers(shipper["id"]),
    )


def test_a_suspended_shipper_may_not_nominate_at_all(api):
    """The gate is a field on a row the payload only names by id: ALPHA is SUSPENDED
    for a credit review, and that alone refuses a 30000 bbl nomination that breaks no
    other rule.

    PRD 3.1: "A suspended shipper may neither nominate, nor resubmit a revised
    nomination, nor have a batch injected on its behalf — all three are refused with
    `ERR_SHIPPER_NOT_ACTIVE`."

    PRD 3.1: "Suspension is a single administrative act that records a
    `suspended_reason` and moves `status` to `SUSPENDED`; the only two values `status`
    may take are `ACTIVE` and `SUSPENDED`."

    Design: Difficulty/cross_entity_state_dependency/nomination_blocked_by_suspended_shipper
    """
    ctx = _open_cycle_with_a_suspended_alpha()

    validate_error(
        _submit(ctx, "ALPHA", 30000), "ERR_SHIPPER_NOT_ACTIVE", expected_status=409
    )

    alpha = refresh_shipper(ctx, "ALPHA")
    assert alpha["status"] == "SUSPENDED"
    assert alpha["suspended_reason"] == SUSPENSION_REASON


def test_the_blocked_nomination_leaves_the_open_cycle_exactly_as_it_found_it(api):
    """No row is created for the refused submission, and the cycle it was aimed at is
    untouched: still OPEN, still carrying nothing, still at the version the shipper
    read.

    PRD 3.3: "Every accepted submission has two consequences on the parent cycle. The
    cycle's `version` increments by one — which is exactly why the next submission
    must re-read it — and the cycle's `nominated_total_bbl`, `allocated_total_bbl` and
    `unallocated_capacity_bbl` are recomputed."

    Design: Difficulty/cross_entity_state_dependency/nomination_blocked_by_suspended_shipper
    """
    ctx = _open_cycle_with_a_suspended_alpha()
    version_before = int(ctx["cycle"]["version"])

    validate_error(
        _submit(ctx, "ALPHA", 30000), "ERR_SHIPPER_NOT_ACTIVE", expected_status=409
    )

    listing = api_client.list_nominations(SCHEDULER, params={"cycle_id": ctx["cycle"]["id"]})
    assert int(listing.json()["meta"]["total_count"]) == 0

    cycle = refresh_cycle(ctx)
    assert cycle["status"] == "OPEN"
    assert _barrels(cycle["nominated_total_bbl"]) == 0
    assert int(cycle["version"]) == version_before


def _published_cycle_behind_a_shut_line():
    """ALPHA's single 30000 bbl ULSD batch is ready to inject in every respect, and
    then a full outage in November shuts the line."""
    ctx = setup_multi_shipper_cycle(
        [("ALPHA", "ULSD", 30000)],
        origin_stock_bbl=100000,
        publish=True,
    )
    set_clock("2026-08-25T00:00:00Z", SCHEDULER)
    event = plan_maintenance(
        ctx,
        kind="VALVE_REPAIR",
        window_start="2026-11-10T00:00:00Z",
        window_end="2026-11-20T00:00:00Z",
        capacity_derate_pct=1.0,
        notes="full outage for a girth weld repair",
    )
    notify_maintenance(ctx, event["id"])
    return ctx


def test_a_shut_segment_refuses_an_otherwise_perfect_injection(api):
    """The ticket is PLANNED, the product is on specification at 9 ppm, the tank holds
    100000 bbl and the credit line is untouched -- and the injection is still refused,
    because a governing derate of exactly 1 shuts the line. Nothing moves: the ticket
    keeps both its statuses and its retest counter, and no barrel leaves the tank.

    PRD 3.7: "The segment must be usable: its `operational_status` must be
    `OPERATIONAL` or `DERATED`, and a segment that is `SHUT` refuses the injection with
    `ERR_SEGMENT_UNAVAILABLE`."

    PRD 3.4: "The segment's own `derate_pct` is always the largest
    `capacity_derate_pct` among the maintenance events on that segment whose `status`
    is `NOTIFIED` or `ACTIVE`, and is 0 when no such event exists."

    Design: Difficulty/cross_entity_state_dependency/injection_blocked_by_shut_segment
    """
    ctx = _published_cycle_behind_a_shut_line()
    ticket = ticket_at(ctx, 1)

    validate_error(
        api_client.inject_batch(ticket["id"], inject_payload(30000, 9, 10), OPERATOR),
        "ERR_SEGMENT_UNAVAILABLE",
        expected_status=409,
    )

    segment = refresh_segment(ctx)
    assert segment["operational_status"] == "SHUT"
    assert round(float(segment["derate_pct"]), 2) == 1.0

    refresh_tickets(ctx)
    untouched = ticket_at(ctx, 1)
    assert untouched["movement_status"] == "PLANNED"
    assert untouched["quality_status"] == "PENDING"
    assert int(untouched["retest_count"]) == 0

    assert _volume(refresh_origin(ctx)["inventory_bbl"]) == 100000.00
    assert _volume(segment["in_transit_bbl"]) == 0.00
    assert _money(refresh_shipper(ctx, "ALPHA")["exposure_usd"]) == 0.00


def test_a_november_outage_does_not_resize_a_september_cycle(api):
    """The derate is real on the segment and irrelevant to this cycle: the outage runs
    from 10 to 20 November and the cycle ships through September, so the two windows do
    not intersect and the cycle keeps its full 100000 bbl of effective capacity, stays
    PUBLISHED and leaves the nomination SCHEDULED for all 30000 bbl.

    PRD 3.4: "When a maintenance transition changes `derate_pct`, only the cycles of
    that segment whose shipping window from `ship_start_at` inclusive to `ship_end_at`
    exclusive intersects the event's window from `window_start` through `window_end`
    inclusive recompute anything; a cycle whose shipping window does not intersect the
    maintenance window keeps its existing `effective_capacity_bbl` and
    `derate_pct_applied` untouched."

    Design: Difficulty/cross_entity_state_dependency/injection_blocked_by_shut_segment
    """
    ctx = _published_cycle_behind_a_shut_line()

    cycle = refresh_cycle(ctx)
    assert cycle["status"] == "PUBLISHED"
    assert _barrels(cycle["effective_capacity_bbl"]) == 100000

    nomination = refresh_nomination(ctx, nomination_key("ALPHA", "ULSD"))
    assert nomination["status"] == "SCHEDULED"
    assert _barrels(nomination["allocated_bbl"]) == 30000


def _segment_with_one_planned_pigging_run():
    """A bare network carrying a single PLANNED outage from 10 to 12 September, whose
    24-hour buffer on each side closes 9 September through 13 September."""
    ctx = setup_network()
    plan_maintenance(
        ctx,
        kind="PIGGING",
        window_start="2026-09-10T00:00:00Z",
        window_end="2026-09-12T00:00:00Z",
        capacity_derate_pct=0.30,
        notes="scraper run through the September batches",
    )
    return ctx


def _plan_an_integrity_dig(ctx, window_start, window_end):
    return api_client.create_maintenance_event(
        {
            "segment_id": ctx["segment"]["id"],
            "kind": "INTEGRITY_DIG",
            "window_start": window_start,
            "window_end": window_end,
            "capacity_derate_pct": 0.20,
            "notes": "anomaly verification dig",
        },
        SCHEDULER,
    )


def test_a_new_outage_landing_on_the_buffer_conflicts_with_the_planned_one(api):
    """A dig starting the instant the buffer ends -- 13 September, one day after the
    pigging run's own window closes -- is refused, because the buffer is compared
    closed at both ends and a window that merely touches it still conflicts.

    PRD 3.8: "A new maintenance window must not overlap, within a buffer of one full
    day — 24 hours — on each side, any existing maintenance event on the same segment
    whose `status` is `PLANNED`, `NOTIFIED` or `ACTIVE`; the comparison treats both
    windows as closed at both ends, so windows that merely touch inside the buffer
    still conflict."

    Design: Difficulty/resource_temporal_overlap/maintenance_window_buffer_conflict_on_segment
    """
    ctx = _segment_with_one_planned_pigging_run()

    validate_error(
        _plan_an_integrity_dig(ctx, "2026-09-13T00:00:00Z", "2026-09-14T00:00:00Z"),
        "ERR_MAINTENANCE_WINDOW_CONFLICT",
        expected_status=409,
    )

    listing = api_client.list_maintenance_events(
        SCHEDULER, params={"segment_id": ctx["segment"]["id"]}
    )
    assert int(listing.json()["meta"]["total_count"]) == 1
    assert ctx["events"][0]["status"] == "PLANNED"


def test_the_same_outage_one_day_later_clears_the_buffer_and_is_planned(api):
    """Moved on by 24 hours to start on 14 September, the identical dig is accepted and
    filed as PLANNED alongside the first -- and because neither has been notified, the
    segment is not derated and stays OPERATIONAL.

    PRD 3.4: "The segment's own `derate_pct` is always the largest
    `capacity_derate_pct` among the maintenance events on that segment whose `status`
    is `NOTIFIED` or `ACTIVE`, and is 0 when no such event exists."

    Design: Difficulty/resource_temporal_overlap/maintenance_window_buffer_conflict_on_segment
    """
    ctx = _segment_with_one_planned_pigging_run()
    validate_error(
        _plan_an_integrity_dig(ctx, "2026-09-13T00:00:00Z", "2026-09-14T00:00:00Z"),
        "ERR_MAINTENANCE_WINDOW_CONFLICT",
        expected_status=409,
    )

    accepted = validate_success(
        _plan_an_integrity_dig(ctx, "2026-09-14T00:00:00Z", "2026-09-15T00:00:00Z"),
        expected_status=201,
    )

    assert _at(accepted["window_start"]) == "2026-09-14T00:00:00"
    assert accepted["status"] == "PLANNED"

    listing = api_client.list_maintenance_events(
        SCHEDULER, params={"segment_id": ctx["segment"]["id"]}
    )
    assert int(listing.json()["meta"]["total_count"]) == 2

    segment = refresh_segment(ctx)
    assert round(float(segment["derate_pct"]), 2) == 0
    assert segment["operational_status"] == "OPERATIONAL"


def _three_planned_batches_at_a_two_bay_terminal():
    """NOVA, ORION and PEGASUS each hold 20000 bbl of ULSD, and the built schedule
    gives them consecutive 24-hour slots from 1 September at a terminal with two bays."""
    return setup_two_bay_terminal_schedule()


def _reschedule(ticket_id, window_start, window_end):
    return api_client.reschedule_window(
        ticket_id, reschedule_window_payload(window_start, window_end), SCHEDULER
    )


def test_a_window_straddling_two_planned_peers_fills_both_bays_and_is_refused(api):
    """Moving the third batch to noon on 1 September would have it sharing the manifold
    with both of its peers at once, and two overlapping peers is the whole of a two-bay
    terminal, so the move is refused and the ticket keeps its original slot.

    PRD 3.6: "If the number of overlapping peers is greater than or equal to the origin
    terminal's `injection_bays`, the reschedule is refused with
    `ERR_TERMINAL_BAY_CONFLICT` (HTTP 409); otherwise the two window fields are
    replaced."

    PRD 3.6: "The peers considered are every *other* batch ticket whose nomination
    shares the same `origin_terminal_id`, whose `movement_status` is `PLANNED`, and
    whose own half-open injection window intersects the requested half-open window —
    counted across every cycle, not just this one, because a bay is physical."

    Design: Difficulty/resource_temporal_overlap/terminal_bay_aggregate_overlap_half_open
    """
    ctx = _three_planned_batches_at_a_two_bay_terminal()
    assert _barrels(ctx["origin"]["injection_bays"]) == 2
    third = ticket_at(ctx, 3)
    assert _at(third["injection_window_start"]) == "2026-09-03T00:00:00"

    validate_error(
        _reschedule(third["id"], "2026-09-01T12:00:00Z", "2026-09-02T12:00:00Z"),
        "ERR_TERMINAL_BAY_CONFLICT",
        expected_status=409,
    )

    refresh_tickets(ctx)
    unmoved = ticket_at(ctx, 3)
    assert _at(unmoved["injection_window_start"]) == "2026-09-03T00:00:00"
    assert _at(unmoved["injection_window_end"]) == "2026-09-04T00:00:00"
    assert unmoved["movement_status"] == "PLANNED"


def test_abutting_a_peer_exactly_is_not_an_overlap_so_the_move_is_accepted(api):
    """Shifted back by only twelve hours to start exactly when the first batch's slot
    ends, the same move overlaps one peer instead of two -- abutment is not overlap --
    so it is accepted, the peers keep their own windows, and the cycle's allocations
    are entirely undisturbed by the reshuffle.

    PRD 3.6: "Because the arithmetic is half-open, a peer whose window ends exactly
    when the requested window starts does not overlap it, and neither does a peer whose
    window starts exactly when the requested window ends; instants are compared at
    millisecond resolution."

    Design: Difficulty/resource_temporal_overlap/terminal_bay_aggregate_overlap_half_open
    """
    ctx = _three_planned_batches_at_a_two_bay_terminal()
    third = ticket_at(ctx, 3)
    validate_error(
        _reschedule(third["id"], "2026-09-01T12:00:00Z", "2026-09-02T12:00:00Z"),
        "ERR_TERMINAL_BAY_CONFLICT",
        expected_status=409,
    )

    moved = validate_success(
        _reschedule(third["id"], "2026-09-02T00:00:00Z", "2026-09-03T00:00:00Z")
    )

    assert _at(moved["injection_window_start"]) == "2026-09-02T00:00:00"
    assert _at(moved["injection_window_end"]) == "2026-09-03T00:00:00"
    assert int(moved["sequence_position"]) == 3

    refresh_tickets(ctx)
    assert _at(ticket_at(ctx, 1)["injection_window_start"]) == "2026-09-01T00:00:00"
    assert _at(ticket_at(ctx, 2)["injection_window_start"]) == "2026-09-02T00:00:00"
    for position in (1, 2, 3):
        assert ticket_at(ctx, position)["movement_status"] == "PLANNED"

    cycle = refresh_cycle(ctx)
    assert _barrels(cycle["allocated_total_bbl"]) == 60000
    assert _barrels(cycle["unallocated_capacity_bbl"]) == 40000
    assert _ratio(cycle["proration_factor"]) == 1.000000
