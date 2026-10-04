"""Platform envelope shape, context-header gating, typed not-found errors,
role authorization, and customer scoping."""
from test_helpers import (
    ApiErrorId,
    assignment_payload,
    create_customer,
    create_mission,
    create_port,
    create_signed_contract,
    file_customer_license,
    get_contract,
    mission_version,
    payload_entry,
    set_clock,
    validate_error,
    validate_paginated,
    validate_success,
    api_client,
)
from test_helpers.test_users import TEST_USERS, make_customer_headers

ADMIN = TEST_USERS["admin_headers"]
MOPS = TEST_USERS["mission_ops_headers"]
CM = TEST_USERS["contract_manager_headers"]
REG = TEST_USERS["regulator_headers"]
RO = TEST_USERS["range_officer_headers"]


def test_unknown_ids_return_typed_not_found(api):
    """PRD §2.6: "Referenced resources must exist, validated left-to-right along
    the URL path and then across body fields in their declared input order,
    surfacing the appropriate one of `ERR_CUSTOMER_NOT_FOUND`,
    `ERR_MISSION_NOT_FOUND`, `ERR_CONTRACT_NOT_FOUND`, `ERR_PAYLOAD_NOT_FOUND`,
    `ERR_DISPENSER_PORT_NOT_FOUND`, `ERR_ASSIGNMENT_NOT_FOUND`,
    `ERR_RANGE_SLOT_NOT_FOUND`, `ERR_LICENSE_NOT_FOUND`,
    `ERR_SEPARATION_EVENT_NOT_FOUND`, or `ERR_ANOMALY_NOT_FOUND` (all 404)."

    Design: Corner/entities/unknown_ids_return_typed_not_found
    """
    set_clock()
    create_customer()
    validate_error(
        api_client.get_mission("00000000-0000-4000-8000-000000000001", MOPS),
        ApiErrorId.ERR_MISSION_NOT_FOUND,
    )
    validate_error(
        api_client.get_contract("00000000-0000-4000-8000-000000000002", CM),
        ApiErrorId.ERR_CONTRACT_NOT_FOUND,
    )
    validate_error(
        api_client.get_assignment("00000000-0000-4000-8000-000000000003", MOPS),
        ApiErrorId.ERR_ASSIGNMENT_NOT_FOUND,
    )
    validate_error(
        api_client.get_license("00000000-0000-4000-8000-000000000004", REG),
        ApiErrorId.ERR_LICENSE_NOT_FOUND,
    )
    validate_error(
        api_client.reserve_range_slot("00000000-0000-4000-8000-000000000005", RO),
        ApiErrorId.ERR_RANGE_SLOT_NOT_FOUND,
    )
    validate_error(
        api_client.report_separation_outcome(
            "00000000-0000-4000-8000-000000000006", {"outcome": "EXECUTED"}, MOPS
        ),
        ApiErrorId.ERR_SEPARATION_EVENT_NOT_FOUND,
    )
    validate_error(
        api_client.transition_anomaly(
            "00000000-0000-4000-8000-000000000007", {"to_state": "UNDER_INVESTIGATION"}, MOPS
        ),
        ApiErrorId.ERR_ANOMALY_NOT_FOUND,
    )


def test_error_response_carries_envelope_error_shape(api):
    """PRD §2.2: "All error API responses (4xx status codes) follow this
    standard envelope format" with `response_type` "error" and `data` carrying
    `error_id` and `message`.
    PRD §2.2: "The `meta` object for error responses contains only
    `api_request_id` and `api_request_timestamp`."
    PRD §2.2: "The `error_id` is a unique, machine-readable string that
    identifies the specific error."

    Design: Corner/endpoints/error_response_carries_envelope_error_shape
    """
    set_clock()
    resp = api_client.get_mission("00000000-0000-4000-8000-000000000020", MOPS)
    assert resp.status_code == 404
    body = resp.json()
    assert body["response_type"] == "error"
    assert isinstance(body["meta"]["api_request_id"], str)
    assert isinstance(body["meta"]["api_request_timestamp"], str)
    data = body["data"]
    assert data["error_id"] == "ERR_MISSION_NOT_FOUND"
    assert isinstance(data["message"], str) and data["message"].strip()
    assert "id" not in data, "no entity fields leak into an error envelope"


def test_request_missing_x_user_headers_returns_400(api):
    """PRD §2.1: "Every request must carry two HTTP headers: `X-User-ID`,
    identifying the acting user, and `X-User-Role`, naming their operational
    capacity. A request in which either header is missing or empty is rejected
    with `ERR_MISSING_OR_INVALID_CONTEXT_HEADER` (HTTP 400)."
    PRD §2.6: "Context headers. `X-User-ID` and `X-User-Role` must be present
    and non-empty, else `ERR_MISSING_OR_INVALID_CONTEXT_HEADER` (400)." — stage
    1, before resource existence at stage 5.

    Design: Corner/errors/request_missing_x_user_headers_returns_400
    """
    set_clock()
    no_headers = api_client.get_mission(
        "00000000-0000-4000-8000-000000000020", None
    )
    validate_error(no_headers, ApiErrorId.ERR_MISSING_OR_INVALID_CONTEXT_HEADER)

    with_headers = api_client.get_mission(
        "00000000-0000-4000-8000-000000000020", MOPS
    )
    validate_error(with_headers, ApiErrorId.ERR_MISSION_NOT_FOUND)


