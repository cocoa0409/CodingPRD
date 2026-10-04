"""Pre-built role headers for every role in the PRD.

AdvisorOps is entity_backed:Advisor, so its shared constant is only a fallback
for calls that are not ownership-gated. Every ownership-gated call must use
make_advisor_ops_headers(advisor_id) with the real Advisor.id.
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    # Opaque roles — the shared constant is the canonical form.
    "platform_admin_headers": build_user_headers("test-platform-admin-1", "PlatformAdmin"),
    "branch_manager_headers": build_user_headers("test-branch-manager-1", "BranchManager"),
    "compliance_officer_headers": build_user_headers(
        "test-compliance-officer-1", "ComplianceOfficer"),
    # entity_backed:Advisor — fallback for non-ownership-gated calls only.
    "advisor_ops_headers": build_user_headers("test-advisor-ops-1", "AdvisorOps"),
}


def make_advisor_ops_headers(advisor_id: str) -> dict:
    """For AdvisorOps (entity_backed:Advisor). Pass the acting Advisor.id."""
    return build_user_headers(advisor_id, "AdvisorOps")