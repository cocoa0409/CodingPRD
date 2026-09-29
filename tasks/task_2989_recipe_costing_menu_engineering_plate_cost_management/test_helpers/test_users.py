"""Pre-built authentication headers for each role of PRD section 2.1.

Four of the five roles carry an opaque operator identifier that the API records
on audit fields but never compares against an entity id.  ``UnitManager`` is the
exception: its ``X-User-ID`` *is* the id of the Unit it acts for, so it has no
default header pair and must always be built with
``make_unit_manager_headers(unit_id)``.

Distinct operator ids per role keep segregation-of-duties chains honest: an
approver acting as ``u-dir-1`` on work submitted by ``u-dev-1`` is a different
person, which is exactly what the rule tests.
"""

from typing import Dict, Optional

from prd_bench_local_runner.testing import build_user_headers

from .types import Role

# ─── Operator identifiers ─────────────────────────────

ADMIN_USER_ID = "user-admin-1"
DEVELOPER_USER_ID = "user-dev-1"
DIRECTOR_USER_ID = "user-dir-1"
ANALYST_USER_ID = "user-analyst-1"

# Short-form pair used where a submitter and an approver must be told apart.
SUBMITTER_USER_ID = "u-dev-1"
APPROVER_USER_ID = "u-dir-1"

# A second operator inside each role, for "same role, different person" cases.
DEVELOPER_USER_ID_ALT = "user-dev-2"
DIRECTOR_USER_ID_ALT = "user-dir-2"
ANALYST_USER_ID_ALT = "user-analyst-2"


# ─── Default header pairs ─────────────────────────────

PLATFORM_ADMIN = build_user_headers(ADMIN_USER_ID, Role.PLATFORM_ADMIN)
RECIPE_DEVELOPER = build_user_headers(DEVELOPER_USER_ID, Role.RECIPE_DEVELOPER)
CULINARY_DIRECTOR = build_user_headers(DIRECTOR_USER_ID, Role.CULINARY_DIRECTOR)
COST_ANALYST = build_user_headers(ANALYST_USER_ID, Role.COST_ANALYST)

# Every role that is not entity-backed, keyed by its role string.
OPAQUE_ROLE_HEADERS: Dict[str, Dict[str, str]] = {
    Role.PLATFORM_ADMIN: PLATFORM_ADMIN,
    Role.RECIPE_DEVELOPER: RECIPE_DEVELOPER,
    Role.CULINARY_DIRECTOR: CULINARY_DIRECTOR,
    Role.COST_ANALYST: COST_ANALYST,
}


# ─── Per-instance builders ────────────────────────────


def make_platform_admin_headers(user_id: str = ADMIN_USER_ID) -> Dict[str, str]:
    return build_user_headers(user_id, Role.PLATFORM_ADMIN)


def make_recipe_developer_headers(
    user_id: str = DEVELOPER_USER_ID,
) -> Dict[str, str]:
    return build_user_headers(user_id, Role.RECIPE_DEVELOPER)


def make_culinary_director_headers(
    user_id: str = DIRECTOR_USER_ID,
) -> Dict[str, str]:
    return build_user_headers(user_id, Role.CULINARY_DIRECTOR)


def make_cost_analyst_headers(user_id: str = ANALYST_USER_ID) -> Dict[str, str]:
    return build_user_headers(user_id, Role.COST_ANALYST)


def make_unit_manager_headers(unit_id: str) -> Dict[str, str]:
    """A UnitManager's ``X-User-ID`` is the id of the Unit it manages."""
    return build_user_headers(unit_id, Role.UNIT_MANAGER)


def make_headers(role: str, user_id: str) -> Dict[str, str]:
    """Build a header pair for an arbitrary role/user combination."""
    return build_user_headers(user_id, role)


# ─── Deliberately malformed credentials ───────────────


def headers_without_user_id(role: str = Role.RECIPE_DEVELOPER) -> Dict[str, str]:
    """Header set that omits ``X-User-ID`` entirely."""
    return {"X-User-Role": role, "Content-Type": "application/json"}


def headers_without_role(user_id: str = DEVELOPER_USER_ID) -> Dict[str, str]:
    """Header set that omits ``X-User-Role`` entirely."""
    return {"X-User-ID": user_id, "Content-Type": "application/json"}


def headers_with_empty_user_id(
    role: str = Role.RECIPE_DEVELOPER,
) -> Dict[str, str]:
    """``X-User-ID`` present but empty — an empty string, never a space."""
    return {
        "X-User-ID": "",
        "X-User-Role": role,
        "Content-Type": "application/json",
    }


def headers_with_empty_role(user_id: str = DEVELOPER_USER_ID) -> Dict[str, str]:
    """``X-User-Role`` present but empty — an empty string, never a space."""
    return {
        "X-User-ID": user_id,
        "X-User-Role": "",
        "Content-Type": "application/json",
    }


def headers_with_unknown_role(
    user_id: str = DEVELOPER_USER_ID, role: str = "LineCook"
) -> Dict[str, str]:
    """A syntactically fine header pair naming a role the system does not know."""
    return build_user_headers(user_id, role)


NO_HEADERS: Optional[Dict[str, str]] = {"Content-Type": "application/json"}
