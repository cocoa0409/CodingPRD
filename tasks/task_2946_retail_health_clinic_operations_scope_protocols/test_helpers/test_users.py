"""Pre-built role headers for the five roles the PRD recognizes.

`ClinicAdmin` and `FrontDeskAgent` are opaque operator identities, so a shared
constant is always correct for them. `Clinician`, `CollaboratingPhysician` and
`Patient` are entity-backed: their `X-User-ID` must resolve to a persisted row,
so any call that resolves identity or checks ownership has to use the
`make_*_headers(<row id>)` builders below with the real row id.
"""
from prd_bench_local_runner.testing import build_user_headers

from .constants import (
    ROLE_CLINIC_ADMIN,
    ROLE_CLINICIAN,
    ROLE_COLLABORATING_PHYSICIAN,
    ROLE_FRONT_DESK_AGENT,
    ROLE_PATIENT,
)

TEST_USERS = {
    # Opaque roles — never compared against any entity id.
    "admin_headers": build_user_headers("test-admin-1", ROLE_CLINIC_ADMIN),
    "front_desk_headers": build_user_headers("test-frontdesk-1", ROLE_FRONT_DESK_AGENT),
    # Entity-backed roles — these shared constants carry unresolvable ids and are
    # only for tests that deliberately probe identity resolution.
    "clinician_headers": build_user_headers("test-clinician-1", ROLE_CLINICIAN),
    "physician_headers": build_user_headers("test-physician-1", ROLE_COLLABORATING_PHYSICIAN),
    "patient_headers": build_user_headers("test-patient-1", ROLE_PATIENT),
}


def make_admin_headers(user_id: str = "test-admin-1") -> dict:
    """ClinicAdmin is opaque; the id is recorded but never resolved."""
    return build_user_headers(user_id, ROLE_CLINIC_ADMIN)


def make_front_desk_headers(user_id: str = "test-frontdesk-1") -> dict:
    """FrontDeskAgent is opaque; the id is recorded but never resolved."""
    return build_user_headers(user_id, ROLE_FRONT_DESK_AGENT)


def make_clinician_headers(clinician_id: str) -> dict:
    """Pass the acting Clinician.id — ownership compares it to the row's
    clinician reference."""
    return build_user_headers(clinician_id, ROLE_CLINICIAN)


def make_physician_headers(physician_id: str) -> dict:
    """Pass the acting Physician.id — ownership compares it to the row's
    physician reference."""
    return build_user_headers(physician_id, ROLE_COLLABORATING_PHYSICIAN)


def make_patient_headers(patient_id: str) -> dict:
    """Pass the acting Patient.id — ownership compares it to the row's patient
    reference."""
    return build_user_headers(patient_id, ROLE_PATIENT)


def make_headers(user_id: str, role: str) -> dict:
    """Arbitrary (id, role) pair, for role-matrix probes."""
    return build_user_headers(user_id, role)


def headers_without_user_id(role: str) -> dict:
    """Headers with X-User-ID genuinely omitted."""
    return {"X-User-Role": role, "Content-Type": "application/json"}


def headers_without_role(user_id: str = "test-admin-1") -> dict:
    """Headers with X-User-Role genuinely omitted."""
    return {"X-User-ID": user_id, "Content-Type": "application/json"}


def headers_with_empty_user_id(role: str) -> dict:
    """X-User-ID present but empty — a real empty string, never whitespace."""
    return {"X-User-ID": "", "X-User-Role": role, "Content-Type": "application/json"}


def headers_with_empty_role(user_id: str = "test-admin-1") -> dict:
    """X-User-Role present but empty — a real empty string, never whitespace."""
    return {"X-User-ID": user_id, "X-User-Role": "", "Content-Type": "application/json"}
