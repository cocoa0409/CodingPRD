"""Assessment-center sessions: booking gates, slot capacity pools keyed on the
exact start instant, the seat compensating invariant, completion cascade hop 1,
and the clock-driven NO_SHOW sweep."""
from datetime import datetime, timedelta

import pytest

from test_helpers import (
    BOARD,
    SCORING_ADMIN,
    SESSION_DURATION_MINUTES,
    STANDARD_COMPLETION_CLOCK,
    STANDARD_SLOT_START,
    ApiErrorId,
    BookingStatus,
    CertificationStatus,
    SubmissionStatus,
    assert_booking,
    booking_transition_payload,
    create_assessment_center,
    create_booking_for_assessment,
    create_booking_payload,
    create_eligible_candidate,
    create_eligible_candidate_with_assessment_submission,
    create_open_cycle,
    expected_weighted_total,
    get_certification_for,
    make_candidate_headers,
    score_assessment_component,
    set_logical_clock,
    validate_created,
    validate_error,
    validate_paginated,
    validate_success,
)

SECOND_SLOT_START = "2027-01-21T14:00:00Z"
OFFSET_SLOT_START = "2027-01-20T14:30:00Z"  # overlaps the 14:00 session in time
PAST_SLOT_END_CLOCK = "2027-01-20T16:01:00Z"  # 14:00 slot + 120 min = 16:00 end
PAST_SLOT_START = "2027-01-05T14:00:00Z"  # before the 2027-01-10 work clock
PAST_WINDOW_CLOSE_SLOT = "2027-03-05T14:00:00Z"  # after the 2027-03-01 close


