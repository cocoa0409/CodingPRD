"""Pre-built role headers for every role in the PRD.

ShopManager is entity-backed by Shop: ownership-gated calls must use
make_shop_manager_headers(shop["id"]) so X-User-ID equals the shop's id.
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    # Opaque roles — shared constants are the canonical form.
    "admin_headers": build_user_headers("test-admin-1", "NetworkAdmin"),
    "admin2_headers": build_user_headers("adm-2", "NetworkAdmin"),
    "auditor_headers": build_user_headers("aud-1", "NetworkAuditor"),
    "auditor2_headers": build_user_headers("aud-2", "NetworkAuditor"),
    "dealer_headers": build_user_headers("test-dealer-1", "DealerRep"),
    "insurer_headers": build_user_headers("test-insurer-1", "InsurerRep"),
    # ShopManager shared constant — ONLY for tests that do not exercise
    # ownership gating. Ownership-gated calls must use the builder below.
    "shop_manager_headers": build_user_headers("test-shop-1", "ShopManager"),
}


def make_shop_manager_headers(shop_id: str) -> dict:
    """For ShopManager (entity-backed by Shop). Pass the actual Shop.id
    whenever the call is ownership-gated."""
    return build_user_headers(shop_id, "ShopManager")


def make_auditor_headers(user_id: str) -> dict:
    """For NetworkAuditor with a specific user id (segregation-of-duties
    tests need distinct auditor identities)."""
    return build_user_headers(user_id, "NetworkAuditor")


def make_admin_headers(user_id: str) -> dict:
    """For NetworkAdmin with a specific user id (warranty segregation
    tests need distinct admin identities)."""
    return build_user_headers(user_id, "NetworkAdmin")


# Anonymous locator search: no headers at all.
ANONYMOUS_HEADERS = None
