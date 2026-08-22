"""Pre-built role headers.

`SchoolNurse`, `HealthAide` and `Guardian` are entity-backed roles: the acting
`X-User-ID` must be the id of the Nurse (or Student) row the call acts for, so
tests build those headers per instance. `DistrictHealthAdmin`, `SchoolPhysician`
and `RecordsOfficer` carry opaque operator identifiers.
"""

from prd_bench_local_runner.testing import build_user_headers

ADMIN_USER_ID = "dist-admin-01"
PHYSICIAN_USER_ID = "phys-md-01"
PHYSICIAN_USER_ID_ALT = "phys-md-02"
RECORDS_OFFICER_USER_ID = "rec-off-01"
RECORDS_OFFICER_USER_ID_ALT = "rec-off-02"

TEST_USERS = {
    "admin_headers": build_user_headers(ADMIN_USER_ID, "DistrictHealthAdmin"),
    "physician_headers": build_user_headers(PHYSICIAN_USER_ID, "SchoolPhysician"),
    "physician_alt_headers": build_user_headers(PHYSICIAN_USER_ID_ALT, "SchoolPhysician"),
    "records_officer_headers": build_user_headers(RECORDS_OFFICER_USER_ID, "RecordsOfficer"),
    "records_officer_alt_headers": build_user_headers(RECORDS_OFFICER_USER_ID_ALT, "RecordsOfficer"),
    # Fallbacks for tests that never exercise ownership (bad payloads, unknown ids).
    "nurse_headers": build_user_headers("test-nurse-1", "SchoolNurse"),
    "aide_headers": build_user_headers("test-aide-1", "HealthAide"),
    "guardian_headers": build_user_headers("test-guardian-1", "Guardian"),
}


def make_nurse_headers(nurse_id: str) -> dict:
    """Headers for a SchoolNurse; pass the acting Nurse row's id."""
    return build_user_headers(nurse_id, "SchoolNurse")


def make_aide_headers(nurse_id: str) -> dict:
    """Headers for a HealthAide; pass the acting Nurse row's id."""
    return build_user_headers(nurse_id, "HealthAide")


def make_guardian_headers(student_id: str) -> dict:
    """Headers for a Guardian; pass the acting Student row's id."""
    return build_user_headers(student_id, "Guardian")


def make_physician_headers(user_id: str = PHYSICIAN_USER_ID) -> dict:
    return build_user_headers(user_id, "SchoolPhysician")


def make_records_officer_headers(user_id: str = RECORDS_OFFICER_USER_ID) -> dict:
    return build_user_headers(user_id, "RecordsOfficer")


def make_admin_headers(user_id: str = ADMIN_USER_ID) -> dict:
    return build_user_headers(user_id, "DistrictHealthAdmin")
