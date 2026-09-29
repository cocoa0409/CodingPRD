"""Pre-built identity headers for every role named by the PRD.

Every request carries ``X-User-ID`` and ``X-User-Role``. For the roles the PRD
backs with an entity (GeneralManager / SponsorshipManager / OpsManager are the
Organization; PlayerAgent / GuardianRepresentative are the Player) the
``X-User-ID`` must equal that entity's ``id``, so callers use the per-instance
builders below instead of the shared constants.
"""

from prd_bench_local_runner.testing import build_user_headers

from .constants import (
    COACH_USER_ID,
    FINANCE_OFFICER_USER_ID,
    LEAGUE_ADMIN_USER_ID,
    PERFORMANCE_SUPPORT_USER_ID,
    SCOUT_USER_ID,
    SECOND_FINANCE_OFFICER_USER_ID,
    SECOND_LEAGUE_ADMIN_USER_ID,
)
from .types import UserRole

# Shared constants. Canonical for the opaque roles (LeagueAdmin, Scout,
# CoachingStaff, PerformanceSupport, FinanceOfficer); for the entity-backed
# roles they are only safe where the call is not ownership-gated.
TEST_USERS = {
    "league_admin_headers": build_user_headers(
        LEAGUE_ADMIN_USER_ID, UserRole.LEAGUE_ADMIN.value
    ),
    "second_league_admin_headers": build_user_headers(
        SECOND_LEAGUE_ADMIN_USER_ID, UserRole.LEAGUE_ADMIN.value
    ),
    "scout_headers": build_user_headers(SCOUT_USER_ID, UserRole.SCOUT.value),
    "coaching_staff_headers": build_user_headers(
        COACH_USER_ID, UserRole.COACHING_STAFF.value
    ),
    "performance_support_headers": build_user_headers(
        PERFORMANCE_SUPPORT_USER_ID, UserRole.PERFORMANCE_SUPPORT.value
    ),
    "finance_officer_headers": build_user_headers(
        FINANCE_OFFICER_USER_ID, UserRole.FINANCE_OFFICER.value
    ),
    "second_finance_officer_headers": build_user_headers(
        SECOND_FINANCE_OFFICER_USER_ID, UserRole.FINANCE_OFFICER.value
    ),
    "general_manager_headers": build_user_headers(
        "test-general-manager-1", UserRole.GENERAL_MANAGER.value
    ),
    "sponsorship_manager_headers": build_user_headers(
        "test-sponsorship-manager-1", UserRole.SPONSORSHIP_MANAGER.value
    ),
    "ops_manager_headers": build_user_headers(
        "test-ops-manager-1", UserRole.OPS_MANAGER.value
    ),
    "player_agent_headers": build_user_headers(
        "test-player-agent-1", UserRole.PLAYER_AGENT.value
    ),
    "guardian_representative_headers": build_user_headers(
        "test-guardian-representative-1", UserRole.GUARDIAN_REPRESENTATIVE.value
    ),
}


# ─── Per-instance builders ────────────────────────────────────────────────────


def make_league_admin_headers(user_id: str = LEAGUE_ADMIN_USER_ID) -> dict:
    """LeagueAdmin identities are opaque; the id only has to be stable."""
    return build_user_headers(user_id, UserRole.LEAGUE_ADMIN.value)


def make_scout_headers(user_id: str = SCOUT_USER_ID) -> dict:
    return build_user_headers(user_id, UserRole.SCOUT.value)


def make_coaching_staff_headers(user_id: str = COACH_USER_ID) -> dict:
    return build_user_headers(user_id, UserRole.COACHING_STAFF.value)


def make_performance_support_headers(
    user_id: str = PERFORMANCE_SUPPORT_USER_ID,
) -> dict:
    return build_user_headers(user_id, UserRole.PERFORMANCE_SUPPORT.value)


def make_finance_officer_headers(user_id: str = FINANCE_OFFICER_USER_ID) -> dict:
    return build_user_headers(user_id, UserRole.FINANCE_OFFICER.value)


def make_general_manager_headers(user_id: str) -> dict:
    """GeneralManager is the Organization: pass the Organization's id."""
    return build_user_headers(user_id, UserRole.GENERAL_MANAGER.value)


def make_sponsorship_manager_headers(user_id: str) -> dict:
    """SponsorshipManager is the Organization: pass the Organization's id."""
    return build_user_headers(user_id, UserRole.SPONSORSHIP_MANAGER.value)


def make_ops_manager_headers(user_id: str) -> dict:
    """OpsManager is the Organization: pass the Organization's id."""
    return build_user_headers(user_id, UserRole.OPS_MANAGER.value)


def make_player_agent_headers(user_id: str) -> dict:
    """PlayerAgent is the Player: pass the Player's id."""
    return build_user_headers(user_id, UserRole.PLAYER_AGENT.value)


def make_guardian_representative_headers(user_id: str) -> dict:
    """GuardianRepresentative is the Player: pass the Player's id."""
    return build_user_headers(user_id, UserRole.GUARDIAN_REPRESENTATIVE.value)


def make_headers(role: str, user_id: str) -> dict:
    """Generic builder for parametrised role tests."""
    return build_user_headers(user_id, role)


def headers_without_user_id(role: str) -> dict:
    """Identity headers whose X-User-ID is present but empty."""
    return build_user_headers("", role)


def headers_without_role(user_id: str) -> dict:
    """Identity headers whose X-User-Role is present but empty."""
    return build_user_headers(user_id, "")
