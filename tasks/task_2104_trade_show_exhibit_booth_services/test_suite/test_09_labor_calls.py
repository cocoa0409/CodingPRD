"""Union labor on the show floor.

Covers the buffered turnaround geometry that guards a second crew at one booth,
the straight-time/overtime band split and its minimum-call padding, the Sunday
double-time override, the no-show billing path and the committed crew-hour
ledger that a dispatch raises and a cancellation returns to zero.
"""

import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    assert_labor_call,
    assert_posture,
    cancel_labor_call,
    complete_labor_call,
    create_jurisdiction,
    create_labor_call_payload,
    create_venue,
    dispatch_labor_call,
    get_booth,
    get_labor_call,
    get_show,
    request_labor_call,
    setup_labor_ground,
    setup_requested_labor_call,
    setup_worked_labor_call,
    validate_error,
    validate_error_is_one_of,
    validate_paginated,
    validate_success,
)

OPS = TEST_USERS["show_operations_headers"]
LABOR = TEST_USERS["labor_supervisor_headers"]

# The commercial terms every crew below dispatches under: 14000 cents an hour
# straight time, 1.5 overtime, 2.0 double time, a four hour minimum call, six
# workers at most, and a thirty minute turnaround between two calls at a booth.
RIGGING_TERMS = {
    "trade": "RIGGING",
    "straight_time_rate_cents_per_hour": 14000,
    "overtime_multiplier": 1.5,
    "doubletime_multiplier": 2.0,
    "min_call_hours": 4,
    "crew_max_size": 6,
    "exhibitor_self_install_allowed": False,
    "turnaround_buffer_minutes": 30,
}

# The Monday window every occupancy scenario starts from: four workers, 13:00
# to 17:00 on the show's first open day.
MONDAY_CALL = {
    "scheduled_start": "2026-09-21T13:00:00Z",
    "scheduled_end": "2026-09-21T17:00:00Z",
    "crew_size": 4,
}


# ---------------------------------------------------------------------------
# Turnaround buffer: the accepted edge
# ---------------------------------------------------------------------------

def test_second_call_starting_exactly_one_buffer_after_the_first_is_accepted(api):
    """PRD §3.7: "The crew resource must be free, accounting for the
    jurisdiction's mandatory turnaround: considering the same `jurisdiction_id`
    and `booth_id` pair, and every existing call on that pair whose `status` is
    `REQUESTED`, `DISPATCHED` or `ON_SITE`, the request is refused with
    `ERR_LABOR_CALL_OVERLAP` when the new `scheduled_start` falls strictly
    before the existing call's `scheduled_end` extended forward by
    `turnaround_buffer_minutes` **and** the existing `scheduled_start` falls
    strictly before the new `scheduled_end` extended forward by the same
    buffer."
    PRD §3.7: "A gap exactly equal to the buffer is accepted."

    Design: Difficulty/boundary_precision_check/labor_turnaround_gap_exactly_buffer_is_accepted
    """
    ground = setup_requested_labor_call(show_status="ON_SITE",
                                        jurisdiction_overrides=RIGGING_TERMS,
                                        call_overrides=MONDAY_CALL)
    booth_id = ground["booth"]["id"]

    # 17:30 sits exactly one 30 minute buffer after the 17:00 end of the first
    # call, so the new start is not strictly before the buffered end.
    response = api.create_labor_call(
        create_labor_call_payload(booth_id, ground["jurisdiction"]["id"],
                                  scheduled_start="2026-09-21T17:30:00Z",
                                  scheduled_end="2026-09-21T20:00:00Z",
                                  crew_size=4),
        OPS)
    second = validate_success(response, 201)

    assert_labor_call(second)
    assert second["status"] == "REQUESTED", \
        f"a call admitted at the buffer edge is born REQUESTED, got {second['status']}"

    rows, meta = validate_paginated(
        api.list_labor_calls(OPS, {"booth_id": booth_id}))
    assert meta["total_count"] == 2, \
        f"both calls must stand on the booth, got {meta['total_count']}"
    assert {row["id"] for row in rows} == {ground["labor_call"]["id"], second["id"]}, \
        "the booth must carry exactly the first call and the buffer-edge call"


