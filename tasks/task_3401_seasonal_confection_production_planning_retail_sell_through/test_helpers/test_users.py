"""Pre-built role headers for the six declared roles (PRD §2.1).

Role spellings are exact wire values. Retailer is entity-backed by
RetailerAccount: ownership checks compare the resource's retailer_id to
X-User-ID, so any ownership-gated call MUST use make_retailer_headers() with
the real account id. The shared "retailer_headers" entry is a fallback only
for tests that never exercise ownership (e.g. 400/404 paths).

Disposition segregation of duties (PRD §3.9) requires the approving
CategoryManager to be a DIFFERENT user than the proposer, so two distinct
CategoryManager identities are provided: cm-alice (proposer) and cm-bob
(approver).
"""
from prd_bench_local_runner.testing import build_user_headers

from .types import UserRole

# CategoryManager operator identifiers recorded on disposition orders
# (proposed_by_user_id / approved_by_user_id, PRD §2.1 and §3.9).
CM_ALICE_USER_ID = "cm-alice"
CM_BOB_USER_ID = "cm-bob"

TEST_USERS = {
    # Opaque roles (PRD §2.1): X-User-ID is not tied to any persisted entity.
    "platform_admin_headers": build_user_headers("pa-admin-1", UserRole.PLATFORM_ADMIN.value),
    "production_planner_headers": build_user_headers("pp-planner-1", UserRole.PRODUCTION_PLANNER.value),
    "category_manager_headers": build_user_headers(CM_ALICE_USER_ID, UserRole.CATEGORY_MANAGER.value),
    "category_manager_b_headers": build_user_headers(CM_BOB_USER_ID, UserRole.CATEGORY_MANAGER.value),
    "logistics_coordinator_headers": build_user_headers("lc-logistics-1", UserRole.LOGISTICS_COORDINATOR.value),
    "claims_adjuster_headers": build_user_headers("ca-adjuster-1", UserRole.CLAIMS_ADJUSTER.value),
    # Entity-backed role fallback — safe ONLY for tests that do not exercise
    # ownership (bad-payload 400s, not-found 404s, role-denial 403s). Any
    # ownership-gated call must use make_retailer_headers(account["id"]).
    "retailer_headers": build_user_headers("retailer-unlinked-1", UserRole.RETAILER.value),
}


def make_retailer_headers(retailer_account_id: str) -> dict:
    """Headers for the entity-backed Retailer role (PRD §2.1).

    Pass the acting RetailerAccount's id: ownership checks on commitment
    create/submit/revise/reorder/cancel, heat-claim provide-info, and
    sell-through report create compare retailer_id to X-User-ID.
    """
    return build_user_headers(retailer_account_id, UserRole.RETAILER.value)


def make_category_manager_headers(user_id: str) -> dict:
    """Headers for an arbitrary CategoryManager operator (segregation tests)."""
    return build_user_headers(user_id, UserRole.CATEGORY_MANAGER.value)


def make_platform_admin_headers(user_id: str) -> dict:
    """Headers for an arbitrary PlatformAdmin operator."""
    return build_user_headers(user_id, UserRole.PLATFORM_ADMIN.value)


def make_production_planner_headers(user_id: str) -> dict:
    """Headers for an arbitrary ProductionPlanner operator."""
    return build_user_headers(user_id, UserRole.PRODUCTION_PLANNER.value)


def make_logistics_coordinator_headers(user_id: str) -> dict:
    """Headers for an arbitrary LogisticsCoordinator operator."""
    return build_user_headers(user_id, UserRole.LOGISTICS_COORDINATOR.value)


def make_claims_adjuster_headers(user_id: str) -> dict:
    """Headers for an arbitrary ClaimsAdjuster operator."""
    return build_user_headers(user_id, UserRole.CLAIMS_ADJUSTER.value)
