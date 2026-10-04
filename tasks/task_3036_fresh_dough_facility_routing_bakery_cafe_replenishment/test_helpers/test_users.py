"""Pre-built role headers for every role in the PRD.

CafeManager is entity-backed: its X-User-ID must be the acting Cafe's id for
any ownership-gated call. Use make_cafe_manager_headers(cafe_id) in that case.
The opaque roles never have their X-User-ID compared against entity ids.
"""
from prd_bench_local_runner.testing import build_user_headers


TEST_USERS = {
    # entity_backed role: shared constant is a fallback for non-ownership tests only
    # (e.g. 400/404 probes where no specific cafe's resources are touched).
    "cafe_manager_headers": build_user_headers("test-cafe-manager-1", "CafeManager"),
    # opaque roles: shared constants are canonical.
    "facility_planner_headers": build_user_headers("test-planner-1", "FacilityPlanner"),
    "route_dispatcher_headers": build_user_headers("test-dispatcher-1", "RouteDispatcher"),
    "donation_coordinator_headers": build_user_headers("test-coordinator-1", "DonationCoordinator"),
    "finance_admin_headers": build_user_headers("test-finance-1", "FinanceAdmin"),
}


def make_cafe_manager_headers(cafe_id: str) -> dict:
    """CafeManager is entity-backed by Cafe. Pass the actual Cafe.id whenever
    the call is ownership-gated (orders, schedules, bake entries)."""
    return build_user_headers(cafe_id, "CafeManager")


def make_facility_planner_headers(user_id: str = "test-planner-1") -> dict:
    return build_user_headers(user_id, "FacilityPlanner")


def make_route_dispatcher_headers(user_id: str = "test-dispatcher-1") -> dict:
    return build_user_headers(user_id, "RouteDispatcher")


def make_donation_coordinator_headers(user_id: str = "test-coordinator-1") -> dict:
    return build_user_headers(user_id, "DonationCoordinator")


def make_finance_admin_headers(user_id: str = "test-finance-1") -> dict:
    return build_user_headers(user_id, "FinanceAdmin")