def test_call_admitted_at_the_buffer_edge_carries_its_own_hours_and_trade(api):
    """PRD §3.7: "A gap exactly equal to the buffer is accepted."
    PRD §3.7: "On creation the call copies the jurisdiction's `trade` onto
    itself, and computes `scheduled_hours` as the difference between
    `scheduled_end` and `scheduled_start` expressed in hours to two decimal
    places."
    PRD §2.6: "A labor call's scheduled hours and a show's committed crew-hours
    are both two-decimal quantities, and where a sum of hours is stored it is
    rounded half up to two decimals."

    Design: Difficulty/boundary_precision_check/labor_turnaround_gap_exactly_buffer_is_accepted
    """
    ground = setup_requested_labor_call(show_status="ON_SITE",
                                        jurisdiction_overrides=RIGGING_TERMS,
                                        call_overrides=MONDAY_CALL)

    second = request_labor_call(ground["booth"]["id"], ground["jurisdiction"]["id"],
                                scheduled_start="2026-09-21T17:30:00Z",
                                scheduled_end="2026-09-21T20:00:00Z",
                                crew_size=4)

    assert second["scheduled_hours"] == pytest.approx(2.5, abs=0.01), \
        f"17:30 to 20:00 is 2.50 scheduled hours, got {second['scheduled_hours']}"
    assert second["trade"] == "RIGGING", \
        f"the call copies the jurisdiction's trade, got {second['trade']}"

    stored = get_labor_call(second["id"])
    assert stored["scheduled_hours"] == pytest.approx(2.5, abs=0.01), \
        f"the stored call keeps 2.50 scheduled hours, got {stored['scheduled_hours']}"
    assert stored["status"] == "REQUESTED", \
        f"the buffer-edge call rests in REQUESTED, got {stored['status']}"


# ---------------------------------------------------------------------------
# Turnaround buffer: the rejected interior
# ---------------------------------------------------------------------------

def test_call_starting_twenty_minutes_after_the_first_ends_is_rejected(api):
    """PRD §3.7: "The crew resource must be free, accounting for the
    jurisdiction's mandatory turnaround: considering the same `jurisdiction_id`
    and `booth_id` pair, and every existing call on that pair whose `status` is
    `REQUESTED`, `DISPATCHED` or `ON_SITE`, the request is refused with
    `ERR_LABOR_CALL_OVERLAP` when the new `scheduled_start` falls strictly
    before the existing call's `scheduled_end` extended forward by
    `turnaround_buffer_minutes` **and** the existing `scheduled_start` falls
    strictly before the new `scheduled_end` extended forward by the same
    buffer."
    PRD §2.9: "Buffered crew overlap — otherwise `ERR_LABOR_CALL_OVERLAP`
    (409)."

    Design: Difficulty/resource_temporal_overlap/labor_crew_buffered_interval_overlap_rejects
    """
    ground = setup_requested_labor_call(show_status="ON_SITE",
                                        jurisdiction_overrides=RIGGING_TERMS,
                                        call_overrides=MONDAY_CALL)

    # 17:20 is twenty minutes after the first call ends, strictly inside the
    # 17:30 buffered end, while 13:00 is strictly before 20:30.
    response = api.create_labor_call(
        create_labor_call_payload(ground["booth"]["id"], ground["jurisdiction"]["id"],
                                  scheduled_start="2026-09-21T17:20:00Z",
                                  scheduled_end="2026-09-21T20:00:00Z",
                                  crew_size=4),
        OPS)

    validate_error(response, ApiErrorId.ERR_LABOR_CALL_OVERLAP.value, 409)


