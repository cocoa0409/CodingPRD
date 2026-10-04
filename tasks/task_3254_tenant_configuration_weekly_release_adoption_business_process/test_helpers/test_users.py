"""Pre-built role headers and per-instance builders for every role in the PRD.

Identity semantics (PRD §2.1): TenantAdministrator, ImplementationPartner and
Approver are entity-backed — X-User-ID must be the acting Worker's id whenever
the call is ownership- or segregation-gated. PlatformOperator and
IntegrationDeveloper use opaque operator identifiers.
"""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for opaque roles and for calls that are not
# ownership-gated (e.g. RBAC-denial probes).
TEST_USERS = {
    "platform_operator_headers": build_user_headers("operator-1", "PlatformOperator"),
    "integration_developer_headers": build_user_headers("intdev-1", "IntegrationDeveloper"),
    # Fallbacks for entity-backed roles in non-ownership contexts only.
    "tenant_admin_headers": build_user_headers("test-admin-1", "TenantAdministrator"),
    "implementation_partner_headers": build_user_headers("test-partner-1", "ImplementationPartner"),
    "approver_headers": build_user_headers("test-approver-1", "Approver"),
}


def make_platform_operator_headers(user_id: str = "operator-1") -> dict:
    """PlatformOperator (opaque identity)."""
    return build_user_headers(user_id, "PlatformOperator")


def make_integration_developer_headers(user_id: str = "intdev-1") -> dict:
    """IntegrationDeveloper (opaque identity)."""
    return build_user_headers(user_id, "IntegrationDeveloper")


def make_tenant_admin_headers(user_id: str) -> dict:
    """TenantAdministrator (entity-backed:Worker). Pass the acting Worker's id
    whenever the call is ownership- or segregation-gated — e.g. the tenant's
    bootstrap_admin_worker_id for administration, or a specific worker id when
    initiating transactions."""
    return build_user_headers(user_id, "TenantAdministrator")


def make_implementation_partner_headers(user_id: str) -> dict:
    """ImplementationPartner (entity-backed:Worker)."""
    return build_user_headers(user_id, "ImplementationPartner")


def make_approver_headers(user_id: str) -> dict:
    """Approver (entity-backed:Worker). Pass the acting Worker's id; approver
    membership and segregation checks compare it against group membership and
    the transaction's initiator_worker_id."""
    return build_user_headers(user_id, "Approver")
