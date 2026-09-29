"""Operator identity headers for every role in the PRD.

Four of the five roles are opaque operator identities that are never resolved to
a row, so a shared constant is the canonical form for them. ``CrewMember`` is
different: its ``X-User-ID`` is the id of the acting crew-member record, so
ownership-gated calls MUST use ``make_crew_member_headers(crew_member["id"])``.
"""

from prd_bench_local_runner.testing import build_user_headers

# Opaque operator identifiers. Two TechnicalDirector identifiers exist because
# several rules compare operator identifier strings across calls.
PRODUCTION_MANAGER_ID = "pm-001"
PRODUCTION_MANAGER_ID_ALT = "pm-002"
TECHNICAL_DIRECTOR_ID = "td-001"
TECHNICAL_DIRECTOR_ID_ALT = "td-002"
LEAGUE_OPERATIONS_ID = "lo-001"
UNION_STEWARD_ID = "us-001"

TEST_USERS = {
    "production_manager_headers": build_user_headers(
        PRODUCTION_MANAGER_ID, "ProductionManager"
    ),
    "production_manager_alt_headers": build_user_headers(
        PRODUCTION_MANAGER_ID_ALT, "ProductionManager"
    ),
    "technical_director_headers": build_user_headers(
        TECHNICAL_DIRECTOR_ID, "TechnicalDirector"
    ),
    "technical_director_alt_headers": build_user_headers(
        TECHNICAL_DIRECTOR_ID_ALT, "TechnicalDirector"
    ),
    "league_operations_headers": build_user_headers(
        LEAGUE_OPERATIONS_ID, "LeagueOperations"
    ),
    "union_steward_headers": build_user_headers(UNION_STEWARD_ID, "UnionSteward"),
    # Fallback constant for CrewMember, safe only where no ownership check runs.
    "crew_member_headers": build_user_headers("cm-unowned", "CrewMember"),
}


def make_crew_member_headers(crew_member_id: str) -> dict:
    """Headers for the acting CrewMember (identity is the CrewMember row's id).

    Pass the real ``crew_member["id"]`` whenever the call is ownership-gated,
    for example when responding to a crew call.
    """
    return build_user_headers(crew_member_id, "CrewMember")


def make_production_manager_headers(user_id: str) -> dict:
    """ProductionManager headers under a caller-chosen operator identifier."""
    return build_user_headers(user_id, "ProductionManager")


def make_technical_director_headers(user_id: str) -> dict:
    """TechnicalDirector headers under a caller-chosen operator identifier."""
    return build_user_headers(user_id, "TechnicalDirector")


def make_league_operations_headers(user_id: str) -> dict:
    """LeagueOperations headers under a caller-chosen operator identifier."""
    return build_user_headers(user_id, "LeagueOperations")


def make_union_steward_headers(user_id: str) -> dict:
    """UnionSteward headers under a caller-chosen operator identifier."""
    return build_user_headers(user_id, "UnionSteward")


def make_headers(user_id: str, role: str) -> dict:
    """Arbitrary identity/role pair, including roles the PRD never declares."""
    return build_user_headers(user_id, role)


def make_empty_user_id_headers(role: str) -> dict:
    """A request whose ``X-User-ID`` is transmitted as an empty string."""
    return build_user_headers("", role)


def make_empty_role_headers(user_id: str) -> dict:
    """A request whose ``X-User-Role`` is transmitted as an empty string."""
    return build_user_headers(user_id, "")


#: A role string that is not one of the five the PRD declares.
UNDECLARED_ROLE = "Producer"
