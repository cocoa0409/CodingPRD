"""
The five role identities and the header builders that thread ownership.

Three roles are opaque: X-User-ID "need only be present and non-empty, and no
existence check is performed against it", so a fixed constant identifier is
correct for a SystemAdmin, an IntakeClerk and a StateAuditor.

Two roles are entity-backed: a CountyOfficer's X-User-ID is a Representative
id and a VeteranClient's X-User-ID is a Veteran id. For those two, tests must
build headers from the id of the row they actually own, which is what
make_county_officer_headers() and make_veteran_client_headers() are for. The
constants below for those two roles carry identifiers that resolve to nothing
and therefore exist only to exercise ERR_UNKNOWN_ACTOR.
"""

from typing import Dict

from prd_bench_local_runner.testing import NON_EXISTENT_UUID, build_user_headers

from .constants import (
    ROLE_COUNTY_OFFICER,
    ROLE_INTAKE_CLERK,
    ROLE_STATE_AUDITOR,
    ROLE_SYSTEM_ADMIN,
    ROLE_VETERAN_CLIENT,
)

# ─── Opaque operator identifiers ──────────────────────

SYSTEM_ADMIN_ID = "admin-operator-001"
INTAKE_CLERK_ID = "clerk-operator-001"
STATE_AUDITOR_ID = "auditor-operator-001"

SYSTEM_ADMIN_HEADERS = build_user_headers(SYSTEM_ADMIN_ID, ROLE_SYSTEM_ADMIN)
INTAKE_CLERK_HEADERS = build_user_headers(INTAKE_CLERK_ID, ROLE_INTAKE_CLERK)
STATE_AUDITOR_HEADERS = build_user_headers(STATE_AUDITOR_ID, ROLE_STATE_AUDITOR)

# ─── Entity-backed identifiers that resolve to nothing ─

UNRESOLVED_REPRESENTATIVE_ID = NON_EXISTENT_UUID
UNRESOLVED_VETERAN_ID = NON_EXISTENT_UUID

UNKNOWN_COUNTY_OFFICER_HEADERS = build_user_headers(
    UNRESOLVED_REPRESENTATIVE_ID, ROLE_COUNTY_OFFICER
)
UNKNOWN_VETERAN_CLIENT_HEADERS = build_user_headers(
    UNRESOLVED_VETERAN_ID, ROLE_VETERAN_CLIENT
)

TEST_USERS: Dict[str, Dict[str, str]] = {
    "system_admin": SYSTEM_ADMIN_HEADERS,
    "intake_clerk": INTAKE_CLERK_HEADERS,
    "state_auditor": STATE_AUDITOR_HEADERS,
    "unknown_county_officer": UNKNOWN_COUNTY_OFFICER_HEADERS,
    "unknown_veteran_client": UNKNOWN_VETERAN_CLIENT_HEADERS,
}


# ─── Identity builders for the two entity-backed roles ─

def make_county_officer_headers(representative_id: str) -> Dict[str, str]:
    """Headers for a CountyOfficer acting as the named representative."""
    return build_user_headers(representative_id, ROLE_COUNTY_OFFICER)


def make_veteran_client_headers(veteran_id: str) -> Dict[str, str]:
    """Headers for a VeteranClient acting as the named veteran."""
    return build_user_headers(veteran_id, ROLE_VETERAN_CLIENT)


def make_system_admin_headers(user_id: str = SYSTEM_ADMIN_ID) -> Dict[str, str]:
    return build_user_headers(user_id, ROLE_SYSTEM_ADMIN)


def make_intake_clerk_headers(user_id: str = INTAKE_CLERK_ID) -> Dict[str, str]:
    return build_user_headers(user_id, ROLE_INTAKE_CLERK)


def make_state_auditor_headers(user_id: str = STATE_AUDITOR_ID) -> Dict[str, str]:
    return build_user_headers(user_id, ROLE_STATE_AUDITOR)


def make_headers_for_role(role: str, user_id: str) -> Dict[str, str]:
    """Headers for an arbitrary role/id pair, for role-matrix tests."""
    return build_user_headers(user_id, role)


# ─── Malformed header sets ────────────────────────────

def headers_without_user_id(role: str = ROLE_SYSTEM_ADMIN) -> Dict[str, str]:
    """Headers carrying a role but no X-User-ID at all."""
    return {"X-User-Role": role, "Content-Type": "application/json"}


def headers_without_role(user_id: str = SYSTEM_ADMIN_ID) -> Dict[str, str]:
    """Headers carrying an identifier but no X-User-Role at all."""
    return {"X-User-ID": user_id, "Content-Type": "application/json"}


def headers_with_empty_user_id(role: str = ROLE_SYSTEM_ADMIN) -> Dict[str, str]:
    return {"X-User-ID": "", "X-User-Role": role, "Content-Type": "application/json"}


def headers_with_empty_role(user_id: str = SYSTEM_ADMIN_ID) -> Dict[str, str]:
    return {"X-User-ID": user_id, "X-User-Role": "", "Content-Type": "application/json"}


def headers_with_bad_role(
    role_value: str, user_id: str = SYSTEM_ADMIN_ID
) -> Dict[str, str]:
    """Headers whose X-User-Role is not one of the five role names."""
    return build_user_headers(user_id, role_value)


NO_HEADERS: Dict[str, str] = {}

__all__ = [
    "SYSTEM_ADMIN_ID",
    "INTAKE_CLERK_ID",
    "STATE_AUDITOR_ID",
    "SYSTEM_ADMIN_HEADERS",
    "INTAKE_CLERK_HEADERS",
    "STATE_AUDITOR_HEADERS",
    "UNRESOLVED_REPRESENTATIVE_ID",
    "UNRESOLVED_VETERAN_ID",
    "UNKNOWN_COUNTY_OFFICER_HEADERS",
    "UNKNOWN_VETERAN_CLIENT_HEADERS",
    "TEST_USERS",
    "make_county_officer_headers",
    "make_veteran_client_headers",
    "make_system_admin_headers",
    "make_intake_clerk_headers",
    "make_state_auditor_headers",
    "make_headers_for_role",
    "headers_without_user_id",
    "headers_without_role",
    "headers_with_empty_user_id",
    "headers_with_empty_role",
    "headers_with_bad_role",
    "NO_HEADERS",
]
