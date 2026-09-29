"""Error identity and admission precedence: authentication first, then existence."""

from test_helpers import (
    ANALYST_ISSUER,
    NON_EXISTENT_UUID,
    PLATFORM_ADMIN,
    VALET_OPS_MANAGER,
    ApiErrorId,
    api_client,
    factories,
    fixtures,
    make_missing_role_headers,
    make_property_manager_headers,
    make_resident_headers,
    make_undeclared_role_headers,
    make_valet_headers,
    validate_error,
)

UNKNOWN_NIGHT_ID = "00000000-0000-4000-8000-000000000901"
UNKNOWN_FINE_ID = "00000000-0000-4000-8000-000000000902"
UNKNOWN_ROUTE_ID = "00000000-0000-4000-8000-000000000903"
UNKNOWN_STATEMENT_ID = "00000000-0000-4000-8000-000000000905"
UNKNOWN_INCIDENT_ID = "00000000-0000-4000-8000-000000000906"
UNKNOWN_CONTRACT_ID = "00000000-0000-4000-8000-000000000907"
UNKNOWN_RESIDENT_ID = "00000000-0000-4000-8000-000000000908"


# --------------------------------------------------------------------------
# Rung 1: authentication, before anything else
# --------------------------------------------------------------------------
def test_an_empty_role_header_is_an_authentication_failure_not_a_default():
    """The header is transmitted as a real empty string and judged by the API.

    PRD 2.5: "**Authentication.** Both headers present and non-blank, and
    `X-User-Role` a declared role — otherwise `ERR_UNAUTHENTICATED` (401). Applies
    to every endpoint."

    Design: Corner/errors/blank_user_role_header_returns_unauthenticated
    """
    fixtures.set_clock("2026-09-01T00:00:00Z")
    prop = fixtures.create_property(name="Cedar Ridge", unit_count=4)
    headers = make_missing_role_headers()
    assert headers["X-User-Role"] == "", (
        "a whitespace-only value is a different fixture and must not be substituted"
    )

    response = api_client.get_property(prop["id"], headers)

    validate_error(response, ApiErrorId.ERR_UNAUTHENTICATED.value, 401)


def test_an_undeclared_role_is_a_401_not_a_403():
    """'Concierge' is well formed but is not one of the seven declared roles.

    PRD 2.1: "If either header is absent, is present but blank, or `X-User-Role`
    names a role outside the seven declared below, the request is rejected with
    `ERR_UNAUTHENTICATED` (HTTP 401) before anything else about the request is
    examined. When both headers are well formed but the named role is not among the
    roles authorized for the endpoint being called, the rejection is
    `ERR_UNAUTHORIZED` (HTTP 403)."

    PRD 2.5: "**Authentication.** Both headers present and non-blank, and
    `X-User-Role` a declared role — otherwise `ERR_UNAUTHENTICATED` (401). Applies
    to every endpoint."

    Design: Corner/errors/undeclared_role_header_returns_unauthenticated
    """
    fixtures.set_clock("2026-09-01T00:00:00Z")
    prop = fixtures.create_property(name="Cedar Ridge", unit_count=4)

    response = api_client.get_property(
        prop["id"], make_undeclared_role_headers(role="Concierge")
    )

    validate_error(response, ApiErrorId.ERR_UNAUTHENTICATED.value, 401)
    assert response.status_code != 403, (
        "an unknown role fails authentication before permissions are consulted"
    )


# --------------------------------------------------------------------------
# Rung 3: path existence beats state, ownership, duties and temporal rules
# --------------------------------------------------------------------------
def test_closing_an_unknown_night_is_a_404_not_a_state_error():
    """Existence is rung 3 and the declared-transition check is only rung 8.

    PRD 2.5: "**Path existence.** Every identifier in the path resolves, left to
    right — otherwise the corresponding 404 code above. Applies to every endpoint
    that has a path identifier."

    Design: Corner/errors/close_of_an_unknown_night_returns_service_night_not_found
    """
    fixtures.set_clock("2026-09-01T00:00:00Z")

    response = api_client.close_service_night(UNKNOWN_NIGHT_ID, VALET_OPS_MANAGER)

    validate_error(response, ApiErrorId.ERR_SERVICE_NIGHT_NOT_FOUND.value, 404)


