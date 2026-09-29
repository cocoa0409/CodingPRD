"""Caller identities and request headers.

Every request carries ``X-User-ID`` and ``X-User-Role``. Four of the five roles
present an opaque operator identifier; ``VenueRep`` presents the ``id`` of the
acting venue, so its headers can only be built once a venue exists — use
:func:`make_venue_rep_headers` for that role.
"""

from typing import Dict

from prd_bench_local_runner.testing import build_user_headers

from .constants import (
    ROLE_CONTRACT_APPROVER,
    ROLE_FINANCE_CONTROLLER,
    ROLE_PROGRAM_ADMIN,
    ROLE_SOURCING_MANAGER,
    ROLE_VENUE_REP,
)

# Opaque operator identifiers. None of these is ever matched against a stored row.
PLANNER_USER_ID = "planner-anita"
PLANNER_ALT_USER_ID = "planner-bruno"
APPROVER_USER_ID = "approver-bo"
APPROVER_ALT_USER_ID = "approver-cy"
APPROVER_THIRD_USER_ID = "approver-dee"
FINANCE_USER_ID = "treasury-mira"
PROGRAM_ADMIN_USER_ID = "program-owner-nils"
PROGRAM_ADMIN_ALT_USER_ID = "program-owner-oona"
INSPECTOR_USER_ID = "insp-dana"

TEST_USERS: Dict[str, Dict[str, str]] = {
    "planner": {"user_id": PLANNER_USER_ID, "role": ROLE_SOURCING_MANAGER},
    "planner_alt": {"user_id": PLANNER_ALT_USER_ID, "role": ROLE_SOURCING_MANAGER},
    "approver": {"user_id": APPROVER_USER_ID, "role": ROLE_CONTRACT_APPROVER},
    "approver_alt": {"user_id": APPROVER_ALT_USER_ID, "role": ROLE_CONTRACT_APPROVER},
    "approver_third": {"user_id": APPROVER_THIRD_USER_ID, "role": ROLE_CONTRACT_APPROVER},
    "finance": {"user_id": FINANCE_USER_ID, "role": ROLE_FINANCE_CONTROLLER},
    "program_admin": {"user_id": PROGRAM_ADMIN_USER_ID, "role": ROLE_PROGRAM_ADMIN},
    "program_admin_alt": {
        "user_id": PROGRAM_ADMIN_ALT_USER_ID,
        "role": ROLE_PROGRAM_ADMIN,
    },
}

PLANNER_HEADERS = build_user_headers(PLANNER_USER_ID, ROLE_SOURCING_MANAGER)
PLANNER_ALT_HEADERS = build_user_headers(PLANNER_ALT_USER_ID, ROLE_SOURCING_MANAGER)
APPROVER_HEADERS = build_user_headers(APPROVER_USER_ID, ROLE_CONTRACT_APPROVER)
APPROVER_ALT_HEADERS = build_user_headers(APPROVER_ALT_USER_ID, ROLE_CONTRACT_APPROVER)
APPROVER_THIRD_HEADERS = build_user_headers(
    APPROVER_THIRD_USER_ID, ROLE_CONTRACT_APPROVER
)
FINANCE_HEADERS = build_user_headers(FINANCE_USER_ID, ROLE_FINANCE_CONTROLLER)
PROGRAM_ADMIN_HEADERS = build_user_headers(PROGRAM_ADMIN_USER_ID, ROLE_PROGRAM_ADMIN)
PROGRAM_ADMIN_ALT_HEADERS = build_user_headers(
    PROGRAM_ADMIN_ALT_USER_ID, ROLE_PROGRAM_ADMIN
)


def make_venue_rep_headers(venue_id: str) -> Dict[str, str]:
    """Headers for the supplier-side representative of ``venue_id``.

    ``VenueRep`` is the one entity-backed role: ``X-User-ID`` must be the acting
    venue's own ``id`` for the five ownership-gated operations.
    """
    return build_user_headers(venue_id, ROLE_VENUE_REP)


def make_headers(user_id: str, role: str) -> Dict[str, str]:
    """Headers for an arbitrary identity/role pair."""
    return build_user_headers(user_id, role)


def headers_for_role(role: str, venue_id: str = None) -> Dict[str, str]:
    """A representative caller for ``role``.

    ``VenueRep`` requires ``venue_id`` because its identifier is the venue's own
    ``id``; the other four roles use their opaque operator identifiers.
    """
    if role == ROLE_VENUE_REP:
        if venue_id is None:
            raise ValueError("VenueRep headers require the acting venue's id")
        return make_venue_rep_headers(venue_id)
    mapping = {
        ROLE_SOURCING_MANAGER: PLANNER_HEADERS,
        ROLE_CONTRACT_APPROVER: APPROVER_HEADERS,
        ROLE_FINANCE_CONTROLLER: FINANCE_HEADERS,
        ROLE_PROGRAM_ADMIN: PROGRAM_ADMIN_HEADERS,
    }
    return dict(mapping[role])


NO_HEADERS: Dict[str, str] = {}
MISSING_ROLE_HEADERS: Dict[str, str] = {"X-User-ID": PLANNER_USER_ID}
MISSING_USER_HEADERS: Dict[str, str] = {"X-User-Role": ROLE_SOURCING_MANAGER}
UNKNOWN_ROLE_HEADERS: Dict[str, str] = {
    "X-User-ID": PLANNER_USER_ID,
    "X-User-Role": "VenueOwner",
}
