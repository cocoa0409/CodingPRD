"""Caller identities for the four programme roles.

A ``ProgramAdmin`` or ``RegistryOfficer`` identifier is opaque, so those headers
are fixed constants. A ``Grower`` identifier must be the id of the acting grower
row and a ``Verifier`` identifier the id of the acting verification body, so
those headers are built per scenario from the row the fixture created.

Because several workflows enforce segregation of duties between two distinct
administrator identities, the administrators below are deliberately separate
operators rather than one shared account.
"""

from typing import Dict, Optional

from prd_bench_local_runner.testing import build_user_headers

from .constants import (
    ROLE_GROWER,
    ROLE_PROGRAM_ADMIN,
    ROLE_REGISTRY_OFFICER,
    ROLE_VERIFIER,
)

# Opaque operator identifiers for programme administration staff.
ADMIN_ID = "admin-general-01"
ADMIN_SCREENER_ID = "admin-screener-01"
ADMIN_BASELINE_ID = "admin-baseline-01"
ADMIN_BASELINE_ALT_ID = "admin-baseline-02"
ADMIN_REVERSAL_REPORTER_ID = "admin-reversal-01"
ADMIN_REVERSAL_ASSESSOR_ID = "admin-reversal-02"

# Opaque custodian identifiers for the registry.
REGISTRY_OFFICER_ID = "registry-officer-01"
REGISTRY_OFFICER_ALT_ID = "registry-officer-02"

ADMIN_HEADERS = build_user_headers(ADMIN_ID, ROLE_PROGRAM_ADMIN)
ADMIN_SCREENER_HEADERS = build_user_headers(ADMIN_SCREENER_ID, ROLE_PROGRAM_ADMIN)
ADMIN_BASELINE_HEADERS = build_user_headers(ADMIN_BASELINE_ID, ROLE_PROGRAM_ADMIN)
ADMIN_BASELINE_ALT_HEADERS = build_user_headers(ADMIN_BASELINE_ALT_ID, ROLE_PROGRAM_ADMIN)
ADMIN_REVERSAL_REPORTER_HEADERS = build_user_headers(
    ADMIN_REVERSAL_REPORTER_ID, ROLE_PROGRAM_ADMIN
)
ADMIN_REVERSAL_ASSESSOR_HEADERS = build_user_headers(
    ADMIN_REVERSAL_ASSESSOR_ID, ROLE_PROGRAM_ADMIN
)
REGISTRY_HEADERS = build_user_headers(REGISTRY_OFFICER_ID, ROLE_REGISTRY_OFFICER)
REGISTRY_ALT_HEADERS = build_user_headers(REGISTRY_OFFICER_ALT_ID, ROLE_REGISTRY_OFFICER)

#: The shared identity table, keyed by a short label.
TEST_USERS = {
    "admin": {"id": ADMIN_ID, "role": ROLE_PROGRAM_ADMIN},
    "admin_screener": {"id": ADMIN_SCREENER_ID, "role": ROLE_PROGRAM_ADMIN},
    "admin_baseline": {"id": ADMIN_BASELINE_ID, "role": ROLE_PROGRAM_ADMIN},
    "admin_baseline_alt": {"id": ADMIN_BASELINE_ALT_ID, "role": ROLE_PROGRAM_ADMIN},
    "admin_reversal_reporter": {"id": ADMIN_REVERSAL_REPORTER_ID, "role": ROLE_PROGRAM_ADMIN},
    "admin_reversal_assessor": {"id": ADMIN_REVERSAL_ASSESSOR_ID, "role": ROLE_PROGRAM_ADMIN},
    "registry_officer": {"id": REGISTRY_OFFICER_ID, "role": ROLE_REGISTRY_OFFICER},
    "registry_officer_alt": {"id": REGISTRY_OFFICER_ALT_ID, "role": ROLE_REGISTRY_OFFICER},
}


def grower_headers(grower_id: str) -> Dict[str, str]:
    """Headers for a grower acting on its own records."""
    return build_user_headers(grower_id, ROLE_GROWER)


def verifier_headers(verification_body_id: str) -> Dict[str, str]:
    """Headers for a verification body acting on its own verifications."""
    return build_user_headers(verification_body_id, ROLE_VERIFIER)


def admin_headers(user_id: str = ADMIN_ID) -> Dict[str, str]:
    """Headers for a named programme administration operator."""
    return build_user_headers(user_id, ROLE_PROGRAM_ADMIN)


def registry_headers(user_id: str = REGISTRY_OFFICER_ID) -> Dict[str, str]:
    """Headers for a named registry custodian."""
    return build_user_headers(user_id, ROLE_REGISTRY_OFFICER)


def headers_for(role: str, user_id: str) -> Dict[str, str]:
    """Headers for an arbitrary role/identifier pair."""
    return build_user_headers(user_id, role)


def headers_missing_user_id() -> Dict[str, str]:
    """Headers carrying a role but no caller identifier at all."""
    return {"X-User-Role": ROLE_PROGRAM_ADMIN, "Content-Type": "application/json"}


def headers_missing_role() -> Dict[str, str]:
    """Headers carrying a caller identifier but no role at all."""
    return {"X-User-ID": ADMIN_ID, "Content-Type": "application/json"}


def headers_blank_user_id(role: str = ROLE_PROGRAM_ADMIN) -> Dict[str, str]:
    """Headers whose caller identifier is supplied as an empty string."""
    return {"X-User-ID": "", "X-User-Role": role, "Content-Type": "application/json"}


def headers_blank_role(user_id: str = ADMIN_ID) -> Dict[str, str]:
    """Headers whose role is supplied as an empty string."""
    return {"X-User-ID": user_id, "X-User-Role": "", "Content-Type": "application/json"}


def headers_unknown_role(user_id: str = ADMIN_ID,
                         role: Optional[str] = "SuperAdmin") -> Dict[str, str]:
    """Headers naming a role outside the four declared role names."""
    return {"X-User-ID": user_id, "X-User-Role": role or "", "Content-Type": "application/json"}


NO_HEADERS: Dict[str, str] = {}
