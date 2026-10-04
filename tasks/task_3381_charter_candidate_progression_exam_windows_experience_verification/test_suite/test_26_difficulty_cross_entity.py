"""Difficulty probe — cross_entity_state_dependency: booking gated on the
enrollment's PENDING_PAYMENT -> ENROLLED arc, and society joining gated on the
candidate's charter_awarded flag (which only the award chain can set)."""
from test_helpers import (
    DEFAULTS,
    THREE_WINDOWS_SPEC,
    ApiErrorId,
    award_charter,
    book_checkin_score,
    create_appointment_payload,
    create_candidate,
    create_enrolled_enrollment,
    create_society,
    create_test_center,
    create_three_levels,
    create_three_windows,
    file_conduct_statement,
    get_candidate,
    get_enrollment_of_candidate,
    join_society,
    join_society_payload,
    make_candidate_headers,
    payment_payload,
    PROGRAM_FEE_CENTS,
    set_logical_clock,
    setup_approved_submission,
    setup_bookable_context,
    validate_error,
    validate_success,
)


class TestBookingRequiresEnrolled:
    def test_booking_blocked_while_pending_payment(self, api, program_admin_headers):
        """PRD §3.3: "The enrollment must be `ENROLLED`
        (`ERR_ENROLLMENT_NOT_ENROLLED`)"
        PRD §3.1: "The moment the outstanding balance reaches zero, the
        enrollment automatically advances from `PENDING_PAYMENT` to `ENROLLED`
        and its curriculum access list is recomputed per §2.10."

        Design: Difficulty/cross_entity_state_dependency/booking_requires_enrolled_enrollment_arc
        """
        context = setup_bookable_context(auto_pay=False)
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
        payment = api.post_enrollment_payment(
            context["enrollment"]["id"],
            payment_payload(PROGRAM_FEE_CENTS),
            program_admin_headers,
        )
        assert validate_success(payment, 200)["status"] == "ENROLLED"

    def test_booking_succeeds_once_enrolled(self, api):
        """PRD §3.3: "The appointment's `fee_tier` is `EARLY` when its
        `created_at` falls on or before the window's `early_fee_deadline_at` —
        an appointment created exactly at the deadline books at the early tier —
        and `STANDARD` otherwise."
        PRD §3.3: "Only after every other gate does the money rule fire: the
        enrollment's `outstanding_balance_cents` must be zero before the exam
        fee posts, else `ERR_OUTSTANDING_BALANCE`."

        Design: Difficulty/cross_entity_state_dependency/booking_requires_enrolled_enrollment_arc
        """
        context = setup_bookable_context(auto_pay=False)
        pay_enrollment_ok = api.post_enrollment_payment(
            context["enrollment"]["id"],
            payment_payload(PROGRAM_FEE_CENTS),
            context["candidate_headers"],
        )
        validate_success(pay_enrollment_ok, 200)
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
        assert data["exam_fee_cents"] == 94000
        assert data["fee_tier"] == "EARLY"
        enrollment = get_enrollment_of_candidate(context["candidate"]["id"])
        assert enrollment["outstanding_balance_cents"] == 94000


def _charter_ready_with_society():
    """Candidate with an ENROLLED enrollment, all three levels passed, an
    APPROVED 41-month experience submission and the current-year PCS filed —
    everything the award gate chain needs — plus a society to join. The charter
    has NOT been awarded yet."""
    set_logical_clock(DEFAULTS["CLOCK_SETUP"])
    candidate = create_candidate()
    enrollment = create_enrolled_enrollment(candidate["id"])
    levels = create_three_levels()
    windows = create_three_windows(levels)
    center = create_test_center()
    for code in ("LEVEL_I", "LEVEL_II", "LEVEL_III"):
        spec = THREE_WINDOWS_SPEC[code]
        book_checkin_score(
            candidate,
            enrollment,
            windows[code],
            center,
            exam_date=spec["exam_date"],
            scaled_score=levels[code]["mps_scaled_score"],
            score_clock=spec["score_clock"],
        )
    setup_approved_submission(candidate)
    file_conduct_statement(candidate, disclosure_year=2027)
    society = create_society()
    return {
        "candidate": candidate,
        "enrollment": enrollment,
        "society": society,
        "candidate_headers": make_candidate_headers(candidate["id"]),
    }


class TestMembershipRequiresCharter:
    def test_join_before_charter_award_rejected(self, api, program_admin_headers):
        """PRD §3.9: "Joining requires the candidate's `charter_awarded` to be
        true (`ERR_CHARTER_REQUIRED`)"
        PRD §3.8: "Awarding flips the enrollment from `ENROLLED` to
        `CHARTER_AWARDED`, sets the candidate's `charter_awarded` true, stamps
        the enrollment's `chartered_at` with the current clock, and widens the
        enrollment's `curriculum_access_cycle_ids` to every `PUBLISHED` cycle in
        the program."

        Design: Difficulty/cross_entity_state_dependency/membership_join_requires_awarded_charter
        """
        context = _charter_ready_with_society()
        resp = api.create_membership(
            context["society"]["id"],
            join_society_payload(context["candidate"]["id"], 27500),
            context["candidate_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_CHARTER_REQUIRED)
        assert resp.status_code == 422
        awarded = api.award_charter(
            context["enrollment"]["id"], program_admin_headers
        )
        assert validate_success(awarded, 200)["status"] == "CHARTER_AWARDED"
        assert get_candidate(context["candidate"]["id"])["charter_awarded"] is True

    def test_join_after_charter_award_succeeds(self, api):
        """PRD §3.9: "A new membership opens `ACTIVE` with `paid_through_year`
        set to the logical clock's current calendar year and an empty
        `ce_records` list."
        PRD §3.9: "dues are exact — `dues_payment_cents` must equal the
        society's `annual_dues_cents` to the cent, else
        `ERR_INCORRECT_DUES_AMOUNT`."

        Design: Difficulty/cross_entity_state_dependency/membership_join_requires_awarded_charter
        """
        context = _charter_ready_with_society()
        award_charter(context["enrollment"]["id"])
        membership = join_society(context["society"], context["candidate"])
        assert membership["status"] == "ACTIVE"
        assert membership["paid_through_year"] == 2027
        assert membership["ce_records"] == []
