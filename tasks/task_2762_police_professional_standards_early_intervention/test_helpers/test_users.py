"""Caller identities for the eight declared roles.

Every request carries an ``X-User-ID`` and an ``X-User-Role`` header. Three
roles are entity-backed: the acting user's identifier is matched against a
stored officer identifier, so a Supervisor, an Investigator and an IACommander
must present the identifier of a real Officer row. Those three therefore get
per-call builders that take the officer identifier the test created. The other
five roles are never matched against a stored row, so a stable opaque
identifier is enough.
"""

from typing import Dict

from prd_bench_local_runner.testing import build_user_headers

from .constants import (
    ROLE_APPEALS_OFFICER,
    ROLE_COMPLAINANT,
    ROLE_IA_COMMANDER,
    ROLE_INVESTIGATOR,
    ROLE_OFFICER_REPRESENTATIVE,
    ROLE_RECORDS_CUSTODIAN,
    ROLE_SUPERVISOR,
    ROLE_SYSTEM_ADMIN,
)

# Opaque identifiers for the roles that are not matched against an Officer row.
TEST_USERS: Dict[str, Dict[str, str]] = {
    "system_admin": {"id": "11111111-1111-4111-8111-111111111111", "role": ROLE_SYSTEM_ADMIN},
    "complainant": {"id": "22222222-2222-4222-8222-222222222222", "role": ROLE_COMPLAINANT},
    "appeals_officer": {"id": "33333333-3333-4333-8333-333333333333", "role": ROLE_APPEALS_OFFICER},
    "officer_representative": {
        "id": "44444444-4444-4444-8444-444444444444",
        "role": ROLE_OFFICER_REPRESENTATIVE,
    },
    "records_custodian": {"id": "55555555-5555-4555-8555-555555555555", "role": ROLE_RECORDS_CUSTODIAN},
}

# Ready-made header dicts for the opaque roles.
SYSTEM_ADMIN_HEADERS = build_user_headers(TEST_USERS["system_admin"]["id"], ROLE_SYSTEM_ADMIN)
COMPLAINANT_HEADERS = build_user_headers(TEST_USERS["complainant"]["id"], ROLE_COMPLAINANT)
APPEALS_OFFICER_HEADERS = build_user_headers(TEST_USERS["appeals_officer"]["id"], ROLE_APPEALS_OFFICER)
OFFICER_REPRESENTATIVE_HEADERS = build_user_headers(
    TEST_USERS["officer_representative"]["id"], ROLE_OFFICER_REPRESENTATIVE
)
RECORDS_CUSTODIAN_HEADERS = build_user_headers(
    TEST_USERS["records_custodian"]["id"], ROLE_RECORDS_CUSTODIAN
)


# ── Entity-backed roles ────────────────────────────────────────────────────

def make_supervisor_headers(officer_id: str) -> Dict[str, str]:
    """Headers for a Supervisor acting as the officer with this identifier."""
    return build_user_headers(officer_id, ROLE_SUPERVISOR)


def make_investigator_headers(officer_id: str) -> Dict[str, str]:
    """Headers for an Investigator acting as the officer with this identifier."""
    return build_user_headers(officer_id, ROLE_INVESTIGATOR)


def make_ia_commander_headers(officer_id: str) -> Dict[str, str]:
    """Headers for an IACommander acting as the officer with this identifier."""
    return build_user_headers(officer_id, ROLE_IA_COMMANDER)


def make_complainant_headers(user_id: str = None) -> Dict[str, str]:
    """Headers for a Complainant; authority is proven by the intake code, not the id."""
    return build_user_headers(user_id or TEST_USERS["complainant"]["id"], ROLE_COMPLAINANT)


# ── Malformed credentials, for the header-presence and role-authorization tiers ──

def headers_without_role(user_id: str) -> Dict[str, str]:
    """Headers that omit X-User-Role entirely."""
    return {"X-User-ID": user_id, "Content-Type": "application/json"}


def headers_without_user_id(role: str) -> Dict[str, str]:
    """Headers that omit X-User-ID entirely."""
    return {"X-User-Role": role, "Content-Type": "application/json"}


def headers_with_empty_role(user_id: str) -> Dict[str, str]:
    """Headers whose X-User-Role is present but empty."""
    return {"X-User-ID": user_id, "X-User-Role": "", "Content-Type": "application/json"}


# A syntactically valid header value that names no declared role.
UNDECLARED_ROLE = "DeputyChief"


def headers_with_undeclared_role(user_id: str) -> Dict[str, str]:
    """Headers naming a role the contract does not declare."""
    return build_user_headers(user_id, UNDECLARED_ROLE)
