"""Difficulty probe — boundary_precision_check: the MPS equality boundary on
scoring (700 passes, 699 fails) and the exact-full seat boundary on booking
(last seat succeeds, next fails, per center+date)."""
from test_helpers import (
    ApiErrorId,
    book_appointment,
    check_in_appointment,
    create_appointment_payload,
    create_candidate,
    create_enrolled_enrollment,
    create_test_center,
    get_appointment,
    get_candidate,
    get_exam_window,
    list_appointments,
    make_candidate_headers,
    score_attempt,
    set_logical_clock,
    setup_bookable_context,
    validate_error,
    validate_success,
)

CLOCK = "2027-01-05T00:00:00Z"


def _two_candidates_checked_in():
    """Candidates A and B, both ENROLLED, both booked into the default LEVEL_I
    window on 2027-03-03 at the two-seat default center, both checked in on
    exam day; the clock is then advanced past the window's close."""
    context = setup_bookable_context()
    cand_b = create_candidate(
        email="b.cand@example.com",
        full_name="B Candidate",
        date_of_birth="1993-09-30",
        gov_id_number="GOV-B-1002",
    )
    enr_b = create_enrolled_enrollment(cand_b["id"])
    appt_a = book_appointment(context, exam_date="2027-03-03")
    ctx_b = {
        "candidate": cand_b,
        "enrollment": enr_b,
        "window": context["window"],
        "center": context["center"],
        "candidate_headers": make_candidate_headers(cand_b["id"]),
    }
    appt_b = book_appointment(
        ctx_b, exam_date="2027-03-03", calculator_model="HP_12C"
    )
    _, attempt_a = check_in_appointment(appt_a, context["candidate"])
    _, attempt_b = check_in_appointment(appt_b, cand_b)
    set_logical_clock("2027-03-16T00:00:00Z")
    return context, cand_b, appt_a, appt_b, attempt_a, attempt_b


def _tiny_center_setup():
    """Candidates A and B ENROLLED; a one-seat test center under the default
    LEVEL_I window."""
    context = setup_bookable_context()
    cand_b = create_candidate(
        email="b.cand@example.com",
        full_name="B Candidate",
        date_of_birth="1993-09-30",
        gov_id_number="GOV-B-1002",
    )
    enr_b = create_enrolled_enrollment(cand_b["id"])
    tiny = create_test_center(name="Tiny Center", daily_seat_capacity=1)
    ctx_b = {
        "candidate": cand_b,
        "enrollment": enr_b,
        "window": context["window"],
        "center": tiny,
        "candidate_headers": make_candidate_headers(cand_b["id"]),
    }
    context["center"] = tiny
    return context, ctx_b


class TestMpsBoundary:
    def test_mps_boundary_pass_and_fail(self, api):
        """PRD §3.5: "The result is a pure threshold comparison against the
        level's `mps_scaled_score`: the attempt's `result` is `PASS` when the
        scaled score is at least the minimum — a score exactly equal to the
        boundary passes, and one point below it `FAIL`s."

        Design: Difficulty/boundary_precision_check/mps_exact_boundary_pass_fail
        """
        context, cand_b, _a, _b, attempt_a, attempt_b = _two_candidates_checked_in()
        scored_a = score_attempt(attempt_a["id"], 700, clock_iso="2027-03-16T00:00:00Z")
        assert scored_a["result"] == "PASS"
        scored_b = score_attempt(attempt_b["id"], 699, clock_iso="2027-03-16T00:00:00Z")
        assert scored_b["result"] == "FAIL"
        assert (
            get_candidate(context["candidate"]["id"])["highest_level_passed_code"]
            == "LEVEL_I"
        )
        assert get_candidate(cand_b["id"])["highest_level_passed_code"] is None

    def test_window_publishes_only_when_all_scored(self, api):
        """PRD §3.5: "when a scoring event leaves **every** attempt belonging to
        the window in `SCORED`, the window itself auto-publishes, moving from
        `OPEN` to `RESULTS_PUBLISHED`: as part of publication, any appointment
        of the window still `SCHEDULED` is flipped to `NO_SHOW` first, and then
        every `CHECKED_IN` appointment of the window advances to `COMPLETED`."

        Design: Difficulty/boundary_precision_check/mps_exact_boundary_pass_fail
        """
        context, _cand_b, appt_a, appt_b, attempt_a, attempt_b = (
            _two_candidates_checked_in()
        )
        score_attempt(attempt_a["id"], 700, clock_iso="2027-03-16T00:00:00Z")
        assert get_exam_window(context["window"]["id"])["status"] == "OPEN"
        score_attempt(attempt_b["id"], 699, clock_iso="2027-03-16T00:00:00Z")
        assert (
            get_exam_window(context["window"]["id"])["status"]
            == "RESULTS_PUBLISHED"
        )
        assert get_appointment(appt_a["id"])["booking_status"] == "COMPLETED"
        assert get_appointment(appt_b["id"])["booking_status"] == "COMPLETED"


class TestSeatBoundary:
    def test_last_seat_booking_succeeds_next_fails(self, api):
        """PRD §3.3: "A booking requires at least one seat free: the booking
        that fills the last seat succeeds, and the next one fails with
        `ERR_NO_SEAT_CAPACITY`."

        Design: Difficulty/boundary_precision_check/seat_last_available_succeeds_next_fails
        """
        context, ctx_b = _tiny_center_setup()
        first = book_appointment(context, exam_date="2027-03-03")
        assert first["exam_fee_cents"] == 94000
        assert first["fee_tier"] == "EARLY"
        resp = api.create_appointment(
            create_appointment_payload(
                ctx_b["enrollment"]["id"],
                context["window"]["id"],
                context["center"]["id"],
                exam_date="2027-03-03",
                calculator_model="HP_12C",
            ),
            ctx_b["candidate_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_NO_SEAT_CAPACITY)
        assert resp.status_code == 409

    def test_capacity_boundary_is_per_center_and_date(self, api):
        """PRD §3.3: "The seats consumed at a center on a date are the
        appointments at that center on that date whose booking status is
        `SCHEDULED`, `CHECKED_IN`, `COMPLETED` or `NO_SHOW`; a `CANCELLED`
        appointment releases its seat, while a no-show keeps the seat consumed —
        the seat was held through exam day and the fee is forfeited."

        Design: Difficulty/boundary_precision_check/seat_last_available_succeeds_next_fails
        """
        context, ctx_b = _tiny_center_setup()
        book_appointment(context, exam_date="2027-03-03")
        ok = api.create_appointment(
            create_appointment_payload(
                ctx_b["enrollment"]["id"],
                context["window"]["id"],
                context["center"]["id"],
                exam_date="2027-03-04",
                calculator_model="HP_12C",
            ),
            ctx_b["candidate_headers"],
        )
        validate_success(ok, 201)
        rows = list_appointments(
            params={
                "test_center_id": context["center"]["id"],
                "booking_status": "SCHEDULED",
            }
        )
        assert len(rows) == 2
