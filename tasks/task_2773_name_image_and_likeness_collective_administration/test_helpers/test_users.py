"""Caller identities for the six roles of PRD s2.1.

Five roles are opaque service roles: their ``X-User-ID`` is an operator handle
that the server never matches against a row, but it is still load-bearing because
a compliance officer's handle is stored as ``verified_by_user_id`` and a treasury
officer's handle as ``initiated_by_user_id``, and the segregation-of-duties rule
of PRD s2.11 compares exactly those two strings. The ``Athlete`` role alone is
entity-backed: its ``X-User-ID`` must equal the acting athlete's
``portal_user_id``.
"""

from typing import Dict, Optional

from prd_bench_local_runner.testing import build_user_headers

from .constants import (
    ROLE_ATHLETE,
    ROLE_COLLECTIVE_DIRECTOR,
    ROLE_COMPLIANCE_OFFICER,
    ROLE_INSTITUTION_REVIEWER,
    ROLE_PLATFORM_ADMIN,
    ROLE_TREASURY_OFFICER,
)

# Default opaque operator handles, one per service role.
TEST_USERS: Dict[str, Dict[str, str]] = {
    ROLE_PLATFORM_ADMIN: {"user_id": "admin-1", "role": ROLE_PLATFORM_ADMIN},
    ROLE_COLLECTIVE_DIRECTOR: {"user_id": "director-1", "role": ROLE_COLLECTIVE_DIRECTOR},
    ROLE_COMPLIANCE_OFFICER: {"user_id": "compliance-1", "role": ROLE_COMPLIANCE_OFFICER},
    ROLE_INSTITUTION_REVIEWER: {"user_id": "reviewer-1", "role": ROLE_INSTITUTION_REVIEWER},
    ROLE_TREASURY_OFFICER: {"user_id": "treasury-1", "role": ROLE_TREASURY_OFFICER},
}


def headers_for_role(role: str, user_id: str) -> Dict[str, str]:
    """Both headers of PRD s2.1 for an arbitrary role string and handle."""
    return build_user_headers(user_id, role)


def make_admin_headers(user_id: str = "admin-1") -> Dict[str, str]:
    return build_user_headers(user_id, ROLE_PLATFORM_ADMIN)


def make_director_headers(user_id: str = "director-1") -> Dict[str, str]:
    return build_user_headers(user_id, ROLE_COLLECTIVE_DIRECTOR)


def make_compliance_headers(user_id: str = "compliance-1") -> Dict[str, str]:
    """A compliance officer's handle becomes ``verified_by_user_id`` on review."""
    return build_user_headers(user_id, ROLE_COMPLIANCE_OFFICER)


def make_reviewer_headers(user_id: str = "reviewer-1") -> Dict[str, str]:
    return build_user_headers(user_id, ROLE_INSTITUTION_REVIEWER)


def make_treasury_headers(user_id: str = "treasury-1") -> Dict[str, str]:
    """A treasury officer's handle becomes ``initiated_by_user_id`` on a release."""
    return build_user_headers(user_id, ROLE_TREASURY_OFFICER)


def make_athlete_headers(portal_user_id: str) -> Dict[str, str]:
    """The entity-backed role: ``X-User-ID`` is the athlete's ``portal_user_id``."""
    return build_user_headers(portal_user_id, ROLE_ATHLETE)


# Convenience singletons for the common case where the handle does not matter.
ADMIN = make_admin_headers()
DIRECTOR = make_director_headers()
COMPLIANCE = make_compliance_headers()
REVIEWER = make_reviewer_headers()
TREASURY = make_treasury_headers()


def make_headers_without_auth() -> Dict[str, str]:
    """No ``X-User-Role`` and no ``X-User-ID`` at all (PRD s2.1, priority 1)."""
    return {"Content-Type": "application/json"}


def make_headers_missing_user_id(role: str = ROLE_PLATFORM_ADMIN) -> Dict[str, str]:
    """A role with no actor handle at all (PRD s2.1, priority 1)."""
    return {"Content-Type": "application/json", "X-User-Role": role}


def make_headers_empty_user_id(role: str = ROLE_PLATFORM_ADMIN) -> Dict[str, str]:
    """A present but empty ``X-User-ID`` (PRD s2.1, priority 1)."""
    return {"Content-Type": "application/json", "X-User-Role": role, "X-User-ID": ""}


def make_headers_unknown_role(
    role_name: str = "NotARealRole", user_id: Optional[str] = "ghost-1"
) -> Dict[str, str]:
    """A recognisable handle presenting a role name outside the six (PRD s2.1)."""
    return build_user_headers(user_id or "ghost-1", role_name)
