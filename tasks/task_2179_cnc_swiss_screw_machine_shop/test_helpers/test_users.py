"""Pre-built identity headers for every role in the PRD."""

from prd_bench_local_runner.testing import build_user_headers

# ShopPlanner and QualityManager carry an opaque X-User-ID that is never
# resolved against a stored row, so the shared constants below are the
# canonical form for those two roles.
#
# Machinist and Inspector are backed by an Operator row: X-User-ID must be the
# acting Operator's id.  The shared constants for those two roles therefore
# name no operator at all and are only usable where the call is expected to be
# rejected before or by the operator-existence check.
TEST_USERS = {
    "shop_planner_headers": build_user_headers("planner-1", "ShopPlanner"),
    "quality_manager_headers": build_user_headers("qm-1", "QualityManager"),
    "machinist_headers": build_user_headers(
        "00000000-0000-4000-8000-000000000000", "Machinist"
    ),
    "inspector_headers": build_user_headers(
        "00000000-0000-4000-8000-000000000000", "Inspector"
    ),
}


def make_shop_planner_headers(user_id: str = "planner-1") -> dict:
    """ShopPlanner identity is opaque; the id is logged, never compared."""
    return build_user_headers(user_id, "ShopPlanner")


def make_quality_manager_headers(user_id: str = "qm-1") -> dict:
    """QualityManager identity is opaque; the id is logged, never compared."""
    return build_user_headers(user_id, "QualityManager")


def make_machinist_headers(operator_id: str) -> dict:
    """Machinist is backed by an Operator: pass the acting Operator's id."""
    return build_user_headers(operator_id, "Machinist")


def make_inspector_headers(operator_id: str) -> dict:
    """Inspector is backed by an Operator: pass the acting Operator's id."""
    return build_user_headers(operator_id, "Inspector")


def headers_without_identity() -> dict:
    """Neither X-User-ID nor X-User-Role, for the authentication probe."""
    return {"Content-Type": "application/json"}
