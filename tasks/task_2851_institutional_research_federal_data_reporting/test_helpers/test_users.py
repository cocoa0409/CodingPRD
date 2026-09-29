"""
Actor identities and per-role header builders.

Every request must identify its actor through the two mandatory headers
X-User-ID and X-User-Role. X-User-ID is an opaque operator identifier: the server
records it on the rows the actor touches but never resolves it to an entity, so
the only comparisons made against it are the string-equality checks that enforce
segregation of duties. Each role therefore gets its own distinct default
identifier, and SHARED_ACTOR_ID exists purely to drive those equality checks.
"""

from typing import Dict, Optional

from prd_bench_local_runner.testing import build_user_headers

from .constants import (
    ROLE_DATA_STEWARD,
    ROLE_DISCLOSURE_OFFICER,
    ROLE_IR_ANALYST,
    ROLE_IR_DIRECTOR,
    ROLE_REGISTRAR_OFFICER,
    UNRECOGNISED_ROLE,
)

# ─── Distinct opaque operator identifiers, one per role ───────────

ANALYST_USER_ID = "analyst-1"
ANALYST_USER_ID_ALT = "analyst-2"
DIRECTOR_USER_ID = "director-1"
DIRECTOR_USER_ID_ALT = "director-2"
REGISTRAR_USER_ID = "registrar-1"
STEWARD_USER_ID = "steward-1"
DISCLOSURE_USER_ID = "disclosure-1"

# One identifier deliberately reused across two capacities so that the
# segregation-of-duties comparison finds a match.
SHARED_ACTOR_ID = "u-shared"

TEST_USERS: Dict[str, Dict[str, str]] = {
    ROLE_IR_ANALYST: {"user_id": ANALYST_USER_ID, "role": ROLE_IR_ANALYST},
    ROLE_IR_DIRECTOR: {"user_id": DIRECTOR_USER_ID, "role": ROLE_IR_DIRECTOR},
    ROLE_REGISTRAR_OFFICER: {
        "user_id": REGISTRAR_USER_ID,
        "role": ROLE_REGISTRAR_OFFICER,
    },
    ROLE_DATA_STEWARD: {"user_id": STEWARD_USER_ID, "role": ROLE_DATA_STEWARD},
    ROLE_DISCLOSURE_OFFICER: {
        "user_id": DISCLOSURE_USER_ID,
        "role": ROLE_DISCLOSURE_OFFICER,
    },
}


# ─── Per-role header builders ─────────────────────────────────────


def make_analyst_headers(user_id: Optional[str] = None) -> Dict[str, str]:
    """Headers for an IRAnalyst; pass user_id to override the default identifier."""
    return build_user_headers(user_id or ANALYST_USER_ID, ROLE_IR_ANALYST)


def make_director_headers(user_id: Optional[str] = None) -> Dict[str, str]:
    """Headers for an IRDirector."""
    return build_user_headers(user_id or DIRECTOR_USER_ID, ROLE_IR_DIRECTOR)


def make_registrar_headers(user_id: Optional[str] = None) -> Dict[str, str]:
    """Headers for a RegistrarOfficer."""
    return build_user_headers(user_id or REGISTRAR_USER_ID, ROLE_REGISTRAR_OFFICER)


def make_steward_headers(user_id: Optional[str] = None) -> Dict[str, str]:
    """Headers for a DataSteward."""
    return build_user_headers(user_id or STEWARD_USER_ID, ROLE_DATA_STEWARD)


def make_disclosure_headers(user_id: Optional[str] = None) -> Dict[str, str]:
    """Headers for a DisclosureOfficer."""
    return build_user_headers(user_id or DISCLOSURE_USER_ID, ROLE_DISCLOSURE_OFFICER)


HEADER_BUILDERS = {
    ROLE_IR_ANALYST: make_analyst_headers,
    ROLE_IR_DIRECTOR: make_director_headers,
    ROLE_REGISTRAR_OFFICER: make_registrar_headers,
    ROLE_DATA_STEWARD: make_steward_headers,
    ROLE_DISCLOSURE_OFFICER: make_disclosure_headers,
}


def headers_for_role(role: str, user_id: Optional[str] = None) -> Dict[str, str]:
    """Build headers for any of the five recognised roles by name."""
    return HEADER_BUILDERS[role](user_id)


def make_headers_without_auth() -> Dict[str, str]:
    """Headers that omit both mandatory actor headers entirely."""
    return {"Content-Type": "application/json"}


def make_headers_missing_user_id(role: str = ROLE_IR_ANALYST) -> Dict[str, str]:
    """Headers that carry a role but omit X-User-ID."""
    return {"X-User-Role": role, "Content-Type": "application/json"}


def make_headers_missing_role(user_id: str = ANALYST_USER_ID) -> Dict[str, str]:
    """Headers that carry an actor identifier but omit X-User-Role."""
    return {"X-User-ID": user_id, "Content-Type": "application/json"}


def make_headers_unknown_role(user_id: str = ANALYST_USER_ID) -> Dict[str, str]:
    """Headers whose X-User-Role is not one of the five recognised roles."""
    return build_user_headers(user_id, UNRECOGNISED_ROLE)
