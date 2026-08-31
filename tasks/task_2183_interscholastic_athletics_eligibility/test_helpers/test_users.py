"""Pre-built role headers for every role the service declares."""
from prd_bench_local_runner.testing import build_user_headers

from .constants import (
    ADMIN_USER_ID,
    COORDINATOR_USER_ID,
    MEDICAL_ALT_USER_ID,
    MEDICAL_THIRD_USER_ID,
    MEDICAL_USER_ID,
    REVIEWER_ALT_USER_ID,
    REVIEWER_USER_ID,
)

# Shared constants.  Safe for the opaque roles, and for calls that never reach
# an ownership comparison (bad payloads, unknown resources, list reads).
TEST_USERS = {
    "admin_headers": build_user_headers(ADMIN_USER_ID, "AssociationAdmin"),
    "reviewer_headers": build_user_headers(REVIEWER_USER_ID, "EligibilityReviewer"),
    "reviewer_alt_headers": build_user_headers(REVIEWER_ALT_USER_ID, "EligibilityReviewer"),
    "medical_headers": build_user_headers(MEDICAL_USER_ID, "MedicalOfficer"),
    "medical_alt_headers": build_user_headers(MEDICAL_ALT_USER_ID, "MedicalOfficer"),
    "medical_third_headers": build_user_headers(MEDICAL_THIRD_USER_ID, "MedicalOfficer"),
    "coordinator_headers": build_user_headers(COORDINATOR_USER_ID, "OfficialsCoordinator"),
    # The two school-backed roles and the official-backed role have no useful
    # shared constant for ownership-gated writes; use the builders below.
    "director_headers": build_user_headers("test-director-1", "SchoolAthleticDirector"),
    "registrar_headers": build_user_headers("test-registrar-1", "Registrar"),
    "official_headers": build_user_headers("test-official-1", "Official"),
}


def make_director_headers(school_id: str) -> dict:
    """SchoolAthleticDirector acts for one member school: X-User-ID is the School id."""
    return build_user_headers(school_id, "SchoolAthleticDirector")


def make_registrar_headers(school_id: str) -> dict:
    """Registrar acts for one member school: X-User-ID is the School id."""
    return build_user_headers(school_id, "Registrar")


def make_official_headers(official_id: str) -> dict:
    """Official acts for themselves: X-User-ID is the Official id."""
    return build_user_headers(official_id, "Official")


def make_admin_headers(user_id: str = ADMIN_USER_ID) -> dict:
    return build_user_headers(user_id, "AssociationAdmin")


def make_reviewer_headers(user_id: str = REVIEWER_USER_ID) -> dict:
    return build_user_headers(user_id, "EligibilityReviewer")


def make_medical_headers(user_id: str = MEDICAL_USER_ID) -> dict:
    return build_user_headers(user_id, "MedicalOfficer")


def make_coordinator_headers(user_id: str = COORDINATOR_USER_ID) -> dict:
    return build_user_headers(user_id, "OfficialsCoordinator")
