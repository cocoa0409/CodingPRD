"""Program registration, customer registration, auth headers, error envelope."""
from test_helpers import (
    ApiErrorId, NON_EXISTENT_UUID, assert_customer, assert_program,
    create_customer_payload, create_program_payload, make_customer_headers,
    validate_error, validate_success,
)


def test_program_creation_returns_all_fields(api, program_admin_headers):
    """PRD §3.1: "A `ProgramAdmin` opens a program by supplying a unique
    `program_code` ... together with a display `name` and the full cost-recovery
    configuration".
    PRD §2.5: "`version` is an integer that starts at its initial value on
    creation and increments by one on every mutation of the resource".

    Design: Corner/entities/program_creation_returns_all_fields
    """
    resp = api.create_program(create_program_payload(program_code="NIST-RM-C01"),
                              program_admin_headers)
    data = validate_success(resp, 201)
    assert_program(data)
    assert data["program_code"] == "NIST-RM-C01"
    assert data["version"] == 1
    assert data["material_unit_price_cents"] == 1000


def test_customer_defaults_good_standing(api, program_admin_headers):
    """PRD §3.7: "the account begins with `pt_fail_count` at zero,
    `accreditation_standing` at `GOOD_STANDING`, and `credit_hold` false."

    Design: Corner/entities/customer_defaults_good_standing
    """
    resp = api.create_customer(create_customer_payload(name="Fresh Lab"),
                               program_admin_headers)
    data = validate_success(resp, 201)
    assert_customer(data)
    assert data["pt_fail_count"] == 0
    assert data["accreditation_standing"] == "GOOD_STANDING"
    assert data["credit_hold"] is False


def test_duplicate_program_code_rejected(api, program_admin_headers):
    """PRD §3.1: "A `ProgramAdmin` opens a program by supplying a unique
    `program_code` — a duplicate is refused with `ERR_DUPLICATE_PROGRAM_CODE`".

    Design: Corner/errors/duplicate_program_code_rejected
    """
    payload = create_program_payload(program_code="NIST-RM-C39")
    validate_success(api.create_program(payload, program_admin_headers), 201)
    resp = api.create_program(
        create_program_payload(program_code="NIST-RM-C39", name="P2",
                               material_unit_price_cents=2000),
        program_admin_headers,
    )
    validate_error(resp, ApiErrorId.ERR_DUPLICATE_PROGRAM_CODE)


def test_customer_cannot_create_program(api, program_admin_headers):
    """PRD §2.1: "a request whose role is not among them — or whose role is not
    permitted for the specific transition target named in a transition request —
    is rejected with `ERR_UNAUTHORIZED_ROLE` (HTTP 403)."

    Design: Corner/rbac/customer_cannot_create_program
    """
    customer = validate_success(
        api.create_customer(create_customer_payload(name="C41"), program_admin_headers), 201
    )
    resp = api.create_program(create_program_payload(program_code="NIST-RM-C41"),
                              make_customer_headers(customer["id"]))
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED_ROLE)


def test_missing_auth_headers_rejected(api):
    """PRD §2.1: "A request in which either header is missing or empty is
    rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT` (HTTP 400)."

    Design: Corner/validations/missing_auth_headers_rejected
    """
    resp = api.create_program(create_program_payload(program_code="NIST-RM-C28"), {})
    validate_error(resp, ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT)


def test_error_envelope_shape(api, program_admin_headers):
    """PRD §2.2: "The `error_id` is a unique, machine-readable string that
    identifies the specific error."
    PRD §2.2: "The `meta` object for error responses contains only
    `api_request_id` and `api_request_timestamp`."

    Design: Corner/endpoints/error_envelope_shape
    """
    resp = api.get_material_lot(NON_EXISTENT_UUID, program_admin_headers)
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND)
    body = resp.json()
    assert body["response_type"] == "error"
    assert isinstance(body["data"]["message"], str) and body["data"]["message"]
    assert body["meta"]["api_request_id"]
