"""Pre-built role headers for every role in the PRD."""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for opaque roles, and for tests that don't exercise ownership.
TEST_USERS = {
    "platform_admin_headers": build_user_headers("test-platform-admin-1", "PlatformAdmin"),
    "complex_director_headers": build_user_headers("test-complex-director-1", "ComplexDirector"),
    "community_liaison_headers": build_user_headers("test-community-liaison-1", "CommunityLiaison"),
    "field_coordinator_headers": build_user_headers("test-field-coordinator-1", "FieldCoordinator"),
    "pitching_coordinator_headers": build_user_headers("test-pitching-coordinator-1", "PitchingCoordinator"),
    "travel_coordinator_headers": build_user_headers("test-travel-coordinator-1", "TravelCoordinator"),
    "team_physician_headers": build_user_headers("test-team-physician-1", "TeamPhysician"),
    "roster_manager_headers": build_user_headers("test-roster-manager-1", "RosterManager"),
    "minor_league_coordinator_headers": build_user_headers("test-minor-league-coordinator-1", "MinorLeagueCoordinator"),
    "analytics_headers": build_user_headers("test-analytics-1", "Analytics"),
    # entity_backed role: the shared constant is a fallback for non-ownership calls only.
    "player_headers": build_user_headers("test-player-1", "Player"),
}

# Per-instance builders — required for every entity_backed role.
# Player is the single entity-backed role; pass the actual Player.id as user_id
# whenever the call is ownership-gated (invitation acknowledgement).


def make_actor_headers(user_id: str, role: str) -> dict:
    """Build headers for an arbitrary distinct opaque principal.

    Used where segregation of duties requires two different X-User-IDs
    acting in the same role (an applier and a finalizer, a settler and a voider).
    """
    return build_user_headers(user_id, role)


def make_player_headers(player_id: str) -> dict:
    """For the Player role (entity_backed:Player). Pass the actual Player.id as
    user_id whenever the call is ownership-gated."""
    return build_user_headers(player_id, "Player")