def test_a_resident_disputing_an_unknown_fine_gets_the_fine_404_not_the_ownership_403():
    """Rung 3 precedes the rung 4 ownership check, so the missing row wins.

    PRD 2.5: "**Resource ownership.** For an entity-backed role, `X-User-ID` owns
    the addressed resource — otherwise `ERR_NOT_RESOURCE_OWNER` (403). Applies to
    every write endpoint reachable by `Valet`, `Resident` or `PropertyManager`."

    Design: Corner/errors/dispute_of_an_unknown_fine_returns_fine_not_found
    """
    fixtures.set_clock("2026-09-01T00:00:00Z")

    response = api_client.dispute_fine(
        UNKNOWN_FINE_ID,
        factories.dispute_payload("The bin was not mine"),
        make_resident_headers(NON_EXISTENT_UUID),
    )

    validate_error(response, ApiErrorId.ERR_FINE_NOT_FOUND.value, 404)
    assert response.status_code != 403, "ownership is only consulted once the row exists"


def test_a_valet_accepting_an_unknown_route_gets_the_route_404():
    """No route row exists, so there is no owner to compare the caller against.

    PRD 2.5: "The ten path identifiers used by this API are `property_id`,
    `contract_id`, `resident_id`, `contractor_id`, `night_id`, `route_id`,
    `scan_id`, `fine_id`, `incident_id` and `statement_id`, and each maps to its own
    not-found code: `ERR_PROPERTY_NOT_FOUND`, `ERR_CONTRACT_NOT_FOUND`,
    `ERR_RESIDENT_NOT_FOUND`, `ERR_CONTRACTOR_NOT_FOUND`,
    `ERR_SERVICE_NIGHT_NOT_FOUND`, `ERR_ROUTE_NOT_FOUND`, `ERR_SCAN_NOT_FOUND`,
    `ERR_FINE_NOT_FOUND`, `ERR_INCIDENT_NOT_FOUND` and `ERR_STATEMENT_NOT_FOUND`,
    all at HTTP 404."

    Design: Corner/errors/accept_of_an_unknown_route_returns_route_not_found
    """
    fixtures.set_clock("2026-09-01T00:00:00Z")

    response = api_client.accept_route(
        UNKNOWN_ROUTE_ID, make_valet_headers(NON_EXISTENT_UUID)
    )

    validate_error(response, ApiErrorId.ERR_ROUTE_NOT_FOUND.value, 404)


def test_issuing_an_unknown_statement_is_a_404_not_a_segregation_of_duties_403():
    """Rung 3 fires long before the rung 13 duties comparison needs a drafter.

    PRD 2.5: "**Segregation of duties.** The `BillingAnalyst` issuing a statement
    must not be the one who drafted it, and the `ComplianceOfficer` running an
    `OBSERVED` reclassification must not be the one who recorded that contractor's
    background check — otherwise `ERR_SEGREGATION_OF_DUTIES` (403). Applies to two
    endpoints: statement issue and contractor classification."

    Design: Corner/errors/issue_of_an_unknown_statement_returns_statement_not_found
    """
    fixtures.set_clock("2026-09-01T00:00:00Z")

    response = api_client.issue_statement(UNKNOWN_STATEMENT_ID, ANALYST_ISSUER)

    validate_error(response, ApiErrorId.ERR_STATEMENT_NOT_FOUND.value, 404)


def test_escalating_an_unknown_incident_attempts_no_deadline_arithmetic():
    """The 404 precedes the rung 18 window check, which has no deadline to read.

    PRD 2.5: "**Escalation window elapsed.** Escalation must be attempted at or
    after the incident's `ack_deadline_at` on the logical clock — otherwise
    `ERR_ESCALATION_WINDOW_NOT_ELAPSED` (409). Applies to incident escalation."

    Design: Corner/errors/escalate_of_an_unknown_incident_returns_incident_not_found
    """
    fixtures.set_clock("2026-09-01T00:00:00Z")

    response = api_client.escalate_incident(UNKNOWN_INCIDENT_ID, VALET_OPS_MANAGER)

    validate_error(response, ApiErrorId.ERR_INCIDENT_NOT_FOUND.value, 404)


