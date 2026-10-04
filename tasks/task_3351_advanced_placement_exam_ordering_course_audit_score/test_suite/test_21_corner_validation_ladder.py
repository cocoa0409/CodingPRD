"""One failing rung of the ordered ladder at a time."""
from test_helpers import (
    ACCOM_REVIEWER,
    ADMIN,
    ApiErrorId,
    LATE_WINDOW_CLOCK_UTC,
    MID_REGULAR_CLOCK_UTC,
    REVIEWER,
    api_client,
    create_accommodation,
    create_audit,
    create_school,
    get_accommodation,
    get_order,
    get_school,
    host_headers,
    set_clock,
    setup_approved_school,
    setup_fee_pending_registration,
    setup_open_order,
    take_audit_into_review,
    transition_accommodation,
    transition_registration,
    validate_error,
    validate_paginated,
)


def test_registration_is_refused_outside_the_ordering_window():
    """PRD §2.4: "Because the default clock is `2026-09-01T00:00:00Z`, any order classified without an explicit clock set lands in `NOT_OPEN`."
    PRD §3.3: "the ordering-window classification at the logical clock must be `REGULAR` or `LATE`, with `CLOSED` and `NOT_OPEN` refused as `ERR_ORDER_WINDOW_CLOSED`"

    Design: Corner/validations/registration_refused_outside_ordering_window
    """
    bundle = setup_open_order(clock=None)
    assert bundle["order"]["ordering_window"] == "NOT_OPEN"

    response = api_client.create_exam_registration(
        {
            "exam_order_id": bundle["order"]["id"],
            "student_id": bundle["student"]["id"],
            "exam_subject": "AP-US-HIST",
            "registration_tier": "REGULAR",
        },
        host_headers(bundle["school"]),
    )
    validate_error(response, ApiErrorId.ERR_ORDER_WINDOW_CLOSED)

    _data, meta = validate_paginated(
        api_client.list_order_registrations(bundle["order"]["id"], host_headers(bundle["school"]))
    )
    assert meta["total_count"] == 0


def test_submitting_an_empty_order_is_refused_as_below_minimum_size():
    """PRD §3.2: "Submitting an order to the program moves it from `OPEN` to `SUBMITTED` and requires that the order holds at least one registration"
    PRD §2.6: "| 13 | An exam order entering `SUBMITTED` has a `registration_count` of at least 1 | `ERR_ORDER_MIN_SIZE` | 422 |"

    Design: Corner/validations/order_submit_below_min_size_returns_min_size_error
    """
    bundle = setup_open_order(clock=MID_REGULAR_CLOCK_UTC)
    order = bundle["order"]

    response = api_client.transition_exam_order(
        order["id"],
        {"to_status": "SUBMITTED", "expected_exam_order_version": order["version"]},
        host_headers(bundle["school"]),
    )
    validate_error(response, ApiErrorId.ERR_ORDER_MIN_SIZE)

    after = get_order(order["id"])
    assert after["status"] == "OPEN"
    assert after["registration_count"] == 0
    assert after["order_fee_cents"] == 0, "a refused submit never charges the provisional variant"


def test_confirming_with_an_unpaid_late_fee_returns_payment_required():
    """PRD §3.3: "a `LATE` tier pays 4000 cents when the window is `LATE`"
    PRD §3.3: "The forward move to `CONFIRMED` requires `fees_paid_cents` to be at least `late_fee_cents`, and a registration whose late fee is still unpaid is refused with `ERR_LATE_FEE_UNPAID`"

    Design: Corner/validations/confirm_with_unpaid_late_fee_returns_payment_required
    """
    bundle = setup_fee_pending_registration(clock=LATE_WINDOW_CLOCK_UTC)
    registration = bundle["registration"]
    assert registration["late_fee_cents"] == 4000
    assert registration["status"] == "FEE_PENDING"

    response = api_client.transition_exam_registration(
        registration["id"], {"to_status": "CONFIRMED"}, host_headers(bundle["school"])
    )
    validate_error(response, ApiErrorId.ERR_LATE_FEE_UNPAID)

    after_response = api_client.get_exam_registration(
        registration["id"], host_headers(bundle["school"])
    )
    after = after_response.json()["data"]
    assert after["status"] == "FEE_PENDING"
    assert after["fees_paid_cents"] == 0


