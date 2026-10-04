"""Pre-built role headers for every role in the PRD (§2.1).

All seven operational roles have opaque identities: X-User-ID is never compared
against an entity id, but it IS compared against accountability fields in the
four-eyes (verify) and segregation-of-duties (disposition) checks. Tests
exercising those checks therefore need several DISTINCT, stable identities per
role — hence both the shared constants below and the per-instance builders.
"""
from prd_bench_local_runner.testing import build_user_headers

# Canonical stable user ids, reused across fixtures and tests so that
# accountability fields (manufactured_by_user_id, recorded_by_user_id,
# verified_by_user_id, opened_by_user_id, closed_by_user_id) are predictable.
USER_IDS = {
    "admin": "admin-1",
    "engineer": "pe-1",
    "operator": "op-1",
    "operator_2": "op-9",
    "analyst": "qc-1",
    "analyst_2": "qc-2",
    "reviewer": "qa-1",
    "reviewer_2": "qa-2",
    "reviewer_3": "qa-3",
    "planner": "sp-1",
    "regulatory": "ra-1",
}

TEST_USERS = {
    "platform_admin_headers": build_user_headers(USER_IDS["admin"], "PlatformAdmin"),
    "process_engineer_headers": build_user_headers(USER_IDS["engineer"], "ProcessEngineer"),
    "manufacturing_operator_headers": build_user_headers(USER_IDS["operator"], "ManufacturingOperator"),
    "manufacturing_operator_2_headers": build_user_headers(USER_IDS["operator_2"], "ManufacturingOperator"),
    "quality_control_analyst_headers": build_user_headers(USER_IDS["analyst"], "QualityControlAnalyst"),
    "quality_control_analyst_2_headers": build_user_headers(USER_IDS["analyst_2"], "QualityControlAnalyst"),
    "quality_assurance_reviewer_headers": build_user_headers(USER_IDS["reviewer"], "QualityAssuranceReviewer"),
    "quality_assurance_reviewer_2_headers": build_user_headers(USER_IDS["reviewer_2"], "QualityAssuranceReviewer"),
    "quality_assurance_reviewer_3_headers": build_user_headers(USER_IDS["reviewer_3"], "QualityAssuranceReviewer"),
    "supply_planner_headers": build_user_headers(USER_IDS["planner"], "SupplyPlanner"),
    "regulatory_affairs_specialist_headers": build_user_headers(USER_IDS["regulatory"], "RegulatoryAffairsSpecialist"),
}

# Requests sent with these headers omit X-User-ID / X-User-Role entirely
# (authentication-context rejection tests).
NO_AUTH_HEADERS = {"Content-Type": "application/json"}


# Per-instance builders — use whenever a test needs a caller identity that is
# distinct from (or, for negative checks, identical to) a recorded
# accountability id such as manufactured_by_user_id or recorded_by_user_id.
def make_platform_admin_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "PlatformAdmin")


def make_process_engineer_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "ProcessEngineer")


def make_manufacturing_operator_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "ManufacturingOperator")


def make_quality_control_analyst_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "QualityControlAnalyst")


def make_quality_assurance_reviewer_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "QualityAssuranceReviewer")


def make_supply_planner_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "SupplyPlanner")


def make_regulatory_affairs_specialist_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "RegulatoryAffairsSpecialist")
