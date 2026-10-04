"""Pre-built role headers for every role in the PRD.

Six roles are opaque operator identities; ``PartnerOps`` is the one
entity-backed role, whose ``X-User-ID`` must be the acting ``PartnerAccount.id``.
All endpoints sit under the ``/accelerators`` prefix.
"""
from prd_bench_local_runner.testing import build_user_headers

API_PREFIX = "/accelerators"

TEST_USERS = {
    "platform_admin_headers": build_user_headers("test-platform-admin-1", "PlatformAdmin"),
    "supply_planner_headers": build_user_headers("test-supply-planner-1", "SupplyPlanner"),
    "partner_program_manager_headers": build_user_headers(
        "test-partner-program-manager-1", "PartnerProgramManager"
    ),
    "support_account_manager_headers": build_user_headers(
        "test-support-account-manager-1", "SupportAccountManager"
    ),
    # A second SupportAccountManager identity. The separation-of-duties gate
    # (PRD 3.7) refuses a termination whose X-User-ID matches the deployment's
    # activation actor, so a test that intends a *valid* termination after a
    # rotation must hand over and terminate under a different operator id.
    "support_account_manager_2_headers": build_user_headers(
        "test-support-account-manager-2", "SupportAccountManager"
    ),
    "supply_compliance_officer_headers": build_user_headers(
        "test-supply-compliance-officer-1", "SupplyComplianceOfficer"
    ),
    "lifecycle_program_manager_headers": build_user_headers(
        "test-lifecycle-program-manager-1", "LifecycleProgramManager"
    ),
    # entity_backed role: the shared constant is a fallback for non-ownership calls only.
    "partner_ops_headers": build_user_headers("test-partner-ops-1", "PartnerOps"),
}


def make_partner_ops_headers(partner_id: str) -> dict:
    """For PartnerOps (entity_backed:PartnerAccount). Pass the actual
    PartnerAccount.id as ``partner_id`` whenever the call is ownership-gated."""
    return build_user_headers(partner_id, "PartnerOps")