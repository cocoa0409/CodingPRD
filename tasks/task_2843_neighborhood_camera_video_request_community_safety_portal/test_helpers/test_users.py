"""Caller identities for the six declared roles.

Every request carries ``X-User-ID`` and ``X-User-Role``. Three roles are
entity-backed, so the acting identifier must be the identifier of a stored row:
an AgencyAdmin presents the agency's identifier, an Officer presents the
officer's identifier and a Resident presents the resident's identifier. Those
three therefore get per-call builders that take the identifier the test created;
falling back to a shared constant would make the caller a different principal
from the row's owner.

The three remaining roles — PlatformAdmin, Moderator and Anonymous — are never
matched against a stored row, so stable opaque identifiers are enough. Two
distinct platform administrators and two distinct moderators are provided
because the contract enforces separated duties on the acting identifier: a
report may not be certified by the user who compiled it, and a moderation case
may not be decided by the user who opened it.

Registering a resident account is exempt from the header requirement entirely,
so a headerless variant is provided for that one call.
"""

from typing import Dict, Optional

from prd_bench_local_runner.testing import build_user_headers

from .constants import (
    ROLE_AGENCY_ADMIN,
    ROLE_ANONYMOUS,
    ROLE_MODERATOR,
    ROLE_OFFICER,
    ROLE_PLATFORM_ADMIN,
    ROLE_RESIDENT,
)

# Opaque identifiers for the roles that are not matched against a stored row.
TEST_USERS: Dict[str, Dict[str, str]] = {
    "platform_admin": {"id": "admin-1", "role": ROLE_PLATFORM_ADMIN},
    "platform_admin_second": {"id": "admin-2", "role": ROLE_PLATFORM_ADMIN},
    "moderator": {"id": "mod-1", "role": ROLE_MODERATOR},
    "moderator_second": {"id": "mod-2", "role": ROLE_MODERATOR},
    "anonymous": {"id": "anon-1", "role": ROLE_ANONYMOUS},
}

PLATFORM_ADMIN_ID = TEST_USERS["platform_admin"]["id"]
PLATFORM_ADMIN_SECOND_ID = TEST_USERS["platform_admin_second"]["id"]
MODERATOR_ID = TEST_USERS["moderator"]["id"]
MODERATOR_SECOND_ID = TEST_USERS["moderator_second"]["id"]

PLATFORM_ADMIN_HEADERS = build_user_headers(PLATFORM_ADMIN_ID, ROLE_PLATFORM_ADMIN)
PLATFORM_ADMIN_SECOND_HEADERS = build_user_headers(
    PLATFORM_ADMIN_SECOND_ID, ROLE_PLATFORM_ADMIN
)
MODERATOR_HEADERS = build_user_headers(MODERATOR_ID, ROLE_MODERATOR)
MODERATOR_SECOND_HEADERS = build_user_headers(MODERATOR_SECOND_ID, ROLE_MODERATOR)
ANONYMOUS_HEADERS = build_user_headers(TEST_USERS["anonymous"]["id"], ROLE_ANONYMOUS)


# ── Entity-backed roles ────────────────────────────────────────────────────

def make_agency_admin_headers(agency_id: str) -> Dict[str, str]:
    """Headers for the administrator of the agency with this identifier."""
    return build_user_headers(agency_id, ROLE_AGENCY_ADMIN)


def make_officer_headers(officer_id: str) -> Dict[str, str]:
    """Headers for the officer with this identifier."""
    return build_user_headers(officer_id, ROLE_OFFICER)


def make_resident_headers(resident_id: str) -> Dict[str, str]:
    """Headers for the resident with this identifier."""
    return build_user_headers(resident_id, ROLE_RESIDENT)


def make_platform_admin_headers(user_id: str = PLATFORM_ADMIN_ID) -> Dict[str, str]:
    """Headers for a platform administrator acting under this opaque identifier."""
    return build_user_headers(user_id, ROLE_PLATFORM_ADMIN)


def make_moderator_headers(user_id: str = MODERATOR_ID) -> Dict[str, str]:
    """Headers for a moderator acting under this opaque identifier."""
    return build_user_headers(user_id, ROLE_MODERATOR)


def make_anonymous_headers(user_id: Optional[str] = None) -> Dict[str, str]:
    """Headers naming the anonymous role, which needs no acting identifier."""
    if user_id is None:
        return {"X-User-Role": ROLE_ANONYMOUS, "Content-Type": "application/json"}
    return build_user_headers(user_id, ROLE_ANONYMOUS)


# Registering a resident account is exempt from the header requirement.
NO_HEADERS: Dict[str, str] = {"Content-Type": "application/json"}


# ── Malformed credentials ──────────────────────────────────────────────────

def headers_without_role(user_id: str) -> Dict[str, str]:
    """Headers that omit X-User-Role entirely."""
    return {"X-User-ID": user_id, "Content-Type": "application/json"}


def headers_without_user_id(role: str) -> Dict[str, str]:
    """Headers that omit X-User-ID entirely."""
    return {"X-User-Role": role, "Content-Type": "application/json"}


def headers_with_empty_user_id(role: str) -> Dict[str, str]:
    """Headers whose X-User-ID is present but empty."""
    return {"X-User-ID": "", "X-User-Role": role, "Content-Type": "application/json"}


def headers_with_empty_role(user_id: str) -> Dict[str, str]:
    """Headers whose X-User-Role is present but empty."""
    return {"X-User-ID": user_id, "X-User-Role": "", "Content-Type": "application/json"}


# A syntactically valid header value naming no declared role.
UNDECLARED_ROLE = "PrecinctCaptain"


def headers_with_undeclared_role(user_id: str) -> Dict[str, str]:
    """Headers naming a role the contract does not declare."""
    return build_user_headers(user_id, UNDECLARED_ROLE)
