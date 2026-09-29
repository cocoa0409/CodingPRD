"""Pre-built role headers for every role named in the PRD.

`ProgramAdmin`, `EnforcementOfficer`, `StateDataSteward` and `TrainingOfficer`
carry an opaque identity, so the shared constant is their canonical form.
`Inspector`, `DeconTechnician` and `ReleaseVerifier` resolve `X-User-ID` to an
inspector row, so every ownership-, certification- or standing-gated call MUST
use the per-instance builder with the real inspector id.
"""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for opaque roles and for tests that never touch an
# ownership, certification or standing gate.
TEST_USERS = {
    "program_admin_headers": build_user_headers("admin-1", "ProgramAdmin"),
    "enforcement_officer_headers": build_user_headers("eo-1", "EnforcementOfficer"),
    "state_data_steward_headers": build_user_headers("sds-1", "StateDataSteward"),
    "training_officer_headers": build_user_headers("to-1", "TrainingOfficer"),
    # Entity-backed roles: fallback only, the id resolves to no inspector row.
    "inspector_headers": build_user_headers("insp-unresolvable-1", "Inspector"),
    "decon_technician_headers": build_user_headers("tech-unresolvable-1", "DeconTechnician"),
    "release_verifier_headers": build_user_headers("verif-unresolvable-1", "ReleaseVerifier"),
}

PROGRAM_ADMIN = TEST_USERS["program_admin_headers"]
ENFORCEMENT_OFFICER = TEST_USERS["enforcement_officer_headers"]
STATE_DATA_STEWARD = TEST_USERS["state_data_steward_headers"]
TRAINING_OFFICER = TEST_USERS["training_officer_headers"]


def make_program_admin_headers(user_id: str = "admin-1") -> dict:
    """ProgramAdmin carries an opaque identity; any non-empty id is accepted."""
    return build_user_headers(user_id, "ProgramAdmin")


def make_enforcement_officer_headers(user_id: str = "eo-1") -> dict:
    """EnforcementOfficer carries an opaque identity."""
    return build_user_headers(user_id, "EnforcementOfficer")


def make_state_data_steward_headers(user_id: str = "sds-1") -> dict:
    """StateDataSteward carries an opaque identity."""
    return build_user_headers(user_id, "StateDataSteward")


def make_training_officer_headers(user_id: str = "to-1") -> dict:
    """TrainingOfficer carries an opaque identity."""
    return build_user_headers(user_id, "TrainingOfficer")


def make_inspector_headers(inspector_id: str) -> dict:
    """Inspector resolves X-User-ID to an inspector row: pass the real id."""
    return build_user_headers(inspector_id, "Inspector")


def make_decon_technician_headers(inspector_id: str) -> dict:
    """DeconTechnician resolves X-User-ID to an inspector row."""
    return build_user_headers(inspector_id, "DeconTechnician")


def make_release_verifier_headers(inspector_id: str) -> dict:
    """ReleaseVerifier resolves X-User-ID to an inspector row."""
    return build_user_headers(inspector_id, "ReleaseVerifier")


def raw_headers(user_id, role) -> dict:
    """Build a header dict verbatim, including empty-string values.

    Used by the authentication tests that must transmit an empty
    `X-User-ID` or `X-User-Role`; a single space would be rejected by the
    HTTP client before it ever reached the server.
    """
    headers = {"Content-Type": "application/json"}
    if user_id is not None:
        headers["X-User-ID"] = user_id
    if role is not None:
        headers["X-User-Role"] = role
    return headers


ROLE_HEADER_BUILDERS = {
    "ProgramAdmin": make_program_admin_headers,
    "Inspector": make_inspector_headers,
    "DeconTechnician": make_decon_technician_headers,
    "ReleaseVerifier": make_release_verifier_headers,
    "EnforcementOfficer": make_enforcement_officer_headers,
    "StateDataSteward": make_state_data_steward_headers,
    "TrainingOfficer": make_training_officer_headers,
}
