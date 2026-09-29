"""Pre-built auth headers for every role of PRD §2.1.

PRD §2.1 splits the eight roles in two. "Only one role is tied to a persisted
entity. When ``X-User-Role`` is ``Member``, ``X-User-ID`` is the ``id`` of the
acting ``Household``" — so Member headers must be built per household, and each
distinct household owner gets its own ``X-User-ID``. Every other role's
``X-User-ID`` "is an opaque operator identifier not tied to any persisted
entity", so those can be fixed constants.

Two-person control (PRD §2.8) needs two *different* operator identifiers inside
the same role, which is why the board-president, health-inspector and treasurer
identities come in pairs.
"""

from typing import Dict

from prd_bench_local_runner.testing import build_user_headers

from .types import Role

# ─── Opaque operator identifiers (PRD §2.1) ───────────
MEMBERSHIP_CHAIR_USER_ID = "mc-001"
POOL_MANAGER_USER_ID = "pm-001"
POOL_MANAGER_USER_ID_2 = "pm-002"
SWIM_TEAM_COACH_USER_ID = "tc-001"
HEALTH_INSPECTOR_USER_ID = "hi-001"
HEALTH_INSPECTOR_USER_ID_2 = "hi-002"
TREASURER_USER_ID = "tr-001"
TREASURER_USER_ID_2 = "tr-002"
BOARD_PRESIDENT_USER_ID = "bp-001"
BOARD_PRESIDENT_USER_ID_2 = "bp-002"
SYSTEM_OPERATOR_USER_ID = "so-001"


def make_headers(user_id: str, role: str) -> Dict[str, str]:
    """Build headers for an arbitrary user/role pair."""
    return build_user_headers(user_id, role)


def make_member_headers(household_id: str) -> Dict[str, str]:
    """Member headers for a specific household.

    PRD §2.1: "ownership checks on any resource that references a ``Household``
    compare the resource's household reference to ``X-User-ID``".
    """
    return build_user_headers(household_id, Role.MEMBER)


# ─── Per-role header dicts ────────────────────────────
MEMBERSHIP_CHAIR = make_headers(MEMBERSHIP_CHAIR_USER_ID, Role.MEMBERSHIP_CHAIR)
POOL_MANAGER = make_headers(POOL_MANAGER_USER_ID, Role.POOL_MANAGER)
POOL_MANAGER_2 = make_headers(POOL_MANAGER_USER_ID_2, Role.POOL_MANAGER)
SWIM_TEAM_COACH = make_headers(SWIM_TEAM_COACH_USER_ID, Role.SWIM_TEAM_COACH)
HEALTH_INSPECTOR = make_headers(HEALTH_INSPECTOR_USER_ID, Role.HEALTH_INSPECTOR)
HEALTH_INSPECTOR_2 = make_headers(HEALTH_INSPECTOR_USER_ID_2, Role.HEALTH_INSPECTOR)
TREASURER = make_headers(TREASURER_USER_ID, Role.TREASURER)
TREASURER_2 = make_headers(TREASURER_USER_ID_2, Role.TREASURER)
BOARD_PRESIDENT = make_headers(BOARD_PRESIDENT_USER_ID, Role.BOARD_PRESIDENT)
BOARD_PRESIDENT_2 = make_headers(BOARD_PRESIDENT_USER_ID_2, Role.BOARD_PRESIDENT)
SYSTEM_OPERATOR = make_headers(SYSTEM_OPERATOR_USER_ID, Role.SYSTEM_OPERATOR)

TEST_USERS: Dict[str, Dict[str, str]] = {
    "membership_chair": MEMBERSHIP_CHAIR,
    "pool_manager": POOL_MANAGER,
    "pool_manager_2": POOL_MANAGER_2,
    "swim_team_coach": SWIM_TEAM_COACH,
    "health_inspector": HEALTH_INSPECTOR,
    "health_inspector_2": HEALTH_INSPECTOR_2,
    "treasurer": TREASURER,
    "treasurer_2": TREASURER_2,
    "board_president": BOARD_PRESIDENT,
    "board_president_2": BOARD_PRESIDENT_2,
    "system_operator": SYSTEM_OPERATOR,
}


# ─── Deliberately malformed identities (PRD §2.1 / ladder band 1) ───
# PRD §2.1: "If either header is absent or empty, or if X-User-Role names a
# role outside the enumeration below, the request is rejected with
# ERR_UNAUTHENTICATED". An intentionally blank header must carry the empty
# string, never whitespace: a spaces-only value never reaches the server.

NO_ROLE_HEADER = {
    "X-User-ID": POOL_MANAGER_USER_ID,
    "Content-Type": "application/json",
}

BLANK_ROLE = {
    "X-User-ID": POOL_MANAGER_USER_ID,
    "X-User-Role": "",
    "Content-Type": "application/json",
}

BLANK_USER_ID = {
    "X-User-ID": "",
    "X-User-Role": Role.POOL_MANAGER,
    "Content-Type": "application/json",
}

NO_USER_ID_HEADER = {
    "X-User-Role": Role.POOL_MANAGER,
    "Content-Type": "application/json",
}


def unknown_role_headers(role_name: str = "PoolAttendant",
                         user_id: str = POOL_MANAGER_USER_ID) -> Dict[str, str]:
    """Headers naming a role outside the eight-role enumeration."""
    return build_user_headers(user_id, role_name)


UNKNOWN_ROLE = unknown_role_headers()
