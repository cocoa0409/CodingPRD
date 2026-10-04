"""Pre-built role headers for every role in the PRD.

Entity-backed roles (OrgAdmin, DeploymentAdmin, ResellerAgent, EndUser) must
thread the backing entity's id through the per-instance builders below whenever
the call is ownership-gated. The shared constants are only safe for calls whose
success does not depend on identity scoping, and for SystemAdmin (opaque).
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    # Opaque role: shared constant is the canonical form.
    "system_admin_headers": build_user_headers("test-system-admin-1", "SystemAdmin"),
    # Entity-backed roles: fallback constants only for non-ownership tests.
    "org_admin_headers": build_user_headers("test-org-admin-1", "OrgAdmin"),
    "deployment_admin_headers": build_user_headers("test-deployment-admin-1", "DeploymentAdmin"),
    "reseller_agent_headers": build_user_headers("test-reseller-agent-1", "ResellerAgent"),
    "end_user_headers": build_user_headers("test-end-user-1", "EndUser"),
}


def make_org_admin_headers(admin_id: str) -> dict:
    """OrgAdmin identity is entity_backed:Admin (SYSTEM_ADMIN or PRODUCT_ADMIN kind).

    Pass the actual Admin.id whenever the call is ownership-gated.
    """
    return build_user_headers(admin_id, "OrgAdmin")


def make_deployment_admin_headers(admin_id: str) -> dict:
    """DeploymentAdmin identity is entity_backed:Admin (DEPLOYMENT_ADMIN kind)."""
    return build_user_headers(admin_id, "DeploymentAdmin")


def make_reseller_agent_headers(reseller_id: str) -> dict:
    """ResellerAgent identity is the Reseller entity itself."""
    return build_user_headers(reseller_id, "ResellerAgent")


def make_end_user_headers(end_user_id: str) -> dict:
    """EndUser identity is the EndUser entity."""
    return build_user_headers(end_user_id, "EndUser")
