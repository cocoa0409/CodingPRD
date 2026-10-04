"""Pre-built role headers for every role in the PRD."""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for opaque roles and for tests that don't exercise
# entity-backed ownership.
TEST_USERS = {
    # opaque roles
    "admin_headers": build_user_headers("pa-1", "ProgramAdmin"),
    "admin2_headers": build_user_headers("pa-2", "ProgramAdmin"),
    "house_manager_headers": build_user_headers("hm-1", "HouseManager"),
    "house_manager2_headers": build_user_headers("hm-2", "HouseManager"),
    "volunteer_coordinator_headers": build_user_headers("vc-1", "VolunteerCoordinator"),
    # entity-backed roles: fallback constants for non-ownership tests only.
    "hospital_referrer_headers": build_user_headers("test-hospital-1", "HospitalReferrer"),
    "family_contact_headers": build_user_headers("test-family-1", "FamilyContact"),
}


def make_hospital_referrer_headers(hospital_id: str) -> dict:
    """HospitalReferrer is entity-backed by Hospital: pass the Hospital.id."""
    return build_user_headers(hospital_id, "HospitalReferrer")


def make_family_contact_headers(family_id: str) -> dict:
    """FamilyContact is entity-backed by Family: pass the Family.id."""
    return build_user_headers(family_id, "FamilyContact")
