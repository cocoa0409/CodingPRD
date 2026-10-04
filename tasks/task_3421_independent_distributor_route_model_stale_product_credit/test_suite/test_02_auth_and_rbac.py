"""Auth headers, role authorization, and distributor ownership scope.

Covers PRD §2.1 (headers, roles, entity-backed distributor identity) and §3.6
(segregation of duties between claim decision and credit issuance).
Instances: Corner/validations/missing_auth_header_returns_400 and
Corner/rbac/* (4).
"""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    api_client,
    claim_item,
    create_distributor,
    create_order,
    create_territory,
    decide_claim_payload,
    get_agreement,
    get_distributor,
    list_orders,
    list_stale_claims,
    make_distributor_headers,
    order_line,
    reset_clock_to_default,
    setup_active_cash_agreement,
    setup_approved_claim,
    setup_submitted_claim,
    validate_error,
    validate_paginated,
)
from test_helpers.fixtures import suspend_agreement  # not re-exported by the barrel

_ADMIN = TEST_USERS["company_admin_headers"]
_ROUTE_OPS = TEST_USERS["route_ops_manager_headers"]


def test_missing_auth_header_returns_400(api):
    """PRD §2.1: "Every request must carry two HTTP headers: `X-User-ID`
    identifying the caller and `X-User-Role` naming the caller's operational
    capacity. ... A request missing either header, or carrying a role string
    other than these four, is rejected with
    `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400)."

    Design: Corner/validations/missing_auth_header_returns_400
    """
    reset_clock_to_default()
    territory = create_territory()
    resp = api_client.get_territory(territory["id"], headers={})
    validate_error(resp, ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER)


def test_distributor_cannot_decide_claim_returns_forbidden(api):
    """PRD §2.1: "A request whose role is valid but not among the roles
    authorized for the targeted operation is rejected with
    `ERR_FORBIDDEN_FOR_ROLE` (HTTP 403); this includes the
    segregation-of-duties boundary between route operations and the credit
    desk, under which a `CreditAnalyst` may not decide stale claims and a
    `RouteOpsManager` may not issue credits."
    PRD §3.6: "Review belongs to a `RouteOpsManager` and only while the claim
    is `SUBMITTED`; deciding a claim in any other state is rejected with
    `ERR_CLAIM_NOT_REVIEWABLE`."

    Design: Corner/rbac/distributor_cannot_decide_claim_returns_forbidden
    """
    ctx = setup_active_cash_agreement()
    _, _, claim = setup_submitted_claim(
        ctx,
        "2026-09-04",
        [order_line("WHT-24", 5)],
        [claim_item("WHT-24", "2026-09-04", 1, "2026-09-10")],
        file_clock="2026-09-10T09:00:00Z",
    )
    resp = api_client.decide_claim(
        claim["id"],
        decide_claim_payload("APPROVE"),
        make_distributor_headers(ctx["distributor"]["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN_FOR_ROLE)
    current = [
        c for c in list_stale_claims(ctx["distributor"]["id"])
        if c["id"] == claim["id"]
    ][0]
    assert current["status"] == "SUBMITTED"


def test_route_ops_cannot_issue_credit_returns_forbidden(api):
    """PRD §3.6: "Issuing money is deliberately segregated from deciding: only
    a `CreditAnalyst` may issue credit on an `APPROVED` claim — a
    `RouteOpsManager` attempting it is refused with `ERR_FORBIDDEN_FOR_ROLE`,
    and a claim not in `APPROVED` rejects the issuance with
    `ERR_INVALID_STATE_TRANSITION`."

    Design: Corner/rbac/route_ops_cannot_issue_credit_returns_forbidden
    """
    ctx = setup_active_cash_agreement()
    _, _, claim = setup_approved_claim(
        ctx,
        "2026-09-04",
        [order_line("WHT-24", 5)],
        [claim_item("WHT-24", "2026-09-04", 1, "2026-09-10")],
        file_clock="2026-09-10T09:00:00Z",
    )
    resp = api_client.issue_credit(claim["id"], _ROUTE_OPS)
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN_FOR_ROLE)
    current = [
        c for c in list_stale_claims(ctx["distributor"]["id"])
        if c["id"] == claim["id"]
    ][0]
    assert current["status"] == "APPROVED"
    assert current["issued_credit_cents"] is None
    distributor = get_distributor(ctx["distributor"]["id"])
    assert distributor["trade_balance_cents"] == 1280, (
        "WHT-24 x5 delivery charge (5 * 256) unchanged by the refused issuance"
    )


def test_distributor_b_cannot_read_distributor_a_orders(api):
    """PRD §2.1: "When `X-User-Role` is `Distributor`, `X-User-ID` is the `id`
    of the acting `Distributor` entity; ownership checks on any resource that
    references a distributor — the path distributor id, or the owning
    distributor of the addressed order, claim, or financing plan — compare that
    foreign key to `X-User-ID`, and a mismatch is rejected with
    `ERR_NOT_RESOURCE_OWNER` (HTTP 403)."

    Design: Corner/rbac/distributor_b_cannot_read_distributor_a_orders
    """
    ctx = setup_active_cash_agreement()
    dist_a = ctx["distributor"]
    create_order(dist_a, "2026-09-04", [order_line("WHT-24", 2)])
    dist_b = create_distributor(
        legal_name="Interloper Routes", credit_limit_cents=100000
    )
    resp = api_client.list_orders(
        dist_a["id"], make_distributor_headers(dist_b["id"])
    )
    validate_error(resp, ApiErrorId.ERR_NOT_RESOURCE_OWNER)
    rows, meta = validate_paginated(
        api_client.list_orders(dist_a["id"], make_distributor_headers(dist_a["id"]))
    )
    assert len(rows) == 1
    assert meta["total_count"] == 1


def test_route_ops_cannot_reinstate_classification_suspension(api):
    """PRD §3.7: "From `SUSPENDED_CLASSIFICATION`, only a `CompanyAdmin` may
    act — a `RouteOpsManager` is refused with `ERR_REINSTATE_FORBIDDEN` — and
    the supplied `resolution` decides the outcome."

    Design: Corner/rbac/route_ops_cannot_reinstate_classification_suspension
    """
    ctx = setup_active_cash_agreement()
    suspend_agreement(ctx["agreement"]["id"], "CLASSIFICATION_DISPUTE")
    resp = api_client.reinstate_agreement(
        ctx["agreement"]["id"], {"resolution": "CONFIRMED_IC"}, _ROUTE_OPS
    )
    validate_error(resp, ApiErrorId.ERR_REINSTATE_FORBIDDEN)
    agreement = get_agreement(ctx["agreement"]["id"])
    assert agreement["status"] == "SUSPENDED_CLASSIFICATION"
    distributor = get_distributor(ctx["distributor"]["id"])
    assert distributor["classification_status"] == "DISPUTED"
