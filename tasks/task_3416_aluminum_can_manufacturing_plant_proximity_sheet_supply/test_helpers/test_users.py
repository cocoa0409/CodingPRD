"""Pre-built role headers for every role in the PRD (§2.1).

CustomerPlanner is entity-backed by Customer: its X-User-ID must equal the id of
the Customer it acts for. Use make_customer_planner_headers(customer_id) for any
ownership-gated call; the shared constant is only for tests that never exercise
ownership (or deliberately probe the ownership rule with a bogus id).
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    "platform_admin_headers": build_user_headers("test-platform-admin-1", "PlatformAdmin"),
    "plant_manager_headers": build_user_headers("test-plant-manager-1", "PlantManager"),
    "line_scheduler_headers": build_user_headers("test-line-scheduler-1", "LineScheduler"),
    # Fallback ONLY for non-ownership tests (e.g. 400/404 probes) or negative
    # ownership tests where a non-existent customer id is exactly the point.
    "customer_planner_headers": build_user_headers("test-customer-planner-1", "CustomerPlanner"),
    "quality_engineer_headers": build_user_headers("test-quality-engineer-1", "QualityEngineer"),
}


def make_customer_planner_headers(customer_id: str) -> dict:
    """CustomerPlanner headers bound to a real Customer id (PRD §2.1 ownership).

    Mandatory for sign / open-renegotiation / forecasts create / forecast close /
    scrap-returns create whenever the call must pass the ownership check.
    """
    return build_user_headers(customer_id, "CustomerPlanner")


def admin():
    return TEST_USERS["platform_admin_headers"]


def manager():
    return TEST_USERS["plant_manager_headers"]


def scheduler():
    return TEST_USERS["line_scheduler_headers"]


def engineer():
    return TEST_USERS["quality_engineer_headers"]
