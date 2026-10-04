"""Cross-cutting access control and existence mapping: authentication before
everything, role exclusivity, the admin-only clock, and the per-resource
not-found error ids.
"""

from test_helpers import (
    ACCOUNT_MANAGER,
    DISPATCHER,
    NON_EXISTENT_UUID,
    SUPPLY_OPS,
    ApiErrorId,
    api_client,
    contract_renew_payload,
    create_account,
    engineer_payload,
    make_lab_procurement_headers,
    plus_days,
    service_request_payload,
    validate_error,
    CLOCK_START_UTC,
)


def test_missing_auth_headers_returns_unauthenticated(api):
    """PRD section 2.1: "A request that arrives without both headers, whose
    `X-User-Role` is not one of the six declared roles, or — for the
    entity-backed roles described below — whose `X-User-ID` does not identify
    an existing entity of the bound type is rejected with
    `ERR_UNAUTHENTICATED` (HTTP 401)."  Authentication is priority 1, ahead
    even of the not-found check.

    Design: Corner/validations/missing_auth_headers_returns_unauthenticated
    """
    response = api_client.get_account(NON_EXISTENT_UUID, headers=None)
    validate_error(response, ApiErrorId.ERR_UNAUTHENTICATED)


def test_procurement_cannot_create_engineers_forbidden(api):
    """PRD section 2.1: "A request whose role is not among an endpoint's
    authorized roles, or that violates an ownership rule, is rejected with
    `ERR_FORBIDDEN` (HTTP 403)." and PRD section 4: "Register a field service
    engineer | ServiceDispatcher, PlatformAdmin".

    Design: Corner/rbac/procurement_cannot_create_engineers_forbidden
    """
    account = create_account(name="RBAC Lab")
    response = api_client.create_engineer(
        engineer_payload(name="Sneaky"),
        headers=make_lab_procurement_headers(account["id"]),
    )
    validate_error(response, ApiErrorId.ERR_FORBIDDEN)


def test_non_admin_cannot_set_clock_forbidden(api):
    """PRD section 3.8: "The clock-setting capability accepts a target instant
    `to_iso8601`, returns the new logical time as `current_utc`, and is
    restricted to `PlatformAdmin`."

    Design: Corner/rbac/non_admin_cannot_set_clock_forbidden
    """
    response = api_client.set_clock(
        plus_days(CLOCK_START_UTC, 1), headers=SUPPLY_OPS
    )
    validate_error(response, ApiErrorId.ERR_FORBIDDEN)


def test_not_found_errors_across_entities(api):
    """PRD section 2.9: "Unknown path identifiers and unknown body references
    are rejected before any state or business rule runs: a request naming a
    nonexistent identifier always fails with the corresponding not-found error
    — `ERR_ACCOUNT_NOT_FOUND`, `ERR_AGREEMENT_NOT_FOUND`,
    `ERR_INSTRUMENT_NOT_FOUND`, `ERR_CONTRACT_NOT_FOUND`,
    `ERR_SERVICE_REQUEST_NOT_FOUND`, `ERR_ORDER_NOT_FOUND`, or
    `ERR_SURGE_EVENT_NOT_FOUND` by resource, and
    `ERR_CATALOG_ITEM_NOT_FOUND` when an order line names a `sku` absent from
    the catalog or a body `account_id` / `instrument_id` reference fails to
    resolve."

    Design: Corner/endpoints/not_found_errors_across_entities
    """
    create_account(name="Probe Lab", segment="ACADEMIC")

    cases = [
        (
            api_client.get_enterprise_agreement(
                NON_EXISTENT_UUID, headers=ACCOUNT_MANAGER
            ),
            ApiErrorId.ERR_AGREEMENT_NOT_FOUND,
        ),
        (
            api_client.renew_service_contract(
                NON_EXISTENT_UUID,
                contract_renew_payload(1),
                headers=ACCOUNT_MANAGER,
            ),
            ApiErrorId.ERR_CONTRACT_NOT_FOUND,
        ),
        (
            api_client.get_service_request(NON_EXISTENT_UUID, headers=DISPATCHER),
            ApiErrorId.ERR_SERVICE_REQUEST_NOT_FOUND,
        ),
        (
            api_client.get_order(NON_EXISTENT_UUID, headers=SUPPLY_OPS),
            ApiErrorId.ERR_ORDER_NOT_FOUND,
        ),
        (
            api_client.resolve_surge_event(NON_EXISTENT_UUID, headers=SUPPLY_OPS),
            ApiErrorId.ERR_SURGE_EVENT_NOT_FOUND,
        ),
        (
            api_client.create_service_request(
                service_request_payload(NON_EXISTENT_UUID),
                headers=ACCOUNT_MANAGER,
            ),
            ApiErrorId.ERR_INSTRUMENT_NOT_FOUND,
        ),
    ]
    for response, expected in cases:
        validate_error(response, expected)
