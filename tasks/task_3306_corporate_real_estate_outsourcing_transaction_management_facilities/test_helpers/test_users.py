"""Pre-built role headers for every role in the PRD (§2.1).

Two roles are entity-backed and their X-User-ID must be the id of a real
persisted entity when a call is ownership-gated:

* AccountExecutive -> X-User-ID is the id of the acting PortfolioAccount.
* ApprovalAuthority -> X-User-ID is the id of the acting AccountAssignment.

The remaining six roles supply an opaque operator identifier.
"""
from prd_bench_local_runner.testing import build_user_headers


TEST_USERS = {
    # entity_backed:PortfolioAccount — the shared constant is a fallback for
    # tests that do not exercise ownership; ownership-gated calls must use
    # make_account_executive_headers(account["id"]).
    "account_executive_headers": build_user_headers("test-ae-1", "AccountExecutive"),
    # entity_backed:AccountAssignment — ownership-gated decisions must use
    # make_approval_authority_headers(assignment["id"]).
    "approval_authority_headers": build_user_headers("test-auth-1", "ApprovalAuthority"),
    # opaque roles — the shared constant is the canonical form.
    "transaction_manager_headers": build_user_headers("test-tm-1", "TransactionManager"),
    "facilities_manager_headers": build_user_headers("test-fm-1", "FacilitiesManager"),
    "occupancy_planner_headers": build_user_headers("test-op-1", "OccupancyPlanner"),
    "governance_manager_headers": build_user_headers("test-gm-1", "GovernanceManager"),
    "data_steward_headers": build_user_headers("test-ds-1", "DataSteward"),
    "transition_manager_headers": build_user_headers("test-trans-1", "TransitionManager"),
}

# A request carrying no role at all (PRD §2.1: absent role -> ERR_UNAUTHENTICATED).
ANONYMOUS_HEADERS = {"X-User-ID": "anonymous-principal", "Content-Type": "application/json"}


def make_account_executive_headers(account_id: str) -> dict:
    """For AccountExecutive (entity_backed:PortfolioAccount).

    Pass the actual PortfolioAccount.id whenever the call is ownership-gated.
    """
    return build_user_headers(account_id, "AccountExecutive")


def make_approval_authority_headers(assignment_id: str) -> dict:
    """For ApprovalAuthority (entity_backed:AccountAssignment).

    Pass the actual AccountAssignment.id whenever the decision is ownership-gated.
    """
    return build_user_headers(assignment_id, "ApprovalAuthority")