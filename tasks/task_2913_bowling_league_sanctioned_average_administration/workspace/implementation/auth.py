"""Authentication, role authorisation and officer/owner binding (PRD 2.1, 2.6)."""

from flask import request

from errors import ApiError
from store import store

ROLES = ["Bowler", "TeamCaptain", "LeagueSecretary", "LeagueTreasurer",
         "AssociationOfficer"]
ENTITY_BACKED = ["Bowler", "TeamCaptain", "LeagueSecretary", "LeagueTreasurer"]
ALL_ROLES = list(ROLES)
READ_ROLES = list(ROLES)
FINANCIAL_READ_ROLES = ["LeagueSecretary", "LeagueTreasurer", "AssociationOfficer"]


def authenticate(allowed_roles):
    """Checks 1, 2 and 3 of PRD 2.6, in that order."""
    uid = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if uid is None or str(uid).strip() == "":
        raise ApiError("ERR_UNAUTHENTICATED")
    if role is None or str(role).strip() == "":
        raise ApiError("ERR_UNAUTHENTICATED")
    uid = str(uid).strip()
    role = str(role).strip()
    if role not in ROLES or role not in allowed_roles:
        raise ApiError("ERR_FORBIDDEN_ROLE")
    if role in ENTITY_BACKED and uid not in store.members:
        raise ApiError("ERR_UNKNOWN_ACTOR")
    return uid, role


# --- existence resolution --------------------------------------------------

TABLES = {
    "member": ("members", "ERR_MEMBER_NOT_FOUND"),
    "league": ("leagues", "ERR_LEAGUE_NOT_FOUND"),
    "team": ("teams", "ERR_TEAM_NOT_FOUND"),
    "membership": ("memberships", "ERR_MEMBERSHIP_NOT_FOUND"),
    "fee_remittance": ("fee_remittances", "ERR_FEE_REMITTANCE_NOT_FOUND"),
    "lane_pair": ("lane_pairs", "ERR_LANE_PAIR_NOT_FOUND"),
    "match": ("matches", "ERR_MATCH_NOT_FOUND"),
    "series_entry": ("series_entries", "ERR_SERIES_ENTRY_NOT_FOUND"),
    "dues_payment": ("dues_payments", "ERR_DUES_PAYMENT_NOT_FOUND"),
    "prize_fund": ("prize_funds", "ERR_PRIZE_FUND_NOT_FOUND"),
    "prize_award": ("prize_awards", "ERR_PRIZE_AWARD_NOT_FOUND"),
    "award_application": ("award_applications", "ERR_AWARD_APPLICATION_NOT_FOUND"),
    "protest": ("protests", "ERR_PROTEST_NOT_FOUND"),
}


def fetch(kind, row_id):
    """Resolve an id to a row or raise that entity's not-found error."""
    attr, err = TABLES[kind]
    table = getattr(store, attr)
    if not isinstance(row_id, str) or row_id not in table:
        raise ApiError(err, "%s was not found." % kind.replace("_", " "))
    return table[row_id]


def body_ref(kind, value):
    """Body-reference existence (check 5): only a present string is resolved.

    A missing or non-string value is left for the shape pass (check 9).
    """
    if value is None:
        return None
    if not isinstance(value, str):
        return None
    return fetch(kind, value)


# --- officer and owner binding ---------------------------------------------

def require_secretary(league, uid, role):
    if role == "LeagueSecretary" and league.get("secretary_member_id") != uid:
        raise ApiError("ERR_NOT_LEAGUE_SECRETARY")


def require_treasurer(league, uid, role):
    if role == "LeagueTreasurer" and league.get("treasurer_member_id") != uid:
        raise ApiError("ERR_NOT_LEAGUE_TREASURER")


def memberships_of_member(member_id, league_id=None):
    rows = [m for m in store.memberships.values() if m["member_id"] == member_id]
    if league_id is not None:
        rows = [m for m in rows if m["league_id"] == league_id]
    return rows


def require_captain_of_team(uid, league_id, team_id):
    """PRD 2.1: the captaincy is asserted by the header and bound to a
    membership of that league whose team_id is the team being acted for."""
    for m in memberships_of_member(uid, league_id):
        if m["team_id"] is not None and m["team_id"] == team_id:
            return
    raise ApiError("ERR_NOT_RESOURCE_OWNER")


def require_own_membership(uid, membership):
    if membership["member_id"] != uid:
        raise ApiError("ERR_NOT_RESOURCE_OWNER")
