"""Response-envelope shape and authentication/authorization entry gates."""
from test_helpers import (
    NON_EXISTENT_UUID,
    ApiErrorId,
    create_fleet_customer,
    create_supplier_payload,
    is_iso8601_timestamp,
    is_valid_uuid,
    make_fleet_manager_headers,
    set_logical_clock,
    validate_error,
    validate_success,
)


def test_success_envelope_shape_on_create(api, production_planner_headers):
    """PRD section 2.2: "All successful API responses (those with 2xx status
    codes) follow this standard envelope format in their JSON body" and
    "The `api_request_id` is a server-generated unique identifier for the
    request that starts with `req_`."; also "Pagination-related fields in
    `meta` (`limit`, `offset`, `total_count`, `has_more`) are included for
    list endpoints."

    Design: Corner/endpoints/success_envelope_shape_on_create
    """
    set_logical_clock()
    resp = api.create_supplier(
        create_supplier_payload(name="Envelope Cells", contact_email="e@cells.test"),
        production_planner_headers,
    )
    data = validate_success(resp, 201)
    body = resp.json()
    assert body["response_type"] == "object", "single-resource create must be an object response"
    meta = body["meta"]
    assert isinstance(meta.get("api_request_id"), str) and meta["api_request_id"].startswith("req_"), (
        "api_request_id must start with req_"
    )
    assert is_iso8601_timestamp(meta.get("api_request_timestamp", "")), (
        "api_request_timestamp must be ISO 8601"
    )
    assert is_valid_uuid(data.get("id", "")), "data.id must be a server-minted UUID"
    for field in ("limit", "offset", "total_count", "has_more"):
        assert field not in meta, f"pagination field {field} must not appear on an object response"


def test_error_envelope_shape_on_failure(api, production_planner_headers):
    """PRD section 2.2: "All error API responses (4xx status codes) follow
    this standard envelope format" and "The `meta` object for error responses
    contains only `api_request_id` and `api_request_timestamp`."

    Design: Corner/endpoints/error_envelope_shape_on_failure
    """
    set_logical_clock()
    resp = api.get_supplier(NON_EXISTENT_UUID, production_planner_headers)
    error_data = validate_error(resp, ApiErrorId.ERR_NOT_FOUND)
    assert isinstance(error_data.get("message"), str) and error_data["message"].strip(), (
        "error data.message must be a non-empty human-readable explanation"
    )
    body = resp.json()
    assert body["response_type"] == "error"
    meta = body["meta"]
    assert set(meta.keys()) == {"api_request_id", "api_request_timestamp"}, (
        "error meta must contain only api_request_id and api_request_timestamp"
    )
    assert isinstance(meta["api_request_id"], str) and meta["api_request_id"]
    assert is_iso8601_timestamp(meta["api_request_timestamp"])


def test_missing_auth_headers_returns_unauthenticated(api):
    """PRD section 2.1: "A request missing either header, or presenting an
    `X-User-Role` value that is not one of the declared roles, is rejected
    with `ERR_UNAUTHENTICATED` (HTTP 401)."

    Design: Corner/validations/missing_auth_headers_returns_unauthenticated
    """
    set_logical_clock()
    customer = create_fleet_customer()
    resp = api.get_fleet_customer(customer["id"], headers=None)
    validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED)


def test_fleet_manager_cannot_register_supplier_forbidden(api):
    """PRD section 2.1: "A request whose role is not listed for the endpoint
    is rejected with `ERR_FORBIDDEN` (HTTP 403)"; PRD section 4 lists POST
    /evfleet/suppliers under "Register a battery/component supplier" with
    authorized role ProductionPlanner only.

    Design: Corner/validations/fleet_manager_cannot_register_supplier_forbidden
    """
    set_logical_clock()
    customer = create_fleet_customer()
    resp = api.create_supplier(
        create_supplier_payload(name="Sneaky Cells", contact_email="x@sneaky.test"),
        make_fleet_manager_headers(customer["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN)
