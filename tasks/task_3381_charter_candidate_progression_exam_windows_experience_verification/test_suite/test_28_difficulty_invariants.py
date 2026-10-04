"""Difficulty probe — compensating_invariant: the seats-consumed count and the
net_billed_cents money invariant each return to their pre-pair value when a
booking is paired with its compensating cancellation."""
from test_helpers import (
    ApiErrorId,
    api_client,
    assert_enrollment_ledger_invariants,
    book_appointment,
    create_appointment_payload,
    create_candidate,
    create_enrolled_enrollment,
    create_exam_level,
    create_exam_window,
    create_test_center,
    get_enrollment_of_candidate,
    list_appointments,
    make_candidate_headers,
    set_logical_clock,
    setup_bookable_context,
    validate_error,
    validate_success,
)

CLOCK = "2027-01-05T00:00:00Z"


def _duo_center_setup():
    """Three ENROLLED candidates; a two-seat center; A and B hold both seats on
    2027-03-03 in the default LEVEL_I window."""
    set_logical_clock(CLOCK)
    candidates = {}
    for key, email, name, dob, gov in (
        ("a", "a.cand@example.com", "A Candidate", "1995-04-12", "GOV-A-1001"),
        ("b", "b.cand@example.com", "B Candidate", "1993-09-30", "GOV-B-1002"),
        ("c", "c.cand@example.com", "C Candidate", "1990-01-20", "GOV-C-1003"),
    ):
        candidate = create_candidate(
            email=email, full_name=name, date_of_birth=dob, gov_id_number=gov
        )
        enrollment = create_enrolled_enrollment(candidate["id"])
        candidates[key] = (candidate, enrollment)
    level = create_exam_level()
    window = create_exam_window(level["id"])
    center = create_test_center(name="Duo Center", daily_seat_capacity=2)
    contexts = {
        key: {
            "candidate": pair[0],
            "enrollment": pair[1],
            "window": window,
            "center": center,
            "candidate_headers": make_candidate_headers(pair[0]["id"]),
        }
        for key, pair in candidates.items()
    }
    appt_a = book_appointment(contexts["a"], exam_date="2027-03-03", pay_fee=False)
    book_appointment(
        contexts["b"], exam_date="2027-03-03", calculator_model="HP_12C", pay_fee=False
    )
    return contexts, appt_a, center


def _book(context, exam_date="2027-03-03", calculator_model="TI_BA_II_PLUS"):
    return api_client.create_appointment(
        create_appointment_payload(
            context["enrollment"]["id"],
            context["window"]["id"],
            context["center"]["id"],
            exam_date=exam_date,
            calculator_model=calculator_model,
        ),
        context["candidate_headers"],
    )


class TestSeatCountInvariant:
    def test_third_booking_fails_when_full(self, api):
        """PRD §3.3: "The seats consumed at a center on a date are the
        appointments at that center on that date whose booking status is
        `SCHEDULED`, `CHECKED_IN`, `COMPLETED` or `NO_SHOW`; a `CANCELLED`
        appointment releases its seat, while a no-show keeps the seat consumed —
        the seat was held through exam day and the fee is forfeited."

        Design: Difficulty/compensating_invariant/seat_count_invariant_book_cancel_pair
        """
        contexts, _appt_a, _center = _duo_center_setup()
        resp = _book(contexts["c"])
        validate_error(resp, ApiErrorId.ERR_NO_SEAT_CAPACITY)
        assert resp.status_code == 409

    def test_cancel_releases_seat_for_retry(self, api):
        """PRD §3.3: "a `CANCELLED` appointment releases its seat"
        PRD §3.3: "A booking requires at least one seat free: the booking that
        fills the last seat succeeds, and the next one fails with
        `ERR_NO_SEAT_CAPACITY`."

        Design: Difficulty/compensating_invariant/seat_count_invariant_book_cancel_pair
        """
        contexts, appt_a, center = _duo_center_setup()
        blocked = _book(contexts["c"])
        validate_error(blocked, ApiErrorId.ERR_NO_SEAT_CAPACITY)
        cancelled = api.cancel_appointment(
            appt_a["id"], contexts["a"]["candidate_headers"]
        )
        assert validate_success(cancelled, 200)["booking_status"] == "CANCELLED"
        retry = _book(contexts["c"])
        validate_success(retry, 201)
        rows = list_appointments(
            params={"test_center_id": center["id"], "booking_status": "SCHEDULED"}
        )
        assert len(rows) == 2


class TestNetBilledInvariant:
    def test_booking_raises_net_billed(self, api):
        """PRD §2.8: "`credit_balance_cents` is the posted credits not yet
        absorbed by charges — credits posted minus credits applied — and
        overpayments land here as well; `outstanding_balance_cents` is what the
        candidate still owes — lifetime charges minus lifetime payments minus
        applied credits; and `net_billed_cents` is the compensating-invariant
        anchor — lifetime charges minus credits posted."

        Design: Difficulty/compensating_invariant/net_billed_invariant_book_cancel_pair
        """
        context = setup_bookable_context()
        book_appointment(context, exam_date="2027-03-03", pay_fee=False)
        enrollment = get_enrollment_of_candidate(context["candidate"]["id"])
        assert enrollment["net_billed_cents"] == 35003 + 94000
        assert enrollment["outstanding_balance_cents"] == 94000
        assert_enrollment_ledger_invariants(enrollment)

    def test_cancel_restores_net_billed(self, api):
        """PRD §3.4: "a candidate- or admin-initiated cancellation credits the
        appointment's full `exam_fee_cents` to the enrollment when the logical
        clock is no later than the window's `scheduling_deadline_at`, and
        credits nothing once that deadline has passed; reschedule fees are never
        credited under any circumstances."
        PRD §2.8: "When a credit posts to an enrollment, it absorbs outstanding
        charges first — the applied portion is the lesser of the credit and the
        current outstanding balance, which reduces `outstanding_balance_cents`
        and increases `lifetime_credits_applied_cents` — and any remainder
        raises `credit_balance_cents`."

        Design: Difficulty/compensating_invariant/net_billed_invariant_book_cancel_pair
        """
        context = setup_bookable_context()
        appointment = book_appointment(context, exam_date="2027-03-03", pay_fee=False)
        cancelled = api.cancel_appointment(
            appointment["id"], context["candidate_headers"]
        )
        validate_success(cancelled, 200)
        enrollment = get_enrollment_of_candidate(context["candidate"]["id"])
        assert enrollment["net_billed_cents"] == 35003
        assert enrollment["lifetime_credits_posted_cents"] == 94000
        assert enrollment["lifetime_credits_applied_cents"] == 94000
        assert enrollment["outstanding_balance_cents"] == 0
        assert enrollment["credit_balance_cents"] == 0
        assert_enrollment_ledger_invariants(enrollment)