def test_activating_an_unknown_contract_creates_no_community_side_effects():
    """The refusal is total: no property is written because none was addressed.

    PRD 3.1: "Activation is where the community itself comes alive: alongside
    setting the contract's `status` to `ACTIVE` and incrementing its `version`, the
    community's `active_contract_id` is set to that contract and its `status` moves
    `ONBOARDING → ACTIVE`, incrementing the community's `version` in the same
    request."

    Design: Corner/errors/activate_of_an_unknown_contract_returns_contract_not_found
    """
    fixtures.set_clock("2026-09-01T00:00:00Z")

    response = api_client.activate_contract(UNKNOWN_CONTRACT_ID, PLATFORM_ADMIN)

    validate_error(response, ApiErrorId.ERR_CONTRACT_NOT_FOUND.value, 404)
    assert fixtures.list_properties() == [], "nothing was created or mutated"
    assert fixtures.list_contracts() == []


def test_moving_out_an_unknown_resident_uses_the_same_id_as_the_body_check():
    """One error id serves both the path-existence and body-foreign-key call sites.

    PRD 2.5: "**Body foreign keys resolve.** The `contractor_id` supplied when
    creating a route assignment must name an existing contractor, and the
    `resident_id` supplied when recording a scan must name an existing resident —
    otherwise `ERR_CONTRACTOR_NOT_FOUND` or `ERR_RESIDENT_NOT_FOUND` (404). Applies
    to exactly those two endpoints."

    Design: Corner/errors/move_out_of_an_unknown_resident_returns_resident_not_found
    """
    fixtures.set_clock("2026-09-01T00:00:00Z")

    response = api_client.move_out_resident(
        UNKNOWN_RESIDENT_ID,
        factories.move_out_payload("2026-09-15"),
        make_property_manager_headers(NON_EXISTENT_UUID),
    )

    validate_error(response, ApiErrorId.ERR_RESIDENT_NOT_FOUND.value, 404)


# --------------------------------------------------------------------------
# Rung 6: a body foreign key that does not resolve
# --------------------------------------------------------------------------
def test_a_route_naming_an_unknown_contractor_fails_the_body_key_before_eligibility():
    """The night and the version are both fine; only the body's contractor is not.

    PRD 2.5: "**Body foreign keys resolve.** The `contractor_id` supplied when
    creating a route assignment must name an existing contractor, and the
    `resident_id` supplied when recording a scan must name an existing resident —
    otherwise `ERR_CONTRACTOR_NOT_FOUND` or `ERR_RESIDENT_NOT_FOUND` (404). Applies
    to exactly those two endpoints."

    PRD 2.5: "**Contractor service eligibility.** The contractor being assigned
    must have `onboarding_status` equal to `CLEARED` and a `classification` other
    than `UNCLASSIFIED` — otherwise `ERR_CONTRACTOR_NOT_ELIGIBLE` (409). Applies to
    route-assignment creation."

    Design: Corner/errors/route_create_with_an_unknown_contractor_id_returns_contractor_not_found
    """
    world = fixtures.build_active_community(
        name="Cedar Ridge", unit_count=4, resident_units=(), with_contractor=False
    )
    night = fixtures.schedule_night(world["contract"]["id"], "2026-09-01")
    assert fixtures.list_contractors() == []

    response = api_client.create_route_assignment(
        night["id"],
        factories.route_payload(NON_EXISTENT_UUID, 101, 104, night["version"]),
        VALET_OPS_MANAGER,
    )

    validate_error(response, ApiErrorId.ERR_CONTRACTOR_NOT_FOUND.value, 404)
    unchanged = fixtures.read_night(night["id"])
    assert unchanged["version"] == night["version"]
    assert unchanged["assigned_unit_coverage_count"] == 0
    assert fixtures.list_routes({"service_night_id": night["id"]}) == []
