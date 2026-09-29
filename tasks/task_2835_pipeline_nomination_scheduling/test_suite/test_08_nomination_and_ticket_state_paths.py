"""Non-linear state paths: a nomination that re-enters a state it already held, and
a batch ticket whose two status dimensions advance on their own timetables.

Both shapes break the assumption that a lifecycle is a one-way ladder. The
nomination walks SUBMITTED -> PRORATED -> REVISION_REQUESTED -> SUBMITTED and then
refuses to loop again; the ticket's quality dimension moves twice while its
movement dimension does not move at all.
"""

from test_helpers import (
    OPERATOR,
    SCHEDULER,
    api_client,
    inject_payload,
    make_shipper_headers,
    nomination_key,
    refresh_cycle,
    refresh_nomination,
    refresh_origin,
    refresh_segment,
    refresh_shipper,
    refresh_tickets,
    resubmit_nomination_payload,
    setup_multi_shipper_cycle,
    ticket_at,
    validate_error,
    validate_success,
)

ALPHA_HISTORY = [
    ("ALPHA", 30000, "2026-06-30T00:00:00Z"),
    ("ALPHA", 42000, "2026-07-31T00:00:00Z"),
]


def _barrels(value) -> int:
    return int(round(float(value)))


def _volume(value) -> float:
    return round(float(value), 2)


def _money(value) -> float:
    return round(float(value), 2)


def _prorated_over_nominated_cycle():
    """ALPHA nominates 70000 bbl of ULSD against 100000 bbl of capacity and the
    cycle is prorated, so the nomination holds all 70000 bbl and 30000 bbl are
    left unallocated."""
    return setup_multi_shipper_cycle(
        [("ALPHA", "ULSD", 70000)],
        history=ALPHA_HISTORY,
        prorate=True,
    )


def _request_revision(ctx, key):
    nomination = ctx["nominations"][key]
    return api_client.request_revision(nomination["id"], SCHEDULER)


def _resubmit(ctx, key, nominated_bbl):
    nomination = ctx["nominations"][key]
    return api_client.resubmit_nomination(
        nomination["id"],
        resubmit_nomination_payload(nominated_bbl),
        make_shipper_headers(nomination["shipper_id"]),
    )


def test_requesting_a_revision_releases_the_allocation_back_to_the_cycle(api):
    """A hand-issued revision request on a PRORATED nomination zeroes its
    allocation, bumps the loop counter to 1, and hands all 100000 bbl of effective
    capacity back to the cycle as unallocated.

    PRD 3.8: "On success the nomination moves to `REVISION_REQUESTED`, its
    `allocated_bbl` is set to 0, its `revision_count` increments by one, every batch
    ticket of that nomination still in `PLANNED` is cancelled, and the cycle's
    `allocated_total_bbl` and `unallocated_capacity_bbl` are recomputed."

    Design: Difficulty/non_linear_state_machine/nomination_revision_loop_returns_to_submitted_and_then_locks
    """
    ctx = _prorated_over_nominated_cycle()
    key = nomination_key("ALPHA", "ULSD")
    assert _barrels(ctx["nominations"][key]["allocated_bbl"]) == 70000
    assert _barrels(ctx["cycle"]["unallocated_capacity_bbl"]) == 30000

    validate_success(_request_revision(ctx, key))

    nomination = refresh_nomination(ctx, key)
    cycle = refresh_cycle(ctx)
    assert nomination["status"] == "REVISION_REQUESTED"
    assert _barrels(nomination["allocated_bbl"]) == 0
    assert int(nomination["revision_count"]) == 1
    assert _barrels(cycle["allocated_total_bbl"]) == 0
    assert _barrels(cycle["unallocated_capacity_bbl"]) == 100000


def test_resubmitting_re_enters_submitted_without_resetting_the_loop_counter(api):
    """Resubmission takes the nomination back to the SUBMITTED state it already
    occupied once, replaces its volume with the smaller 50000 bbl figure, and leaves
    `revision_count` at 1 — the counter records the loop, it does not restart with it.

    PRD 3.8: "On success the nomination's `nominated_bbl` is replaced with the body
    value, its `allocated_bbl` is set to 0, it moves `REVISION_REQUESTED →
    SUBMITTED`, and the cycle's `nominated_total_bbl`, `allocated_total_bbl` and
    `unallocated_capacity_bbl` are recomputed."

    Design: Difficulty/non_linear_state_machine/nomination_revision_loop_returns_to_submitted_and_then_locks
    """
    ctx = _prorated_over_nominated_cycle()
    key = nomination_key("ALPHA", "ULSD")
    validate_success(_request_revision(ctx, key))

    validate_success(_resubmit(ctx, key, 50000))

    nomination = refresh_nomination(ctx, key)
    assert nomination["status"] == "SUBMITTED"
    assert _barrels(nomination["nominated_bbl"]) == 50000
    assert int(nomination["revision_count"]) == 1
    assert _barrels(nomination["allocated_bbl"]) == 0


