"""Pre-built role headers for every role in the PRD."""

from prd_bench_local_runner.testing import build_user_headers

# Operator identifiers used across the suite.  All five roles are opaque:
# X-User-ID is an operator string that never needs to match any resource id.
# Distinct ids matter only for the segregation-of-duties comparison between a
# project's submitting analyst and its deciding administrator.
PROGRAM_ADMIN_USER = "admin-1"
PROGRAM_ADMIN_USER_ALT = "admin-2"
REAL_ESTATE_MANAGER_USER = "rem-1"
NETWORK_PLANNER_USER = "np-1"
OPERATIONS_LEAD_USER = "ops-1"
FINANCE_ANALYST_USER = "fa-1"

TEST_USERS = {
    "program_admin_headers": build_user_headers(PROGRAM_ADMIN_USER, "PROGRAM_ADMIN"),
    "real_estate_manager_headers": build_user_headers(
        REAL_ESTATE_MANAGER_USER, "REAL_ESTATE_MANAGER"
    ),
    "network_planner_headers": build_user_headers(NETWORK_PLANNER_USER, "NETWORK_PLANNER"),
    "operations_lead_headers": build_user_headers(OPERATIONS_LEAD_USER, "OPERATIONS_LEAD"),
    "finance_analyst_headers": build_user_headers(FINANCE_ANALYST_USER, "FINANCE_ANALYST"),
}


def make_program_admin_headers(user_id: str = PROGRAM_ADMIN_USER) -> dict:
    return build_user_headers(user_id, "PROGRAM_ADMIN")


def make_real_estate_manager_headers(user_id: str = REAL_ESTATE_MANAGER_USER) -> dict:
    return build_user_headers(user_id, "REAL_ESTATE_MANAGER")


def make_network_planner_headers(user_id: str = NETWORK_PLANNER_USER) -> dict:
    return build_user_headers(user_id, "NETWORK_PLANNER")


def make_operations_lead_headers(user_id: str = OPERATIONS_LEAD_USER) -> dict:
    return build_user_headers(user_id, "OPERATIONS_LEAD")


def make_finance_analyst_headers(user_id: str = FINANCE_ANALYST_USER) -> dict:
    return build_user_headers(user_id, "FINANCE_ANALYST")
