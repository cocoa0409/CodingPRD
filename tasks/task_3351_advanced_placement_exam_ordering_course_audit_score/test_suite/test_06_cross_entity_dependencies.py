"""Rules whose outcome depends on another entity's state, not the caller's own."""
from test_helpers import (
    ApiErrorId,
    MID_REGULAR_CLOCK_UTC,
    POST_RELEASE_CLOCK_UTC,
    SPECIALIST,
    api_client,
    approve_audit,
    create_audit,
    create_order,
    create_school,
    get_order,
    get_score,
    get_school,
    host_headers,
    open_case,
    set_clock,
    setup_aggregated_score,
    take_audit_into_review,
    transition_case,
    validate_error,
    validate_success,
)


# --------------------------------------------------------------------------
# ExamOrder <- CourseAudit / School
# --------------------------------------------------------------------------

def test_draft_order_cannot_open_against_an_unapproved_audit():
    """PRD §3.2: "Both paths require the referenced audit to be `APPROVED`, the school's `program_label_authorized` to be true, and the school's `test_center_status` to be `ACTIVE`; an order that tries to open against an unapproved audit or an unauthorized school is refused with `ERR_COURSE_AUDIT_NOT_APPROVED`."

    Design: Difficulty/cross_entity_state_dependency/exam_order_open_depends_on_audit_approved_and_label
    """
    school = create_school()
    set_clock(MID_REGULAR_CLOCK_UTC)
    audit = create_audit(school)
    order = create_order(school, audit)

    response = api_client.transition_exam_order(
        order["id"],
        {"to_status": "OPEN", "expected_exam_order_version": order["version"]},
        host_headers(school),
    )
    validate_error(response, ApiErrorId.ERR_COURSE_AUDIT_NOT_APPROVED)

    assert get_order(order["id"])["status"] == "DRAFT", "the refusal leaves the order untouched"
    assert get_school(school["id"])["program_label_authorized"] is False


def test_order_becomes_openable_once_the_audit_reaches_approved():
    """PRD §2.9: "a school's `program_label_authorized` flag is derived, never set directly: it is true exactly while the school has at least one course audit in `APPROVED` status, and it gates every course-label and exam-order operation"
    PRD §3.2: "Both paths require the referenced audit to be `APPROVED`, the school's `program_label_authorized` to be true, and the school's `test_center_status` to be `ACTIVE`"

    Design: Difficulty/cross_entity_state_dependency/exam_order_open_depends_on_audit_approved_and_label
    """
    school = create_school()
    set_clock(MID_REGULAR_CLOCK_UTC)
    audit = create_audit(school)
    order = create_order(school, audit)

    audit = take_audit_into_review(audit)
    approve_audit(audit)

    assert get_school(school["id"])["program_label_authorized"] is True
    assert get_order(order["id"])["status"] == "OPEN", (
        "the approved audit is what makes the pinned DRAFT order openable"
    )


# --------------------------------------------------------------------------
# ExamScore <- IrregularityCase
# --------------------------------------------------------------------------

def test_release_is_refused_while_an_irregularity_case_is_open():
    """PRD §3.8: "A release is also refused while the score's `release_blocked` flag is true, which it is whenever an irregularity case for the same registration sits in `OPEN` or `INVESTIGATING`; that refusal carries `ERR_RELEASE_BLOCKED`."
    PRD §3.9: "opening it immediately sets `release_blocked` to true on every score of that registration that is `AGGREGATED` or `RELEASED`, so an investigation stops a release before it can happen rather than unwinding it afterwards."

    Design: Difficulty/cross_entity_state_dependency/score_release_depends_on_irregularity_case_cleared
    """
    bundle = setup_aggregated_score()
    set_clock(POST_RELEASE_CLOCK_UTC)
    open_case(bundle["registration"], bundle["school"], "UNAUTHORIZED_DEVICE")

    score = get_score(bundle["score"]["id"])
    assert score["release_blocked"] is True

    response = api_client.transition_exam_score(
        score["id"],
        {"to_status": "RELEASED", "expected_exam_score_version": score["version"]},
        SPECIALIST,
    )
    validate_error(response, ApiErrorId.ERR_RELEASE_BLOCKED)


def test_dismissing_the_case_reopens_the_release_path():
    """PRD §3.9: "A case is dismissed from `DECISION_PENDING` only when its `finding_code` is `NO_FINDING` or is empty, and dismissal clears `release_blocked` on every score of the linked registration."
    PRD §3.7: "a composite of 96.0 or more is a 5"

    Design: Difficulty/cross_entity_state_dependency/score_release_depends_on_irregularity_case_cleared
    """
    bundle = setup_aggregated_score()
    set_clock(POST_RELEASE_CLOCK_UTC)
    case = open_case(bundle["registration"], bundle["school"], "UNAUTHORIZED_DEVICE")
    case = transition_case(case, "INVESTIGATING")
    case = transition_case(case, "DECISION_PENDING", {"finding_code": "NO_FINDING"})
    transition_case(case, "DISMISSED")

    score = get_score(bundle["score"]["id"])
    assert score["release_blocked"] is False, "dismissal clears the block"

    released = validate_success(
        api_client.transition_exam_score(
            score["id"],
            {"to_status": "RELEASED", "expected_exam_score_version": score["version"]},
            SPECIALIST,
        )
    )
    assert released["status"] == "RELEASED"
    assert released["ap_score"] == 5
