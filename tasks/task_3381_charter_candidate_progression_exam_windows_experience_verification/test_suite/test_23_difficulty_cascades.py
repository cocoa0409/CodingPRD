"""Difficulty probe — transitive_cascade: EXAM_INVALIDATION sanction ->
attempt invalidation -> progression downgrade -> curriculum access shrink; and
window cancellation -> appointment cancellation -> enrollment credit ->
credit-drawn rebooking."""
from test_helpers import (
    adjudicate_case,
    book_appointment,
    check_in_appointment,
    create_appointment_payload,
    create_candidate,
    create_curriculum_cycle,
    create_enrolled_enrollment,
    create_exam_level,
    create_exam_window,
    create_test_center,
    get_appointment,
    get_attempt_for_appointment,
    get_candidate,
    get_enrollment_of_candidate,
    make_candidate_headers,
    open_incident_case,
    score_attempt,
    set_logical_clock,
    setup_bookable_context,
    validate_success,
)

CLOCK = "2027-01-05T00:00:00Z"


def _scored_with_cycles_setup():
    """Candidate ENROLLED; LEVEL_I and LEVEL_II each with a PUBLISHED 2027
    cycle; the LEVEL_I appointment checked in and scored a boundary PASS, so
    the enrollment's access list covers both levels' cycles. An incident case
    on the LEVEL_I appointment is left OPENED."""
    set_logical_clock(CLOCK)
    candidate = create_candidate()
    enrollment = create_enrolled_enrollment(candidate["id"])
    level_1 = create_exam_level()
    level_2 = create_exam_level(level_code="LEVEL_II", mps_scaled_score=720)
    cycle_1 = create_curriculum_cycle(level_1["id"])
    cycle_2 = create_curriculum_cycle(
        level_2["id"], content_version="L2-2027"
    )
    window = create_exam_window(level_1["id"])
    center = create_test_center()
    context = {
        "candidate": candidate,
        "enrollment": enrollment,
        "level": level_1,
        "window": window,
        "center": center,
        "candidate_headers": make_candidate_headers(candidate["id"]),
    }
    appointment = book_appointment(context, exam_date="2027-03-03")
    _, attempt = check_in_appointment(appointment, candidate)
    scored = score_attempt(attempt["id"], 700, clock_iso="2027-03-16T00:00:00Z")
    assert scored["result"] == "PASS"
    case = open_incident_case(
        candidate["id"], appointment["id"], allegation="Calculator concealment suspected"
    )
    return {
        "candidate": candidate,
        "enrollment": enrollment,
        "appointment": appointment,
        "attempt": attempt,
        "case": case,
        "cycle_1": cycle_1,
        "cycle_2": cycle_2,
    }


def _window_cancel_setup():
    """Candidate ENROLLED with a fully paid EARLY booking in the default
    window; a second, later LEVEL_I window stands ready for rebooking."""
    context = setup_bookable_context()
    window_later = create_exam_window(
        context["level"]["id"],
        window_opens_at="2027-04-01T00:00:00Z",
        window_closes_at="2027-04-15T00:00:00Z",
        scheduling_deadline_at="2027-03-20T00:00:00Z",
        reschedule_deadline_at="2027-03-25T00:00:00Z",
        early_fee_deadline_at="2027-02-28T00:00:00Z",
    )
    appointment = book_appointment(context, exam_date="2027-03-03")
    return context, appointment, window_later


