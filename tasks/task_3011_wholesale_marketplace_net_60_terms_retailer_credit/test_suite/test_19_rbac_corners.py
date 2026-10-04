"""Queue B (Corner/rbac): role denials and ownership enforcement."""

from test_helpers import (
    RISK,
    ApiErrorId,
    active_brand,
    make_brand_headers,
    make_retailer_headers,
    open_credit_account,
    order_line,
    place_order,
    read_order,
    read_retailer,
    register_retailer,
    validate_error,
    verified_retailer,
)


def test_retailer_cannot_review_own_documents(api):
    """PRD §2.1: "A request whose role is valid but is not in the set of roles
    authorized for the target endpoint is rejected with `ERR_UNAUTHORIZED`
    (HTTP 403)."
    PRD §4: POST /wholesale/retailers/{id}/documents/review is authorized for
    PlatformAdmin only.

    Design: Corner/rbac/retailer_cannot_review_own_documents
    """
    retailer = register_retailer(api)
    response = api.review_document(
        retailer["id"],
        {"document_type": "STOREFRONT_PROOF", "decision": "CONFIRM"},
        make_retailer_headers(retailer["id"]),
    )
    validate_error(response, ApiErrorId.ERR_UNAUTHORIZED, 403)
    assert read_retailer(api, retailer["id"])["storefront_proof_status"] == "PENDING"


def test_retailer_cannot_ship_and_wrong_brand_cannot_ship(api):
    """PRD §2.1: "Beyond role membership, entity-backed callers are subject to
    an ownership check: when an entity-backed role acts on a resource it owns,
    the resource's foreign key must match the caller's `X-User-ID`, and a
    mismatch is rejected with `ERR_FORBIDDEN` (HTTP 403)."
    PRD §3.5: "A brand ships one of its own orders — `X-User-ID` must equal
    the order's `brand_id` — moving it `PLACED → SHIPPED`"

    Design: Corner/rbac/retailer_cannot_ship_own_order_and_wrong_brand_cannot_ship
    """
    retailer = verified_retailer(api)
    open_credit_account(api, retailer["id"])
    brand1 = active_brand(api, lead_time_days=0)
    brand2 = active_brand(api, lead_time_days=0)
    order = place_order(api, retailer["id"], brand1["id"], [order_line("S1", 5000, 1)])

    # Role denial: the Retailer role may not ship.
    role_denied = api.ship_order(order["id"], make_retailer_headers(retailer["id"]))
    validate_error(role_denied, ApiErrorId.ERR_UNAUTHORIZED, 403)

    # Ownership denial: a different Brand may not ship brand1's order.
    wrong_brand = api.ship_order(order["id"], make_brand_headers(brand2["id"]))
    validate_error(wrong_brand, ApiErrorId.ERR_FORBIDDEN, 403)

    assert read_order(api, order["id"])["status"] == "PLACED"


def test_unauthenticated_and_risk_analyst_denied(api):
    """PRD §2.1: "A request whose `X-User-Role` header is missing or does not
    name one of the declared roles, or whose `X-User-ID` header is missing, is
    rejected with `ERR_UNAUTHENTICATED` (HTTP 401)."
    PRD §2.1: "A request whose role is valid but is not in the set of roles
    authorized for the target endpoint is rejected with `ERR_UNAUTHORIZED`
    (HTTP 403)."

    Design: Corner/rbac/unauthenticated_and_risk_analyst_denied
    """
    retailer = register_retailer(api)

    # Role denial: RiskAnalyst may not verify a retailer.
    denied = api.verify_retailer(retailer["id"], {"decision": "APPROVE"}, RISK)
    validate_error(denied, ApiErrorId.ERR_UNAUTHORIZED, 403)

    # Authentication denial: no X-User-Role header at all.
    unauthenticated = api.review_document(
        retailer["id"],
        {"document_type": "STOREFRONT_PROOF", "decision": "CONFIRM"},
        {"X-User-ID": "admin-1", "Content-Type": "application/json"},
    )
    validate_error(unauthenticated, ApiErrorId.ERR_UNAUTHENTICATED, 401)
