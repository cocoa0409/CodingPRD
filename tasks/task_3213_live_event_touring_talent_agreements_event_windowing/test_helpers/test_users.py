"""Pre-built role headers for every role in the PRD (§2.1).

All roles use an opaque operator identifier: the server never compares
X-User-ID against any entity's id for ownership. Medic segregation of duties
compares the cleared_by / evaluator_id strings, which the request bodies carry
directly — so the shared per-role headers below are the canonical form for
every role.
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    "contract_admin_headers": build_user_headers("test-contract-admin-1", "ContractAdmin"),
    "tour_planner_headers": build_user_headers("test-tour-planner-1", "TourPlanner"),
    "talent_relations_headers": build_user_headers("test-talent-relations-1", "TalentRelations"),
    "storyline_editor_headers": build_user_headers("test-storyline-editor-1", "StorylineEditor"),
    "distribution_manager_headers": build_user_headers("test-distribution-manager-1", "DistributionManager"),
    "merch_ops_headers": build_user_headers("test-merch-ops-1", "MerchOps"),
    "medic_headers": build_user_headers("test-medic-1", "Medic"),
    "logistics_coordinator_headers": build_user_headers("test-logistics-coordinator-1", "LogisticsCoordinator"),
}


def make_medic_headers(user_id: str) -> dict:
    """Headers for an individual medic, for segregation-of-duties scenarios
    where the operator identity string matters alongside the body's
    evaluator_id / cleared_by values."""
    return build_user_headers(user_id, "Medic")
