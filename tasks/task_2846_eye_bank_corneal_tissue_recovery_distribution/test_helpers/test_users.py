"""
Identity threading for the six roles.

Three roles are opaque -- ``EyeBankCoordinator``, ``LabTechnician`` and
``MedicalDirector`` -- so a fixed operator identifier is enough for them and the
shared header dictionaries below can be reused by every test.

Three roles are entity-backed: ``RecoveryTechnician`` and ``EvaluationTechnician``
carry a ``Technician`` row id in ``X-User-ID`` and ``Surgeon`` carries a ``Surgeon``
row id. Those identifiers only exist once the corresponding row has been created, so
tests must build the headers per-request with the ``make_*_headers`` builders.
"""

from prd_bench_local_runner.testing import build_user_headers

from .constants import (
    ROLE_COORDINATOR,
    ROLE_EVALUATION_TECHNICIAN,
    ROLE_LAB_TECHNICIAN,
    ROLE_MEDICAL_DIRECTOR,
    ROLE_RECOVERY_TECHNICIAN,
    ROLE_SURGEON,
)

# ---------------------------------------------------------------------------
# Opaque operator identifiers
# ---------------------------------------------------------------------------
COORDINATOR_USER_ID = "op-coordinator-2846"
COORDINATOR_USER_ID_ALT = "op-coordinator-2846-alt"
LAB_TECHNICIAN_USER_ID = "op-lab-2846"
MEDICAL_DIRECTOR_USER_ID = "op-director-2846"
MEDICAL_DIRECTOR_USER_ID_ALT = "op-director-2846-alt"

COORDINATOR_HEADERS = build_user_headers(COORDINATOR_USER_ID, ROLE_COORDINATOR)
COORDINATOR_HEADERS_ALT = build_user_headers(COORDINATOR_USER_ID_ALT, ROLE_COORDINATOR)
LAB_TECHNICIAN_HEADERS = build_user_headers(LAB_TECHNICIAN_USER_ID, ROLE_LAB_TECHNICIAN)
MEDICAL_DIRECTOR_HEADERS = build_user_headers(
    MEDICAL_DIRECTOR_USER_ID, ROLE_MEDICAL_DIRECTOR
)
MEDICAL_DIRECTOR_HEADERS_ALT = build_user_headers(
    MEDICAL_DIRECTOR_USER_ID_ALT, ROLE_MEDICAL_DIRECTOR
)

# ---------------------------------------------------------------------------
# Entity-backed header builders
# ---------------------------------------------------------------------------


def make_recovery_technician_headers(technician_id):
    """Headers for a ``RecoveryTechnician`` acting as the given Technician row."""
    return build_user_headers(str(technician_id), ROLE_RECOVERY_TECHNICIAN)


def make_evaluation_technician_headers(technician_id):
    """Headers for an ``EvaluationTechnician`` acting as the given Technician row."""
    return build_user_headers(str(technician_id), ROLE_EVALUATION_TECHNICIAN)


def make_surgeon_headers(surgeon_id):
    """Headers for a ``Surgeon`` acting as the given Surgeon row."""
    return build_user_headers(str(surgeon_id), ROLE_SURGEON)


def make_coordinator_headers(user_id=COORDINATOR_USER_ID):
    """Headers for an opaque ``EyeBankCoordinator`` operator."""
    return build_user_headers(str(user_id), ROLE_COORDINATOR)


def make_lab_technician_headers(user_id=LAB_TECHNICIAN_USER_ID):
    """Headers for an opaque ``LabTechnician`` operator."""
    return build_user_headers(str(user_id), ROLE_LAB_TECHNICIAN)


def make_medical_director_headers(user_id=MEDICAL_DIRECTOR_USER_ID):
    """Headers for an opaque ``MedicalDirector`` operator."""
    return build_user_headers(str(user_id), ROLE_MEDICAL_DIRECTOR)


def make_headers(role, user_id):
    """Headers for an arbitrary (role, user id) pair."""
    return build_user_headers(str(user_id), role)


# ---------------------------------------------------------------------------
# Shared registry used by role-matrix probes
# ---------------------------------------------------------------------------
TEST_USERS = {
    ROLE_COORDINATOR: {
        "user_id": COORDINATOR_USER_ID,
        "role": ROLE_COORDINATOR,
        "headers": COORDINATOR_HEADERS,
        "entity_backed": False,
    },
    ROLE_LAB_TECHNICIAN: {
        "user_id": LAB_TECHNICIAN_USER_ID,
        "role": ROLE_LAB_TECHNICIAN,
        "headers": LAB_TECHNICIAN_HEADERS,
        "entity_backed": False,
    },
    ROLE_MEDICAL_DIRECTOR: {
        "user_id": MEDICAL_DIRECTOR_USER_ID,
        "role": ROLE_MEDICAL_DIRECTOR,
        "headers": MEDICAL_DIRECTOR_HEADERS,
        "entity_backed": False,
    },
    ROLE_RECOVERY_TECHNICIAN: {
        "user_id": None,
        "role": ROLE_RECOVERY_TECHNICIAN,
        "headers": None,
        "entity_backed": True,
        "builder": make_recovery_technician_headers,
    },
    ROLE_EVALUATION_TECHNICIAN: {
        "user_id": None,
        "role": ROLE_EVALUATION_TECHNICIAN,
        "headers": None,
        "entity_backed": True,
        "builder": make_evaluation_technician_headers,
    },
    ROLE_SURGEON: {
        "user_id": None,
        "role": ROLE_SURGEON,
        "headers": None,
        "entity_backed": True,
        "builder": make_surgeon_headers,
    },
}

# Headers with no X-User-ID / X-User-Role at all.
NO_AUTH_HEADERS = {"Content-Type": "application/json"}
MISSING_ROLE_HEADERS = {
    "X-User-ID": COORDINATOR_USER_ID,
    "Content-Type": "application/json",
}
MISSING_USER_ID_HEADERS = {
    "X-User-Role": ROLE_COORDINATOR,
    "Content-Type": "application/json",
}
INVALID_ROLE_HEADERS = build_user_headers(COORDINATOR_USER_ID, "SuperAdmin")


__all__ = [
    "COORDINATOR_USER_ID",
    "COORDINATOR_USER_ID_ALT",
    "LAB_TECHNICIAN_USER_ID",
    "MEDICAL_DIRECTOR_USER_ID",
    "MEDICAL_DIRECTOR_USER_ID_ALT",
    "COORDINATOR_HEADERS",
    "COORDINATOR_HEADERS_ALT",
    "LAB_TECHNICIAN_HEADERS",
    "MEDICAL_DIRECTOR_HEADERS",
    "MEDICAL_DIRECTOR_HEADERS_ALT",
    "make_recovery_technician_headers",
    "make_evaluation_technician_headers",
    "make_surgeon_headers",
    "make_coordinator_headers",
    "make_lab_technician_headers",
    "make_medical_director_headers",
    "make_headers",
    "TEST_USERS",
    "NO_AUTH_HEADERS",
    "MISSING_ROLE_HEADERS",
    "MISSING_USER_ID_HEADERS",
    "INVALID_ROLE_HEADERS",
]