def test_buffered_overlap_rejection_leaves_the_existing_call_alone(api):
    """PRD §3.7: "The crew resource must be free, accounting for the
    jurisdiction's mandatory turnaround: considering the same `jurisdiction_id`
    and `booth_id` pair, and every existing call on that pair whose `status` is
    `REQUESTED`, `DISPATCHED` or `ON_SITE`, the request is refused with
    `ERR_LABOR_CALL_OVERLAP` when the new `scheduled_start` falls strictly
    before the existing call's `scheduled_end` extended forward by
    `turnaround_buffer_minutes` **and** the existing `scheduled_start` falls
    strictly before the new `scheduled_end` extended forward by the same
    buffer."
    PRD §3.7: "Calls may be listed and filtered by `booth_id`,
    `jurisdiction_id`, `service_order_id` and `status`."

    Design: Difficulty/resource_temporal_overlap/labor_crew_buffered_interval_overlap_rejects
    """
    ground = setup_requested_labor_call(show_status="ON_SITE",
                                        jurisdiction_overrides=RIGGING_TERMS,
                                        call_overrides=MONDAY_CALL)
    booth_id = ground["booth"]["id"]
    first_id = ground["labor_call"]["id"]

    response = api.create_labor_call(
        create_labor_call_payload(booth_id, ground["jurisdiction"]["id"],
                                  scheduled_start="2026-09-21T17:20:00Z",
                                  scheduled_end="2026-09-21T20:00:00Z",
                                  crew_size=4),
        OPS)
    validate_error(response, ApiErrorId.ERR_LABOR_CALL_OVERLAP.value, 409)

    first = get_labor_call(first_id)
    assert first["status"] == "REQUESTED", \
        f"the sitting call is untouched by the refusal, got {first['status']}"

    rows, meta = validate_paginated(
        api.list_labor_calls(OPS, {"booth_id": booth_id}))
    assert meta["total_count"] == 1, \
        f"the refused call must not persist, got {meta['total_count']} rows"
    assert [row["id"] for row in rows] == [first_id], \
        "only the original call may remain on the booth"


# ---------------------------------------------------------------------------
# Committed crew-hours: the conserved quantity round trip
# ---------------------------------------------------------------------------

def test_dispatch_commits_crew_hours_and_cancel_returns_the_show_to_zero():
    """PRD §3.7: "`Show.committed_labor_hours` is a full recomputation over the
    show's calls: it sums, for every labor call reachable through a booth of
    this show whose `status` is `DISPATCHED` or `ON_SITE`, that call's
    `crew_size` multiplied by its `scheduled_hours`, with the final sum rounded
    half up to two decimal places."
    PRD §3.7: "Calls still `REQUESTED` are not yet committed, and calls that
    have reached `COMPLETED`, `NO_SHOW` or `CANCELLED` are no longer
    committed."
    PRD §2.11: "None of them is maintained as an incremental delta, because a
    forward action and its compensating reversal must land the aggregate back
    on exactly the figure it held before — issuing and then voiding an invoice
    is a perfect round trip, and checking a crate in and then moving it out
    returns a warehouse's committed weight to its prior value."

    Design: Difficulty/compensating_invariant/labor_dispatch_then_cancel_conserves_committed_labor_hours
    """
    ground = setup_requested_labor_call(show_status="ON_SITE",
                                        jurisdiction_overrides=RIGGING_TERMS,
                                        call_overrides=MONDAY_CALL)
    show_id = ground["show"]["id"]
    call_id = ground["labor_call"]["id"]

    assert ground["labor_call"]["scheduled_hours"] == pytest.approx(4.00, abs=0.01), \
        f"13:00 to 17:00 is 4.00 scheduled hours, got {ground['labor_call']['scheduled_hours']}"
    assert get_show(show_id)["committed_labor_hours"] == pytest.approx(0.00, abs=0.01), \
        "a merely REQUESTED call commits no crew-hours to the show"

    dispatch_labor_call(call_id)
    assert get_show(show_id)["committed_labor_hours"] == pytest.approx(16.00, abs=0.01), \
        "dispatching 4 workers for 4.00 hours commits 16.00 crew-hours"

    cancel_labor_call(call_id, reason="Exhibitor deferred the hang")
    assert get_show(show_id)["committed_labor_hours"] == pytest.approx(0.00, abs=0.01), \
        "cancelling the dispatched call returns committed crew-hours to exactly 0.00"


