"""Authentication, role authorization, and BrandManager ownership (PRD §2.1)."""
from test_helpers import (
    ApiErrorId,
    create_active_agreement,
    create_agreement,
    create_brand,
    create_variety,
    get_success_data,
    make_brand_manager_headers,
    validate_error,
)


def test_missing_auth_headers_returns_unauthenticated(api):
    """PRD §2.1: "A request missing either header, or presenting a role the
    system does not recognize, is rejected with `ERR_UNAUTHENTICATED`
    (HTTP 401)."

    Design: Corner/validations/missing_auth_headers_returns_unauthenticated
    """
    # No X-User-Role / X-User-ID headers at all.
    resp = api.create_brand(
        {"name": "NoAuth Brand", "kind": "LICENSED", "home_region": "US"}, {})
    validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED)


def test_brand_manager_cannot_create_facilities(api):
    """PRD §2.1: "a request whose role is authenticated but not admitted by the
    endpoint is rejected with `ERR_FORBIDDEN` (HTTP 403)."
    PRD §4 assigns POST /facilities to OperationsDirector only.

    Design: Corner/rbac/brand_manager_cannot_create_facilities
    """
    brand = create_brand(kind="PLATFORM_OWNED", name="RBAC Brand")
    resp = api.create_facility(
        {"name": "Sneaky Plant", "kind": "OWNED", "region": "US"},
        make_brand_manager_headers(brand["id"]))
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN)


def test_finance_analyst_cannot_transition_agreements(api, finance_headers,
                                                      licensing_headers):
    """PRD §2.1: "a request whose role is authenticated but not admitted by the
    endpoint is rejected with `ERR_FORBIDDEN` (HTTP 403)."
    PRD §4 assigns POST /license-agreements/{id}/transition to LicensingManager
    only.

    Design: Corner/rbac/finance_analyst_cannot_transition_agreements
    """
    brand = create_brand(kind="LICENSED", name="RBAC License Co")
    agreement = create_agreement(brand["id"])

    resp = api.transition_license_agreement(
        agreement["id"], {"target_state": "ACTIVE"}, finance_headers)
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN)

    read_back = get_success_data(
        api.get_license_agreement(agreement["id"], licensing_headers))
    assert read_back["status"] == "DRAFT"


def test_quality_auditor_cannot_create_statements(api, auditor_headers):
    """PRD §2.1: "a request whose role is authenticated but not admitted by the
    endpoint is rejected with `ERR_FORBIDDEN` (HTTP 403)."
    PRD §4 assigns POST /license-agreements/{id}/royalty-statements to
    FinanceAnalyst only.

    Design: Corner/rbac/quality_auditor_cannot_create_statements
    """
    brand = create_brand(kind="LICENSED", name="RBAC Audit Co")
    agreement = create_active_agreement(brand["id"])

    resp = api.create_royalty_statement(
        agreement["id"],
        {"period": "2026-08", "sell_in_units": 10, "sell_through_units": 10,
         "unlicensed_share_pct": 0},
        auditor_headers)
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN)


def test_production_planner_cannot_drive_variety_lifecycle(api, planner_headers):
    """PRD §2.1: "a request whose role is authenticated but not admitted by the
    endpoint is rejected with `ERR_FORBIDDEN` (HTTP 403)."
    PRD §4 assigns POST /pod-varieties/{id}/transition to BrandManager only.

    Design: Corner/rbac/production_planner_cannot_drive_variety_lifecycle
    """
    brand = create_brand(kind="PLATFORM_OWNED", name="RBAC Var Brand")
    variety = create_variety(brand["id"], name="RBAC Var")

    resp = api.transition_pod_variety(
        variety["id"], {"target_state": "PHASE_OUT"}, planner_headers)
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN)

    read_back = get_success_data(api.get_pod_variety(variety["id"], planner_headers))
    assert read_back["status"] == "ACTIVE"


def test_brand_manager_limited_to_own_brand(api):
    """PRD §2.1: "a `BrandManager` may only create a pod variety whose
    `brand_id` equals their own `X-User-ID`, and may only drive transitions on
    varieties belonging to that brand; a mismatch is rejected with
    `ERR_BRAND_OWNERSHIP` (HTTP 403)."

    Design: Corner/rbac/brand_manager_limited_to_own_brand
    """
    brand_a = create_brand(kind="LICENSED", name="Owner A")
    brand_b = create_brand(kind="LICENSED", name="Owner B")
    variety_b = create_variety(brand_b["id"], name="B's Var")
    headers_a = make_brand_manager_headers(brand_a["id"])

    forged = api.create_pod_variety(
        {"brand_id": brand_b["id"], "name": "A forging B", "roast_level": "LIGHT",
         "flavor_family": "UNFLAVORED", "wholesale_price_cents": 90,
         "margin_cents": 10},
        headers_a)
    validate_error(forged, ApiErrorId.ERR_BRAND_OWNERSHIP)

    resp = api.transition_pod_variety(
        variety_b["id"], {"target_state": "PHASE_OUT"}, headers_a)
    validate_error(resp, ApiErrorId.ERR_BRAND_OWNERSHIP)

    read_back = get_success_data(api.get_pod_variety(
        variety_b["id"], make_brand_manager_headers(brand_b["id"])))
    assert read_back["status"] == "ACTIVE"
