"""Role headers for every role in the contract.

``AssociationAdmin`` is an opaque role: its ``X-User-ID`` is not tied to any
persisted entity, so the shared constant is canonical.

``HomePlanOperator`` and ``HostPlanOperator`` are entity-backed: their
``X-User-ID`` must equal the ``id`` of the acting Plan whenever a call is
ownership-gated. Use ``make_home_plan_operator_headers(plan["id"])`` /
``make_host_plan_operator_headers(plan["id"])`` for those calls; the shared
constants are fallbacks for tests that do not exercise ownership.
"""

from prd_bench_local_runner.testing import build_user_headers

ASSOCIATION_ADMIN_HEADERS = build_user_headers("test-association-admin-1", "AssociationAdmin")
HOME_PLAN_OPERATOR_HEADERS = build_user_headers("test-home-plan-operator-1", "HomePlanOperator")
HOST_PLAN_OPERATOR_HEADERS = build_user_headers("test-host-plan-operator-1", "HostPlanOperator")

TEST_USERS = {
    "association_admin_headers": ASSOCIATION_ADMIN_HEADERS,
    "home_plan_operator_headers": HOME_PLAN_OPERATOR_HEADERS,
    "host_plan_operator_headers": HOST_PLAN_OPERATOR_HEADERS,
}


def make_home_plan_operator_headers(plan_id: str) -> dict:
    """Headers for a HomePlanOperator acting on behalf of the given Plan."""
    return build_user_headers(plan_id, "HomePlanOperator")


def make_host_plan_operator_headers(plan_id: str) -> dict:
    """Headers for a HostPlanOperator acting on behalf of the given Plan."""
    return build_user_headers(plan_id, "HostPlanOperator")
