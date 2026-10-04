"""Pre-built role headers for every role in the PRD."""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for opaque roles, and for entity-backed roles only in
# tests that do not exercise ownership checks.
TEST_USERS = {
    # entity_backed:Advisor — fallback for non-ownership tests only.
    "advisor_headers": build_user_headers("test-advisor-1", "Advisor"),
    # entity_backed:BranchOfficeAdministrator — fallback for non-ownership tests only.
    "branch_administrator_headers": build_user_headers("test-boa-1", "BranchAdministrator"),
    # opaque roles — canonical form.
    "home_office_admin_headers": build_user_headers("test-hoa-1", "HomeOfficeAdmin"),
    "compliance_principal_headers": build_user_headers("test-cp-1", "CompliancePrincipal"),
}


def make_advisor_headers(user_id: str) -> dict:
    """For Advisor (entity-backed on Advisor.id). Pass the actual Advisor.id as
    user_id whenever the call is ownership-gated."""
    return build_user_headers(user_id, "Advisor")


def make_branch_administrator_headers(user_id: str) -> dict:
    """For BranchAdministrator (entity-backed on BranchOfficeAdministrator.id).
    Pass the actual BranchOfficeAdministrator.id as user_id whenever the call is
    ownership-gated."""
    return build_user_headers(user_id, "BranchAdministrator")
