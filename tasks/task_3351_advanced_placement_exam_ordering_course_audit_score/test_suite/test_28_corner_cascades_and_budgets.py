"""One fan-out cascade and one cumulative budget trigger."""
from test_helpers import (
    ADMIN,
    ApiErrorId,
    DESIGNATION_SLOT_BUDGET,
    MID_REGULAR_CLOCK_UTC,
    SPECIALIST,
    api_client,
    create_accommodation,
    create_registration,
    create_send,
    get_registration,
    get_school,
    get_student,
    setup_open_order,
    setup_released_score,
    transition_accommodation,
    validate_error,
    validate_paginated,
)


def _accommodation_under_review():
    bundle = setup_open_order(clock=MID_REGULAR_CLOCK_UTC)
    school, student = bundle["school"], bundle["student"]
    registration = create_registration(
        order=bundle["order"],
        student=student,
        school=school,
        exam_subject="AP-BIO",
        registration_tier="REGULAR",
    )
    request = create_accommodation(
        student,
        school,
        exam_subject="AP-BIO",
        accommodation_type="EXTENDED_TIME",
        documentation_completeness=3,
    )
    request = transition_accommodation(request, "UNDER_DOC_REVIEW")
    bundle["registration"] = registration
    bundle["request"] = request
    return bundle


def test_approving_an_accommodation_provisions_the_extended_time_multiplier():
    """PRD §3.4: "Approval sets `extended_time_multiplier` to 1.5 when the accommodation type is `EXTENDED_TIME` and to 1.0 for every other type"
    PRD §3.4: "every registration of that student for the same `exam_subject` that is still `REGISTERED` transitions to `CONFIRMED`"

    Design: Corner/cross_cutting_complexity_layers/accommodation_approval_cascade_confirms_matching_registration
    """
    bundle = _accommodation_under_review()

    approved = transition_accommodation(bundle["request"], "APPROVED")

    assert approved["status"] == "APPROVED"
    assert approved["extended_time_multiplier"] == 1.5
    registration = get_registration(bundle["registration"]["id"])
    assert registration["status"] == "CONFIRMED", "the approval confirms the matching registration"
    assert registration["fees_paid_cents"] == 0, "the cascade, not a fee settlement, confirmed it"


def test_accommodation_approval_marks_the_student_and_the_registration_eligible():
    """PRD §3.4: "sets the student's `accommodation_eligible` flag to true and increments the student's `version`"
    PRD §3.3: "Confirming re-derives the student's `accommodation_eligible` flag from the existence of an approved accommodation request and copies it onto the registration as `accommodation_flag`"

    Design: Corner/cross_cutting_complexity_layers/accommodation_approval_cascade_confirms_matching_registration
    """
    bundle = _accommodation_under_review()

    transition_accommodation(bundle["request"], "APPROVED")

    assert get_student(bundle["student"]["id"])["accommodation_eligible"] is True
    assert get_registration(bundle["registration"]["id"])["accommodation_flag"] is True


def test_ninth_college_send_is_refused_at_the_designation_budget():
    """PRD §3.8: "A new college send is refused once that counter has reached the designation budget of 8 for the administration year, with `ERR_DESIGNATION_SLOTS_EXHAUSTED`."
    PRD §3.8: "creating it recomputes the school's `designation_slots_used` counter, which counts every send of that school's students whose recipient type is `COLLEGE` and whose status is `PENDING`, `SENT` or `ACKNOWLEDGED`"

    Design: Corner/cross_cutting_complexity_layers/ninth_college_send_refused_at_designation_budget
    """
    bundle = setup_released_score()
    score, school = bundle["score"], bundle["school"]
    for index in range(DESIGNATION_SLOT_BUDGET):
        create_send(score, school, recipient_type="COLLEGE", recipient_code=f"C-31{index:02d}")

    response = api_client.create_score_send(
        {
            "exam_score_id": score["id"],
            "recipient_type": "COLLEGE",
            "recipient_code": "C-3109",
            "designation_year": 2027,
        },
        SPECIALIST,
    )
    validate_error(response, ApiErrorId.ERR_DESIGNATION_SLOTS_EXHAUSTED)
    assert response.status_code == 422

    assert get_school(school["id"])["designation_slots_used"] == DESIGNATION_SLOT_BUDGET
    rows, meta = validate_paginated(
        api_client.list_score_sends(ADMIN, params={"exam_score_id": score["id"]})
    )
    assert meta["total_count"] == DESIGNATION_SLOT_BUDGET
    assert all(row["recipient_code"] != "C-3109" for row in rows)
