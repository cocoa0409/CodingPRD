"""Difficulty probe — priority_pair_validation_conflict: when one request
violates rules from two pipeline stages, the earlier stage's error is the one
returned (state before money; clock rules before capacity)."""
from test_helpers import (
    ApiErrorId,
    PROGRAM_FEE_CENTS,
    book_appointment,
    create_appointment_payload,
    create_candidate,
    create_enrolled_enrollment,
    create_exam_level,
    create_exam_window,
    create_test_center,
    get_appointment,
    get_enrollment_of_candidate,
    list_appointments,
    make_candidate_headers,
    payment_payload,
    reschedule_appointment_payload,
    set_logical_clock,
    setup_bookable_context,
    validate_error,
    validate_success,
)

CLOCK = "2027-01-05T00:00:00Z"


def _deadline_capacity_setup():
    """Window with reschedule deadline 2027-02-25; candidate A holds the only
    seat at Center A on 2027-03-03 and candidate B holds the only seat at
    Center B on 2027-03-05 (so Center B on that date is fully booked)."""
    set_logical_clock(CLOCK)
    cand_a = create_candidate()
    enr_a = create_enrolled_enrollment(cand_a["id"])
    cand_b = create_candidate(
        email="b.cand@example.com",
        full_name="B Candidate",
        date_of_birth="1993-09-30",
        gov_id_number="GOV-B-1002",
    )
    enr_b = create_enrolled_enrollment(
        cand_b["id"],
        pathway="WORK_EXPERIENCE",
        declared_work_months=48,
        declared_work_hours=6000,
    )
    level = create_exam_level()
    window = create_exam_window(
        level["id"], reschedule_deadline_at="2027-02-25T00:00:00Z"
    )
    center_a = create_test_center(name="Center A", daily_seat_capacity=1)
    center_b = create_test_center(name="Center B", daily_seat_capacity=1)
    ctx_a = {
        "candidate": cand_a,
        "enrollment": enr_a,
        "window": window,
        "center": center_a,
        "candidate_headers": make_candidate_headers(cand_a["id"]),
    }
    ctx_b = {
        "candidate": cand_b,
        "enrollment": enr_b,
        "window": window,
        "center": center_b,
        "candidate_headers": make_candidate_headers(cand_b["id"]),
    }
    appt_a = book_appointment(ctx_a, exam_date="2027-03-03", pay_fee=False)
    book_appointment(
        ctx_b, exam_date="2027-03-05", calculator_model="HP_12C", pay_fee=False
    )
    return ctx_a, appt_a, center_b


