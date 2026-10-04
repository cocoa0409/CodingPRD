"""Difficulty queue — temporal-overlap conflicts and compensating invariants.

Half-open testing-interval conflicts on exam windows and UTC date-equality
conflicts on course bookings (PRD §3.3, §3.7); seat-count and money
conservation across register/cancel/promote (PRD §3.3).
"""
from test_helpers import (
    ApiErrorId,
    FEE_EARLY_CENTS,
    SESSION_CODE,
    SESSION_CODE_NEXT_DAY,
    SESSION_CODE_SAME_DAY,
    SESSION_ENDS,
    SESSION_NEXT_DAY_ENDS,
    SESSION_NEXT_DAY_STARTS,
    SESSION_SAME_DAY_ENDS,
    SESSION_SAME_DAY_STARTS,
    SESSION_STARTS,
    WINDOW_CAPACITY_TIGHT,
    book_attendance,
    cancel_registration,
    create_exam_window_payload,
    get_success_data,
    get_window,
    make_active_exam,
    make_candidate,
    make_candidate_headers,
    make_registrar_headers,
    make_session,
    make_window,
    register,
    setup_associate,
    setup_open_window,
    setup_registered,
    validate_error,
    validate_success,
)


def test_overlapping_window_rejected(api):
    """PRD §3.3: "the new window's testing interval, treated as half-open from
    `testing_starts_at` up to but not including `testing_ends_at`, must not
    overlap the testing interval of any other window of the same exam ... An
    overlap is rejected with `ERR_WINDOW_SCHEDULE_CONFLICT`."

    Design: Difficulty/resource_temporal_overlap/same_exam_window_overlap_half_open
    """
    _, exam = make_active_exam(api)
    make_window(api, exam["id"], window_code="P-2026-10")
    resp = api.create_exam_window(
        create_exam_window_payload(
            exam["id"], window_code="P-2026-11",
            testing_starts_at="2026-10-12T12:00:00Z",
            testing_ends_at="2026-10-14T17:00:00Z"),
        make_registrar_headers())
    validate_error(resp, ApiErrorId.ERR_WINDOW_SCHEDULE_CONFLICT)


def test_adjacent_window_accepted(api):
    """PRD §3.3: "two windows whose intervals merely touch, one ending exactly
    when the other begins, are permitted."

    Design: Difficulty/resource_temporal_overlap/same_exam_window_overlap_half_open
    """
    _, exam = make_active_exam(api)
    make_window(api, exam["id"], window_code="P-2026-10")
    resp = api.create_exam_window(
        create_exam_window_payload(
            exam["id"], window_code="P-2026-12",
            testing_starts_at="2026-10-12T17:00:00Z",
            testing_ends_at="2026-10-15T17:00:00Z"),
        make_registrar_headers())
    created = validate_success(resp, 201)
    assert created["status"] == "SCHEDULED"
    assert created["testing_starts_at"].startswith("2026-10-12T17:00")


def test_same_day_session_booking_conflict(api):
    """PRD §3.7: "a candidate may not hold a `BOOKED` or `ATTENDED` attendance
    to any other session whose `starts_at` falls on the same UTC calendar date
    as this session's, a pure date-equality test rather than any interval
    overlap; a violation is rejected with `ERR_SESSION_SAME_DAY_CONFLICT`."

    Design: Difficulty/resource_temporal_overlap/course_booking_same_day_conflict
    """
    candidate = setup_associate(api)["candidate"]
    session1 = make_session(api, session_code=SESSION_CODE, starts_at=SESSION_STARTS,
                            ends_at=SESSION_ENDS)
    session2 = make_session(api, session_code=SESSION_CODE_SAME_DAY,
                            starts_at=SESSION_SAME_DAY_STARTS,
                            ends_at=SESSION_SAME_DAY_ENDS)
    first = book_attendance(api, session1["id"], candidate)
    assert first["status"] == "BOOKED"
    # Disjoint clock times on the same UTC calendar date still conflict.
    resp = api.create_course_attendance(
        {"course_session_id": session2["id"]}, make_candidate_headers(candidate["id"]))
    validate_error(resp, ApiErrorId.ERR_SESSION_SAME_DAY_CONFLICT)


def test_next_day_session_booking_succeeds(api):
    """PRD §3.7: "a candidate may not hold a `BOOKED` or `ATTENDED` attendance
    to any other session whose `starts_at` falls on the same UTC calendar date
    as this session's, a pure date-equality test rather than any interval
    overlap."

    Design: Difficulty/resource_temporal_overlap/course_booking_same_day_conflict
    """
    candidate = setup_associate(api)["candidate"]
    session1 = make_session(api, session_code=SESSION_CODE, starts_at=SESSION_STARTS,
                            ends_at=SESSION_ENDS)
    session3 = make_session(api, session_code=SESSION_CODE_NEXT_DAY,
                            starts_at=SESSION_NEXT_DAY_STARTS,
                            ends_at=SESSION_NEXT_DAY_ENDS)
    first = book_attendance(api, session1["id"], candidate)
    assert first["status"] == "BOOKED"
    third = book_attendance(api, session3["id"], candidate)
    assert third["status"] == "BOOKED"
    assert third["course_session_id"] == session3["id"]


