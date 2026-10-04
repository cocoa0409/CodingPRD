"""Stale-version rejection on the four endpoints that enforce optimistic concurrency."""
from test_helpers import (
    ADMIN,
    ALTERNATE_PLANNING_CLOCK_UTC,
    ApiErrorId,
    MID_REGULAR_CLOCK_UTC,
    REVIEWER,
    SPECIALIST,
    api_client,
    calibrate_reader,
    create_alternate,
    create_audit,
    create_order,
    create_registration,
    create_school,
    create_score,
    get_order,
    get_registration,
    get_school,
    host_headers,
    recruit_reader,
    set_clock,
    setup_material_assigned_registration,
    setup_open_order,
    take_audit_into_review,
    transition_alternate,
    transition_registration,
    transition_score,
    validate_error,
    validate_paginated,
)


def test_stale_course_audit_version_is_rejected():
    """PRD §2.5: "The course-audit status transitions require `expected_course_audit_version` matching the target audit's current `version`."
    PRD §2.5: "each rejects the request with `ERR_STALE_VERSION` and HTTP 412 when that value does not equal the entity's current `version`"

    Design: Corner/cross_cutting_complexity_layers/audit_transition_with_stale_expected_version_returns_412
    """
    school = create_school()
    audit = take_audit_into_review(create_audit(school))
    current_version = audit["version"]

    response = api_client.transition_course_audit(
        audit["id"],
        {
            "to_status": "APPROVED",
            "expected_course_audit_version": current_version - 1,
            "decision_notes": "syllabus meets the curricular requirements",
        },
        REVIEWER,
    )
    validate_error(response, ApiErrorId.ERR_STALE_VERSION)
    assert response.status_code == 412

    data, _meta = validate_paginated(
        api_client.list_course_audits(ADMIN, params={"school_id": school["id"]})
    )
    assert data[0]["status"] == "IN_REVIEW"
    assert data[0]["version"] == current_version
    assert get_school(school["id"])["program_label_authorized"] is False


def test_stale_exam_order_version_is_rejected():
    """PRD §2.5: "The exam-order status transitions require `expected_exam_order_version` matching the target order's current `version`."
    PRD §3.2: "Every order transition carries `expected_exam_order_version`, and a caller whose view of the order's `status` or `order_fee_cents` predates a cascade — an audit approval that opened the order, or a seal-break revert that pushed it back — is rejected as stale."

    Design: Corner/cross_cutting_complexity_layers/order_transition_with_stale_expected_version_returns_412
    """
    bundle = setup_open_order(clock=MID_REGULAR_CLOCK_UTC)
    create_registration(
        bundle["order"], bundle["student"], bundle["school"], exam_subject="AP-MACRO"
    )
    order = get_order(bundle["order"]["id"])

    response = api_client.transition_exam_order(
        order["id"],
        {"to_status": "SUBMITTED", "expected_exam_order_version": order["version"] - 1},
        host_headers(bundle["school"]),
    )
    validate_error(response, ApiErrorId.ERR_STALE_VERSION)
    assert response.status_code == 412

    after = get_order(order["id"])
    assert after["status"] == "OPEN"
    assert after["version"] == order["version"]
    # PRD §3.2: "`order_fee_cents` holds the provisional figure while the order
    # is `OPEN`", and the provisional variant charges every registered exam at
    # the base fee of 18000 cents — so the rejected transition leaves the one
    # registered exam's 18000-cent provisional figure on the row, unchanged.
    assert after["order_fee_cents"] == 18000, (
        f"the rejected transition must not reprice the order, got {after['order_fee_cents']}"
    )


def test_stale_alternate_request_version_is_rejected():
    """PRD §2.5: "The alternate-exam-request status transitions require `expected_alternate_exam_request_version` matching the target request's current `version`."
    PRD §3.6: "a caller holding a stale view of the approved date is rejected as stale rather than allowed to overwrite it"

    Design: Corner/cross_cutting_complexity_layers/alternate_request_transition_with_stale_expected_version_returns_412
    """
    bundle = setup_open_order(clock=ALTERNATE_PLANNING_CLOCK_UTC)
    school = bundle["school"]
    registration = create_registration(
        bundle["order"], bundle["student"], school, exam_subject="AP-SPAN-LANG"
    )
    registration = transition_registration(registration, "CONFIRMED", school=school)

    alternate = create_alternate(
        registration,
        school,
        alternate_date_utc="2027-06-20T00:00:00Z",
        reason_code="SCHEDULE_CONFLICT",
        form_code="ALT-FORM-27",
    )
    alternate = transition_alternate(alternate, "UNDER_REVIEW", school=school)

    response = api_client.transition_alternate_exam_request(
        alternate["id"],
        {
            "to_status": "APPROVED",
            "expected_alternate_exam_request_version": alternate["version"] - 1,
        },
        host_headers(school),
    )
    validate_error(response, ApiErrorId.ERR_STALE_VERSION)
    assert response.status_code == 412

    data, _meta = validate_paginated(
        api_client.list_registration_alternate_requests(
            registration["id"], host_headers(school)
        )
    )
    assert data[0]["status"] == "UNDER_REVIEW"
    assert data[0]["version"] == alternate["version"]


def test_stale_exam_score_version_is_rejected():
    """PRD §2.5: "The exam-score status transitions require `expected_exam_score_version` matching the target score's current `version`."
    PRD §2.5: "A caller whose view of `release_blocked` predates a release-block write is rejected."

    Design: Corner/cross_cutting_complexity_layers/score_transition_with_stale_expected_version_returns_412
    """
    bundle = setup_material_assigned_registration(subject="AP-FRENCH")
    reader = calibrate_reader(recruit_reader("AP-FRENCH"))
    score = create_score(bundle["registration"], reader, raw_composite=80.0)
    score = transition_score(score, "RUBRIC_PENDING")

    response = api_client.transition_exam_score(
        score["id"],
        {"to_status": "AGGREGATED", "expected_exam_score_version": score["version"] - 1},
        SPECIALIST,
    )
    validate_error(response, ApiErrorId.ERR_STALE_VERSION)
    assert response.status_code == 412

    from test_helpers import get_score

    after = get_score(score["id"])
    assert after["status"] == "RUBRIC_PENDING"
    assert after["ap_score"] == 0
    assert get_registration(bundle["registration"]["id"])["status"] == "MATERIAL_ASSIGNED"
