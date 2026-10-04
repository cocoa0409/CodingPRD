"""The cyclic edges: the audit revision loop and the irregularity appeal cycle."""
from test_helpers import (
    APPEAL_CYCLE_CLOCK_UTC,
    INTEGRITY_INVESTIGATOR_2,
    REVIEWER,
    api_client,
    create_audit,
    create_school,
    get_school,
    get_score,
    host_headers,
    make_integrity_investigator_headers,
    open_case,
    request_audit_revision,
    resubmit_audit,
    set_clock,
    setup_released_score,
    take_audit_into_review,
    transition_case,
    validate_success,
)


def _reject_audit(audit, notes="curricular requirements not met"):
    return validate_success(
        api_client.transition_course_audit(
            audit["id"],
            {
                "to_status": "REJECTED",
                "expected_course_audit_version": audit["version"],
                "decision_notes": notes,
            },
            REVIEWER,
        )
    )


def _trip_revision_loop(school, audit, new_hash):
    audit = request_audit_revision(audit)
    audit = resubmit_audit(audit, school, new_hash)
    return take_audit_into_review(audit)


# --------------------------------------------------------------------------
# CourseAudit: the revision cycle and the divergent rejection branch
# --------------------------------------------------------------------------

def test_revision_loop_increments_syllabus_revision_count():
    """PRD §3.1: "A `SchoolCoordinator` returns a `REVISION_REQUESTED` audit to `SUBMITTED`, supplying a fresh `syllabus_hash`"
    PRD §3.1: "A successful revision increments `syllabus_revision_count` by 1."
    PRD §3.1: "A revision request deliberately leaves the school's `program_label_authorized` untouched, because the audit was never approved and the school has no designation authority to lose."

    Design: Difficulty/non_linear_state_machine/course_audit_revision_loop_with_rejection_branch
    """
    school = create_school()
    audit = take_audit_into_review(create_audit(school))
    audit = request_audit_revision(audit)
    assert audit["status"] == "REVISION_REQUESTED"

    audit = resubmit_audit(audit, school, "hash-pc-1-rev")

    assert audit["status"] == "SUBMITTED", "the loop re-enters the machine at SUBMITTED"
    assert audit["syllabus_revision_count"] == 1, (
        f"one loop trip must record one revision, got {audit['syllabus_revision_count']}"
    )
    assert get_school(school["id"])["program_label_authorized"] is False


def test_rejection_branch_terminates_the_audit_after_two_revisions():
    """PRD §3.1: "A reviewer may instead reject from `IN_REVIEW`, moving the audit to `REJECTED` when `review_round` is at least 1, `syllabus_revision_count` is at least 2, and `decision_notes` is non-empty"
    PRD §3.1: "`REJECTED` and `EXPIRED` are the audit's terminal states, and any further transition attempt on such an audit is refused as terminal."

    Design: Difficulty/non_linear_state_machine/course_audit_revision_loop_with_rejection_branch
    """
    school = create_school()
    audit = take_audit_into_review(create_audit(school))
    audit = _trip_revision_loop(school, audit, "hash-pc-1-rev")
    audit = _trip_revision_loop(school, audit, "hash-pc-1-rev2")
    assert audit["syllabus_revision_count"] == 2

    rejected = _reject_audit(audit)

    assert rejected["status"] == "REJECTED", "the fork takes the terminal branch"
    assert rejected["review_round"] >= 1
    assert rejected["syllabus_revision_count"] == 2
    school_after = get_school(school["id"])
    assert school_after["program_label_authorized"] is False
    assert school_after["designated_course_count"] == 0


# --------------------------------------------------------------------------
# IrregularityCase: the appeal cycle re-opens investigation
# --------------------------------------------------------------------------

def _confirmed_warning_only_case(bundle):
    """Drive a case to CONFIRMED with a WARNING_ONLY finding and return it."""
    case = open_case(bundle["registration"], bundle["school"], "UNAUTHORIZED_DEVICE")
    case = transition_case(case, "INVESTIGATING")
    case = transition_case(
        case, "DECISION_PENDING", {"finding_code": "WARNING_ONLY", "reporter_user_id": "reporter-x"}
    )
    return transition_case(
        case,
        "CONFIRMED",
        headers=make_integrity_investigator_headers(INTEGRITY_INVESTIGATOR_2),
    )


def test_appeal_cycle_returns_the_case_to_investigating_for_a_second_round():
    """PRD §3.9: "From `APPEALED`, an `IntegrityInvestigator` returns the case to `INVESTIGATING`, incrementing `investigation_round` again"
    PRD §3.9: "A `SchoolCoordinator` may move a confirmed case to `APPEALED` while the logical clock is before the later of thirty days after the case was confirmed and `2027-08-15T23:59:59Z`"

    Design: Difficulty/non_linear_state_machine/irregularity_case_appeal_cycle_and_score_reblock
    """
    bundle = setup_released_score()
    set_clock(APPEAL_CYCLE_CLOCK_UTC)
    case = _confirmed_warning_only_case(bundle)

    case = transition_case(case, "APPEALED", headers=host_headers(bundle["school"]))
    assert case["status"] == "APPEALED"
    case = transition_case(case, "INVESTIGATING")

    assert case["status"] == "INVESTIGATING", "the cycle re-enters investigation"
    assert case["investigation_round"] == 2, (
        f"the appeal round must increment investigation_round, got {case['investigation_round']}"
    )


def test_appeal_cycle_re_blocks_score_release():
    """PRD §3.9: "Confirming with `WARNING_ONLY` instead clears `release_blocked` on every score of the registration and changes no score state at all."
    PRD §3.9: "an `IntegrityInvestigator` returns the case to `INVESTIGATING`, incrementing `investigation_round` again and re-blocking release on every score of the registration that had been released"

    Design: Difficulty/non_linear_state_machine/irregularity_case_appeal_cycle_and_score_reblock
    """
    bundle = setup_released_score()
    set_clock(APPEAL_CYCLE_CLOCK_UTC)
    case = _confirmed_warning_only_case(bundle)

    assert get_score(bundle["score"]["id"])["release_blocked"] is False, (
        "WARNING_ONLY clears the release block"
    )

    case = transition_case(case, "APPEALED", headers=host_headers(bundle["school"]))
    transition_case(case, "INVESTIGATING")

    assert get_score(bundle["score"]["id"])["release_blocked"] is True, (
        "re-entering INVESTIGATING must re-block the released score"
    )