def test_seats_held_at_capacity_waitlists(api):
    """PRD §3.3: "`seats_held` is the count of its registrations whose
    `logistics_status` is `REGISTERED` and is kept equal to that count at all
    times, and `waitlist_count` is the count of its `WAITLISTED`
    registrations."
    PRD §3.3: "when `seats_held` has reached `capacity` — the boundary is
    inclusive, so equality waitlists — the registration is `WAITLISTED`, and
    this overflow is expressly not an error."

    Design: Difficulty/compensating_invariant/seats_held_invariant_under_register_cancel_promote
    """
    ctx = setup_registered(api, num_candidates=2, capacity=WINDOW_CAPACITY_TIGHT)
    reg1, reg2 = ctx["registrations"]
    assert reg1["logistics_status"] == "REGISTERED"
    assert reg2["logistics_status"] == "WAITLISTED"
    assert reg2["fee_charged_cents"] is None
    window = get_window(api, ctx["window"]["id"])
    assert window["seats_held"] == 1
    assert window["waitlist_count"] == 1


def test_cancel_promotes_preserving_seats_held(api):
    """PRD §3.3: "Whenever a `REGISTERED` row is cancelled the window's
    `seats_held` is recomputed one seat down, and if the window is still
    `REGISTRATION_OPEN` that freed seat immediately promotes a waitlisted
    registration."
    PRD §3.3: "The promoted row becomes `REGISTERED` and its `fee_charged_cents`
    is computed by the same fee rule at the promotion timestamp."

    Design: Difficulty/compensating_invariant/seats_held_invariant_under_register_cancel_promote
    """
    ctx = setup_registered(api, num_candidates=2, capacity=WINDOW_CAPACITY_TIGHT)
    cand1, cand2 = ctx["candidates"]
    reg1, reg2 = ctx["registrations"]
    cancelled = cancel_registration(api, reg1["id"], make_candidate_headers(cand1["id"]))
    assert cancelled["logistics_status"] == "CANCELLED"
    assert cancelled["refund_cents"] == FEE_EARLY_CENTS

    window = get_window(api, ctx["window"]["id"])
    # The cancel + promotion pair is compensating: the seat stays held.
    assert window["seats_held"] == 1
    assert window["waitlist_count"] == 0
    promoted = get_success_data(api.list_candidate_registrations(cand2["id"],
                                                                 make_registrar_headers()))[0]
    assert promoted["id"] == reg2["id"]
    assert promoted["logistics_status"] == "REGISTERED"
    assert promoted["fee_charged_cents"] == FEE_EARLY_CENTS


def test_registration_fee_charged_at_creation(api):
    """PRD §3.3: "The registration fee is computed at the moment a seat is
    held, whether at creation for a `REGISTERED` row or at promotion for a
    formerly waitlisted one, and is recorded as `fee_charged_cents`."

    Design: Difficulty/compensating_invariant/net_fee_paid_invariant_under_register_then_full_refund_cancel
    """
    ctx = setup_open_window(api)
    candidate = make_candidate(api)
    registration = register(api, ctx["window"]["id"], candidate)
    # 30000 + round_half_up(30000 * 0.015) = 30000 + 450 at the early tier.
    assert registration["fee_charged_cents"] == FEE_EARLY_CENTS
    assert registration["logistics_status"] == "REGISTERED"


def test_full_refund_cancel_nets_zero(api):
    """PRD §3.3: "cancelling before the `registration_deadline` refunds the
    entire `fee_charged_cents`."

    Design: Difficulty/compensating_invariant/net_fee_paid_invariant_under_register_then_full_refund_cancel
    """
    ctx = setup_open_window(api)
    candidate = make_candidate(api)
    registration = register(api, ctx["window"]["id"], candidate)
    cancelled = cancel_registration(api, registration["id"],
                                    make_candidate_headers(candidate["id"]))
    assert cancelled["logistics_status"] == "CANCELLED"
    assert cancelled["cancel_reason"] == "CANDIDATE"
    # The pair conserves net fee paid: 30450 - 30450 == 0.
    assert cancelled["refund_cents"] == registration["fee_charged_cents"]
    assert registration["fee_charged_cents"] - cancelled["refund_cents"] == 0
