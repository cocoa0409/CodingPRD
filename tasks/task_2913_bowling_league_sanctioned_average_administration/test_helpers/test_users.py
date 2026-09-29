"""Authentication headers for the five roles (PRD §2.1).

Four roles are entity-backed: ``Bowler``, ``TeamCaptain``, ``LeagueSecretary``
and ``LeagueTreasurer`` all carry the ``id`` of the acting ``Member`` in
``X-User-ID``, so their header builders *require* a member id and there is no
"generic bowler" identity to reach for.  ``AssociationOfficer`` is the one
exception: its ``X-User-ID`` is an opaque operator string tied to no entity, so
a module-level default is legitimate there and only there.
"""
from typing import Dict

from prd_bench_local_runner.testing.headers import build_user_headers

from test_helpers.types import UserRole

# The opaque operator identifier for the national/association side.  It is
# never compared to any entity id, but it *is* captured into audit fields, so a
# second distinct officer is provided for duty-segregation scenarios (§2.10).
ASSOCIATION_OFFICER_ID = "officer-national-001"
SECOND_ASSOCIATION_OFFICER_ID = "officer-national-002"


def make_headers(user_id: str, role: UserRole) -> Dict[str, str]:
    """Build both required headers for an arbitrary role/principal pair."""
    return build_user_headers(user_id, role.value if isinstance(role, UserRole) else role)


def make_bowler_headers(member_id: str) -> Dict[str, str]:
    """Act as the ``Member`` with this id, in the plain ``Bowler`` capacity."""
    return make_headers(member_id, UserRole.BOWLER)


def make_team_captain_headers(member_id: str) -> Dict[str, str]:
    """Act as the ``Member`` with this id, asserting the captaincy by header."""
    return make_headers(member_id, UserRole.TEAM_CAPTAIN)


def make_league_secretary_headers(member_id: str) -> Dict[str, str]:
    """Act as the ``Member`` who is the league's ``secretary_member_id``."""
    return make_headers(member_id, UserRole.LEAGUE_SECRETARY)


def make_league_treasurer_headers(member_id: str) -> Dict[str, str]:
    """Act as the ``Member`` who is the league's ``treasurer_member_id``."""
    return make_headers(member_id, UserRole.LEAGUE_TREASURER)


def make_association_officer_headers(
    user_id: str = ASSOCIATION_OFFICER_ID,
) -> Dict[str, str]:
    """Act as an association officer; ``user_id`` is opaque, not a member id."""
    return make_headers(user_id, UserRole.ASSOCIATION_OFFICER)


# ─── Deliberately malformed identities, for the §2.1 refusals ───

def headers_missing_user_id(role: UserRole) -> Dict[str, str]:
    """Omit ``X-User-ID`` entirely — expects ``ERR_UNAUTHENTICATED``."""
    return {
        "X-User-Role": role.value if isinstance(role, UserRole) else role,
        "Content-Type": "application/json",
    }


def headers_missing_role(user_id: str) -> Dict[str, str]:
    """Omit ``X-User-Role`` entirely — expects ``ERR_UNAUTHENTICATED``."""
    return {"X-User-ID": user_id, "Content-Type": "application/json"}


def headers_empty_user_id(role: UserRole) -> Dict[str, str]:
    """Present but empty ``X-User-ID``.

    The value is the empty string, never a space: a whitespace value is a
    *different* input and some HTTP stacks refuse to transmit it at all.
    """
    return {
        "X-User-ID": "",
        "X-User-Role": role.value if isinstance(role, UserRole) else role,
        "Content-Type": "application/json",
    }


def headers_empty_role(user_id: str) -> Dict[str, str]:
    """Present but empty ``X-User-Role`` — expects ``ERR_UNAUTHENTICATED``."""
    return {
        "X-User-ID": user_id,
        "X-User-Role": "",
        "Content-Type": "application/json",
    }


def headers_unrecognised_role(
    user_id: str, role_value: str = "LeagueVicePresident"
) -> Dict[str, str]:
    """A role string outside the five declared spellings.

    Expects ``ERR_FORBIDDEN_ROLE``.  The default value is also a case-correct
    near-miss of nothing in the catalogue, so it cannot be confused with a
    misspelling the server might charitably repair.
    """
    return {
        "X-User-ID": user_id,
        "X-User-Role": role_value,
        "Content-Type": "application/json",
    }
