"""Exam day and results publication: check-in date and policy gates, the
attempt created by check-in, scoring preconditions, the no-show sweep and
window auto-publication, and appointment/window cancellation semantics."""
from test_helpers import (
    NON_EXISTENT_UUID,
    ApiErrorId,
    assert_exam_attempt,
    book_appointment,
    check_in_appointment,
    check_in_payload,
    create_candidate,
    create_enrolled_enrollment,
    get_appointment,
    get_enrollment_of_candidate,
    get_exam_window,
    list_exam_attempts,
    make_candidate_headers,
    score_attempt,
    score_payload,
    set_logical_clock,
    setup_bookable_context,
    setup_scored_appointment,
    validate_error,
    validate_success,
)

CLOCK = "2027-01-05T00:00:00Z"


def _enrolled_candidate(email, full_name, date_of_birth, gov_id_number):
    candidate = create_candidate(
        email=email,
        full_name=full_name,
        date_of_birth=date_of_birth,
        gov_id_number=gov_id_number,
    )
    enrollment = create_enrolled_enrollment(candidate["id"])
    return candidate, enrollment


def _mini_context(candidate, enrollment, window, center):
    return {
        "candidate": candidate,
        "enrollment": enrollment,
        "window": window,
        "center": center,
        "candidate_headers": make_candidate_headers(candidate["id"]),
    }


class TestCheckIn:
    def test_checkin_on_wrong_date_rejected(self, api, proctor_headers):
        """PRD §3.5: "The appointment must be `SCHEDULED`
        (`ERR_APPOINTMENT_NOT_SCHEDULED`) — note that the appointment's
        `compliance_status` does **not** gate check-in — and the logical clock's
        calendar date must equal the appointment's `exam_date`
        (`ERR_CHECKIN_NOT_ON_EXAM_DATE`)."

        Design: Corner/errors/c_checkin_on_wrong_date_rejected
        """
        context = setup_bookable_context()
        appointment = book_appointment(context, exam_date="2027-03-03")
        set_logical_clock("2027-03-04T08:00:00Z")
        resp = api.check_in_appointment(
            appointment["id"],
            check_in_payload(
                context["candidate"]["gov_id_number"], appointment["calculator_model"]
            ),
            proctor_headers,
        )
        validate_error(resp, ApiErrorId.ERR_CHECKIN_NOT_ON_EXAM_DATE)
        assert resp.status_code == 422
        assert get_appointment(appointment["id"])["booking_status"] == "SCHEDULED"
        assert list_exam_attempts(params={"exam_appointment_id": appointment["id"]}) == []

    def test_identity_checked_before_calculator(self, api, proctor_headers):
        """PRD §3.5: "Identity comes first: the presented
        `identity_document_number` must equal the candidate's registered
        `gov_id_number`, compared verbatim, else
        `ERR_IDENTITY_VERIFICATION_FAILED`. Only then is the calculator policy
        applied: the `actual_calculator_model` presented at the desk must equal
        the appointment's declared `calculator_model` and be one of the two
        approved models, else `ERR_CALCULATOR_POLICY_VIOLATION`."

        Design: Corner/errors/c_identity_checked_before_calculator
        """
        context = setup_bookable_context()
        appointment = book_appointment(
            context, exam_date="2027-03-03", calculator_model="TI_BA_II_PLUS"
        )
        set_logical_clock("2027-03-03T08:00:00Z")
        first = api.check_in_appointment(
            appointment["id"],
            check_in_payload("GOV-WRONG", "HP_12C"),
            proctor_headers,
        )
        validate_error(first, ApiErrorId.ERR_IDENTITY_VERIFICATION_FAILED)
        assert first.status_code == 422
        second = api.check_in_appointment(
            appointment["id"],
            check_in_payload(context["candidate"]["gov_id_number"], "HP_12C"),
            proctor_headers,
        )
        validate_error(second, ApiErrorId.ERR_CALCULATOR_POLICY_VIOLATION)
        assert second.status_code == 422
        third = api.check_in_appointment(
            appointment["id"],
            check_in_payload(
                context["candidate"]["gov_id_number"], "TI_BA_II_PLUS"
            ),
            proctor_headers,
        )
        assert validate_success(third, 200)["booking_status"] == "CHECKED_IN"

    def test_checkin_creates_awaiting_score_attempt(self, api):
        """PRD §3.5: "A successful check-in advances the booking from
        `SCHEDULED` to `CHECKED_IN` and creates the appointment's **exam
        attempt** as a side effect."
        PRD §3.5: "Its `attempt_sequence` is the one-based count of **all**
        attempts ever created for that candidate at that level, ordered by
        creation — invalidated attempts included in the count."

        Design: Corner/state_machines/c_checkin_creates_awaiting_score_attempt
        """
        context = setup_bookable_context()
        appointment = book_appointment(context, exam_date="2027-03-03")
        updated, attempt = check_in_appointment(appointment, context["candidate"])
        assert updated["booking_status"] == "CHECKED_IN"
        rows = list_exam_attempts(params={"exam_appointment_id": appointment["id"]})
        assert len(rows) == 1
        assert_exam_attempt(attempt)
        assert attempt["score_status"] == "AWAITING_SCORE"
        assert attempt["validity"] == "VALID"
        assert attempt["attempt_sequence"] == 1
        assert attempt["exam_level_code"] == "LEVEL_I"
        assert attempt["scaled_score"] is None
        assert attempt["result"] is None


