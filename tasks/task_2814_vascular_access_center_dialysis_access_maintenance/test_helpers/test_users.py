"""Pre-built role headers for the six roles the PRD recognises.

``CenterAdmin`` and ``AccessCoordinator`` carry opaque identifiers, so the shared
constants below are the canonical form for them.

``FacilityCoordinator`` carries a ``DialysisFacility.id``; ``Interventionalist``,
``SedationRN`` and ``Coder`` each carry a ``Clinician.id``.  Any call that is
ownership-gated (facility scope, assigned-clinician, attestation identity,
segregation of duties) MUST be made with the corresponding
``make_<role>_headers(<real entity id>)`` builder -- never with the shared
constant, whose identifier matches no row.
"""

from typing import Dict

from prd_bench_local_runner.testing import build_user_headers

CENTER_ADMIN = "CenterAdmin"
ACCESS_COORDINATOR = "AccessCoordinator"
FACILITY_COORDINATOR = "FacilityCoordinator"
INTERVENTIONALIST = "Interventionalist"
SEDATION_RN = "SedationRN"
CODER = "Coder"

ALL_ROLES = [
    CENTER_ADMIN,
    ACCESS_COORDINATOR,
    FACILITY_COORDINATOR,
    INTERVENTIONALIST,
    SEDATION_RN,
    CODER,
]

# Shared constants.  Safe for the two opaque roles, and for tests whose success
# does not depend on the caller owning the subject row (bad payloads, unknown
# ids, plain authorization refusals).
TEST_USERS: Dict[str, Dict[str, str]] = {
    "center_admin_headers": build_user_headers("test-center-admin-1", CENTER_ADMIN),
    "access_coordinator_headers": build_user_headers(
        "test-access-coordinator-1", ACCESS_COORDINATOR
    ),
    "facility_coordinator_headers": build_user_headers(
        "test-facility-coordinator-1", FACILITY_COORDINATOR
    ),
    "interventionalist_headers": build_user_headers(
        "test-interventionalist-1", INTERVENTIONALIST
    ),
    "sedation_rn_headers": build_user_headers("test-sedation-rn-1", SEDATION_RN),
    "coder_headers": build_user_headers("test-coder-1", CODER),
}


def make_center_admin_headers(user_id: str = "test-center-admin-1") -> Dict[str, str]:
    """CenterAdmin identifiers are opaque; the value is never matched against a row."""
    return build_user_headers(user_id, CENTER_ADMIN)


def make_access_coordinator_headers(
    user_id: str = "test-access-coordinator-1",
) -> Dict[str, str]:
    """AccessCoordinator identifiers are opaque; the value is never matched against a row."""
    return build_user_headers(user_id, ACCESS_COORDINATOR)


def make_facility_coordinator_headers(facility_id: str) -> Dict[str, str]:
    """FacilityCoordinator: pass the acting DialysisFacility.id as X-User-ID."""
    return build_user_headers(facility_id, FACILITY_COORDINATOR)


def make_interventionalist_headers(clinician_id: str) -> Dict[str, str]:
    """Interventionalist: pass the acting Clinician.id (clinician_role INTERVENTIONALIST)."""
    return build_user_headers(clinician_id, INTERVENTIONALIST)


def make_sedation_rn_headers(clinician_id: str) -> Dict[str, str]:
    """SedationRN: pass the acting Clinician.id (clinician_role SEDATION_RN)."""
    return build_user_headers(clinician_id, SEDATION_RN)


def make_coder_headers(clinician_id: str) -> Dict[str, str]:
    """Coder: pass the acting Clinician.id (clinician_role CODER)."""
    return build_user_headers(clinician_id, CODER)


ADMIN = TEST_USERS["center_admin_headers"]
COORDINATOR = TEST_USERS["access_coordinator_headers"]