class TestStateBeatsFiscal:
    def test_pending_payment_booking_returns_state_error(self, api):
        """PRD §2.6: "Every request passes through a fixed validation pipeline,
        and the **first** failing check wins — its error is the one returned,
        and later checks are never consulted for that request."
        PRD §3.3: "The enrollment must be `ENROLLED`
        (`ERR_ENROLLMENT_NOT_ENROLLED`)"
        PRD §2.6: "13. **Money gates, always last.** Zero-balance requirements
        (`ERR_OUTSTANDING_BALANCE`) and exact-dues requirements
        (`ERR_INCORRECT_DUES_AMOUNT`) are evaluated only after every other rule
        has passed."

        Design: Difficulty/priority_pair_validation_conflict/state_enrollment_beats_fiscal_balance_on_booking
        """
        context = setup_bookable_context(auto_pay=False)
        enrollment = get_enrollment_of_candidate(context["candidate"]["id"])
        assert enrollment["status"] == "PENDING_PAYMENT"
        assert enrollment["outstanding_balance_cents"] == PROGRAM_FEE_CENTS
        resp = api.create_appointment(
            create_appointment_payload(
                context["enrollment"]["id"],
                context["window"]["id"],
                context["center"]["id"],
                exam_date="2027-03-03",
            ),
            context["candidate_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_ENROLLMENT_NOT_ENROLLED)
        assert resp.status_code == 409
        assert resp.json()["data"]["error_id"] != "ERR_OUTSTANDING_BALANCE"
        assert (
            list_appointments(
                params={"program_enrollment_id": context["enrollment"]["id"]}
            )
            == []
        )

    def test_booking_succeeds_once_state_gate_passes(self, api, program_admin_headers):
        """PRD §3.1: "The moment the outstanding balance reaches zero, the
        enrollment automatically advances from `PENDING_PAYMENT` to `ENROLLED`
        and its curriculum access list is recomputed per §2.10."
        PRD §3.3: "The appointment's `fee_tier` is `EARLY` when its `created_at`
        falls on or before the window's `early_fee_deadline_at` — an appointment
        created exactly at the deadline books at the early tier — and `STANDARD`
        otherwise."

        Design: Difficulty/priority_pair_validation_conflict/state_enrollment_beats_fiscal_balance_on_booking
        """
        context = setup_bookable_context(auto_pay=False)
        payment = api.post_enrollment_payment(
            context["enrollment"]["id"],
            payment_payload(PROGRAM_FEE_CENTS),
            program_admin_headers,
        )
        assert validate_success(payment, 200)["status"] == "ENROLLED"
        resp = api.create_appointment(
            create_appointment_payload(
                context["enrollment"]["id"],
                context["window"]["id"],
                context["center"]["id"],
                exam_date="2027-03-03",
            ),
            context["candidate_headers"],
        )
        data = validate_success(resp, 201)
        assert data["fee_tier"] == "EARLY"
        assert data["exam_fee_cents"] == 94000
        enrollment = get_enrollment_of_candidate(context["candidate"]["id"])
        assert enrollment["outstanding_balance_cents"] == 94000


class TestTemporalBeatsCapacity:
    def test_past_deadline_reschedule_returns_temporal_error(self, api):
        """PRD §3.4: "The logical clock must be no later than the **original**
        window's `reschedule_deadline_at` (`ERR_RESCHEDULE_DEADLINE_PASSED`) —
        the deadline of the window the appointment currently sits in governs,
        even when the reschedule retargets a different window."
        PRD §2.6: "Every request passes through a fixed validation pipeline, and
        the **first** failing check wins — its error is the one returned, and
        later checks are never consulted for that request."

        Design: Difficulty/priority_pair_validation_conflict/temporal_deadline_beats_capacity_on_reschedule
        """
        context, appointment, center_b = _deadline_capacity_setup()
        set_logical_clock("2027-02-26T00:00:00Z")
        resp = api.reschedule_appointment(
            appointment["id"],
            reschedule_appointment_payload(
                appointment["version"],
                test_center_id=center_b["id"],
                exam_date="2027-03-05",
            ),
            context["candidate_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_RESCHEDULE_DEADLINE_PASSED)
        assert resp.status_code == 422
        assert resp.json()["data"]["error_id"] != "ERR_NO_SEAT_CAPACITY"
        after = get_appointment(appointment["id"])
        assert after["exam_date"] == "2027-03-03"
        assert after["reschedule_count"] == 0

    def test_full_center_returns_capacity_error_before_deadline(self, api):
        """PRD §3.4: "a seat must be free at the effective center and date,
        **excluding the appointment's own current seat** from the count
        (`ERR_NO_SEAT_CAPACITY`)."
        PRD §3.3: "A booking requires at least one seat free: the booking that
        fills the last seat succeeds, and the next one fails with
        `ERR_NO_SEAT_CAPACITY`."

        Design: Difficulty/priority_pair_validation_conflict/temporal_deadline_beats_capacity_on_reschedule
        """
        context, appointment, center_b = _deadline_capacity_setup()
        set_logical_clock("2027-02-24T00:00:00Z")
        resp = api.reschedule_appointment(
            appointment["id"],
            reschedule_appointment_payload(
                appointment["version"],
                test_center_id=center_b["id"],
                exam_date="2027-03-05",
            ),
            context["candidate_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_NO_SEAT_CAPACITY)
        assert resp.status_code == 409
        after = get_appointment(appointment["id"])
        assert after["exam_date"] == "2027-03-03"
        assert after["reschedule_count"] == 0
