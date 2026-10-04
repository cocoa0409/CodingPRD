"""Difficulty rule: non_linear_state_machine — placement appeal cycle and
enrollment waitlist revert."""
from test_helpers import (
    TEST_USERS, api_client, validate_success, validate_error, ApiErrorId,
    create_level, create_student, reset_clock, create_placement_evaluation_payload,
    make_student_headers, get_placement, setup_open_term_with_section,
    enroll_with_fresh_version, confirm_enrollment, drop_enrollment, get_enrollment,
    get_section,
)

PD = TEST_USERS["program_director_headers"]
REG = TEST_USERS["registrar_headers"]
PO = TEST_USERS["placement_officer_headers"]


def _denied_portfolio_evaluation():
    reset_clock()
    create_level(code="L1", allows_placement_bypass=False)
    lvl2 = create_level(code="L2", sequence_index=1, requires_level_code="L1",
                        allows_placement_bypass=True)
    student = create_student()
    pe = validate_success(api_client.create_placement_evaluation(
        create_placement_evaluation_payload(
            student["id"], lvl2["id"], prior_institution="Unknown School",
            portfolio_score=40), PO), 201)
    validate_success(api_client.begin_review_placement(pe["id"], PO))
    validate_success(api_client.deny_placement(pe["id"], PO))
    return student, pe


class TestPlacementEvaluationAppealCycle:
    def test_appeal_moves_denied_to_appealed(self):
        """PRD §3.3: "The student who owns a denied petition may appeal it
        (`DENIED → APPEALED`), and a PlacementOfficer may then begin review again
        (`APPEALED → UNDER_REVIEW`) for a second adjudication."

        Design: Difficulty/non_linear_state_machine/placement_evaluation_appeal_cycle
        """
        student, pe = _denied_portfolio_evaluation()
        appealed = validate_success(api_client.appeal_placement(
            pe["id"], make_student_headers(student["id"])))
        assert appealed["decision"] == "APPEALED"

    def test_appealed_can_reenter_under_review_and_double_begin_review_fails(self):
        """PRD §3.3: "The student who owns a denied petition may appeal it
        (`DENIED → APPEALED`), and a PlacementOfficer may then begin review again
        (`APPEALED → UNDER_REVIEW`) for a second adjudication."
        PRD §2.7: "then whether the target entity's current state permits the
        requested transition (`ERR_INVALID_STATE`)"

        Design: Difficulty/non_linear_state_machine/placement_evaluation_appeal_cycle
        """
        student, pe = _denied_portfolio_evaluation()
        validate_success(api_client.appeal_placement(
            pe["id"], make_student_headers(student["id"])))
        under_review = validate_success(api_client.begin_review_placement(pe["id"], PO))
        assert under_review["decision"] == "UNDER_REVIEW"
        resp = api_client.begin_review_placement(pe["id"], PO)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE, 409)


def _waitlist_revert_setup():
    ctx = setup_open_term_with_section(capacity=1)
    s1 = create_student()
    s2 = create_student()
    e1 = enroll_with_fresh_version(s1["id"], ctx["section"]["id"])
    confirm_enrollment(e1["id"])
    e2 = enroll_with_fresh_version(s2["id"], ctx["section"]["id"])
    return ctx, s1, s2, e1, e2


class TestEnrollmentWaitlistRevert:
    def test_full_section_enrollment_born_waitlisted(self):
        """PRD §3.3: "If the section's `enrolled_count` has reached `capacity`, the
        new enrollment is born directly into `WAITLISTED` and the section's
        `waitlist_count` rises by 1."

        Design: Difficulty/non_linear_state_machine/enrollment_branching_with_revert_via_waitlist_promotion
        """
        ctx, s1, s2, e1, e2 = _waitlist_revert_setup()
        assert e2["status"] == "WAITLISTED"
        section = get_section(ctx["section"]["id"])
        assert section["waitlist_count"] == 1

    def test_drop_promotes_waitlisted_back_to_registered(self):
        """PRD §3.3: "The head enrollment transitions `WAITLISTED → REGISTERED`,
        the section's `waitlist_count` falls by 1, and `enrolled_count` does not
        change until the promoted student confirms."
        PRD §3.3: "Before the term's `drop_deadline_utc`, a drop is early: a
        `CONFIRMED` enrollment moves to `DROPPED_EARLY`, the section's
        `enrolled_count` falls by 1"

        Design: Difficulty/non_linear_state_machine/enrollment_branching_with_revert_via_waitlist_promotion
        """
        ctx, s1, s2, e1, e2 = _waitlist_revert_setup()
        dropped = drop_enrollment(e1["id"])
        assert dropped["status"] == "DROPPED_EARLY"
        promoted = get_enrollment(e2["id"])
        assert promoted["status"] == "REGISTERED"
        section = get_section(ctx["section"]["id"])
        assert section["enrolled_count"] == 0
        assert section["waitlist_count"] == 0
