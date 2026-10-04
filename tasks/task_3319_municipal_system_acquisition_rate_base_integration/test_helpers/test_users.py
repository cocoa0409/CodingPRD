"""Pre-built role headers for every role in the PRD.

All roles in this domain are opaque: X-User-ID is a free operator identifier
never compared to any persisted entity id (PRD §2.1).
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    "analyst_headers": build_user_headers("analyst-1", "AcquisitionAnalyst"),
    "analyst2_headers": build_user_headers("analyst-2", "AcquisitionAnalyst"),
    "reviewer_headers": build_user_headers("reviewer-1", "EngineeringReviewer"),
    "appraiser_headers": build_user_headers("appraiser-1", "Appraiser"),
    "appraiser2_headers": build_user_headers("appraiser-2", "Appraiser"),
    "clerk_headers": build_user_headers("clerk-1", "MunicipalClerk"),
    "reg_officer_headers": build_user_headers("regofficer-1", "RegulatoryOfficer"),
    "commissioner_headers": build_user_headers("commissioner-1", "Commissioner"),
    "transition_mgr_headers": build_user_headers("tm-1", "TransitionManager"),
    "hr_headers": build_user_headers("hr-1", "HRDirector"),
    "sysadmin_headers": build_user_headers("sysadmin-1", "SystemAdmin"),
}


def make_headers(user_id: str, role: str) -> dict:
    """Build headers for a specific operator id under a declared role."""
    return build_user_headers(user_id, role)


def make_analyst_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "AcquisitionAnalyst")


def make_reviewer_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "EngineeringReviewer")


def make_appraiser_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "Appraiser")


def make_clerk_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "MunicipalClerk")


def make_reg_officer_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "RegulatoryOfficer")


def make_commissioner_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "Commissioner")


def make_transition_mgr_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "TransitionManager")


def make_hr_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "HRDirector")


def make_sysadmin_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "SystemAdmin")
