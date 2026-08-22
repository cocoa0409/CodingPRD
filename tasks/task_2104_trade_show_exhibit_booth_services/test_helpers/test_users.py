"""Pre-built role headers for every role the PRD recognises."""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants. Safe for the four opaque roles, and for entity-backed roles
# only in tests that do not exercise an ownership check.
TEST_USERS = {
    "show_operations_headers": build_user_headers("ops-1", "ShowOperations"),
    "show_operations_alt_headers": build_user_headers("ops-2", "ShowOperations"),
    "labor_supervisor_headers": build_user_headers("lab-1", "LaborSupervisor"),
    "claims_adjuster_headers": build_user_headers("adj-1", "ClaimsAdjuster"),
    "claims_adjuster_alt_headers": build_user_headers("adj-2", "ClaimsAdjuster"),
    "finance_controller_headers": build_user_headers("fin-1", "FinanceController"),
    "finance_controller_alt_headers": build_user_headers("fin-2", "FinanceController"),
    # Entity-backed roles: these shared constants never match a real row id, so
    # they are only for tests that stop before the ownership check.
    "exhibitor_headers": build_user_headers("test-exhibitor-1", "Exhibitor"),
    "warehouse_agent_headers": build_user_headers("test-warehouse-1", "WarehouseAgent"),
}


def make_exhibitor_headers(exhibitor_id: str) -> dict:
    """For the Exhibitor role, whose X-User-ID is the acting Exhibitor row's id.
    Pass the real exhibitor id whenever the call is ownership-gated."""
    return build_user_headers(exhibitor_id, "Exhibitor")


def make_warehouse_agent_headers(warehouse_id: str) -> dict:
    """For the WarehouseAgent role, whose X-User-ID is the id of the Warehouse
    the agent staffs. Pass the real warehouse id on warehouse-scoped writes."""
    return build_user_headers(warehouse_id, "WarehouseAgent")


def make_show_operations_headers(user_id: str = "ops-1") -> dict:
    return build_user_headers(user_id, "ShowOperations")


def make_labor_supervisor_headers(user_id: str = "lab-1") -> dict:
    return build_user_headers(user_id, "LaborSupervisor")


def make_claims_adjuster_headers(user_id: str = "adj-1") -> dict:
    return build_user_headers(user_id, "ClaimsAdjuster")


def make_finance_controller_headers(user_id: str = "fin-1") -> dict:
    return build_user_headers(user_id, "FinanceController")
