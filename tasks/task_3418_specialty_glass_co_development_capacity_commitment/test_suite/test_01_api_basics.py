"""Response envelope, pagination, authentication, authorization, and 404 rules.

Covers the fixed wire envelope (PRD section 2.2), list pagination (section
2.3), the authentication and role gates (sections 2.1 and 2.8), and the
not-found rule for unresolvable identifiers (section 2.5).
"""

from test_helpers import (
    NON_EXISTENT_UUID,
    TEST_USERS,
    ApiErrorId,
    api_client,
    create_commitment,
    create_device_maker,
    create_license,
    create_program_with_nda,
    factories,
    is_valid_uuid,
    make_device_maker_headers,
    sign_commitment,
    validate_created,
    validate_error,
    validate_paginated,
    get_success_data,
)

ADMIN = TEST_USERS["platform_admin_headers"]
MANAGER = TEST_USERS["program_manager_headers"]
PLANNER = TEST_USERS["capacity_planner_headers"]
FINANCE = TEST_USERS["finance_controller_headers"]
LEGAL = TEST_USERS["legal_counsel_headers"]


def test_success_envelope_contains_meta_and_data():
    """PRD section 2.2: "All successful API responses (those with 2xx status
    codes) follow this standard envelope format in their JSON body" — carrying
    meta.api_request_id, meta.api_request_timestamp, response_type and data.

    Design: Corner/endpoints/success_envelope_contains_meta_and_data
    """
    resp = api_client.create_device_maker(
        factories.create_device_maker_payload(), ADMIN
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["response_type"] == "object"
    assert body["meta"]["api_request_id"]
    assert body["meta"]["api_request_timestamp"]
    data = validate_created(resp)
    assert is_valid_uuid(data["id"])


def test_error_envelope_contains_error_id_and_message():
    """PRD section 2.2: "All error API responses (4xx status codes) follow
    this standard envelope format" — response_type "error" with data.error_id
    and a human-readable data.message.

    Design: Corner/endpoints/error_envelope_contains_error_id_and_message
    """
    resp = api_client.get_program(NON_EXISTENT_UUID, MANAGER)
    assert resp.status_code == 404
    body = resp.json()
    assert body["response_type"] == "error"
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND)
    assert body["data"]["message"]


def test_list_device_makers_pagination_envelope():
    """PRD section 2.3: "List endpoints accept two query parameters: `limit`,
    defaulting to 10 with a minimum of 1 and a maximum of 100, and `offset`,
    defaulting to 0. The `meta` object of a list response carries `limit`,
    `offset`, `total_count`, and `has_more`."

    Design: Corner/entities/list_device_makers_pagination_envelope
    """
    create_device_maker(name="M1", region="US")
    create_device_maker(name="M2", region="EU")
    create_device_maker(name="M3", region="APAC")
    data, meta = validate_paginated(api_client.list_device_makers(MANAGER))
    assert len(data) == 3
    assert meta["total_count"] == 3
    assert meta["has_more"] is False
    assert meta["limit"] == 10
    assert meta["offset"] == 0


def test_missing_auth_headers_returns_unauthenticated():
    """PRD section 2.1: "A request that is missing either header, or whose
    `X-User-Role` value is not one of the declared roles, is rejected with
    `ERR_UNAUTHENTICATED` (HTTP 401)."

    Design: Corner/validations/missing_auth_headers_returns_unauthenticated
    """
    resp = api_client.create_device_maker(
        factories.create_device_maker_payload(), headers=None
    )
    validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED)


def test_device_maker_cannot_create_tank_returns_forbidden():
    """PRD section 2.1: "A request whose role is authenticated but not listed
    among the roles authorized for the target endpoint is rejected with
    `ERR_FORBIDDEN_ROLE` (HTTP 403)." PRD section 2.8: "the failure reported is
    the one with the highest priority: checks are evaluated in the fixed order
    below and the first failure wins" — authorization (2) precedes existence
    (4), so the bogus commitment id never reaches the 404 check.

    Design: Corner/validations/device_maker_cannot_create_tank_returns_forbidden
    """
    maker = create_device_maker()
    resp = api_client.create_tank(
        factories.create_tank_payload(NON_EXISTENT_UUID, capacity_units_per_day=100),
        make_device_maker_headers(maker["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE)


def test_legal_counsel_cannot_countersign_commitment():
    """PRD section 2.1: "A request whose role is authenticated but not listed
    among the roles authorized for the target endpoint is rejected with
    `ERR_FORBIDDEN_ROLE` (HTTP 403)." Countersignature is listed for
    CapacityPlanner only (PRD section 4).

    Design: Corner/rbac/legal_counsel_cannot_countersign_commitment
    """
    chain = create_program_with_nda()
    commitment = create_commitment(chain.program)
    commitment = sign_commitment(commitment, chain.maker)
    resp = api_client.countersign_commitment(commitment["id"], headers=LEGAL)
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE)
    commitment = get_success_data(api_client.get_commitment(commitment["id"], MANAGER))
    assert commitment["status"] == "SIGNED"


def test_finance_cannot_activate_license():
    """PRD section 2.1: "A request whose role is authenticated but not listed
    among the roles authorized for the target endpoint is rejected with
    `ERR_FORBIDDEN_ROLE` (HTTP 403)." License activation is listed for
    LegalCounsel only (PRD section 4), and the role gate fires before any
    program-state business rule.

    Design: Corner/rbac/finance_cannot_activate_license
    """
    chain = create_program_with_nda(maker_name="Beta Devices", maker_region="EU")
    license_ = create_license(chain.maker, chain.program)
    resp = api_client.activate_license(license_["id"], headers=FINANCE)
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE)


def test_get_unknown_program_returns_not_found():
    """PRD section 2.5: "Path identifiers and foreign-key references carried
    in request bodies are validated left to right: the first identifier that
    does not resolve to an existing entity is rejected with `ERR_NOT_FOUND`
    (HTTP 404)."

    Design: Corner/entities/get_unknown_program_returns_not_found
    """
    resp = api_client.get_program(NON_EXISTENT_UUID, MANAGER)
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND)


def test_nonexistent_commitment_sign_returns_not_found_before_state():
    """PRD section 2.5: "the first identifier that does not resolve to an
    existing entity is rejected with `ERR_NOT_FOUND` (HTTP 404)" — existence
    (priority 4) is evaluated before ownership and state, so signing a random
    commitment id can never surface a state error.

    Design: Corner/validations/nonexistent_commitment_sign_returns_not_found_before_state
    """
    maker = create_device_maker()
    resp = api_client.sign_commitment(
        NON_EXISTENT_UUID, headers=make_device_maker_headers(maker["id"])
    )
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND)
