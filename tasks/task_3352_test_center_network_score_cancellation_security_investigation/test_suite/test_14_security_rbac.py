"""Authentication, role authorization, ownership, and request-shape checks."""
from test_helpers import (
    ApiErrorId,
    create_examinee,
    create_test_center_payload,
    validate_error,
    validate_success,
)
from test_helpers import (
    create_accommodation_request_payload,
    decide_accommodation_payload,
    make_examinee_headers,
    make_proctor_headers,
)


def test_missing_auth_headers_unauthenticated(api):
    """PRD §2.1: "If either header is missing or malformed, or the role name
    is not one of the declared roles, the request is rejected with
    `ERR_UNAUTHENTICATED`."
    PRD §2.6: "The `X-User-Role` and `X-User-ID` headers are present and
    well-formed, and the role names one of the six declared roles. Failure:
    `ERR_UNAUTHENTICATED` (HTTP 401)."

    Design: Corner/validations/missing_auth_headers_unauthenticated
    """
    resp = api.create_test_center(
        create_test_center_payload(name="NoAuth", facility_seat_capacity=10,
                                   equipment_list=[]),
        headers={},
    )
    validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED)


def test_proctor_cannot_create_test_center(api):
    """PRD §2.1: "If the role is declared but not permitted on the target
    endpoint, the request is rejected with `ERR_UNAUTHORIZED`."

    Design: Corner/rbac/proctor_cannot_create_test_center
    """
    resp = api.create_test_center(
        create_test_center_payload(name="Nope", facility_seat_capacity=10,
                                   equipment_list=[]),
        make_proctor_headers("some-staff-id"),
    )
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED)


def test_examinee_cannot_decide_accommodation(api):
    """PRD §2.1: "If the role is declared but not permitted on the target
    endpoint, the request is rejected with `ERR_UNAUTHORIZED`."
    PRD §3.3: "A `ProgramAdmin` then decides it by supplying a `decision` of
    `APPROVED` or `DENIED`, which stamps `decided_by` with the decider's
    identifier and moves the request to the chosen terminal state."
    PRD §3.3: "Two types — `SCREEN_READER` and `LARGE_PRINT` — call for
    alternate-format test delivery, so the system derives
    `requires_alternate_format` as true for exactly those two types and false
    for the others."

    Design: Corner/rbac/examinee_cannot_decide_accommodation
    """
    examinee = create_examinee(full_name="Ex RB", id_document_number="PRB9")
    request = validate_success(
        api.create_accommodation_request(
            examinee["id"],
            create_accommodation_request_payload("EXTENDED_TIME"),
            make_examinee_headers(examinee["id"]),
        ),
        201,
    )
    resp = api.decide_accommodation_request(
        request["id"],
        decide_accommodation_payload("APPROVED"),
        make_examinee_headers(examinee["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED)
    requests = validate_success(
        api.list_accommodation_requests(
            examinee["id"], make_examinee_headers(examinee["id"])
        ),
        200,
    )
    assert requests[0]["status"] == "SUBMITTED"
    assert requests[0]["requires_alternate_format"] is False, "EXTENDED_TIME"


def test_examinee_create_missing_required_field(api, program_admin_headers):
    """PRD §2.6: "Required fields are present and enum values and formats are
    valid: `institution_code` must be a string of 4 to 8 characters, each an
    uppercase letter A–Z or a digit 0–9; `section_raws` must be exactly 3
    integers, each between 0 and 50 inclusive; `end_time` must be later than
    `start_time`; `reserved_accommodation_seats` must not exceed
    `total_seats`. Failure: `ERR_INVALID_REQUEST` (HTTP 400)."
    PRD §3.3: "a `ProgramAdmin` creates the examinee's record: the `full_name`
    exactly as it appears on the identity document, the `date_of_birth` in
    `YYYY-MM-DD` form, the `id_document_type` — one of `PASSPORT`,
    `NATIONAL_ID`, or `DRIVERS_LICENSE`"

    Design: Corner/entities/examinee_create_missing_required_field
    """
    resp = api.create_examinee(
        {
            "full_name": "No Doc",
            "date_of_birth": "2000-01-01",
            "id_document_number": "PX",
            "id_document_expiry": "2027-01-01",
        },
        program_admin_headers,
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)
