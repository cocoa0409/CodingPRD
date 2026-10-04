"""Pre-built role headers for the seven PRD roles (PRD §2.1).

Every role's X-User-ID is an opaque operator identifier: the server never
compares it to any entity's id, but segregation-of-duties rules compare the
caller's X-User-ID against recorded provenance fields (chemistry_recorded_by,
bake_recorded_by, last_breach_reading_recorded_by). Tests exercising those
rules must therefore control the user id explicitly — use the per-role
make_*_headers(user_id) builders. The shared TEST_USERS constants are for
calls whose outcome does not depend on the caller's identity.

Default user ids are distinct across roles so the happy path never trips a
segregation check accidentally.
"""
from prd_bench_local_runner.testing import build_user_headers

# Canonical opaque user ids (never equal to any entity id).
FOUNDRY_MANAGER_USER = "fm-1"
MELT_OPERATOR_USER = "op-1"
QUALITY_INSPECTOR_USER = "qi-1"
SEASONING_LEAD_USER = "sl-1"
ENVIRONMENTAL_OFFICER_USER = "eo-1"
# Second officer: certify-remediation must come from an X-User-ID different
# from the officer whose reading/reclaim entry caused the breach.
ENVIRONMENTAL_OFFICER_2_USER = "eo-2"
RETAIL_PLANNER_USER = "rp-1"
OUTLET_MANAGER_USER = "om-1"

TEST_USERS = {
    "foundry_manager_headers": build_user_headers(FOUNDRY_MANAGER_USER, "FoundryManager"),
    "melt_operator_headers": build_user_headers(MELT_OPERATOR_USER, "MeltOperator"),
    "quality_inspector_headers": build_user_headers(QUALITY_INSPECTOR_USER, "QualityInspector"),
    "seasoning_lead_headers": build_user_headers(SEASONING_LEAD_USER, "SeasoningLead"),
    "environmental_officer_headers": build_user_headers(ENVIRONMENTAL_OFFICER_USER,
                                                        "EnvironmentalOfficer"),
    "environmental_officer_2_headers": build_user_headers(ENVIRONMENTAL_OFFICER_2_USER,
                                                          "EnvironmentalOfficer"),
    "retail_planner_headers": build_user_headers(RETAIL_PLANNER_USER, "RetailPlanner"),
    "outlet_manager_headers": build_user_headers(OUTLET_MANAGER_USER, "OutletManager"),
}


def make_foundry_manager_headers(user_id: str = FOUNDRY_MANAGER_USER) -> dict:
    return build_user_headers(user_id, "FoundryManager")


def make_melt_operator_headers(user_id: str = MELT_OPERATOR_USER) -> dict:
    return build_user_headers(user_id, "MeltOperator")


def make_quality_inspector_headers(user_id: str = QUALITY_INSPECTOR_USER) -> dict:
    return build_user_headers(user_id, "QualityInspector")


def make_seasoning_lead_headers(user_id: str = SEASONING_LEAD_USER) -> dict:
    return build_user_headers(user_id, "SeasoningLead")


def make_environmental_officer_headers(user_id: str = ENVIRONMENTAL_OFFICER_USER) -> dict:
    return build_user_headers(user_id, "EnvironmentalOfficer")


def make_retail_planner_headers(user_id: str = RETAIL_PLANNER_USER) -> dict:
    return build_user_headers(user_id, "RetailPlanner")


def make_outlet_manager_headers(user_id: str = OUTLET_MANAGER_USER) -> dict:
    return build_user_headers(user_id, "OutletManager")


def make_headers(user_id: str, role: str) -> dict:
    """Build headers for an arbitrary (user_id, role) pair — e.g. an inspector
    reusing the recording operator's id to trigger ERR_SEGREGATION_OF_DUTIES."""
    return build_user_headers(user_id, role)