def test_a_second_revision_request_from_submitted_terminates_the_loop(api):
    """The loop has an exit: once the nomination is back in SUBMITTED the scheduler
    may not send it round again, and the refusal leaves the row exactly where it was.

    PRD 3.8: "From any other nomination status it is refused with
    `ERR_NOMINATION_INVALID_STATE`, and it is refused with `ERR_NOMINATION_LOCKED`
    once any batch ticket of that nomination has left `PLANNED` — that is, once a
    ticket is `INJECTED` or `DELIVERED`, the volume is in the line and there is
    nothing to revise."

    Design: Difficulty/non_linear_state_machine/nomination_revision_loop_returns_to_submitted_and_then_locks
    """
    ctx = _prorated_over_nominated_cycle()
    key = nomination_key("ALPHA", "ULSD")
    validate_success(_request_revision(ctx, key))
    validate_success(_resubmit(ctx, key, 50000))

    validate_error(
        _request_revision(ctx, key), "ERR_NOMINATION_INVALID_STATE", expected_status=409
    )

    nomination = refresh_nomination(ctx, key)
    assert nomination["status"] == "SUBMITTED"
    assert int(nomination["revision_count"]) == 1
    assert _barrels(nomination["nominated_bbl"]) == 50000


def _published_single_batch_cycle():
    """ALPHA's single 30000 bbl ULSD batch on a published schedule, with 100000 bbl
    in the origin tank; the batch follows the ULSD linefill so it cuts no transmix."""
    ctx = setup_multi_shipper_cycle(
        [("ALPHA", "ULSD", 30000)],
        history=ALPHA_HISTORY,
        origin_stock_bbl=100000,
        publish=True,
    )
    refresh_origin(ctx)
    refresh_segment(ctx)
    return ctx


def _inject(ticket_id, injected_bbl, sulfur, rvp):
    return api_client.inject_batch(
        ticket_id, inject_payload(injected_bbl, sulfur, rvp), OPERATOR
    )


def test_an_off_spec_injection_moves_only_the_quality_dimension(api):
    """Presenting 40 ppm sulfur against a 15 ppm ceiling is refused, yet the refusal
    still writes: the quality dimension moves PENDING to REJECTED and the retest
    counter reaches 1 while the movement dimension stays PLANNED and not one barrel
    leaves the origin tank.

    PRD 3.7: "Specifically, `quality_status` moves `PENDING → REJECTED`, both
    measured values are stored on the ticket, `retest_count` increments by one,
    `movement_status` stays `PLANNED`, and no volume moves anywhere."

    Design: Difficulty/non_linear_state_machine/batch_ticket_movement_and_quality_dimensions_advance_independently
    """
    ctx = _published_single_batch_cycle()
    ticket = ticket_at(ctx, 1)
    assert ticket["quality_status"] == "PENDING"
    assert ticket["movement_status"] == "PLANNED"
    assert int(ticket["retest_count"]) == 0
    assert _barrels(ticket["transmix_bbl"]) == 0

    validate_error(
        _inject(ticket["id"], 30000, 40, 10),
        "ERR_QUALITY_SPEC_VIOLATION",
        expected_status=422,
    )

    refresh_tickets(ctx)
    rejected = ticket_at(ctx, 1)
    assert rejected["quality_status"] == "REJECTED"
    assert rejected["movement_status"] == "PLANNED"
    assert int(rejected["retest_count"]) == 1
    assert _volume(rejected["measured_sulfur_ppm"]) == 40

    assert _volume(refresh_origin(ctx)["inventory_bbl"]) == 100000.00
    assert _volume(refresh_segment(ctx)["in_transit_bbl"]) == 0.00


def test_a_retest_within_specification_carries_out_the_full_injection(api):
    """The same ticket, presented again at 9 ppm, moves its quality dimension
    REJECTED to PASSED without disturbing the retest counter, and only now does the
    movement dimension advance to INJECTED, drawing 30000 bbl out of the tank and
    into the line and booking the shipper's exposure at 55650.00 USD.

    PRD 3.7: "A retest that comes back within specification while `movement_status`
    is `PLANNED` and `retest_count` is still below 2 moves `quality_status`
    `REJECTED → PASSED` and carries out the full injection below."

    PRD 3.7: "The origin terminal's `inventory_bbl` is reduced by the sum of
    `injected_bbl` and `transmix_bbl`."

    Design: Difficulty/non_linear_state_machine/batch_ticket_movement_and_quality_dimensions_advance_independently
    """
    ctx = _published_single_batch_cycle()
    ticket = ticket_at(ctx, 1)
    validate_error(
        _inject(ticket["id"], 30000, 40, 10),
        "ERR_QUALITY_SPEC_VIOLATION",
        expected_status=422,
    )

    validate_success(_inject(ticket["id"], 30000, 9, 10))

    refresh_tickets(ctx)
    injected = ticket_at(ctx, 1)
    assert injected["quality_status"] == "PASSED"
    assert injected["movement_status"] == "INJECTED"
    assert int(injected["retest_count"]) == 1
    assert _volume(injected["injected_bbl"]) == 30000.00

    assert _volume(refresh_origin(ctx)["inventory_bbl"]) == 70000.00
    assert _volume(refresh_segment(ctx)["in_transit_bbl"]) == 30000.00
    assert _money(refresh_shipper(ctx, "ALPHA")["exposure_usd"]) == 55650.00