def test_approving_an_audit_without_decision_notes_returns_audit_not_reviewed():
    """PRD §3.1: "A decision attempted before any review pass — `review_round` still 0, or with empty `decision_notes` — is refused with `ERR_AUDIT_NOT_REVIEWED`."
    PRD §2.6: "| 9 | A course audit entering `APPROVED` has `review_round` at least 1 and a non-empty `decision_notes` | `ERR_AUDIT_NOT_REVIEWED` | 409 |"

    Design: Corner/validations/audit_approval_without_decision_notes_returns_audit_not_reviewed
    """
    school = create_school()
    audit = take_audit_into_review(create_audit(school))
    assert audit["review_round"] == 1

    response = api_client.transition_course_audit(
        audit["id"],
        {"to_status": "APPROVED", "expected_course_audit_version": audit["version"]},
        REVIEWER,
    )
    validate_error(response, ApiErrorId.ERR_AUDIT_NOT_REVIEWED)

    data, _meta = validate_paginated(
        api_client.list_course_audits(ADMIN, params={"school_id": school["id"]})
    )
    assert data[0]["status"] == "IN_REVIEW"
    assert data[0]["review_round"] == 1
    assert get_school(school["id"])["program_label_authorized"] is False


def test_approving_an_accommodation_below_the_documentation_threshold_is_refused():
    """PRD §3.4: "Approval happens from `UNDER_DOC_REVIEW` and requires the completeness to be at least 3 and the actor to be someone other than the filing user; a request below the threshold is refused with `ERR_DOCUMENTS_INCOMPLETE`."
    PRD §3.4: "The `documentation_completeness` value lies between 0 and 3 inclusive, and the completeness threshold for approval is 3."

    Design: Corner/validations/accommodation_approval_with_two_docs_returns_documents_incomplete
    """
    school = create_school()
    set_clock(MID_REGULAR_CLOCK_UTC)
    from test_helpers import create_student

    student = create_student(school)
    request = create_accommodation(
        student, school, accommodation_type="EXTENDED_TIME", documentation_completeness=2
    )
    request = transition_accommodation(request, "UNDER_DOC_REVIEW")
    assert request["review_round"] == 1

    response = api_client.transition_accommodation_request(
        request["id"], {"to_status": "APPROVED"}, ACCOM_REVIEWER
    )
    validate_error(response, ApiErrorId.ERR_DOCUMENTS_INCOMPLETE)

    after = get_accommodation(request["id"])
    assert after["status"] == "UNDER_DOC_REVIEW"
    assert after["extended_time_multiplier"] == 1.0

    nested, _meta = validate_paginated(
        api_client.list_student_accommodation_requests(student["id"], ADMIN)
    )
    assert all(row["status"] != "APPROVED" for row in nested)


def test_unauthorized_role_outranks_a_missing_path_resource():
    """PRD §2.6: "| 3 | The acting role appears in the endpoint's authorized role list | `ERR_UNAUTHORIZED` | 403 |"
    PRD §2.6: "| 5 | The path resource exists | `ERR_RESOURCE_NOT_FOUND` | 404 |"
    PRD §2.6: "Every request is evaluated against an ordered ladder of twenty-nine ranks, and the first failing rank wins"

    Design: Corner/validations/unauthorized_role_outranks_missing_path_resource
    """
    from test_helpers import TEST_USERS

    response = api_client.get_school(
        "does-not-exist-0001", TEST_USERS["scoring_specialist_headers"]
    )
    error = validate_error(response, ApiErrorId.ERR_UNAUTHORIZED)
    assert error["error_id"] != ApiErrorId.ERR_RESOURCE_NOT_FOUND
    assert response.status_code == 403
    assert response.json()["response_type"] == "error"
