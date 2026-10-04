"""Pre-built role headers for every role in the PRD."""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for opaque roles, and for tests that don't exercise
# BuilderContact ownership. BuilderContact is entity-backed: any
# ownership-gated call MUST use make_builder_contact_headers(builder_id).
TEST_USERS = {
    "ops_admin_headers": build_user_headers("test-ops-admin-1", "OpsAdmin"),
    "mill_planner_headers": build_user_headers("test-mill-planner-1", "MillPlanner"),
    "branch_manager_headers": build_user_headers(
        "test-branch-manager-1", "BranchManager"
    ),
    "credit_manager_headers": build_user_headers(
        "test-credit-manager-1", "CreditManager"
    ),
    "account_manager_headers": build_user_headers(
        "test-account-manager-1", "AccountManager"
    ),
    "fleet_coordinator_headers": build_user_headers(
        "test-fleet-coordinator-1", "FleetCoordinator"
    ),
    # Fallback only for non-ownership contexts; never for take-off writes.
    "builder_contact_headers": build_user_headers(
        "test-builder-contact-1", "BuilderContact"
    ),
}


def make_builder_contact_headers(builder_id: str) -> dict:
    """For BuilderContact (entity-backed by Builder). Pass the actual
    Builder.id as user_id whenever the call is ownership-gated (take-off
    create, revise, accept)."""
    return build_user_headers(builder_id, "BuilderContact")