def test_cancelling_a_dispatched_call_bumps_the_one_way_counter_and_bills_nothing():
    """PRD §3.7: "Either way the show's `cancelled_labor_call_count` increases
    by one and its `committed_labor_hours` are recomputed — which releases the
    crew-hours when the call had been `DISPATCHED` and changes nothing when it
    was merely `REQUESTED`, since a requested call never contributed."
    PRD §3.7: "A cancelled call's `labor_charge_cents` stays null: nothing is
    billed."

    Design: Difficulty/compensating_invariant/labor_dispatch_then_cancel_conserves_committed_labor_hours
    """
    ground = setup_requested_labor_call(show_status="ON_SITE",
                                        jurisdiction_overrides=RIGGING_TERMS,
                                        call_overrides=MONDAY_CALL)
    show_id = ground["show"]["id"]
    call_id = ground["labor_call"]["id"]

    assert get_show(show_id)["cancelled_labor_call_count"] == 0, \
        "the show opens with no cancelled labor calls"

    dispatch_labor_call(call_id)
    cancel_labor_call(call_id, reason="Exhibitor deferred the hang")

    show = get_show(show_id)
    assert show["cancelled_labor_call_count"] == 1, \
        f"the one-way counter records the release, got {show['cancelled_labor_call_count']}"
    assert show["committed_labor_hours"] == pytest.approx(0.00, abs=0.01), \
        "the counter rises while the conserved crew-hours fall back to 0.00"

    call = get_labor_call(call_id)
    assert call["status"] == "CANCELLED", \
        f"the released call rests in CANCELLED, got {call['status']}"
    assert call["labor_charge_cents"] is None, \
        f"a cancelled call bills nothing, got {call['labor_charge_cents']}"


# ---------------------------------------------------------------------------
# Band allocation and minimum-call padding
# ---------------------------------------------------------------------------

def test_monday_call_splits_bands_and_pads_into_the_last_worked_band():
    """PRD §3.7: "The elapsed time from `actual_start` to `actual_end` is taken
    in whole minutes; that minute count is divided by sixty and rounded **up**
    to the next half hour."
    PRD §3.7: "`billed_hours` is the greater of the jurisdiction's
    `min_call_hours` and that rounded-up elapsed figure — a twenty-minute call
    under a four-hour minimum bills four hours."
    PRD §3.7: "A minute counts as straight time when its time of day falls at
    or after the venue's `straight_time_start_hhmm` and strictly before its
    `straight_time_end_hhmm`; every other minute counts as overtime."
    PRD §3.7: "All of that padding goes to the band containing the **last
    worked minute** — the minute that begins one minute before `actual_end`."
    PRD §3.7: "Padding is never split across the two bands and is never
    assigned to the band containing `actual_start`."
    PRD §3.1: "The straight-time labor band is declared as two UTC times of day
    in `HH:MM` form: `straight_time_start_hhmm`, defaulting to `08:00`, and
    `straight_time_end_hhmm`, defaulting to `16:30`, whose instant is the
    exclusive end of the band."

    Design: Corner/calculations/labor_billing_splits_bands_and_pads_into_the_last_worked_band
    """
    ground = setup_worked_labor_call("2026-09-21T14:00:00Z", "2026-09-21T17:15:00Z",
                                     show_status="ON_SITE",
                                     jurisdiction_overrides=RIGGING_TERMS,
                                     call_overrides=MONDAY_CALL)
    call = ground["labor_call"]

    assert_labor_call(call)
    assert call["status"] == "COMPLETED", \
        f"the worked call closes in COMPLETED, got {call['status']}"
    assert call["billed_hours"] == pytest.approx(4.00, abs=0.01), \
        f"3.25 elapsed hours round up to 3.5 and the 4 hour minimum wins, got {call['billed_hours']}"
    assert call["st_hours"] == pytest.approx(2.50, abs=0.01), \
        f"14:00 to 16:30 is 2.50 straight-time hours, got {call['st_hours']}"
    assert call["ot_hours"] == pytest.approx(1.50, abs=0.01), \
        f"0.75 worked overtime hours plus the whole 45 minute pad is 1.50, got {call['ot_hours']}"
    assert call["dt_hours"] == pytest.approx(0.00, abs=0.01), \
        f"a Monday call carries no double time, got {call['dt_hours']}"


