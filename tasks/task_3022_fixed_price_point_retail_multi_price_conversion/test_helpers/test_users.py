"""Role header sets for every role the PRD declares.

No role in this API is entity-backed: ``X-User-ID`` is an opaque operator
identifier that is never resolved against a persisted row and never used in an
ownership comparison. Shared constants are therefore safe for every call.
"""

from prd_bench_local_runner.testing import build_user_headers

# Stable opaque operator identifiers, one per role.
USER_CONTEXT = {
    "MerchandiseBuyer": "buyer-marguerite",
    "StoreOperationsManager": "som-raoul",
    "ImportCoordinator": "ic-priya",
    "DistributionCenterOperator": "dco-tomas",
    "ResetCalendarPlanner": "rcp-helena",
    "MerchandiseAnalyst": "analyst-yusuf",
    "LegalCostEngineer": "lce-dana",
    "PlatformAdmin": "admin-harness",
}


def headers_for(role: str, user_id: str = None) -> dict:
    """Build a header set for a role, optionally overriding the opaque operator id."""
    return build_user_headers(user_id or USER_CONTEXT[role], role)


TEST_USERS = {
    "merchandise_buyer_headers": headers_for("MerchandiseBuyer"),
    "store_operations_manager_headers": headers_for("StoreOperationsManager"),
    "import_coordinator_headers": headers_for("ImportCoordinator"),
    "distribution_center_operator_headers": headers_for("DistributionCenterOperator"),
    "reset_calendar_planner_headers": headers_for("ResetCalendarPlanner"),
    "merchandise_analyst_headers": headers_for("MerchandiseAnalyst"),
    "legal_cost_engineer_headers": headers_for("LegalCostEngineer"),
    "platform_admin_headers": headers_for("PlatformAdmin"),
}

# Convenience aliases used across the suite.
BUYER_HEADERS = TEST_USERS["merchandise_buyer_headers"]
SOM_HEADERS = TEST_USERS["store_operations_manager_headers"]
IMPORT_HEADERS = TEST_USERS["import_coordinator_headers"]
DCO_HEADERS = TEST_USERS["distribution_center_operator_headers"]
PLANNER_HEADERS = TEST_USERS["reset_calendar_planner_headers"]
ANALYST_HEADERS = TEST_USERS["merchandise_analyst_headers"]
LEGAL_HEADERS = TEST_USERS["legal_cost_engineer_headers"]
ADMIN_HEADERS = TEST_USERS["platform_admin_headers"]