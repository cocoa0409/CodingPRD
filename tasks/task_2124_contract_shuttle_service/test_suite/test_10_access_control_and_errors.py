"""Authentication, role authorisation, pagination bounds and the 404 catalogue."""

from test_helpers import (
    ApiErrorId,
    NO_AUTH_HEADERS,
    TEST_USERS,
    create_active_contract,
    create_report,
    make_headers,
    make_ops_planner_headers,
    set_clock,
    submit_report,
    validate_error,
    validate_success,
)

ADMIN = TEST_USERS["contract_admin_headers"]
FLEET = TEST_USERS["fleet_manager_headers"]
LIAISON = TEST_USERS["client_liaison_headers"]
PLANNER = TEST_USERS["ops_planner_headers"]


def test_ops_planner_cannot_approve_a_report(api):
    """PRD §2.1: "Each endpoint declares which of them may invoke it — the
    authoritative list is the fourth column of the table in §4 — and a caller whose
    role is not on an endpoint's list is rejected with `ERR_FORBIDDEN_ROLE` and HTTP
    403."
    PRD §2.10: "A `ContractAdmin` may open and submit a reporting period, and a
    `ContractAdmin` is the only role that may approve one — but a `ContractAdmin`
    who submitted a particular report may not approve that same report."

    Design: Corner/rbac/ops_planner_cannot_approve_a_report
    """
    set_clock("2026-09-01T06:00:00Z")
    contract = create_active_contract(client_name="RBAC Hotel")
    report = create_report(
        contract["id"], period_start_date="2026-09-01", period_end_date="2026-09-30"
    )
    submit_report(report["id"], "liaison-r")

    response = api.approve_report(report["id"], make_ops_planner_headers("planner-r"))
    validate_error(response, ApiErrorId.ERR_FORBIDDEN_ROLE.value, 403)

    reread = validate_success(api.get_report(report["id"], ADMIN))
    assert reread["status"] == "SUBMITTED"
    assert reread.get("approved_by_user_id") is None


def test_request_without_auth_headers_is_unauthenticated(api):
    """PRD §2.1: "Every request to the API must be authenticated by two mandatory
    HTTP headers. `X-User-ID` identifies the acting principal, and `X-User-Role`
    declares the capacity in which that principal is acting. If either header is
    absent or is present but empty, the request is rejected with
    `ERR_UNAUTHENTICATED` and HTTP 401."

    Design: Corner/rbac/request_without_auth_headers_returns_unauthenticated
    """
    set_clock("2026-09-01T06:00:00Z")

    response = api.list_contracts(NO_AUTH_HEADERS)
    validate_error(response, ApiErrorId.ERR_UNAUTHENTICATED.value, 401)

    body = response.json()
    assert body["response_type"] == "error"


def test_unrecognised_role_header_is_unauthenticated(api):
    """PRD §2.1: "The same `ERR_UNAUTHENTICATED` rejection with HTTP 401 applies
    when `X-User-Role` carries a value that is not one of the five roles the system
    recognises."
    PRD §2.6: "2. **Role recognition.** `X-User-Role` must name one of the five
    declared roles, on every endpoint. Failure yields `ERR_UNAUTHENTICATED` (401)."

    Design: Corner/rbac/unknown_role_header_returns_unauthenticated
    """
    set_clock("2026-09-01T06:00:00Z")

    response = api.list_contracts(make_headers("auditor-1", "Auditor"))
    validate_error(response, ApiErrorId.ERR_UNAUTHENTICATED.value, 401)

    assert response.status_code != 403, "role recognition precedes role authorisation"
    assert response.json()["data"]["error_id"] != ApiErrorId.ERR_FORBIDDEN_ROLE.value


def test_pagination_limit_above_the_maximum_is_rejected(api):
    """PRD §2.3: "`limit` sets the maximum number of rows returned; it defaults to
    10 when omitted, may not be smaller than 1, and may not be larger than 100."
    PRD §2.3: "A `limit` that is not an integer or falls outside 1 through 100, or
    an `offset` that is not an integer or is below 0, is rejected with
    `ERR_INVALID_PAGINATION` and HTTP 400."

    Design: Corner/validations/pagination_limit_above_the_maximum_is_rejected
    """
    set_clock("2026-09-01T06:00:00Z")

    response = api.list_trips(PLANNER, params={"limit": 101, "offset": 0})
    validate_error(response, ApiErrorId.ERR_INVALID_PAGINATION.value, 400)

    assert response.json()["response_type"] == "error"


def test_each_collection_raises_its_own_not_found_error(api):
    """PRD §2.6: "On every endpoint that takes an identifier in its URL, each
    identifier is resolved left to right, and the first one that names no existing
    row rejects the request with HTTP 404 carrying the error for that resource kind:
    `ERR_CONTRACT_NOT_FOUND`, `ERR_ROUTE_NOT_FOUND`, `ERR_VEHICLE_NOT_FOUND`,
    `ERR_TRIP_NOT_FOUND`, `ERR_REQUEST_NOT_FOUND`, `ERR_MAINTENANCE_ORDER_NOT_FOUND`,
    `ERR_REPORT_NOT_FOUND`, `ERR_MEMO_NOT_FOUND`, or `ERR_OFFER_NOT_FOUND`."

    Design: Corner/errors/unknown_path_ids_return_their_own_not_found_error
    """
    set_clock("2026-09-01T06:00:00Z")

    validate_error(
        api.get_route("11111111-1111-4111-8111-111111111111", PLANNER),
        ApiErrorId.ERR_ROUTE_NOT_FOUND.value, 404,
    )
    validate_error(
        api.get_trip("22222222-2222-4222-8222-222222222222", PLANNER),
        ApiErrorId.ERR_TRIP_NOT_FOUND.value, 404,
    )
    validate_error(
        api.get_vehicle("33333333-3333-4333-8333-333333333333", FLEET),
        ApiErrorId.ERR_VEHICLE_NOT_FOUND.value, 404,
    )
    validate_error(
        api.get_driver("44444444-4444-4444-8444-444444444444", PLANNER),
        ApiErrorId.ERR_DRIVER_NOT_FOUND.value, 404,
    )
    validate_error(
        api.get_on_demand_request("55555555-5555-4555-8555-555555555555", LIAISON),
        ApiErrorId.ERR_REQUEST_NOT_FOUND.value, 404,
    )
    validate_error(
        api.get_report("66666666-6666-4666-8666-666666666666", ADMIN),
        ApiErrorId.ERR_REPORT_NOT_FOUND.value, 404,
    )
    validate_error(
        api.get_credit_memo("77777777-7777-4777-8777-777777777777", ADMIN),
        ApiErrorId.ERR_MEMO_NOT_FOUND.value, 404,
    )
    validate_error(
        api.get_renewal_offer("88888888-8888-4888-8888-888888888888", ADMIN),
        ApiErrorId.ERR_OFFER_NOT_FOUND.value, 404,
    )
    validate_error(
        api.close_maintenance_order(
            "99999999-9999-4999-8999-999999999999", {"outcome": "RETURN_TO_SERVICE"}, FLEET
        ),
        ApiErrorId.ERR_MAINTENANCE_ORDER_NOT_FOUND.value, 404,
    )