def test_completed_call_charge_rounds_once_and_releases_the_committed_hours():
    """PRD §3.7: "`labor_charge_cents` is then the `crew_size` multiplied by the
    sum of three band products: `st_hours` times the jurisdiction's
    `straight_time_rate_cents_per_hour`, plus `ot_hours` times that same rate
    times the jurisdiction's `overtime_multiplier`, plus `dt_hours` times that
    same rate times the jurisdiction's `doubletime_multiplier`."
    PRD §3.7: "The crew multiplication and the three products are carried in
    exact arithmetic and the single final figure is rounded half up to a whole
    cent exactly once at the end — the opposite discipline from service order
    lines, which round before they sum."
    PRD §3.7: "Completion also recomputes the show's committed crew-hours
    downward, since the call is no longer live."

    Design: Corner/calculations/labor_billing_splits_bands_and_pads_into_the_last_worked_band
    """
    ground = setup_worked_labor_call("2026-09-21T14:00:00Z", "2026-09-21T17:15:00Z",
                                     show_status="ON_SITE",
                                     jurisdiction_overrides=RIGGING_TERMS,
                                     call_overrides=MONDAY_CALL)
    call = ground["labor_call"]

    assert call["labor_charge_cents"] == 266000, \
        f"4 workers over 2.50 straight and 1.50 overtime hours bill 266000 cents, " \
        f"got {call['labor_charge_cents']}"

    show = get_show(ground["show"]["id"])
    assert show["committed_labor_hours"] == pytest.approx(0.00, abs=0.01), \
        f"a COMPLETED call is no longer committed, got {show['committed_labor_hours']}"


# ---------------------------------------------------------------------------
# The Sunday override
# ---------------------------------------------------------------------------

def test_sunday_start_bills_the_whole_call_as_double_time():
    """PRD §3.7: "There is one override: when `actual_start` falls on a Sunday
    in UTC, the entire call is double time, `st_hours` and `ot_hours` are both
    zero, and `dt_hours` equals `billed_hours`."
    PRD §3.7: "The override is decided by `actual_start` alone, so a call that
    begins on a Saturday evening and ends on Sunday morning is not double
    time."
    PRD §3.7: "`labor_charge_cents` is then the `crew_size` multiplied by the
    sum of three band products: `st_hours` times the jurisdiction's
    `straight_time_rate_cents_per_hour`, plus `ot_hours` times that same rate
    times the jurisdiction's `overtime_multiplier`, plus `dt_hours` times that
    same rate times the jurisdiction's `doubletime_multiplier`."

    Design: Corner/calculations/labor_sunday_doubletime_override_ignores_bands
    """
    # 2026-09-20 is a Sunday, inside the move-in envelope that opens Saturday.
    ground = setup_worked_labor_call("2026-09-20T14:00:00Z", "2026-09-20T17:15:00Z",
                                     show_status="ON_SITE",
                                     jurisdiction_overrides=RIGGING_TERMS,
                                     call_overrides={
                                         "scheduled_start": "2026-09-20T13:00:00Z",
                                         "scheduled_end": "2026-09-20T17:00:00Z",
                                         "crew_size": 4,
                                     })
    call = ground["labor_call"]

    assert_labor_call(call)
    assert call["billed_hours"] == pytest.approx(4.00, abs=0.01), \
        f"the four hour minimum still fixes billed_hours, got {call['billed_hours']}"
    assert call["dt_hours"] == pytest.approx(4.00, abs=0.01), \
        f"dt_hours equals billed_hours on a Sunday call, got {call['dt_hours']}"
    assert call["st_hours"] == pytest.approx(0.00, abs=0.01), \
        f"the Sunday override zeroes straight time, got {call['st_hours']}"
    assert call["ot_hours"] == pytest.approx(0.00, abs=0.01), \
        f"the Sunday override zeroes overtime, got {call['ot_hours']}"
    assert call["labor_charge_cents"] == 448000, \
        f"4 workers times 4.00 hours times 14000 cents times 2.0 is 448000 cents, " \
        f"got {call['labor_charge_cents']}"


