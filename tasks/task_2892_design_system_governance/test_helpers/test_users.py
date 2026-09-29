"""
Identity builders for the five governance roles.

Four of the roles carry an opaque operator identifier that the API records on the
rows it writes; ContributingTeam is different — its `X-User-ID` is the identifier
of the Team row it acts for, so every ownership-gated call must be made with a
header built from the real team id that the test created. That is why the
ContributingTeam helper is a function of the team id and not a constant.
"""

from prd_bench_local_runner.testing import build_user_headers

from .constants import (
    ROLE_CONTRIBUTING_TEAM,
    ROLE_DESIGN_CRITIQUE_REVIEWER,
    ROLE_DESIGN_SYSTEM_LEAD,
    ROLE_ENGINEERING_REVIEWER,
    ROLE_SYSTEM_ADMIN,
)
from .types import Headers

# ─── Opaque operator identifiers ──────────────────────

ADMIN_USER_ID = "admin-1"
LEAD_USER_ID = "lead-1"
CRITIC_USER_ID = "critic-1"
CRITIC_TWO_USER_ID = "critic-2"
ENGINEER_USER_ID = "eng-1"
ENGINEER_TWO_USER_ID = "eng-2"
DUAL_ROLE_USER_ID = "dual-1"


def make_system_admin_headers(user_id: str = ADMIN_USER_ID) -> Headers:
    """Headers for the platform operator that registers teams and cuts releases."""
    return build_user_headers(user_id, ROLE_SYSTEM_ADMIN)


def make_design_system_lead_headers(user_id: str = LEAD_USER_ID) -> Headers:
    """Headers for the design-system lead that curates tokens and accepts work."""
    return build_user_headers(user_id, ROLE_DESIGN_SYSTEM_LEAD)


def make_design_critique_reviewer_headers(user_id: str = CRITIC_USER_ID) -> Headers:
    """Headers for a reviewer authorised only at the design-critique gate."""
    return build_user_headers(user_id, ROLE_DESIGN_CRITIQUE_REVIEWER)


def make_engineering_reviewer_headers(user_id: str = ENGINEER_USER_ID) -> Headers:
    """Headers for a reviewer authorised only at the engineering-review gate."""
    return build_user_headers(user_id, ROLE_ENGINEERING_REVIEWER)


def make_contributing_team_headers(team_id: str) -> Headers:
    """
    Headers for a contributing team.

    `team_id` must be the id of a Team row created through the API: the server
    compares it against the owning team recorded on the resource being touched.
    """
    return build_user_headers(team_id, ROLE_CONTRIBUTING_TEAM)


# Convenience aliases used where a role name reads better than the full builder.
ADMIN = make_system_admin_headers
LEAD = make_design_system_lead_headers
CRITIC = make_design_critique_reviewer_headers
ENGINEER = make_engineering_reviewer_headers
TEAM = make_contributing_team_headers


def make_headers_with_role(user_id: str, role: str) -> Headers:
    """Headers for an arbitrary user/role pair, including unrecognised role names."""
    return build_user_headers(user_id, role)


def make_headers_without_role(user_id: str = LEAD_USER_ID) -> Headers:
    """Headers that omit `X-User-Role` entirely."""
    return {"X-User-ID": user_id, "Content-Type": "application/json"}


def make_headers_without_user_id(role: str = ROLE_DESIGN_SYSTEM_LEAD) -> Headers:
    """Headers that omit `X-User-ID` entirely."""
    return {"X-User-Role": role, "Content-Type": "application/json"}


def make_headers_with_empty_identity() -> Headers:
    """
    Headers whose identity values are present but empty.

    The empty string is used deliberately: a whitespace-only header value makes
    the HTTP client refuse to send the request, so it could never reach the API.
    """
    return {"X-User-ID": "", "X-User-Role": "", "Content-Type": "application/json"}


def make_headers_with_empty_role(user_id: str = LEAD_USER_ID) -> Headers:
    """Headers carrying a user id but an empty role value."""
    return {"X-User-ID": user_id, "X-User-Role": "", "Content-Type": "application/json"}


def make_headers_with_empty_user_id(role: str = ROLE_DESIGN_SYSTEM_LEAD) -> Headers:
    """Headers carrying a role but an empty user id value."""
    return {"X-User-ID": "", "X-User-Role": role, "Content-Type": "application/json"}


NO_HEADERS: Headers = {"Content-Type": "application/json"}
