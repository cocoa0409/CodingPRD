"""Pre-built role headers for every role in the PRD (§2.1).

DepartmentManager is entity-backed by Department: ownership-gated calls
MUST use make_department_manager_headers(department_id) with the real
Department.id. The shared constant exists only for non-ownership tests.
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    # Opaque roles — shared constants are the canonical form.
    "comp_admin_headers": build_user_headers("test-admin-1", "CompAdmin"),
    "comp_analyst_headers": build_user_headers("test-analyst-1", "CompAnalyst"),
    "comp_manager_headers": build_user_headers("test-cm-1", "CompManager"),
    "comp_manager_2_headers": build_user_headers("test-cm-2", "CompManager"),
    "hrbp_headers": build_user_headers("test-hrbp-1", "HRBP"),
    "finance_partner_headers": build_user_headers("test-fin-1", "FinancePartner"),
    # Entity-backed role: fallback constant ONLY for tests that do not
    # exercise ownership (e.g. RBAC rejection before ownership is reached).
    "department_manager_headers": build_user_headers("test-dept-mgr-1", "DepartmentManager"),
}


def make_department_manager_headers(department_id: str) -> dict:
    """DepartmentManager is entity-backed by Department. Pass the actual
    Department.id whenever the call is ownership-gated (mapping decision
    create/submit/resubmit/withdraw, exception request create/resubmit)."""
    return build_user_headers(department_id, "DepartmentManager")