# ---------------------------------------------------------------------------
# The no-show path
# ---------------------------------------------------------------------------

def test_no_show_completion_bills_the_minimum_call_and_restricts_the_booth():
    """PRD §3.7: "An `outcome` of `NO_SHOW` advances `DISPATCHED → NO_SHOW` and
    takes a different billing path entirely."
    PRD §3.7: "No interval exists, so bands, padding and the Sunday override are
    not consulted at all: `labor_charge_cents` is simply `crew_size` multiplied
    by the jurisdiction's `min_call_hours` multiplied by its
    `straight_time_rate_cents_per_hour`, rounded half up."
    PRD §3.7: "The show's committed crew-hours are recomputed downward, and the
    booth recomputes posture, landing on `RESTRICTED` with `posture_reason`
    `LABOR_NO_SHOW` unless a freezing clause outranks it — which is why a
    no-show blocks the next dispatch at that booth until the situation is
    resolved."
    PRD §3.7: "The call is born `REQUESTED` with `actual_start`, `actual_end`,
    `billed_hours`, `st_hours`, `ot_hours`, `dt_hours` and `labor_charge_cents`
    all null."

    Design: Corner/state_machines/no_show_completion_bills_minimum_call_and_restricts_the_booth
    """
    ground = setup_requested_labor_call(show_status="ON_SITE",
                                        jurisdiction_overrides=RIGGING_TERMS,
                                        call_overrides=MONDAY_CALL)
    call_id = ground["labor_call"]["id"]

    dispatched = dispatch_labor_call(call_id)
    assert dispatched["scheduled_hours"] == pytest.approx(4.00, abs=0.01), \
        f"the dispatched call carries 4.00 scheduled hours, got {dispatched['scheduled_hours']}"

    call = complete_labor_call(call_id, outcome="NO_SHOW")

    assert call["status"] == "NO_SHOW", \
        f"the crew that never arrived closes the call NO_SHOW, got {call['status']}"
    assert call["labor_charge_cents"] == 224000, \
        f"4 workers times the 4 hour minimum times 14000 cents is 224000 cents, " \
        f"got {call['labor_charge_cents']}"
    assert call["billed_hours"] is None, \
        f"the no-show path never computes billed_hours, got {call['billed_hours']}"

    show = get_show(ground["show"]["id"])
    assert show["committed_labor_hours"] == pytest.approx(0.00, abs=0.01), \
        f"a NO_SHOW call releases its crew-hours, got {show['committed_labor_hours']}"

    assert_posture(get_booth(ground["booth"]["id"]), "RESTRICTED", "LABOR_NO_SHOW")


# ---------------------------------------------------------------------------
# Cancelling a terminal call
# ---------------------------------------------------------------------------

