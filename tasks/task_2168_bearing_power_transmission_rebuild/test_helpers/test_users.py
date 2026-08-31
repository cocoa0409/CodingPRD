"""Pre-built role headers for every role in the PRD.

Four of the five roles carry an opaque operator identifier in X-User-ID; only
a Customer caller's X-User-ID is the id of a persisted Customer record, so
ownership-gated calls must use make_customer_headers(customer["id"]).
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    # Opaque roles: the shared constant is the canonical form.
    "shop_admin_headers": build_user_headers("admin-1", "ShopAdmin"),
    "planner_headers": build_user_headers("planner-1", "Planner"),
    "inspector_headers": build_user_headers("insp-1", "Inspector"),
    "reliability_engineer_headers": build_user_headers("eng-1", "ReliabilityEngineer"),
    # Customer identity is entity-backed; this constant is a fallback for
    # tests that never exercise ownership (401/404/400 paths only).
    "customer_headers": build_user_headers("test-customer-1", "Customer"),
}


def make_shop_admin_headers(user_id: str) -> dict:
    """ShopAdmin acting under a specific operator id (segregation of duties)."""
    return build_user_headers(user_id, "ShopAdmin")


def make_planner_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "Planner")


def make_inspector_headers(user_id: str) -> dict:
    """Inspector acting under a specific operator id (four-eyes acceptance)."""
    return build_user_headers(user_id, "Inspector")


def make_reliability_engineer_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "ReliabilityEngineer")


def make_customer_headers(customer_id: str) -> dict:
    """For the Customer role. Pass the acting Customer record's id, which is
    what every ownership check compares against."""
    return build_user_headers(customer_id, "Customer")


# Frequently used operator identities.
ADMIN_1 = make_shop_admin_headers("admin-1")
ADMIN_2 = make_shop_admin_headers("admin-2")
INSP_1 = make_inspector_headers("insp-1")
INSP_2 = make_inspector_headers("insp-2")
INSP_3 = make_inspector_headers("insp-3")
INSP_9 = make_inspector_headers("insp-9")
ENG_1 = make_reliability_engineer_headers("eng-1")
PLANNER_1 = make_planner_headers("planner-1")
