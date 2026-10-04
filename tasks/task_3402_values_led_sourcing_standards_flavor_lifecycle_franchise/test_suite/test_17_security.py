"""Auth, 404 vocabulary, error envelope, clock monotonicity (PRD §2.1, §2.2, §2.5, §2.6)."""
from test_helpers import (
    validate_success, validate_error, get_success_data,
    ApiErrorId, TEST_USERS, api_client,
    create_supplier_payload, assert_error_envelope,
)

SM = TEST_USERS["sourcing_manager_headers"]
FM = TEST_USERS["flavor_manager_headers"]
DPM = TEST_USERS["dairy_program_manager_headers"]
POC = TEST_USERS["parent_ops_controller_headers"]
FA = TEST_USERS["franchise_admin_headers"]
FAN = TEST_USERS["fan_headers"]

GHOST = "8a3e1c0b-2f4d-4a91-9c8b-12e7b6a0f1d2"


def test_missing_auth_headers_unauthenticated(api):
    """PRD §2.1: "A request missing either header, or presenting a role the
    platform does not declare, is rejected with `ERR_UNAUTHENTICATED`
    (HTTP 401)."

    Design: Corner/validations/missing_auth_headers_unauthenticated
    """
    resp = api.get_flavor(GHOST, headers={})
    validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED)


def test_fan_cannot_create_supplier_unauthorized(api):
    """PRD §2.1: "A request whose role is valid but not listed among the roles
    authorized for the target endpoint is rejected with `ERR_UNAUTHORIZED`
    (HTTP 403)."
    PRD §4: "POST | `/creamery/suppliers` | Register a supplier (lands
    `PROSPECT`) | SourcingManager".

    Design: Corner/validations/fan_cannot_create_supplier_unauthorized
    """
    resp = api.create_supplier(
        create_supplier_payload(name="Fan Supplier"), FAN)
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED)


def test_entity_get_unknown_id_returns_not_found(api):
    """PRD §2.6: "The not-found vocabulary is per resource type: `ERR_SUPPLIER_NOT_FOUND`, `ERR_CERTIFICATION_NOT_FOUND`, `ERR_AUDIT_NOT_FOUND`, `ERR_ENROLLMENT_NOT_FOUND`, `ERR_PAYMENT_NOT_FOUND`, `ERR_FLAVOR_NOT_FOUND`, `ERR_REVIVAL_REQUEST_NOT_FOUND`, `ERR_SLOT_NOT_FOUND`, `ERR_CAMPAIGN_NOT_FOUND`, `ERR_SHOP_NOT_FOUND`, and `ERR_ORDER_NOT_FOUND`, each with HTTP 404."

    Design: Corner/errors/entity_get_unknown_id_returns_not_found
    """
    validate_error(api.get_supplier(GHOST, SM), ApiErrorId.ERR_SUPPLIER_NOT_FOUND)
    validate_error(api.get_campaign(GHOST, POC), ApiErrorId.ERR_CAMPAIGN_NOT_FOUND)
    validate_error(api.get_supply_order(GHOST, FA), ApiErrorId.ERR_ORDER_NOT_FOUND)


def test_error_envelope_shape_on_failure(api):
    """PRD §2.2: "The `meta` object for error responses contains only `api_request_id` and `api_request_timestamp`." PRD §2.2: "The `error_id` is a unique, machine-readable string that identifies the specific error." PRD §2.2: "The `message` provides a human-readable explanation of what went wrong."

    Design: Corner/errors/error_envelope_shape_on_failure
    """
    resp = api.get_premium_payment(GHOST, DPM)
    assert resp.status_code == 404
    assert_error_envelope(resp, "ERR_PAYMENT_NOT_FOUND")


def test_clock_regression_rejected(api):
    """PRD §2.5: "The clock is monotonic: a request to set it to an instant
    earlier than the current logical time is rejected with
    `ERR_CLOCK_REGRESSION` (HTTP 422)."

    Design: Corner/endpoints/clock_regression_rejected
    """
    validate_success(api.set_clock({"to_iso8601": "2026-09-02T00:00:00Z"}, POC))
    resp = api.set_clock({"to_iso8601": "2026-09-01T00:00:00Z"}, POC)
    validate_error(resp, ApiErrorId.ERR_CLOCK_REGRESSION)
