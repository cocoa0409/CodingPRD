"""Corner: RBAC role denial and scope."""
from test_helpers import (
    DESK,
    OPERATOR,
    ApiErrorId,
    approved_authorization,
    create_dispute_payload,
    create_issuer_payload,
    get_success_data,
    make_cardholder_headers,
    reset_clock,
    setup_cardholder,
    setup_provisioned_token,
    validate_error,
)


def test_issuer_operator_cannot_manage_issuers(api):
    """PRD section 4: POST /issuers/{issuerId}/suspend lists only
    PlatformAdmin under Authorized Role(s), and section 2.1: "a role outside
    the endpoint's authorized set is rejected with ERR_FORBIDDEN (HTTP 403)."

    Design: Corner/rbac/issuer_operator_cannot_manage_issuers
    """
    reset_clock(api)
    from test_helpers import ADMIN
    issuer = get_success_data(api.create_issuer(create_issuer_payload(), ADMIN))
    resp = api.suspend_issuer(issuer["id"], OPERATOR)
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN)
    issuer = get_success_data(api.get_issuer(issuer["id"]))
    assert issuer["status"] == "DRAFT"


def test_cardholder_cannot_resolve_disputes(api):
    """PRD section 4: POST /disputes/{disputeId}/resolve-dispute lists only
    IssuerOperator under Authorized Role(s), and section 2.1: "a role outside
    the endpoint's authorized set is rejected with ERR_FORBIDDEN (HTTP 403)."
    The cardholder who opened the dispute cannot resolve it.

    Design: Corner/rbac/cardholder_cannot_resolve_disputes
    """
    ns = setup_provisioned_token(api)
    auth = approved_authorization(api, ns["token"], amount_cents=9000,
                                  cryptogram="cgm-r")
    ch = make_cardholder_headers(ns["cardholder"]["id"])
    dispute = get_success_data(
        api.open_dispute(auth["id"], create_dispute_payload(9000), ch))
    resp = api.resolve_dispute(dispute["id"], {"outcome": "WON"}, ch)
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN)
    dispute = get_success_data(api.get_dispute(dispute["id"]))
    assert dispute["status"] == "OPEN"


def test_customer_service_scope(api):
    """PRD section 2.1: "CustomerService is read-mostly, able to report a
    device lost or found and to intake disputes" and section 4:
    POST /devices/{deviceId}/report_lost lists Cardholder, IssuerOperator,
    CustomerService; POST /authorizations/{authorizationId}/disputes lists
    Cardholder, CustomerService; POST /payment-tokens/{tokenId}/authorizations
    lists only IssuerOperator — a CustomerService authorize attempt is
    ERR_FORBIDDEN.

    Design: Corner/rbac/customer_service_can_report_lost_and_open_disputes_but_not_authorize
    """
    ns = setup_provisioned_token(api)
    auth = approved_authorization(api, ns["token"], amount_cents=3000,
                                  cryptogram="cgm-s")
    device = get_success_data(api.report_device_lost(ns["device"]["id"], DESK))
    assert device["security_posture"] == "LOST"
    dispute = get_success_data(
        api.open_dispute(auth["id"], create_dispute_payload(3000, reason="DUPLICATE"),
                         DESK))
    assert dispute["id"]
    resp = api.authorize(ns["token"]["id"], {
        "cryptogram": "cgm-s2", "amount_cents": 3000, "currency": "USD",
        "merchant_id": "m-1", "merchant_category": "GENERAL"}, DESK)
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN)