class TestExamInvalidationCascade:
    def test_invalidation_drops_attempt_validity_and_compliance(self, api):
        """PRD §3.7: "An `EXAM_INVALIDATION` targets attempts: for an
        appointment-linked case, that appointment's attempt is invalidated —
        `VALID` to `INVALIDATED` — and the appointment's `compliance_status`
        advances from `POLICY_FLAGGED` to `CONFIRMED_VIOLATION`"

        Design: Difficulty/transitive_cascade/exam_invalidation_cascades_attempt_progression_curriculum
        """
        bundle = _scored_with_cycles_setup()
        adjudicate_case(
            bundle["case"],
            outcome="SANCTIONED",
            sanction_type="EXAM_INVALIDATION",
            adjudicator_user_id="adj-1",
        )
        attempt = get_attempt_for_appointment(bundle["appointment"]["id"])
        assert attempt["validity"] == "INVALIDATED"
        appointment = get_appointment(bundle["appointment"]["id"])
        assert appointment["compliance_status"] == "CONFIRMED_VIOLATION"

    def test_invalidation_drops_progression_and_curriculum(self, api):
        """PRD §3.7: "Either way the candidate's progression marker and
        curriculum access are then recomputed, and both may shrink."
        PRD §2.10: "While it is `ENROLLED`, the list contains the `PUBLISHED`
        curriculum cycles of every level up to and including the candidate's
        **lowest unpassed** level."
        PRD §2.10: "It is recomputed — never cached — immediately after any
        score publication, invalidation, or reinstatement commits, and the
        recompute may move the marker in either direction: an invalidation can
        drop it, a later reinstatement restores it."

        Design: Difficulty/transitive_cascade/exam_invalidation_cascades_attempt_progression_curriculum
        """
        bundle = _scored_with_cycles_setup()
        before = get_enrollment_of_candidate(bundle["candidate"]["id"])
        assert set(before["curriculum_access_cycle_ids"]) == {
            bundle["cycle_1"]["id"],
            bundle["cycle_2"]["id"],
        }
        adjudicate_case(
            bundle["case"],
            outcome="SANCTIONED",
            sanction_type="EXAM_INVALIDATION",
            adjudicator_user_id="adj-1",
        )
        candidate = get_candidate(bundle["candidate"]["id"])
        assert candidate["highest_level_passed_code"] is None
        after = get_enrollment_of_candidate(bundle["candidate"]["id"])
        assert after["curriculum_access_cycle_ids"] == [bundle["cycle_1"]["id"]]


class TestWindowCancelCascade:
    def test_window_cancel_credits_paid_fee_to_balance(self, api, program_admin_headers):
        """PRD §3.4: "The cascade walks the window's appointments in creation
        order: every appointment still `SCHEDULED` flips to `CANCELLED`
        (appointments already `CHECKED_IN` are not touched), and each
        so-cancelled appointment is compensated with its **full**
        `exam_fee_cents`, deadline-independent, posted per the standard credit
        mechanics."
        PRD §2.8: "When a credit posts to an enrollment, it absorbs outstanding
        charges first — the applied portion is the lesser of the credit and the
        current outstanding balance, which reduces `outstanding_balance_cents`
        and increases `lifetime_credits_applied_cents` — and any remainder
        raises `credit_balance_cents`."

        Design: Difficulty/transitive_cascade/window_cancel_cascades_appointment_credit_ledger
        """
        context, appointment, _later = _window_cancel_setup()
        resp = api.cancel_exam_window(context["window"]["id"], program_admin_headers)
        assert validate_success(resp, 200)["status"] == "CANCELLED"
        assert get_appointment(appointment["id"])["booking_status"] == "CANCELLED"
        enrollment = get_enrollment_of_candidate(context["candidate"]["id"])
        assert enrollment["credit_balance_cents"] == 94000
        assert enrollment["lifetime_credits_posted_cents"] == 94000
        assert enrollment["net_billed_cents"] == 35003

    def test_rebook_draws_down_credit_balance(self, api, program_admin_headers):
        """PRD §2.8: "Conversely, when a new charge posts to an enrollment
        holding a positive credit balance, the credit balance is drawn down
        against the new charge first, so only the unabsorbed remainder adds to
        what the candidate owes."

        Design: Difficulty/transitive_cascade/window_cancel_cascades_appointment_credit_ledger
        """
        context, _appointment, window_later = _window_cancel_setup()
        validate_success(
            api.cancel_exam_window(context["window"]["id"], program_admin_headers), 200
        )
        rebooked = api.create_appointment(
            create_appointment_payload(
                context["enrollment"]["id"],
                window_later["id"],
                context["center"]["id"],
                exam_date="2027-04-02",
            ),
            context["candidate_headers"],
        )
        validate_success(rebooked, 201)
        enrollment = get_enrollment_of_candidate(context["candidate"]["id"])
        assert enrollment["credit_balance_cents"] == 0
        assert enrollment["outstanding_balance_cents"] == 0
        assert enrollment["lifetime_charges_cents"] == 35003 + 94000 + 94000
        assert enrollment["lifetime_credits_posted_cents"] == 94000
