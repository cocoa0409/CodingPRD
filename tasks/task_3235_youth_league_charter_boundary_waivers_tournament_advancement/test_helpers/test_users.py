"""Pre-built role headers for every role in the PRD.

All roles in this system are opaque: ``X-User-ID`` is an operator identifier
never compared to any persisted entity's ``id``. The shared constants below are
therefore the canonical form for every role.
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    "district_admin_headers": build_user_headers("test-district-admin-1", "DistrictAdministrator"),
    "league_admin_headers": build_user_headers("test-league-admin-1", "LeagueAdministrator"),
    "tournament_director_headers": build_user_headers("test-tournament-director-1", "TournamentDirector"),
    "official_scorer_headers": build_user_headers("test-official-scorer-1", "OfficialScorer"),
    "any_headers": build_user_headers("test-any-1", "Any"),
}

# No user context at all — used to exercise the identity check.
NO_USER_HEADERS: dict = {"Content-Type": "application/json"}


def make_role_headers(user_id: str, role: str) -> dict:
    """Headers for an arbitrary identity/role pair."""
    return build_user_headers(user_id, role)
