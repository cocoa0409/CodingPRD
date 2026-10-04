"""Pre-built role headers for every role in the PRD.

All five roles are opaque operator identities (PRD §2.1): X-User-ID is never
compared against any entity's id, so shared constants are sufficient for all
ownership checks (there are none).
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    "network_planner_headers": build_user_headers("planner-1", "NetworkPlanner"),
    "ops_controller_headers": build_user_headers("ops-1", "OpsController"),
    "crew_scheduler_headers": build_user_headers("crew-1", "CrewScheduler"),
    "customer_service_headers": build_user_headers("cs-1", "CustomerService"),
    "finance_analyst_headers": build_user_headers("fin-1", "FinanceAnalyst"),
}

# Anonymous / malformed context: no headers at all.
ANONYMOUS_HEADERS: dict = {}


def make_network_planner_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "NetworkPlanner")


def make_ops_controller_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "OpsController")


def make_crew_scheduler_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "CrewScheduler")


def make_customer_service_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "CustomerService")


def make_finance_analyst_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "FinanceAnalyst")
