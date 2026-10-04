"""Pre-built role headers for every role in the PRD (§2.1).

BrandManager is entity-backed: its X-User-ID must be the acting Brand's id,
so ownership-gated calls MUST use make_brand_manager_headers(brand_id) with
the real brand id. The shared TEST_USERS entry for BrandManager is a fallback
for non-ownership tests only. All other roles are opaque operator identities.
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    "platform_admin_headers": build_user_headers("test-admin-1", "PlatformAdmin"),
    "licensing_manager_headers": build_user_headers("test-lm-1", "LicensingManager"),
    "quality_auditor_headers": build_user_headers("test-qa-1", "QualityAuditor"),
    # entity_backed:Brand — fallback for non-ownership tests only.
    "brand_manager_headers": build_user_headers("test-bm-1", "BrandManager"),
    "operations_director_headers": build_user_headers("test-od-1", "OperationsDirector"),
    "production_planner_headers": build_user_headers("test-pp-1", "ProductionPlanner"),
    "category_manager_headers": build_user_headers("test-cm-1", "CategoryManager"),
    "finance_analyst_headers": build_user_headers("test-fa-1", "FinanceAnalyst"),
    "support_agent_headers": build_user_headers("test-sa-1", "SupportAgent"),
}


def make_brand_manager_headers(user_id: str) -> dict:
    """BrandManager headers keyed to a real Brand.id — required whenever the
    call is ownership-gated (variety creation and variety transitions)."""
    return build_user_headers(user_id, "BrandManager")
