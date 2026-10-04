"""Pre-built role headers for every role in PRD §2.1.

Shared constants are for tests whose success does not depend on a specific
caller identity. Per-instance builders are mandatory wherever identity matters:
ShopOperator is entity-backed by ScoopShop (X-User-ID must equal the shop id),
and segregation-of-duties tests need explicit auditor/verifier/board ids.
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    "sourcing_manager_headers": build_user_headers("test-sourcing-1", "SourcingManager"),
    "sustainability_auditor_headers": build_user_headers("test-auditor-1", "SustainabilityAuditor"),
    "audit_verifier_headers": build_user_headers("test-verifier-1", "AuditVerifier"),
    "dairy_program_manager_headers": build_user_headers("test-dairy-1", "DairyProgramManager"),
    "flavor_manager_headers": build_user_headers("test-flavor-1", "FlavorManager"),
    "plant_scheduler_headers": build_user_headers("test-plant-1", "PlantScheduler"),
    "independent_board_member_headers": build_user_headers("test-board-1", "IndependentBoardMember"),
    "parent_ops_controller_headers": build_user_headers("test-ops-1", "ParentOpsController"),
    "franchise_admin_headers": build_user_headers("test-franchise-1", "FranchiseAdmin"),
    # entity_backed: fallback only for non-ownership tests; prefer the builder.
    "shop_operator_headers": build_user_headers("test-shop-op-1", "ShopOperator"),
    "fan_headers": build_user_headers("test-fan-1", "Fan"),
}


def make_sourcing_manager_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "SourcingManager")


def make_sustainability_auditor_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "SustainabilityAuditor")


def make_audit_verifier_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "AuditVerifier")


def make_dairy_program_manager_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "DairyProgramManager")


def make_flavor_manager_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "FlavorManager")


def make_plant_scheduler_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "PlantScheduler")


def make_independent_board_member_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "IndependentBoardMember")


def make_parent_ops_controller_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "ParentOpsController")


def make_franchise_admin_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "FranchiseAdmin")


def make_shop_operator_headers(shop_id: str) -> dict:
    """ShopOperator is entity-backed: X-User-ID must equal the ScoopShop id."""
    return build_user_headers(shop_id, "ShopOperator")


def make_fan_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "Fan")
