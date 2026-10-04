"""Pre-built role headers for the six declared acting roles (PRD 2.1).

Two forms are emitted per role:

* a shared-contract entry in ``TEST_USERS`` used only by requests whose success
  does not depend on the caller owning the subject resource, and
* a per-instance builder ``make_<role>_headers(user_id)`` for the entity-backed
  roles, so fixtures can thread the actual ``User.id`` into the header when the
  downstream call is ownership-gated.
"""

from prd_bench_local_runner.testing import build_user_headers


def _headers(user_id: str, role: str) -> dict:
    """Build the acting headers, falling back to a plain two-header dict.

    Some framework versions of ``build_user_headers`` ship a fixed
    ``TEST_USERS`` mapping that carries no ``Counselor`` (or other entity-backed)
    entry and raise ``KeyError`` for it. The PRD's six-member role set of §2.1 is
    the contract this suite tests against, so a missing framework constant must
    never deny the suite an acting Counselor identity.
    """
    try:
        return build_user_headers(user_id, role)
    except KeyError:
        return {"X-User-ID": user_id, "X-User-Role": role}


# Shared constants. Safe for opaque roles and for calls that do not exercise
# ownership (bad-payload 400s, missing-resource 404s, role-denial 403s).
TEST_USERS = {
    "program_admin_headers": _headers("test-admin-operator-1", "ProgramAdministrator"),
    "physician_headers": _headers("test-physician-1", "Physician"),
    "nurse_headers": _headers("test-nurse-1", "Nurse"),
    "counselor_headers": _headers("test-counselor-1", "Counselor"),
    "medical_director_headers": _headers("test-director-1", "MedicalDirector"),
    "regulatory_auditor_headers": _headers("test-auditor-1", "RegulatoryAuditor"),
}


def make_program_admin_headers(user_id: str = "test-admin-operator-1") -> dict:
    """ProgramAdministrator carries an opaque operator identifier."""
    return _headers(user_id, "ProgramAdministrator")


def make_physician_headers(user_id: str) -> dict:
    """Physician (entity-backed). Pass the acting Physician User.id whenever the
    call is ownership-gated (diagnosis confirmation, dose orders, exceptions)."""
    return _headers(user_id, "Physician")


def make_nurse_headers(user_id: str) -> dict:
    """Nurse (entity-backed). Pass the acting Nurse User.id for the whole
    observed-dose pipeline and inbound guest acknowledgements."""
    return _headers(user_id, "Nurse")


def make_counselor_headers(user_id: str) -> dict:
    """Counselor (entity-backed). Pass the acting Counselor User.id."""
    return _headers(user_id, "Counselor")


def make_medical_director_headers(user_id: str) -> dict:
    """MedicalDirector (entity-backed). Pass the acting MedicalDirector User.id
    for privilege, exception and reinstatement operations."""
    return _headers(user_id, "MedicalDirector")


def make_regulatory_auditor_headers(user_id: str) -> dict:
    """RegulatoryAuditor (entity-backed). Pass the acting auditor User.id."""
    return _headers(user_id, "RegulatoryAuditor")