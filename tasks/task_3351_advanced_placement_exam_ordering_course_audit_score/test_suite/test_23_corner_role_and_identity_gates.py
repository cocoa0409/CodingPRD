"""Role exclusivity, entity-backed identity and segregation of duties."""
from test_helpers import (
    ACCOM_REVIEWER,
    ACCOMMODATION_REVIEWER,
    ADMIN,
    ApiErrorId,
    COURSE_AUDIT_REVIEWER,
    REVIEWER,
    api_client,
    create_accommodation,
    create_audit,
    create_school,
    create_student,
    get_accommodation,
    get_school,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_scoring_specialist_cannot_register_a_school():
    """PRD §2.1: "only `PlatformAdmin` may register a school"
    PRD §2.6: "| 3 | The acting role appears in the endpoint's authorized role list | `ERR_UNAUTHORIZED` | 403 |"

    Design: Corner/rbac/scoring_specialist_denied_school_creation
    """
    from test_helpers import TEST_USERS

    payload = {
        "name": "Corner Thirteen High",
        "school_code": "CN0013",
        "country_code": "US",
        "center_code": "7013",
        "seat_capacity": 10,
    }

    response = api_client.create_school(payload, TEST_USERS["scoring_specialist_headers"])
    validate_error(response, ApiErrorId.ERR_UNAUTHORIZED)

    # The identical payload is accepted by the one role that owns the capability,
    # so the refusal was the role listing and not the request shape.
    created = validate_success(api_client.create_school(payload, ADMIN), expected_status=201)
    assert created["school_code"] == "CN0013"


def test_integrity_investigator_cannot_drive_the_school_test_center_dimension():
    """PRD §2.1: "only `PlatformAdmin` may register a school, drive the school test-center status dimension or move the logical clock"
    PRD §2.6: "| 3 | The acting role appears in the endpoint's authorized role list | `ERR_UNAUTHORIZED` | 403 |"

    Design: Corner/rbac/integrity_investigator_denied_school_status_transition
    """
    from test_helpers import TEST_USERS

    school = create_school()

    response = api_client.transition_school(
        school["id"],
        {"to_status": "SUSPENDED", "expected_school_version": school["version"]},
        TEST_USERS["integrity_investigator_headers"],
    )
    validate_error(response, ApiErrorId.ERR_UNAUTHORIZED)

    assert get_school(school["id"])["test_center_status"] == "ACTIVE"


def test_coordinator_with_an_unknown_school_identity_is_unauthenticated():
    """PRD §2.1: "a `SchoolCoordinator` request whose `X-User-ID` does not match an existing `School` is rejected as unauthenticated"
    PRD §2.6: "| 2 | `X-User-Role` is a declared role, and for an entity-backed role `X-User-ID` equals the `id` of an existing instance of the backing entity | `ERR_UNAUTHENTICATED` | 401 |"

    Design: Corner/rbac/coordinator_with_unknown_school_id_is_unauthenticated
    """
    from test_helpers import make_school_coordinator_headers

    ghost = "school-that-does-not-exist"
    response = api_client.create_student(
        {
            "full_name": "Juno Vale",
            "school_id": ghost,
            "student_code": "S0001",
            "grade_level": 12,
        },
        make_school_coordinator_headers(ghost),
    )
    error = validate_error(response, ApiErrorId.ERR_UNAUTHENTICATED)
    assert error["error_id"] != ApiErrorId.ERR_UNAUTHORIZED
    assert error["error_id"] != ApiErrorId.ERR_FK_NOT_FOUND
    assert response.status_code == 401


def test_course_audit_reviewer_acting_as_its_own_submitter_is_a_segregation_violation():
    """PRD §2.1: "the acting `X-User-ID` must not be the user recorded as the submitter or reporter of the record under review"
    PRD §2.1: "Its failure is `ERR_SEGREGATION_OF_DUTIES` with HTTP 403."
    PRD §2.1: "The rule is what prevents a coordinator who filed a syllabus from also approving it"

    Design: Corner/rbac/course_audit_reviewer_acting_as_own_submitter_is_segregation_violation
    """
    from test_helpers import make_course_audit_reviewer_headers

    school = create_school()
    audit = create_audit(school, submitted_by_user_id=COURSE_AUDIT_REVIEWER)

    response = api_client.transition_course_audit(
        audit["id"],
        {"to_status": "IN_REVIEW", "expected_course_audit_version": audit["version"]},
        make_course_audit_reviewer_headers(COURSE_AUDIT_REVIEWER),
    )
    validate_error(response, ApiErrorId.ERR_SEGREGATION_OF_DUTIES)

    data, _meta = validate_paginated(
        api_client.list_course_audits(ADMIN, params={"school_id": school["id"]})
    )
    assert data[0]["status"] == "SUBMITTED"
    assert data[0]["review_round"] == 0


def test_accommodation_reviewer_acting_as_the_filing_user_is_a_segregation_violation():
    """PRD §2.1: "This rule applies to exactly three endpoints — the course-audit status transitions, the accommodation-request status transitions, and the irregularity-case status transitions"
    PRD §3.4: "An `AccommodationReviewer` takes the request into `UNDER_DOC_REVIEW` only when the acting reviewer is not the filing user and the recorded completeness is at least 1"

    Design: Corner/rbac/accommodation_reviewer_acting_as_submitter_is_segregation_violation
    """
    from test_helpers import make_accommodation_reviewer_headers

    school = create_school()
    student = create_student(school)
    request = create_accommodation(
        student,
        school,
        exam_subject="AP-PHYSC-1",
        accommodation_type="EXTENDED_TIME",
        documentation_completeness=3,
        submitted_by_user_id=ACCOMMODATION_REVIEWER,
    )

    response = api_client.transition_accommodation_request(
        request["id"],
        {"to_status": "UNDER_DOC_REVIEW"},
        make_accommodation_reviewer_headers(ACCOMMODATION_REVIEWER),
    )
    validate_error(response, ApiErrorId.ERR_SEGREGATION_OF_DUTIES)

    after = get_accommodation(request["id"])
    assert after["status"] == "SUBMITTED"
    assert after["review_round"] == 0
