"""Cascades that propagate through three hops of related rows."""
from test_helpers import (
    INTEGRITY_INVESTIGATOR_2,
    MID_REGULAR_CLOCK_UTC,
    create_audit,
    create_order,
    create_registration,
    create_send,
    get_order,
    get_registration,
    get_school,
    get_score,
    get_send,
    host_headers,
    make_integrity_investigator_headers,
    open_case,
    set_clock,
    setup_approved_school,
    setup_released_score,
    take_audit_into_review,
    approve_audit,
    transition_case,
    transition_send,
)


def _release_blocking_case_to_decision_pending(bundle, finding_code, irregularity_type):
    case = open_case(bundle["registration"], bundle["school"], irregularity_type)
    case = transition_case(case, "INVESTIGATING")
    return transition_case(
        case, "DECISION_PENDING", {"finding_code": finding_code, "reporter_user_id": "reporter-x"}
    )


# --------------------------------------------------------------------------
# IrregularityCase -> ExamScore -> ExamRegistration -> ScoreSend
# --------------------------------------------------------------------------

def _invalidation_setup():
    """A released score carrying two college sends and one school send, all sent."""
    bundle = setup_released_score()
    score, school = bundle["score"], bundle["school"]
    sends = [
        create_send(score, school, recipient_type="COLLEGE", recipient_code="C2001"),
        create_send(score, school, recipient_type="COLLEGE", recipient_code="C2002"),
    ]
    sends.append(
        create_send(score, school, recipient_type="SCHOOL", recipient_code=school["school_code"])
    )
    sent = [
        transition_send(send, "SENT", {"fees_paid_cents": send["fee_cents"]}, school)
        for send in sends
    ]
    bundle["sends"] = sent
    return bundle


def _confirm_invalidation(bundle):
    case = _release_blocking_case_to_decision_pending(
        bundle, "SCORE_INVALIDATION_REQUIRED", "UNAUTHORIZED_DEVICE"
    )
    return transition_case(
        case,
        "CONFIRMED",
        {"finding_code": "SCORE_INVALIDATION_REQUIRED"},
        headers=make_integrity_investigator_headers(INTEGRITY_INVESTIGATOR_2),
    )


def test_score_invalidation_finding_invalidates_score_and_registration():
    """PRD §3.9: "Confirming with `SCORE_INVALIDATION_REQUIRED` runs the deepest cascade in the program: the linked registration transitions to `INVALIDATED`, its score transitions to `INVALIDATED`"

    Design: Difficulty/transitive_cascade/irregularity_invalidation_depth3_cascade
    """
    bundle = _invalidation_setup()
    _confirm_invalidation(bundle)

    assert get_score(bundle["score"]["id"])["status"] == "INVALIDATED", "hop 1"
    assert get_registration(bundle["registration"]["id"])["status"] == "INVALIDATED", "hop 2"


def test_score_invalidation_finding_cancels_every_send_and_credits_back_its_fee():
    """PRD §3.9: "every score send of that score transitions to `CANCELLED` with `credit_back_cents` set to its `fee_cents`, restoring the designation budget those sends had consumed."
    PRD §3.8: "A sent send is cancelled by the system whenever its score becomes `WITHHELD` or `INVALIDATED`, restoring the same credit and releasing the designation budget the original dispatch consumed."

    Design: Difficulty/transitive_cascade/irregularity_invalidation_depth3_cascade
    """
    bundle = _invalidation_setup()
    _confirm_invalidation(bundle)

    for send in bundle["sends"]:
        after = get_send(send["id"], bundle["school"])
        assert after["status"] == "CANCELLED", f"hop 3 must cancel send {send['id']}"
        assert after["credit_back_cents"] == after["fee_cents"], (
            f"the cancelled send must restore exactly its fee: "
            f"{after['credit_back_cents']} != {after['fee_cents']}"
        )

    assert get_school(bundle["school"]["id"])["designation_slots_used"] == 0, (
        "the cancellation restores the designation budget the dispatches had consumed"
    )


# --------------------------------------------------------------------------
# CourseAudit -> ExamOrder -> ExamRegistration
# --------------------------------------------------------------------------

def _second_audit_setup():
    """A label-authorized school with a DRAFT order pinned to a second audit."""
    first = setup_approved_school()
    school = first["school"]
    set_clock(MID_REGULAR_CLOCK_UTC)
    second_audit = create_audit(school, course_title="AP English Literature")
    student = _enroll(school)
    order = create_order(school, second_audit)
    registration = create_registration(
        order, student, school, exam_subject="AP-ENGL-LIT", registration_tier="REGULAR"
    )
    return {
        "school": school,
        "audit": take_audit_into_review(second_audit),
        "order": order,
        "registration": registration,
    }


def _enroll(school):
    from test_helpers import create_student

    return create_student(school)


def test_second_audit_approval_opens_the_draft_order_pinned_to_it():
    """PRD §3.1: "It then cascades: every exam order whose `course_audit_id` points at this audit and whose status is `DRAFT` transitions to `OPEN`, which reclassifies that order's `ordering_window` from the logical clock"
    PRD §3.1: "Approval sets `approval_term_end_utc` to `2027-06-30T23:59:59Z`, recomputes the school's `designated_course_count` as the number of that school's audits now in `APPROVED`, and flips `program_label_authorized` to true, since a designated course now exists."

    Design: Difficulty/transitive_cascade/audit_approval_depth3_cascade_opens_orders_and_confirms
    """
    bundle = _second_audit_setup()
    approve_audit(bundle["audit"])

    order = get_order(bundle["order"]["id"])
    assert order["status"] == "OPEN", "hop 1: the DRAFT order opens with the approval"
    assert order["ordering_window"] == "REGULAR"
    assert bundle["school"]["program_label_authorized"] is True


def test_second_audit_approval_confirms_the_registrations_of_the_opened_order():
    """PRD §3.1: "every registration in `REGISTERED` whose student is not accommodation-eligible transitions to `CONFIRMED`, while a registration whose student holds an accommodation request for that exam that has not been revoked stays `REGISTERED`"

    Design: Difficulty/transitive_cascade/audit_approval_depth3_cascade_opens_orders_and_confirms
    """
    bundle = _second_audit_setup()
    approve_audit(bundle["audit"])

    registration = get_registration(bundle["registration"]["id"])
    assert registration["status"] == "CONFIRMED", (
        "hop 2: the opened order is what confirms its REGISTERED registrations"
    )
    assert registration["fees_paid_cents"] == 0
