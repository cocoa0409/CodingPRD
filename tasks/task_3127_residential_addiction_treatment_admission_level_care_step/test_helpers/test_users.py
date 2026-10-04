"""Pre-built role headers for the seven roles of PRD §2.1.

Only ``Clinician`` is entity-backed: its ``X-User-ID`` must be a real
``Clinician.id`` and ownership checks compare a resource's clinician foreign key
to that value. Ownership-gated calls must therefore use :func:`make_clinician_headers`
with the actual clinician id, never the shared constant. Every other role is an
opaque operator whose identifier is not looked up, so a shared constant is the
canonical form for those.
"""

from prd_bench_local_runner.testing import build_user_headers

# Opaque operator identifiers.
PLATFORM_ADMIN_ID = "admin-ops-1"
CLINICAL_DIRECTOR_ID = "cd-ray"
UTILIZATION_REVIEWER_ID = "ur-dana"
ALUMNI_COORDINATOR_ID = "alum-nia"
INTAKE_NURSE_ID = "intake-nurse-1"


TEST_USERS = {
    "platform_admin_headers": build_user_headers(PLATFORM_ADMIN_ID, "PlatformAdmin"),
    "clinical_director_headers": build_user_headers(CLINICAL_DIRECTOR_ID, "ClinicalDirector"),
    "utilization_reviewer_headers": build_user_headers(
        UTILIZATION_REVIEWER_ID, "UtilizationReviewer"
    ),
    "intake_nurse_headers": build_user_headers(INTAKE_NURSE_ID, "AdmissionsIntakeNurse"),
    "alumni_coordinator_headers": build_user_headers(ALUMNI_COORDINATOR_ID, "AlumniCoordinator"),
    "read_headers": build_user_headers(UTILIZATION_REVIEWER_ID, "Any"),
    # Entity-backed role: this constant is only valid for tests that
    # deliberately act as a clinician that does not exist.
    "unknown_clinician_headers": build_user_headers(
        "00000000-0000-0000-0000-000000000000", "Clinician"
    ),
}


def make_clinician_headers(clinician_id: str) -> dict:
    """Headers for a ``Clinician`` caller; ``clinician_id`` must be a real ``Clinician.id``."""
    return build_user_headers(clinician_id, "Clinician")


def make_platform_admin_headers(user_id: str = PLATFORM_ADMIN_ID) -> dict:
    """Headers for a ``PlatformAdmin`` caller (opaque identifier, never looked up)."""
    return build_user_headers(user_id, "PlatformAdmin")


def make_clinical_director_headers(user_id: str = CLINICAL_DIRECTOR_ID) -> dict:
    """Headers for a ``ClinicalDirector`` caller (opaque identifier)."""
    return build_user_headers(user_id, "ClinicalDirector")


def make_utilization_reviewer_headers(user_id: str = UTILIZATION_REVIEWER_ID) -> dict:
    """Headers for a ``UtilizationReviewer`` caller (opaque identifier)."""
    return build_user_headers(user_id, "UtilizationReviewer")


def make_intake_nurse_headers(user_id: str = INTAKE_NURSE_ID) -> dict:
    """Headers for an ``AdmissionsIntakeNurse`` caller (opaque identifier)."""
    return build_user_headers(user_id, "AdmissionsIntakeNurse")


def make_alumni_coordinator_headers(user_id: str = ALUMNI_COORDINATOR_ID) -> dict:
    """Headers for an ``AlumniCoordinator`` caller (opaque identifier)."""
    return build_user_headers(user_id, "AlumniCoordinator")


def make_read_headers(user_id: str = UTILIZATION_REVIEWER_ID) -> dict:
    """Headers for an ``Any`` caller (read surface only)."""
    return build_user_headers(user_id, "Any")


def make_headers(user_id: str, role: str) -> dict:
    """Headers for an arbitrary role string, including undeclared ones."""
    return build_user_headers(user_id, role)


PLATFORM_ADMIN_HEADERS = TEST_USERS["platform_admin_headers"]
CLINICAL_DIRECTOR_HEADERS = TEST_USERS["clinical_director_headers"]
UTILIZATION_REVIEWER_HEADERS = TEST_USERS["utilization_reviewer_headers"]
INTAKE_NURSE_HEADERS = TEST_USERS["intake_nurse_headers"]
ALUMNI_COORDINATOR_HEADERS = TEST_USERS["alumni_coordinator_headers"]
READ_HEADERS = TEST_USERS["read_headers"]
