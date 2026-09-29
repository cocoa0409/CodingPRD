"""Identity headers for every role of PRD §2.1.

Two families live here.

* Shared constants for the four opaque-identity roles, whose ``X-User-ID`` is
  never compared against an entity id.
* Per-instance builders for the two officer-backed roles, whose ``X-User-ID``
  *is* the acting ``Officer.id`` — so each officer needs their own headers.
"""

from prd_bench_local_runner.testing import build_user_headers

from .constants import (
    ROLE_CHECKPOINT_MANAGER,
    ROLE_DUTY_MANAGER,
    ROLE_PLATFORM_ADMIN,
    ROLE_SCREENING_OFFICER,
    ROLE_STAFFING_PLANNER,
    ROLE_SUPERVISORY_OFFICER,
)
from .types import Headers

# ── Opaque operator identifiers ───────────────────────────────────────────────
ADMIN_USER_ID = "admin-1"
MANAGER_USER_ID = "manager-1"
SECOND_MANAGER_USER_ID = "manager-2"
# Segregation of duties compares identifiers, so the preparing planner and the
# deciding duty manager must be distinguishable from one another and from their
# own second instances.
PLANNER_USER_ID = "planner-1"
SECOND_PLANNER_USER_ID = "planner-2"
DUTY_MANAGER_USER_ID = "duty-1"
SECOND_DUTY_MANAGER_USER_ID = "duty-2"

# ── Shared headers per opaque role ────────────────────────────────────────────
ADMIN_HEADERS: Headers = build_user_headers(ADMIN_USER_ID, ROLE_PLATFORM_ADMIN)
MANAGER_HEADERS: Headers = build_user_headers(MANAGER_USER_ID, ROLE_CHECKPOINT_MANAGER)
SECOND_MANAGER_HEADERS: Headers = build_user_headers(
    SECOND_MANAGER_USER_ID, ROLE_CHECKPOINT_MANAGER
)
PLANNER_HEADERS: Headers = build_user_headers(PLANNER_USER_ID, ROLE_STAFFING_PLANNER)
SECOND_PLANNER_HEADERS: Headers = build_user_headers(
    SECOND_PLANNER_USER_ID, ROLE_STAFFING_PLANNER
)
DUTY_MANAGER_HEADERS: Headers = build_user_headers(
    DUTY_MANAGER_USER_ID, ROLE_DUTY_MANAGER
)
SECOND_DUTY_MANAGER_HEADERS: Headers = build_user_headers(
    SECOND_DUTY_MANAGER_USER_ID, ROLE_DUTY_MANAGER
)

# A DutyManager presenting the preparing planner's own identifier: the role is
# right and only the identity is wrong (PRD §2.1 segregation of duties).
DUTY_MANAGER_AS_PLANNER_HEADERS: Headers = build_user_headers(
    PLANNER_USER_ID, ROLE_DUTY_MANAGER
)

TEST_USERS: dict[str, Headers] = {
    ROLE_PLATFORM_ADMIN: ADMIN_HEADERS,
    ROLE_CHECKPOINT_MANAGER: MANAGER_HEADERS,
    ROLE_STAFFING_PLANNER: PLANNER_HEADERS,
    ROLE_DUTY_MANAGER: DUTY_MANAGER_HEADERS,
}

TEST_USER_IDS: dict[str, str] = {
    ROLE_PLATFORM_ADMIN: ADMIN_USER_ID,
    ROLE_CHECKPOINT_MANAGER: MANAGER_USER_ID,
    ROLE_STAFFING_PLANNER: PLANNER_USER_ID,
    ROLE_DUTY_MANAGER: DUTY_MANAGER_USER_ID,
}


# ── Officer-backed roles: one identity per Officer row ────────────────────────
def make_screening_officer_headers(officer_id: str) -> Headers:
    """Headers for a line officer acting as the Officer row ``officer_id``."""
    return build_user_headers(officer_id, ROLE_SCREENING_OFFICER)


def make_supervisory_officer_headers(officer_id: str) -> Headers:
    """Headers for a floor supervisor acting as the Officer row ``officer_id``."""
    return build_user_headers(officer_id, ROLE_SUPERVISORY_OFFICER)


def make_headers(role: str, user_id: str) -> Headers:
    """Headers for an arbitrary role/identifier pair, including unknown roles."""
    return build_user_headers(user_id, role)


# ── Degenerate identity headers (PRD §2.1) ────────────────────────────────────
def headers_without_role(user_id: str = ADMIN_USER_ID) -> Headers:
    """Identity headers with ``X-User-Role`` omitted entirely."""
    return {"X-User-ID": user_id, "Content-Type": "application/json"}


def headers_without_user_id(role: str = ROLE_PLATFORM_ADMIN) -> Headers:
    """Identity headers with ``X-User-ID`` omitted entirely."""
    return {"X-User-Role": role, "Content-Type": "application/json"}


def headers_with_empty_role(user_id: str = ADMIN_USER_ID) -> Headers:
    """Identity headers whose ``X-User-Role`` is present but blank."""
    return {
        "X-User-ID": user_id,
        "X-User-Role": "",
        "Content-Type": "application/json",
    }


def headers_with_empty_user_id(role: str = ROLE_PLATFORM_ADMIN) -> Headers:
    """Identity headers whose ``X-User-ID`` is present but blank."""
    return {
        "X-User-ID": "",
        "X-User-Role": role,
        "Content-Type": "application/json",
    }


def headers_with_unknown_role(user_id: str = "auditor-1") -> Headers:
    """Headers naming a role that is not one of the six declared roles."""
    return build_user_headers(user_id, "Auditor")


NO_HEADERS: Headers = {"Content-Type": "application/json"}