def _parse_iso(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _setup_single_booking(api, slot_capacity=5, slot_start_at=STANDARD_SLOT_START):
    """OPEN cycle + ELIGIBLE candidate with an IN_PROGRESS CKA attempt + center +
    one BOOKED booking. Returns (cycle, candidate, submission, center, booking)."""
    cycle = create_open_cycle()
    candidate, submission = create_eligible_candidate_with_assessment_submission(cycle["id"])
    center = create_assessment_center(slot_capacity=slot_capacity)
    booking = create_booking_for_assessment(
        cycle["id"], candidate, center["id"], slot_start_at=slot_start_at
    )
    return cycle, candidate, submission, center, booking


def _three_candidates_with_cka(cycle_id: str) -> list:
    return [
        create_eligible_candidate_with_assessment_submission(cycle_id)[0]
        for _ in range(3)
    ]


def test_booking_cancel_twice_terminal_lockdown(api):
    """PRD §3.4: "From `BOOKED`, three exits exist, and any transition requested
    from a status other than `BOOKED` is `ERR_BOOKING_NOT_TRANSITIONABLE`
    (HTTP 409)."
    PRD §3.4: "`COMPLETED`, `CANCELLED`, and `NO_SHOW` are all terminal."

    Design: Corner/state_machines/booking_cancel_twice_terminal_lockdown
    """
    cycle, candidate, _sub, center, booking = _setup_single_booking(api)
    headers = make_candidate_headers(candidate["id"])

    cancelled = validate_success(
        api.transition_booking(booking["id"], booking_transition_payload("CANCELLED"), headers)
    )
    assert cancelled["status"] == BookingStatus.CANCELLED.value

    response = api.transition_booking(
        booking["id"], booking_transition_payload("CANCELLED"), headers
    )
    validate_error(response, ApiErrorId.ERR_BOOKING_NOT_TRANSITIONABLE)

    rows, meta = validate_paginated(
        api.list_bookings(BOARD, params={"center_id": center["id"], "status": "BOOKED"})
    )
    assert meta["total_count"] == 0, "the seat was freed exactly once"


def test_clock_sweep_marks_booking_no_show(api):
    """PRD §2.4: "Advancing the clock performs exactly two sweeps, and no others.
    First, any assessment booking still in `BOOKED` status whose `slot_end_at` the
    new clock has passed flips to `NO_SHOW`."
    PRD §3.4: "A created booking starts `BOOKED`, occupies one seat of its (center,
    slot start) pool, and its `slot_end_at` is computed as `slot_start_at` plus 120
    minutes, the fixed session duration."

    Design: Corner/state_machines/clock_sweep_marks_booking_no_show
    """
    _cycle, _candidate, _sub, _center, booking = _setup_single_booking(api)
    assert _parse_iso(booking["slot_end_at"]) == _parse_iso(
        booking["slot_start_at"]
    ) + timedelta(minutes=SESSION_DURATION_MINUTES)

    set_logical_clock(PAST_SLOT_END_CLOCK)

    reread = validate_success(api.get_booking(booking["id"], BOARD))
    assert reread["status"] == BookingStatus.NO_SHOW.value


def test_booking_slot_in_past_rejected(api):
    """PRD §3.4: "`slot_start_at` must be strictly after the logical clock, else
    `ERR_SLOT_IN_PAST` (HTTP 422)".

    Design: Corner/validations/booking_slot_in_past_rejected
    """
    cycle = create_open_cycle()
    candidate, _sub = create_eligible_candidate_with_assessment_submission(cycle["id"])
    center = create_assessment_center()

    response = api.create_booking(
        create_booking_payload(center["id"], cycle["id"], PAST_SLOT_START),
        make_candidate_headers(candidate["id"]),
    )

    validate_error(response, ApiErrorId.ERR_SLOT_IN_PAST)


def test_booking_slot_after_window_close_rejected(api):
    """PRD §3.4: "it must be no later than the cycle's `submission_window_close`,
    else `ERR_SLOT_OUTSIDE_WINDOW` (HTTP 422)".

    Design: Corner/validations/booking_slot_after_window_close_rejected
    """
    cycle = create_open_cycle()
    candidate, _sub = create_eligible_candidate_with_assessment_submission(cycle["id"])
    center = create_assessment_center()

    response = api.create_booking(
        create_booking_payload(center["id"], cycle["id"], PAST_WINDOW_CLOSE_SLOT),
        make_candidate_headers(candidate["id"]),
    )

    validate_error(response, ApiErrorId.ERR_SLOT_OUTSIDE_WINDOW)


def test_booking_second_active_booking_rejected(api):
    """PRD §3.4: "and the candidate may hold at most one `BOOKED` booking per
    cycle, else `ERR_ACTIVE_BOOKING_EXISTS` (HTTP 409)."

    After the first booking is cancelled the constraint clears and a fresh
    booking succeeds.

    Design: Corner/validations/booking_second_active_booking_rejected
    """
    cycle, candidate, _sub, center, booking = _setup_single_booking(api)
    headers = make_candidate_headers(candidate["id"])

    response = api.create_booking(
        create_booking_payload(center["id"], cycle["id"], SECOND_SLOT_START), headers
    )
    validate_error(response, ApiErrorId.ERR_ACTIVE_BOOKING_EXISTS)

    validate_success(
        api.transition_booking(booking["id"], booking_transition_payload("CANCELLED"), headers)
    )
    rebooked = validate_created(
        api.create_booking(
            create_booking_payload(center["id"], cycle["id"], SECOND_SLOT_START), headers
        )
    )
    assert rebooked["status"] == BookingStatus.BOOKED.value


def test_booking_complete_before_slot_rejected(api):
    """PRD §3.4: "completion is only legal once the logical clock has reached
    `slot_start_at` — earlier is `ERR_BOOKING_NOT_COMPLETABLE` (HTTP 409) — the
    `earned_score` must be supplied (omitting it is `ERR_INVALID_REQUEST`) and must
    sit on the 0.25 grid within [0.00, 4.00] (`ERR_SCORE_INVALID`), and the score is
    recorded on the booking."

    The work clock 2027-01-10 is still ahead of the 2027-01-20 slot.

    Design: Corner/validations/booking_complete_before_slot_rejected
    """
    _cycle, _candidate, _sub, _center, booking = _setup_single_booking(api)

    response = api.transition_booking(
        booking["id"],
        booking_transition_payload("COMPLETED", earned_score=3.00),
        SCORING_ADMIN,
    )

    validate_error(response, ApiErrorId.ERR_BOOKING_NOT_COMPLETABLE)
    reread = validate_success(api.get_booking(booking["id"], BOARD))
    assert reread["status"] == BookingStatus.BOOKED.value
    assert reread["earned_score"] is None


def test_booking_completion_scores_assessment_submission(api):
    """PRD §3.4: "Hop 1: the candidate's matching `ASSESSMENT` attempt for that
    cycle — the latest attempt in `IN_PROGRESS` or `RETURNED` — transitions straight
    to `SCORED` with its `final_score` set to the booking's `earned_score`; an
    assessment component has exactly one score source, so no reads or averaging
    apply."
    PRD §3.7: "`weighted_total_provisional` lives on the certification at all
    times, starts at 0.0, is recomputed on every score event and every retake
    creation, and uses each component's **latest-attempt** `final_score`, treating
    a component whose latest attempt is unscored as 0 — so a worse retake drags the
    provisional total down."
    PRD §3.7: "A certification stays `PENDING` while any component remains
    unscored".

    Design: Corner/endpoints/booking_completion_scores_assessment_submission
    """
    cycle = create_open_cycle()
    candidate = create_eligible_candidate()
    center = create_assessment_center()

    result = score_assessment_component(
        cycle["id"], candidate, center["id"], earned_score=3.00
    )

    booking = result["booking"]
    assert_booking(booking)
    assert booking["status"] == BookingStatus.COMPLETED.value
    assert booking["earned_score"] == 3.00

    scored_submission = result["submission"]
    assert scored_submission["status"] == SubmissionStatus.SCORED.value
    assert scored_submission["final_score"] == 3.00

    certification = get_certification_for(candidate["id"], cycle["id"])
    expected = expected_weighted_total([(3.00, 0.40), (0.0, 0.20), (0.0, 0.20), (0.0, 0.20)])
    assert expected == 1.20
    assert certification["weighted_total_provisional"] == pytest.approx(expected)
    assert certification["status"] == CertificationStatus.PENDING.value
    assert certification["weighted_total_final"] is None


def test_booking_create_immediately_visible_with_computed_slot_end(api):
    """PRD §3.4: "A created booking starts `BOOKED`, occupies one seat of its
    (center, slot start) pool, and its `slot_end_at` is computed as `slot_start_at`
    plus 120 minutes, the fixed session duration."

    The version comparison asserts POST/GET agreement (immediate consistency);
    the PRD pins that version increments on mutation, not the initial value.

    Design: Corner/consistency model/booking_create_immediately_visible_with_computed_slot_end
    """
    cycle = create_open_cycle()
    candidate, _sub = create_eligible_candidate_with_assessment_submission(cycle["id"])
    center = create_assessment_center()

    booking = validate_created(
        api.create_booking(
            create_booking_payload(center["id"], cycle["id"], STANDARD_SLOT_START),
            make_candidate_headers(candidate["id"]),
        )
    )

    assert_booking(booking)
    assert booking["status"] == BookingStatus.BOOKED.value
    assert _parse_iso(booking["slot_end_at"]) == _parse_iso(
        STANDARD_SLOT_START
    ) + timedelta(minutes=SESSION_DURATION_MINUTES)

    reread = validate_success(api.get_booking(booking["id"], BOARD))
    assert reread["status"] == booking["status"]
    assert reread["slot_end_at"] == booking["slot_end_at"]
    assert reread["version"] == booking["version"]


def test_slot_capacity_exactly_full_rejects_next_booking(api):
    """PRD §3.4: "Capacity is the last gate: the occupied count for a pool is the
    number of `BOOKED` bookings at that center with exactly that `slot_start_at`,
    and a booking that would push the occupied count to equal `slot_capacity` is
    rejected with `ERR_SLOT_CAPACITY_FULL` (HTTP 409) — a pool with exactly one
    seat free still accepts the booking."

    Boundary: at capacity 2 the second booking lands (occupied becomes exactly 2);
    the third is refused.

    Design: Difficulty/boundary_precision_check/slot_capacity_exactly_full_rejects_next_booking
    """
    cycle = create_open_cycle()
    center = create_assessment_center(slot_capacity=2)
    cand1, cand2, cand3 = _three_candidates_with_cka(cycle["id"])

    booking1 = create_booking_for_assessment(cycle["id"], cand1, center["id"])
    booking2 = create_booking_for_assessment(cycle["id"], cand2, center["id"])
    assert booking1["status"] == BookingStatus.BOOKED.value
    assert booking2["status"] == BookingStatus.BOOKED.value

    response = api.create_booking(
        create_booking_payload(center["id"], cycle["id"], STANDARD_SLOT_START),
        make_candidate_headers(cand3["id"]),
    )
    validate_error(response, ApiErrorId.ERR_SLOT_CAPACITY_FULL)


def test_slot_capacity_full_pool_lists_exactly_capacity_bookings(api):
    """PRD §3.4: "Capacity is the last gate: the occupied count for a pool is the
    number of `BOOKED` bookings at that center with exactly that `slot_start_at`,
    and a booking that would push the occupied count to equal `slot_capacity` is
    rejected with `ERR_SLOT_CAPACITY_FULL` (HTTP 409) — a pool with exactly one
    seat free still accepts the booking."

    The full pool reads back as exactly slot_capacity BOOKED rows.

    Design: Difficulty/boundary_precision_check/slot_capacity_exactly_full_rejects_next_booking
    """
    cycle = create_open_cycle()
    center = create_assessment_center(slot_capacity=2)
    cand1, cand2, _cand3 = _three_candidates_with_cka(cycle["id"])
    create_booking_for_assessment(cycle["id"], cand1, center["id"])
    create_booking_for_assessment(cycle["id"], cand2, center["id"])

    rows, meta = validate_paginated(
        api.list_bookings(BOARD, params={"center_id": center["id"], "status": "BOOKED"})
    )

    assert meta["total_count"] == 2
    assert len(rows) == 2
    for row in rows:
        assert row["status"] == BookingStatus.BOOKED.value
        assert row["slot_start_at"] == rows[0]["slot_start_at"]


def test_slot_pools_keyed_by_exact_start_instant(api):
    """PRD §2.7: "Capacity for a booking pools on the **exact** `slot_start_at`
    instant: two bookings thirty minutes apart draw from different pools even
    though their 120-minute sessions overlap in time. This is a deliberate contrast
    with cycle windows, which use half-open, adjacency-allowed semantics."

    Capacity 1: the 14:00 pool fills with the first booking; the 14:30 booking
    still succeeds because it draws from a different pool.

    Design: Difficulty/resource_temporal_overlap/slot_capacity_pools_by_exact_start_instant
    """
    cycle = create_open_cycle()
    center = create_assessment_center(slot_capacity=1)
    cand1, cand2, _cand3 = _three_candidates_with_cka(cycle["id"])

    booking1 = create_booking_for_assessment(
        cycle["id"], cand1, center["id"], slot_start_at=STANDARD_SLOT_START
    )
    booking2 = create_booking_for_assessment(
        cycle["id"], cand2, center["id"], slot_start_at=OFFSET_SLOT_START
    )

    assert booking1["status"] == BookingStatus.BOOKED.value
    assert booking2["status"] == BookingStatus.BOOKED.value


def test_slot_pools_reject_second_booking_at_same_instant(api):
    """PRD §2.7: "Capacity for a booking pools on the **exact** `slot_start_at`
    instant: two bookings thirty minutes apart draw from different pools even
    though their 120-minute sessions overlap in time. This is a deliberate contrast
    with cycle windows, which use half-open, adjacency-allowed semantics."
    PRD §3.4: "a booking that would push the occupied count to equal
    `slot_capacity` is rejected with `ERR_SLOT_CAPACITY_FULL` (HTTP 409)".

    The 14:00 pool is already full (1 == capacity), so the repeat instant fails.

    Design: Difficulty/resource_temporal_overlap/slot_capacity_pools_by_exact_start_instant
    """
    cycle = create_open_cycle()
    center = create_assessment_center(slot_capacity=1)
    cand1, _cand2, cand3 = _three_candidates_with_cka(cycle["id"])
    create_booking_for_assessment(
        cycle["id"], cand1, center["id"], slot_start_at=STANDARD_SLOT_START
    )

    response = api.create_booking(
        create_booking_payload(center["id"], cycle["id"], STANDARD_SLOT_START),
        make_candidate_headers(cand3["id"]),
    )

    validate_error(response, ApiErrorId.ERR_SLOT_CAPACITY_FULL)


def test_slot_seats_freed_on_cancel(api):
    """PRD §3.4: "The owning candidate may cancel — the transition request carries
    a `to` of CANCELLED, anyone other than the owning candidate attempting it is
    refused with `ERR_NOT_RESOURCE_OWNER`, and the cancellation frees one seat: the
    pool's occupied count decrements and its remaining capacity increments, a
    compensating invariant that holds across every create-and-cancel pair."

    Two bookings fill the pool (2 occupied); the cancel drops occupancy to 1.

    Design: Difficulty/compensating_invariant/slot_seats_conserved_across_booking_and_cancel
    """
    cycle = create_open_cycle()
    center = create_assessment_center(slot_capacity=2)
    cand1, cand2, _cand3 = _three_candidates_with_cka(cycle["id"])
    booking1 = create_booking_for_assessment(cycle["id"], cand1, center["id"])
    create_booking_for_assessment(cycle["id"], cand2, center["id"])

    _rows, meta_full = validate_paginated(
        api.list_bookings(BOARD, params={"center_id": center["id"], "status": "BOOKED"})
    )
    assert meta_full["total_count"] == 2

    cancelled = validate_success(
        api.transition_booking(
            booking1["id"],
            booking_transition_payload("CANCELLED"),
            make_candidate_headers(cand1["id"]),
        )
    )
    assert cancelled["status"] == BookingStatus.CANCELLED.value

    _rows, meta_after = validate_paginated(
        api.list_bookings(BOARD, params={"center_id": center["id"], "status": "BOOKED"})
    )
    assert meta_after["total_count"] == 1


def test_slot_seat_reusable_after_cancel(api):
    """PRD §3.4: "The owning candidate may cancel — the transition request carries
    a `to` of CANCELLED, anyone other than the owning candidate attempting it is
    refused with `ERR_NOT_RESOURCE_OWNER`, and the cancellation frees one seat: the
    pool's occupied count decrements and its remaining capacity increments, a
    compensating invariant that holds across every create-and-cancel pair."

    The freed seat accepts a new booking, and the cancelled row stays traceable
    through the listing filter.

    Design: Difficulty/compensating_invariant/slot_seats_conserved_across_booking_and_cancel
    """
    cycle = create_open_cycle()
    center = create_assessment_center(slot_capacity=2)
    cand1, cand2, cand3 = _three_candidates_with_cka(cycle["id"])
    booking1 = create_booking_for_assessment(cycle["id"], cand1, center["id"])
    create_booking_for_assessment(cycle["id"], cand2, center["id"])
    validate_success(
        api.transition_booking(
            booking1["id"],
            booking_transition_payload("CANCELLED"),
            make_candidate_headers(cand1["id"]),
        )
    )

    rebooked = validate_created(
        api.create_booking(
            create_booking_payload(center["id"], cycle["id"], STANDARD_SLOT_START),
            make_candidate_headers(cand3["id"]),
        )
    )
    assert rebooked["status"] == BookingStatus.BOOKED.value

    _rows, meta_booked = validate_paginated(
        api.list_bookings(BOARD, params={"center_id": center["id"], "status": "BOOKED"})
    )
    assert meta_booked["total_count"] == 2

    cancelled_rows, meta_cancelled = validate_paginated(
        api.list_bookings(BOARD, params={"center_id": center["id"], "status": "CANCELLED"})
    )
    assert meta_cancelled["total_count"] == 1
    assert cancelled_rows[0]["id"] == booking1["id"]