def test_cancelling_a_completed_call_is_refused_as_an_invalid_transition(api):
    """PRD §3.7: "Cancellation is available from `REQUESTED` and from
    `DISPATCHED`, either by explicit request from a `LaborSupervisor` or
    `ShowOperations` with an optional `reason`, or as a cascade when the call's
    service order enters `HELD` or `CANCELLED`."
    PRD §2.9: "A check is only reached when every check above it has passed."
    PRD §2.9: "The target sits in a from-state the requested transition declares
    — otherwise `ERR_INVALID_STATE_TRANSITION` (409)."
    PRD §2.9: "The target is not already in a terminal state of its machine —
    otherwise `ERR_ENTITY_TERMINAL` (409)."
    PRD §3.7: "`COMPLETED`, `NO_SHOW` and `CANCELLED` are all terminal."

    A COMPLETED call trips both rung 10 and rung 11 at once and the PRD does not
    settle which of the two 409 identifiers wins: the ladder puts rung 10 first,
    while §3.1 states that "requesting any transition out of `CLOSED` or
    `CANCELLED` is refused with `ERR_ENTITY_TERMINAL`" — a reading under which
    rung 11 pre-empts rung 10 for terminal sources. Either identifier is
    PRD-faithful, so both are accepted; every observable side effect below is
    asserted exactly.

    Design: Corner/state_machines/cancel_labor_call_already_completed_returns_invalid_state
    """
    ground = setup_worked_labor_call("2026-09-21T09:00:00Z", "2026-09-21T13:00:00Z",
                                     show_status="ON_SITE",
                                     jurisdiction_overrides=RIGGING_TERMS,
                                     call_overrides=MONDAY_CALL)
    call_id = ground["labor_call"]["id"]

    response = api.cancel_labor_call(call_id, {"reason": "Too late"}, LABOR)
    validate_error_is_one_of(response, [
        ApiErrorId.ERR_INVALID_STATE_TRANSITION.value,
        ApiErrorId.ERR_ENTITY_TERMINAL.value,
    ])
    assert response.status_code == 409, (
        "Both admissible identifiers carry HTTP 409, got "
        f"{response.status_code}")

    call = get_labor_call(call_id)
    assert call["status"] == "COMPLETED", \
        f"the refused cancellation leaves the call COMPLETED, got {call['status']}"
    assert call["billed_hours"] == pytest.approx(4.00, abs=0.01), \
        f"the worked 09:00 to 13:00 window still bills 4.00 hours, got {call['billed_hours']}"
    assert call["labor_charge_cents"] == 224000, \
        f"the settled charge does not move, got {call['labor_charge_cents']}"

    show = get_show(ground["show"]["id"])
    assert show["cancelled_labor_call_count"] == 0, \
        f"a refused cancellation counts for nothing, got {show['cancelled_labor_call_count']}"


# ---------------------------------------------------------------------------
# Request-time guards
# ---------------------------------------------------------------------------

def test_crew_window_past_move_out_end_is_refused(api):
    """PRD §3.7: "The window must be well formed and inside the show envelope:
    `scheduled_start` must be strictly earlier than `scheduled_end`, and the
    whole interval must lie within the show's `move_in_start` through
    `move_out_end` inclusive, or the request is refused with
    `ERR_LABOR_WINDOW_OUTSIDE_SHOW`."
    PRD §2.9: "The requested crew window is well formed and inside the show
    envelope — otherwise `ERR_LABOR_WINDOW_OUTSIDE_SHOW` (422)."

    Design: Corner/validations/labor_window_outside_show_envelope_rejected
    """
    ground = setup_labor_ground(show_status="ON_SITE",
                                jurisdiction_overrides=RIGGING_TERMS)
    booth_id = ground["booth"]["id"]

    # move_out_end is 2026-09-25T18:00:00Z, so a 26 September window is outside.
    response = api.create_labor_call(
        create_labor_call_payload(booth_id, ground["jurisdiction"]["id"],
                                  scheduled_start="2026-09-26T08:00:00Z",
                                  scheduled_end="2026-09-26T12:00:00Z",
                                  crew_size=4),
        OPS)
    validate_error(response, ApiErrorId.ERR_LABOR_WINDOW_OUTSIDE_SHOW.value, 422)

    rows, meta = validate_paginated(
        api.list_labor_calls(OPS, {"booth_id": booth_id}))
    assert meta["total_count"] == 0, \
        f"the refused window must leave no call behind, got {meta['total_count']}"
    assert rows == [], "no labor call may be persisted for a refused window"