class TestScoring:
    def test_score_attempt_twice_rejected(self, api, program_admin_headers):
        """PRD §3.5: "the attempt must still be `AWAITING_SCORE`
        (`ERR_ATTEMPT_ALREADY_SCORED`)"

        Design: Corner/state_machines/c_score_attempt_twice_rejected
        """
        context = setup_scored_appointment(scaled_score=700)
        resp = api.score_exam_attempt(
            context["attempt"]["id"], score_payload(400), program_admin_headers
        )
        validate_error(resp, ApiErrorId.ERR_ATTEMPT_ALREADY_SCORED)
        assert resp.status_code == 409
        attempt = validate_success(
            api.get_exam_attempt(context["attempt"]["id"], program_admin_headers), 200
        )
        assert attempt["scaled_score"] == 700
        assert attempt["result"] == "PASS"

    def test_score_before_window_close_rejected(self, api, program_admin_headers):
        """PRD §3.5: "the logical clock must be no earlier than the window's
        `window_closes_at` (`ERR_WINDOW_NOT_CONCLUDED`)"

        Design: Corner/errors/c_score_before_window_close_rejected
        """
        context = setup_bookable_context()
        appointment = book_appointment(context, exam_date="2027-03-03")
        _, attempt = check_in_appointment(appointment, context["candidate"])
        set_logical_clock("2027-03-10T00:00:00Z")
        resp = api.score_exam_attempt(
            attempt["id"], score_payload(700), program_admin_headers
        )
        validate_error(resp, ApiErrorId.ERR_WINDOW_NOT_CONCLUDED)
        assert resp.status_code == 409
        after = validate_success(
            api.get_exam_attempt(attempt["id"], program_admin_headers), 200
        )
        assert after["score_status"] == "AWAITING_SCORE"
        assert after["result"] is None

    def test_score_unknown_attempt_returns_404(self, api, program_admin_headers):
        """PRD §2.6: "Each identifier embedded in the URL path is resolved in
        left-to-right order, and the first one that does not exist fails the
        request with its own entity-specific error"

        Design: Corner/errors/c_score_unknown_attempt_returns_404
        """
        set_logical_clock(CLOCK)
        resp = api.score_exam_attempt(
            NON_EXISTENT_UUID, score_payload(700), program_admin_headers
        )
        validate_error(resp, ApiErrorId.ERR_ATTEMPT_NOT_FOUND)
        assert resp.status_code == 404

    def test_score_out_of_range_rejected(self, api, program_admin_headers):
        """PRD §3.5: "the submitted `scaled_score` must lie between 0 and 1000
        inclusive — a score outside that range is malformed and rejected as
        `ERR_SCORE_OUT_OF_RANGE` at the request-shape stage, before state or
        clock rules are consulted."

        Design: Corner/errors/c_score_out_of_range_rejected
        """
        context = setup_bookable_context()
        appointment = book_appointment(context, exam_date="2027-03-03")
        _, attempt = check_in_appointment(appointment, context["candidate"])
        set_logical_clock("2027-03-10T00:00:00Z")
        resp = api.score_exam_attempt(
            attempt["id"], score_payload(1001), program_admin_headers
        )
        validate_error(resp, ApiErrorId.ERR_SCORE_OUT_OF_RANGE)
        assert resp.status_code == 400

    def test_no_show_auto_flip_on_first_window_score(self, api):
        """PRD §3.5: "Within the scored attempt's window, the first scoring
        event flips every appointment still sitting in `SCHEDULED` to `NO_SHOW`
        — no attempt is created for a no-show, the exam fee is forfeited with no
        credit, and the seat remains consumed."
        PRD §3.5: "when a scoring event leaves **every** attempt belonging to
        the window in `SCORED`, the window itself auto-publishes, moving from
        `OPEN` to `RESULTS_PUBLISHED`: as part of publication, any appointment
        of the window still `SCHEDULED` is flipped to `NO_SHOW` first, and then
        every `CHECKED_IN` appointment of the window advances to `COMPLETED`."

        Design: Corner/state_machines/c_no_show_auto_flip_on_first_window_score
        """
        context = setup_bookable_context()
        cand_c, enr_c = _enrolled_candidate(
            "c.cand@example.com", "C Candidate", "1990-01-20", "GOV-C-1003"
        )
        appt_a = book_appointment(context, exam_date="2027-03-03")
        appt_c = book_appointment(
            _mini_context(cand_c, enr_c, context["window"], context["center"]),
            exam_date="2027-03-03",
            calculator_model="HP_12C",
            pay_fee=False,
        )
        _, attempt_a = check_in_appointment(appt_a, context["candidate"])
        score_attempt(attempt_a["id"], 700, clock_iso="2027-03-16T00:00:00Z")
        assert get_appointment(appt_a["id"])["booking_status"] == "COMPLETED"
        assert get_appointment(appt_c["id"])["booking_status"] == "NO_SHOW"
        assert list_exam_attempts(params={"candidate_id": cand_c["id"]}) == []
        enrollment_c = get_enrollment_of_candidate(cand_c["id"])
        assert enrollment_c["lifetime_credits_posted_cents"] == 0
        assert enrollment_c["outstanding_balance_cents"] == 94000


