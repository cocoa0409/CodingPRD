"""Pre-built role headers for every role in the PRD (§2.1).

Identity semantics per PRD §2.1:
- CompanyAdmin, RouteOpsManager, CreditAnalyst: X-User-ID is an opaque operator
  identifier, never compared to any entity id. The shared constants below are
  the canonical form for these roles.
- Distributor: X-User-ID IS the acting Distributor entity's id (entity-backed).
  Ownership-gated calls MUST use make_distributor_headers(distributor["id"]) —
  the shared "distributor_headers" constant is only a fallback for tests whose
  outcome does not depend on ownership (e.g. 400-on-bad-payload probes).
"""
from prd_bench_local_runner.testing import build_user_headers

from .types import UserRole

TEST_USERS = {
    "company_admin_headers": build_user_headers(
        "test-company-admin-1", UserRole.COMPANY_ADMIN.value
    ),
    "route_ops_manager_headers": build_user_headers(
        "test-route-ops-1", UserRole.ROUTE_OPS_MANAGER.value
    ),
    "credit_analyst_headers": build_user_headers(
        "test-credit-analyst-1", UserRole.CREDIT_ANALYST.value
    ),
    # Fallback only: never equals a real Distributor.id, so any ownership-gated
    # call made with these headers would be rejected with ERR_NOT_RESOURCE_OWNER.
    "distributor_headers": build_user_headers(
        "test-distributor-1", UserRole.DISTRIBUTOR.value
    ),
}


def make_distributor_headers(user_id: str) -> dict:
    """Headers for the Distributor role. Per PRD §2.1 the X-User-ID must equal
    the acting Distributor entity's id, so pass distributor["id"] whenever the
    call is ownership-gated (orders, claims, deliveries, own-id reads, own
    financing payments, own retail accounts)."""
    return build_user_headers(user_id, UserRole.DISTRIBUTOR.value)


def make_company_admin_headers(user_id: str = "test-company-admin-1") -> dict:
    return build_user_headers(user_id, UserRole.COMPANY_ADMIN.value)


def make_route_ops_manager_headers(user_id: str = "test-route-ops-1") -> dict:
    return build_user_headers(user_id, UserRole.ROUTE_OPS_MANAGER.value)


def make_credit_analyst_headers(user_id: str = "test-credit-analyst-1") -> dict:
    return build_user_headers(user_id, UserRole.CREDIT_ANALYST.value)