def test_cross_role_exclusive_operations_denied(api):
    """PRD §2.1: "Each endpoint authorizes a fixed subset of these roles, and a
    caller whose role is not in the endpoint's list is rejected with
    `ERR_FORBIDDEN` (HTTP 403)."
    PRD §4: the endpoint table authorizes `POST /rideshare/missions` to
    MissionOps, `POST /rideshare/assignments/{id}/safety-reviews` to
    SafetyOfficer, `POST /rideshare/assignments/{id}/verifications` to
    IntegrationEngineer, `POST /rideshare/licenses/{id}/transition` to
    Regulator, and `POST /rideshare/range-slots` to RangeOfficer.

    Design: Corner/rbac/cross_role_exclusive_operations_denied
    """
    set_clock()
    customer = create_customer()
    mission = create_mission()
    port = create_port(mission["id"])
    contract, payloads = create_signed_contract(customer["id"], [payload_entry()])
    lic = file_customer_license(customer["id"])  # SUBMITTED, never decided
    a1 = validate_success(
        api_client.create_assignment(
            assignment_payload(mission["id"], payloads[0]["id"], port["id"],
                               mission_version(mission["id"])),
            MOPS,
        ),
        201,
    )

    r1 = api_client.create_mission(
        {
            "mission_name": "Transporter-Q", "target_orbit": "LEO",
            "window_open_utc": "2026-11-01T00:00:00Z",
            "window_close_utc": "2026-11-10T00:00:00Z",
            "mass_capacity_kg": 100, "volume_capacity_m3": 2.0,
        },
        make_customer_headers(customer["id"]),
    )
    validate_error(r1, ApiErrorId.ERR_FORBIDDEN)

    r2 = api_client.create_safety_review(
        a1["id"], {"decision": "APPROVE"},
        {**TEST_USERS["engineer_headers"]},
    )
    validate_error(r2, ApiErrorId.ERR_FORBIDDEN)

    r3 = api_client.create_verification(
        a1["id"], {"check_type": "ELECTRICAL", "outcome": "PASSED"},
        {**TEST_USERS["safety_headers"]},
    )
    validate_error(r3, ApiErrorId.ERR_FORBIDDEN)

    r4 = api_client.transition_license(lic["id"], "GRANTED", RO)
    validate_error(r4, ApiErrorId.ERR_FORBIDDEN)

    r5 = api_client.create_range_slot(
        {
            "mission_id": mission["id"], "range_code": "VAFB",
            "window_open_utc": "2026-10-10T00:00:00Z",
            "window_close_utc": "2026-10-20T00:00:00Z",
        },
        MOPS,
    )
    validate_error(r5, ApiErrorId.ERR_FORBIDDEN)

    assert get_contract(contract["id"])["status"] == "MANIFESTED"
    license_after = validate_success(api_client.get_license(lic["id"], REG), 200)
    assert license_after["status"] == "SUBMITTED", "the denied transition leaves state unchanged"
    reviews = validate_success(
        api_client.list_safety_reviews(a1["id"], TEST_USERS["safety_headers"]), 200
    )
    verifications = validate_success(
        api_client.list_verifications(a1["id"], TEST_USERS["safety_headers"]), 200
    )
    assert reviews == [] and verifications == [], "no side effects from forbidden calls"


def test_customer_scope_hides_other_customers_contract(api):
    """PRD §2.1: "Customer scoping is enforced as invisibility, not as a
    permission error. A `Customer`-role caller may touch only contracts,
    licenses, payloads, and delay events belonging to the customer whose `id`
    equals `X-User-ID`; attempts to reach another customer's resource surface
    as `ERR_CONTRACT_NOT_FOUND` (HTTP 404), indistinguishable from a
    nonexistent resource. List endpoints visible to the `Customer` role
    auto-filter to the caller's own `customer_id`."
    PRD §3.2: "The caller must present `X-User-Role` of `Customer` with
    `X-User-ID` equal to the contract's `customer_id`; any other caller
    receives `ERR_CONTRACT_NOT_FOUND` (HTTP 404), as if the contract did not
    exist."

    Design: Corner/rbac/customer_scope_hides_other_customers_contract
    """
    set_clock()
    customer_a = create_customer()
    customer_b = create_customer(
        org_name="Beta Orbits", contact_email="ops@beta-orbits.example",
        default_rebookings=2,
    )
    contract, _ = create_signed_contract(customer_a["id"], [payload_entry()])

    read_b = api_client.get_contract(contract["id"], make_customer_headers(customer_b["id"]))
    validate_error(read_b, ApiErrorId.ERR_CONTRACT_NOT_FOUND)

    sign_b = api_client.sign_contract(contract["id"], make_customer_headers(customer_b["id"]))
    validate_error(sign_b, ApiErrorId.ERR_CONTRACT_NOT_FOUND)

    rows_b, meta_b = validate_paginated(
        api_client.list_contracts(make_customer_headers(customer_b["id"]))
    )
    assert rows_b == [] and meta_b["total_count"] == 0

    as_manager = validate_success(api_client.get_contract(contract["id"], CM), 200)
    assert as_manager["status"] == "SIGNED"