class TestCancellation:
    def test_cancel_results_published_window_rejected(self, api, program_admin_headers):
        """PRD §3.4: "A `ProgramAdmin` may also cancel an entire window,
        provided it is still `OPEN` — a window already `RESULTS_PUBLISHED` or
        `CANCELLED` rejects the attempt with `ERR_WINDOW_NOT_CANCELLABLE`."

        Design: Corner/state_machines/c_cancel_results_published_window_rejected
        """
        context = setup_scored_appointment(scaled_score=700)
        resp = api.cancel_exam_window(context["window"]["id"], program_admin_headers)
        validate_error(resp, ApiErrorId.ERR_WINDOW_NOT_CANCELLABLE)
        assert resp.status_code == 409
        assert get_exam_window(context["window"]["id"])["status"] == "RESULTS_PUBLISHED"
        assert (
            get_appointment(context["appointment"]["id"])["booking_status"]
            == "COMPLETED"
        )

    def test_window_cancel_skips_checked_in_appointments(self, api, program_admin_headers):
        """PRD §3.4: "The cascade walks the window's appointments in creation
        order: every appointment still `SCHEDULED` flips to `CANCELLED`
        (appointments already `CHECKED_IN` are not touched), and each
        so-cancelled appointment is compensated with its **full**
        `exam_fee_cents`, deadline-independent, posted per the standard credit
        mechanics."

        Design: Corner/state_machines/c_window_cancel_skips_checked_in_appointments
        """
        context = setup_bookable_context()
        cand_b, enr_b = _enrolled_candidate(
            "b.cand@example.com", "B Candidate", "1993-09-30", "GOV-B-1002"
        )
        appt_a = book_appointment(context, exam_date="2027-03-03", pay_fee=False)
        appt_b = book_appointment(
            _mini_context(cand_b, enr_b, context["window"], context["center"]),
            exam_date="2027-03-03",
            calculator_model="HP_12C",
            pay_fee=False,
        )
        check_in_appointment(appt_a, context["candidate"])
        resp = api.cancel_exam_window(context["window"]["id"], program_admin_headers)
        assert validate_success(resp, 200)["status"] == "CANCELLED"
        assert get_appointment(appt_b["id"])["booking_status"] == "CANCELLED"
        assert get_appointment(appt_a["id"])["booking_status"] == "CHECKED_IN"
        enrollment_b = get_enrollment_of_candidate(cand_b["id"])
        assert enrollment_b["lifetime_credits_posted_cents"] == 94000
        assert enrollment_b["outstanding_balance_cents"] == 0
        enrollment_a = get_enrollment_of_candidate(context["candidate"]["id"])
        assert enrollment_a["lifetime_credits_posted_cents"] == 0
        assert enrollment_a["outstanding_balance_cents"] == 94000

    def test_cancel_cancelled_appointment_rejected(self, api):
        """PRD §3.4: "The appointment must be `SCHEDULED`
        (`ERR_APPOINTMENT_NOT_SCHEDULED`); the owning candidate or a
        `ProgramAdmin` may cancel."
        PRD §3.4: "a candidate- or admin-initiated cancellation credits the
        appointment's full `exam_fee_cents` to the enrollment when the logical
        clock is no later than the window's `scheduling_deadline_at`, and
        credits nothing once that deadline has passed; reschedule fees are never
        credited under any circumstances."

        Design: Corner/errors/c_cancel_cancelled_appointment_rejected
        """
        context = setup_bookable_context()
        appointment = book_appointment(context, exam_date="2027-03-03", pay_fee=False)
        first = api.cancel_appointment(
            appointment["id"], context["candidate_headers"]
        )
        assert validate_success(first, 200)["booking_status"] == "CANCELLED"
        second = api.cancel_appointment(
            appointment["id"], context["candidate_headers"]
        )
        validate_error(second, ApiErrorId.ERR_APPOINTMENT_NOT_SCHEDULED)
        assert second.status_code == 409
        enrollment = get_enrollment_of_candidate(context["candidate"]["id"])
        assert enrollment["lifetime_credits_posted_cents"] == 94000
