"""Pre-built role headers for every role in the PRD (§2.1).

FacilitySupplyDirector is entity-backed: its X-User-ID must equal the acting
Facility's id on ownership-gated calls, so fixtures MUST use
make_facility_director_headers(facility["id"]) there — never the shared
constant. For the opaque roles the shared constants are fine except where a
segregation-of-duties check is person-keyed (lot created_by, tray
proposed_by); use the per-user builders there too.
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    "admin_headers": build_user_headers("admin-1", "SupplyChainAdmin"),
    "regulatory_headers": build_user_headers("reg-1", "RegulatorySpecialist"),
    "planner_headers": build_user_headers("planner-1", "ManufacturingPlanner"),
    "quality_headers": build_user_headers("qm-1", "QualityManager"),
    "conversion_mgr_headers": build_user_headers("cm-1", "ConversionManager"),
    "clinician_headers": build_user_headers("clin-1", "Clinician"),
    # Fallback only for non-ownership paths (e.g. unauthenticated/role tests).
    "facility_director_headers": build_user_headers("director-1", "FacilitySupplyDirector"),
    "gpo_analyst_headers": build_user_headers("gpo-1", "GPOAnalyst"),
}


def make_admin_headers(user_id: str) -> dict:
    """SupplyChainAdmin (opaque identity); person-keyed for tray SoD checks."""
    return build_user_headers(user_id, "SupplyChainAdmin")


def make_regulatory_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "RegulatorySpecialist")


def make_planner_headers(user_id: str) -> dict:
    """ManufacturingPlanner (opaque); the id lands on lot.created_by."""
    return build_user_headers(user_id, "ManufacturingPlanner")


def make_quality_headers(user_id: str) -> dict:
    """QualityManager (opaque); must differ from a lot's created_by on QA calls."""
    return build_user_headers(user_id, "QualityManager")


def make_conversion_manager_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "ConversionManager")


def make_clinician_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "Clinician")


def make_facility_director_headers(facility_id: str) -> dict:
    """FacilitySupplyDirector (entity-backed by Facility): pass the real
    Facility.id whenever the call is ownership-gated (orders, trays,
    substitution REQUESTs)."""
    return build_user_headers(facility_id, "FacilitySupplyDirector")


def make_gpo_analyst_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "GPOAnalyst")
