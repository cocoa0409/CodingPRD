"""Required fields, payload foreign keys and unique codes."""
from test_helpers import (
    ADMIN,
    ApiErrorId,
    api_client,
    create_school,
    get_school,
    host_headers,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_student_without_a_grade_level_is_refused_as_a_request_shape_failure():
    """PRD §2.6: "| 29 | Required fields are present and enum-valued fields carry a declared member | `ERR_INVALID_REQUEST` | 400 |"
    PRD §3.3: "A `SchoolCoordinator` enrolls one with a `full_name`, the owning `school_id`, a `student_code` unique within that school and a `grade_level`"

    Design: Corner/entities/student_missing_grade_level_returns_invalid_request
    """
    school = create_school()

    response = api_client.create_student(
        {"full_name": "Quinn Barrow", "school_id": school["id"], "student_code": "S0001"},
        host_headers(school),
    )
    validate_error(response, ApiErrorId.ERR_INVALID_REQUEST)

    _data, meta = validate_paginated(
        api_client.list_students(ADMIN, params={"school_id": school["id"]})
    )
    assert meta["total_count"] == 0


def test_student_with_an_unresolvable_school_foreign_key_is_refused():
    """PRD §2.6: "| 6 | Every foreign key carried in the payload resolves to an existing row | `ERR_FK_NOT_FOUND` | 404 |"
    PRD §2.6: "| 5 | The path resource exists | `ERR_RESOURCE_NOT_FOUND` | 404 |"

    Design: Corner/entities/student_with_unknown_school_id_returns_fk_not_found
    """
    school = create_school()

    response = api_client.create_student(
        {
            "full_name": "Rhea Lindqvist",
            "school_id": "school-that-does-not-exist",
            "student_code": "S0001",
            "grade_level": 12,
        },
        host_headers(school),
    )
    error = validate_error(response, ApiErrorId.ERR_FK_NOT_FOUND)
    assert error["error_id"] != ApiErrorId.ERR_RESOURCE_NOT_FOUND, (
        "no path resource was addressed, so the failure is the payload foreign key"
    )
    assert response.status_code == 404

    _data, meta = validate_paginated(
        api_client.list_students(ADMIN, params={"school_id": school["id"]})
    )
    assert meta["total_count"] == 0


def test_reusing_a_school_code_is_refused_as_a_duplicate():
    """PRD §2.10: "`school_code` is a six-character code and `center_code` is a four-digit code; each is unique across schools"
    PRD §2.6: "| 28 | `school_code`, `center_code`, `student_code` within a school and `carrier_tracking_id` are unique | `ERR_DUPLICATE_RESOURCE` | 409 |"

    Design: Corner/entities/duplicate_school_code_returns_duplicate_resource
    """
    original = create_school(school_code="CN0024", center_code="7024", name="Corner Twentyfour High")

    response = api_client.create_school(
        {
            "name": "Corner Twentyfour Annex",
            "school_code": "CN0024",
            "country_code": "US",
            "center_code": "7025",
            "seat_capacity": 20,
        },
        ADMIN,
    )
    validate_error(response, ApiErrorId.ERR_DUPLICATE_RESOURCE)

    stored = get_school(original["id"])
    assert stored["name"] == "Corner Twentyfour High"
    assert stored["center_code"] == "7024"
