"""Caller identities for the seven roles of the PRD.

Every role is an opaque operator identifier: the value of X-User-ID is never
compared against any resource identifier. It is recorded on a link as the
installer, the tester or the certifier, and those three recorded values are the
only ones the segregation-of-duties rule ever compares. Tests therefore need
distinct identifiers per role, plus the ability to pair any identifier with any
role header so that a single person acting in two capacities can be expressed.
"""
from typing import Dict, Optional

from prd_bench_local_runner.testing import build_user_headers

from .types import UserRole

# ── Canonical one-identity-per-role operators ──────────────────────────────
PROJECT_MANAGER_ID = "user-pm-01"
DESIGN_ENGINEER_ID = "user-de-01"
INSTALLER_ID = "user-installer-01"
TEST_TECHNICIAN_ID = "user-tester-01"
CERTIFIER_ID = "user-cert-01"
MANUFACTURER_AGENT_ID = "user-mfg-01"
CLIENT_ID = "user-client-01"

# ── Spare identities for multi-operator scenarios ──────────────────────────
SECOND_INSTALLER_ID = "user-installer-02"
SECOND_TEST_TECHNICIAN_ID = "user-tester-02"
SECOND_CERTIFIER_ID = "user-cert-02"
SECOND_PROJECT_MANAGER_ID = "user-pm-02"
SECOND_DESIGN_ENGINEER_ID = "user-de-02"


def headers_for(role: str, user_id: Optional[str] = None) -> Dict[str, str]:
    """Authenticated headers for `role`, defaulting to that role's canonical id."""
    if user_id is None:
        user_id = DEFAULT_USER_IDS[role]
    return build_user_headers(user_id, role)


DEFAULT_USER_IDS: Dict[str, str] = {
    UserRole.PROJECT_MANAGER: PROJECT_MANAGER_ID,
    UserRole.DESIGN_ENGINEER: DESIGN_ENGINEER_ID,
    UserRole.INSTALLER: INSTALLER_ID,
    UserRole.TEST_TECHNICIAN: TEST_TECHNICIAN_ID,
    UserRole.CERTIFIER: CERTIFIER_ID,
    UserRole.MANUFACTURER_AGENT: MANUFACTURER_AGENT_ID,
    UserRole.CLIENT: CLIENT_ID,
}

PM_HEADERS = build_user_headers(PROJECT_MANAGER_ID, UserRole.PROJECT_MANAGER)
DESIGNER_HEADERS = build_user_headers(DESIGN_ENGINEER_ID, UserRole.DESIGN_ENGINEER)
INSTALLER_HEADERS = build_user_headers(INSTALLER_ID, UserRole.INSTALLER)
TESTER_HEADERS = build_user_headers(TEST_TECHNICIAN_ID, UserRole.TEST_TECHNICIAN)
CERTIFIER_HEADERS = build_user_headers(CERTIFIER_ID, UserRole.CERTIFIER)
MANUFACTURER_HEADERS = build_user_headers(
    MANUFACTURER_AGENT_ID, UserRole.MANUFACTURER_AGENT
)
CLIENT_HEADERS = build_user_headers(CLIENT_ID, UserRole.CLIENT)

ROLE_HEADERS: Dict[str, Dict[str, str]] = {
    UserRole.PROJECT_MANAGER: PM_HEADERS,
    UserRole.DESIGN_ENGINEER: DESIGNER_HEADERS,
    UserRole.INSTALLER: INSTALLER_HEADERS,
    UserRole.TEST_TECHNICIAN: TESTER_HEADERS,
    UserRole.CERTIFIER: CERTIFIER_HEADERS,
    UserRole.MANUFACTURER_AGENT: MANUFACTURER_HEADERS,
    UserRole.CLIENT: CLIENT_HEADERS,
}

# ── Unauthenticated header shapes ──────────────────────────────────────────
# A genuinely absent header pair.
NO_AUTH_HEADERS: Dict[str, str] = {"Content-Type": "application/json"}
# Present but empty. The empty string must stay empty: a single space would be a
# non-empty value and would exercise a different branch than intended.
EMPTY_USER_ID_HEADERS: Dict[str, str] = {
    "X-User-ID": "",
    "X-User-Role": UserRole.PROJECT_MANAGER,
    "Content-Type": "application/json",
}
EMPTY_ROLE_HEADERS: Dict[str, str] = {
    "X-User-ID": PROJECT_MANAGER_ID,
    "X-User-Role": "",
    "Content-Type": "application/json",
}
MISSING_USER_ID_HEADERS: Dict[str, str] = {
    "X-User-Role": UserRole.PROJECT_MANAGER,
    "Content-Type": "application/json",
}
MISSING_ROLE_HEADERS: Dict[str, str] = {
    "X-User-ID": PROJECT_MANAGER_ID,
    "Content-Type": "application/json",
}
UNKNOWN_ROLE_HEADERS: Dict[str, str] = build_user_headers(
    PROJECT_MANAGER_ID, "SiteSuperintendent"
)
