"""Pre-built role headers for every role in the PRD (§2.1).

Only the `Welder` role is entity-backed: its X-User-ID is the acting Welder
entity's id. All other roles are opaque operator identifiers. Per-instance
builders exist for every role so segregation-of-duties tests can pick
distinct opaque identities (e.g., PQR reviewer vs WPS approver).
"""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for opaque roles and for tests that do not exercise
# ownership (400-on-bad-payload, 404-on-missing-resource, wrong-role checks).
TEST_USERS = {
    "shop_admin_headers": build_user_headers("test-shop-admin-1", "ShopAdmin"),
    "qc_manager_headers": build_user_headers("test-qc-manager-1", "QCManager"),
    "weld_lead_headers": build_user_headers("test-weld-lead-1", "WeldLead"),
    # entity_backed role: shared constant is a fallback for non-ownership tests only.
    "welder_headers": build_user_headers("test-welder-1", "Welder"),
    "cwi_headers": build_user_headers("test-cwi-1", "CWI"),
    "material_controller_headers": build_user_headers(
        "test-material-controller-1", "MaterialController"),
    "production_planner_headers": build_user_headers(
        "test-production-planner-1", "ProductionPlanner"),
    "quality_inspector_headers": build_user_headers(
        "test-quality-inspector-1", "QualityInspector"),
    "shipping_clerk_headers": build_user_headers(
        "test-shipping-clerk-1", "ShippingClerk"),
}


def make_shop_admin_headers(user_id: str = "test-shop-admin-1") -> dict:
    return build_user_headers(user_id, "ShopAdmin")


def make_qc_manager_headers(user_id: str) -> dict:
    """QCManager is opaque; use distinct ids for segregation-of-duties pairs
    (the PQR reviewer's id must differ from the WPS approver's id)."""
    return build_user_headers(user_id, "QCManager")


def make_weld_lead_headers(user_id: str = "test-weld-lead-1") -> dict:
    return build_user_headers(user_id, "WeldLead")


def make_welder_headers(welder_id: str) -> dict:
    """For Welder (entity_backed:Welder). Pass the acting Welder.id whenever
    the call is ownership-gated (weld-pass recording always is)."""
    return build_user_headers(welder_id, "Welder")


def make_cwi_headers(user_id: str) -> dict:
    """CWI is opaque; the VT segregation rule compares this id against the
    welder ids recorded on the joint's weld passes."""
    return build_user_headers(user_id, "CWI")


def make_material_controller_headers(
        user_id: str = "test-material-controller-1") -> dict:
    return build_user_headers(user_id, "MaterialController")


def make_production_planner_headers(
        user_id: str = "test-production-planner-1") -> dict:
    return build_user_headers(user_id, "ProductionPlanner")


def make_quality_inspector_headers(
        user_id: str = "test-quality-inspector-1") -> dict:
    return build_user_headers(user_id, "QualityInspector")


def make_shipping_clerk_headers(user_id: str = "test-shipping-clerk-1") -> dict:
    return build_user_headers(user_id, "ShippingClerk")