def test_crew_size_above_the_jurisdiction_maximum_is_refused(api):
    """PRD §3.7: "And the crew must be a legal size: `crew_size` must be at
    least 1 and no greater than the jurisdiction's `crew_max_size`, or the
    request is refused with `ERR_CREW_SIZE_LIMIT`."
    PRD §2.9: "Crew size within the jurisdiction's bounds — otherwise
    `ERR_CREW_SIZE_LIMIT` (422)."

    Design: Corner/validations/crew_size_above_jurisdiction_maximum_rejected
    """
    ground = setup_labor_ground(show_status="ON_SITE",
                                jurisdiction_overrides=RIGGING_TERMS)
    booth_id = ground["booth"]["id"]

    # Nine workers against a six worker cap, on a booth carrying no other call.
    response = api.create_labor_call(
        create_labor_call_payload(booth_id, ground["jurisdiction"]["id"],
                                  scheduled_start="2026-09-21T13:00:00Z",
                                  scheduled_end="2026-09-21T17:00:00Z",
                                  crew_size=9),
        OPS)
    validate_error(response, ApiErrorId.ERR_CREW_SIZE_LIMIT.value, 422)

    rows, meta = validate_paginated(
        api.list_labor_calls(OPS, {"booth_id": booth_id}))
    assert meta["total_count"] == 0, \
        f"an oversized crew must not be recorded, got {meta['total_count']} rows"
    assert rows == [], "no labor call may be persisted for an oversized crew"


def test_jurisdiction_from_another_venue_is_refused(api):
    """PRD §3.7: "The craft must belong to the right building: the named
    jurisdiction's `venue_id` must equal the `venue_id` of the show reached from
    the booth, or the request is refused with `ERR_JURISDICTION_VENUE_MISMATCH`."
    PRD §3.1: "Each venue owns a set of **Union Jurisdictions**, created beneath
    the venue in the URL hierarchy so that `venue_id` is taken from the creation
    path rather than from the body — a jurisdiction is scoped to exactly one
    venue."
    PRD §2.9: "The jurisdiction belongs to the venue hosting the booth's show —
    otherwise `ERR_JURISDICTION_VENUE_MISMATCH` (422)."

    Design: Corner/errors/jurisdiction_venue_mismatch_surfaces_on_its_own
    """
    ground = setup_labor_ground(show_status="ON_SITE",
                                jurisdiction_overrides=RIGGING_TERMS)
    booth_id = ground["booth"]["id"]

    other_venue = create_venue(name="Lakeside Expo Hall", city="Milwaukee",
                               max_forklift_capacity_lbs=6000)
    foreign_terms = dict(RIGGING_TERMS, exhibitor_self_install_allowed=True)
    foreign_jurisdiction = create_jurisdiction(other_venue["id"], **foreign_terms)

    # self_install_requested stays false so the union safety rule cannot mask
    # the mismatch that sits below it on the ladder.
    response = api.create_labor_call(
        create_labor_call_payload(booth_id, foreign_jurisdiction["id"],
                                  scheduled_start="2026-09-21T13:00:00Z",
                                  scheduled_end="2026-09-21T17:00:00Z",
                                  crew_size=4,
                                  self_install_requested=False),
        OPS)
    validate_error(response, ApiErrorId.ERR_JURISDICTION_VENUE_MISMATCH.value, 422)

    rows, meta = validate_paginated(
        api.list_labor_calls(OPS, {"booth_id": booth_id}))
    assert meta["total_count"] == 0, \
        f"a foreign craft must not be booked, got {meta['total_count']} rows"
    assert rows == [], "no labor call may be persisted for a foreign jurisdiction"
