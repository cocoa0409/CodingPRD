"""Pre-built role headers for every role in the PRD.

All eleven roles carry opaque X-User-ID values (PRD section 2.1): no role's
X-User-ID is the id of any persisted entity. The single shape exception is
Licensor, whose X-User-ID must exactly equal the licensed line's
licensor_user_id string (itself an opaque identifier chosen at line
creation) — so the per-instance builder make_licensor_headers() MUST be
called with the line's licensor_user_id whenever a licensor-side action is
exercised.
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    "admin_headers": build_user_headers("admin-1", "PlatformAdmin"),
    "sourcing_headers": build_user_headers("sm-1", "SourcingManager"),
    "qa_headers": build_user_headers("qa-1", "QualityAssurance"),
    "qa2_headers": build_user_headers("qa-2", "QualityAssurance"),
    "formulator_headers": build_user_headers("f-1", "Formulator"),
    "formulator2_headers": build_user_headers("f-2", "Formulator"),
    "safety_headers": build_user_headers("so-1", "SafetyOfficer"),
    "lab_headers": build_user_headers("lab-1", "LabTechnician"),
    "brand_headers": build_user_headers("bm-1", "BrandManager"),
    "brand2_headers": build_user_headers("bm-2", "BrandManager"),
    "planner_headers": build_user_headers("ap-1", "AllocationPlanner"),
    "boxoffice_headers": build_user_headers("bo-1", "BoxOffice"),
    "consumer_headers": build_user_headers("voter-1", "Consumer"),
}


def make_admin_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "PlatformAdmin")


def make_sourcing_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "SourcingManager")


def make_qa_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "QualityAssurance")


def make_formulator_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "Formulator")


def make_safety_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "SafetyOfficer")


def make_lab_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "LabTechnician")


def make_brand_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "BrandManager")


def make_licensor_headers(licensor_user_id: str) -> dict:
    """Licensor X-User-ID must equal the line's licensor_user_id."""
    return build_user_headers(licensor_user_id, "Licensor")


def make_planner_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "AllocationPlanner")


def make_boxoffice_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "BoxOffice")


def make_consumer_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "Consumer")
