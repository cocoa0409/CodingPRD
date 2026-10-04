"""Caller identities for the six declared roles.

Every request carries an ``X-User-ID`` and an ``X-User-Role`` header. One role
is entity-backed: when the role is ``Member``, the identifier is matched against
the ``id`` of a real ``Member`` row (and against the owning foreign key of the
target resource), so entity-backed calls must present the identifier of the
Member record the test created. The other five roles are opaque operator
identifiers, so a stable identifier is enough.
"""

from typing import Dict

from prd_bench_local_runner.testing import build_user_headers

from .constants import (
    ROLE_ASSOCIATION_ADMIN,
    ROLE_BOARD_MEMBER,
    ROLE_BRANCH_DIRECTOR,
    ROLE_FRONT_DESK,
    ROLE_MEMBER,
    ROLE_PROGRAM_COORDINATOR,
)

# Opaque identifiers for the roles that are never matched against a Member row.
TEST_USERS: Dict[str, Dict[str, str]] = {
    "association_admin": {"id": "11111111-1111-4111-8111-111111111111", "role": ROLE_ASSOCIATION_ADMIN},
    "branch_director": {"id": "22222222-2222-4222-8222-222222222222", "role": ROLE_BRANCH_DIRECTOR},
    "program_coordinator": {"id": "33333333-3333-4333-8333-333333333333", "role": ROLE_PROGRAM_COORDINATOR},
    "front_desk": {"id": "44444444-4444-4444-8444-444444444444", "role": ROLE_FRONT_DESK},
    "board_member": {"id": "55555555-5555-4555-8555-555555555555", "role": ROLE_BOARD_MEMBER},
}

# Ready-made header dicts for the opaque roles.
ASSOCIATION_ADMIN_HEADERS = build_user_headers(
    TEST_USERS["association_admin"]["id"], ROLE_ASSOCIATION_ADMIN
)
BRANCH_DIRECTOR_HEADERS = build_user_headers(
    TEST_USERS["branch_director"]["id"], ROLE_BRANCH_DIRECTOR
)
PROGRAM_COORDINATOR_HEADERS = build_user_headers(
    TEST_USERS["program_coordinator"]["id"], ROLE_PROGRAM_COORDINATOR
)
FRONT_DESK_HEADERS = build_user_headers(TEST_USERS["front_desk"]["id"], ROLE_FRONT_DESK)
BOARD_MEMBER_HEADERS = build_user_headers(TEST_USERS["board_member"]["id"], ROLE_BOARD_MEMBER)


# ── Entity-backed role ─────────────────────────────────────────────────────

def make_member_headers(member_id: str) -> Dict[str, str]:
    """Headers for a Member acting as the Member record with this identifier.

    The PRD compares the target resource's owning foreign key (for example
    ``primary_member_id`` or ``applicant_member_id``) to ``X-User-ID``, so the
    identifier must be the real Member id the test created.
    """
    return build_user_headers(member_id, ROLE_MEMBER)


# ── Malformed credentials, for the header-presence tier ────────────────────

def headers_without_role(user_id: str) -> Dict[str, str]:
    """Headers that omit X-User-Role entirely."""
    return {"X-User-ID": user_id, "Content-Type": "application/json"}


def headers_without_user_id(role: str) -> Dict[str, str]:
    """Headers that omit X-User-ID entirely."""
    return {"X-User-Role": role, "Content-Type": "application/json"}


# A syntactically valid header value that names no declared role.
UNDECLARED_ROLE = "Custodian"


def headers_with_undeclared_role(user_id: str) -> Dict[str, str]:
    """Headers naming a role the PRD does not declare."""
    return build_user_headers(user_id, UNDECLARED_ROLE)
