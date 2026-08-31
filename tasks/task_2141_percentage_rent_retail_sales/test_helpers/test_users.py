"""Pre-built request headers for every role the PRD declares.

Four of the five roles carry an opaque operator identifier that the server
never compares to a persisted entity's id, so a shared constant is safe.
A `TenantUser` is different: its `X-User-ID` is the id of the acting Tenant,
so any ownership-gated call must build its headers from the real tenant id
through `make_tenant_headers()`.
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    "center_admin_headers": build_user_headers("ca-operator-1", "CenterAdmin"),
    "lease_administrator_headers": build_user_headers(
        "la-operator-1", "LeaseAdministrator"),
    "auditor_headers": build_user_headers("auditor-1", "Auditor"),
    "ownership_analyst_headers": build_user_headers(
        "analyst-1", "OwnershipAnalyst"),
    # Shared fallback for tenant-role calls whose success does not depend on
    # owning the subject resource (401/403/404 paths and plain reads).
    "tenant_user_headers": build_user_headers("tenant-operator-1", "TenantUser"),
}

CENTER_ADMIN = TEST_USERS["center_admin_headers"]
LEASE_ADMIN = TEST_USERS["lease_administrator_headers"]
AUDITOR = TEST_USERS["auditor_headers"]
OWNERSHIP_ANALYST = TEST_USERS["ownership_analyst_headers"]
TENANT_USER = TEST_USERS["tenant_user_headers"]


def make_tenant_headers(tenant_id: str) -> dict:
    """Headers for the tenant of record: X-User-ID is the Tenant's own id."""
    return build_user_headers(tenant_id, "TenantUser")


def make_center_admin_headers(user_id: str) -> dict:
    """Headers for a named owner-side administrator.

    Used where the identity itself matters — relief approval and the
    kick-out waiver's same-administrator rule.
    """
    return build_user_headers(user_id, "CenterAdmin")


def make_lease_administrator_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "LeaseAdministrator")


def make_auditor_headers(user_id: str) -> dict:
    """Headers for a named auditor; the id is recorded as auditor_user_id."""
    return build_user_headers(user_id, "Auditor")


def make_headers(user_id: str, role: str) -> dict:
    """Arbitrary identity/role pair, including roles the service rejects."""
    return build_user_headers(user_id, role)


__all__ = [
    "TEST_USERS", "CENTER_ADMIN", "LEASE_ADMIN", "AUDITOR",
    "OWNERSHIP_ANALYST", "TENANT_USER", "make_tenant_headers",
    "make_center_admin_headers", "make_lease_administrator_headers",
    "make_auditor_headers", "make_headers",
]
