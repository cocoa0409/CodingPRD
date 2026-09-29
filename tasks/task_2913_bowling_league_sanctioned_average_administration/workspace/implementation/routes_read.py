"""Read endpoints: 13 single reads and 12 listings (PRD 4)."""

from flask import Blueprint, request

import derive
import serialize
from auth import ALL_ROLES, FINANCIAL_READ_ROLES, authenticate, fetch
from envelope import ok, page_params, window
from errors import ApiError
from serialize import certification_status
from store import store, ordered

read = Blueprint("read", __name__)


def _str_filter(rows, field, param=None):
    value = request.args.get(param or field)
    if value is None:
        return rows
    return [r for r in rows if r.get(field) == value]


def _int_filter(rows, field):
    raw = request.args.get(field)
    if raw is None:
        return rows
    try:
        value = int(str(raw).strip())
    except (TypeError, ValueError):
        raise ApiError("ERR_INVALID_REQUEST", "%s must be an integer." % field)
    return [r for r in rows if r.get(field) == value]


def _bool_filter(rows, field):
    raw = request.args.get(field)
    if raw is None:
        return rows
    text = str(raw).strip().lower()
    if text not in ("true", "false"):
        raise ApiError("ERR_INVALID_REQUEST", "%s must be true or false." % field)
    value = text == "true"
    return [r for r in rows if bool(r.get(field)) == value]


# --- single reads ----------------------------------------------------------

@read.get("/members/<row_id>")
def get_member(row_id):
    authenticate(ALL_ROLES)
    return ok(serialize.member(fetch("member", row_id)))


@read.get("/leagues/<row_id>")
def get_league(row_id):
    authenticate(ALL_ROLES)
    return ok(serialize.league(fetch("league", row_id)))


@read.get("/teams/<row_id>")
def get_team(row_id):
    authenticate(ALL_ROLES)
    return ok(serialize.team(fetch("team", row_id)))


@read.get("/memberships/<row_id>")
def get_membership(row_id):
    authenticate(ALL_ROLES)
    return ok(serialize.membership(fetch("membership", row_id)))


@read.get("/fee-remittances/<row_id>")
def get_fee_remittance(row_id):
    authenticate(FINANCIAL_READ_ROLES)
    return ok(serialize.fee_remittance(fetch("fee_remittance", row_id)))


@read.get("/lane-pairs/<row_id>")
def get_lane_pair(row_id):
    authenticate(ALL_ROLES)
    return ok(serialize.lane_pair(fetch("lane_pair", row_id)))


@read.get("/matches/<row_id>")
def get_match(row_id):
    authenticate(ALL_ROLES)
    return ok(serialize.match(fetch("match", row_id)))


@read.get("/series-entries/<row_id>")
def get_series_entry(row_id):
    authenticate(ALL_ROLES)
    return ok(serialize.series_entry(fetch("series_entry", row_id)))


@read.get("/dues-payments/<row_id>")
def get_dues_payment(row_id):
    authenticate(FINANCIAL_READ_ROLES)
    return ok(serialize.dues_payment(fetch("dues_payment", row_id)))


@read.get("/prize-funds/<row_id>")
def get_prize_fund(row_id):
    authenticate(ALL_ROLES)
    return ok(serialize.prize_fund(fetch("prize_fund", row_id)))


@read.get("/prize-awards/<row_id>")
def get_prize_award(row_id):
    authenticate(ALL_ROLES)
    return ok(serialize.prize_award(fetch("prize_award", row_id)))


@read.get("/award-applications/<row_id>")
def get_award_application(row_id):
    authenticate(ALL_ROLES)
    return ok(serialize.award_application(fetch("award_application", row_id)))


@read.get("/protests/<row_id>")
def get_protest(row_id):
    authenticate(ALL_ROLES)
    return ok(serialize.protest(fetch("protest", row_id)))


# --- listings --------------------------------------------------------------

@read.get("/leagues")
def list_leagues():
    authenticate(ALL_ROLES)
    limit, offset = page_params()
    rows = ordered(store.leagues.values())
    rows = _int_filter(rows, "season_year")
    rows = _str_filter(rows, "status")
    rows = _str_filter(rows, "secretary_member_id")
    rows = _str_filter(rows, "treasurer_member_id")
    return window(rows, limit, offset, serialize.league)


@read.get("/leagues/<league_id>/teams")
def list_league_teams(league_id):
    authenticate(ALL_ROLES)
    league = fetch("league", league_id)
    limit, offset = page_params()
    rows = derive.teams_of_league(league["id"])
    rows = _str_filter(rows, "status")
    return window(rows, limit, offset, serialize.team)


@read.get("/memberships")
def list_memberships():
    authenticate(ALL_ROLES)
    limit, offset = page_params()
    rows = ordered(store.memberships.values())
    rows = _str_filter(rows, "league_id")
    rows = _str_filter(rows, "member_id")
    rows = _str_filter(rows, "team_id")
    rows = _str_filter(rows, "sanction_status")
    rows = _str_filter(rows, "remittance_status")
    return window(rows, limit, offset, serialize.membership)


@read.get("/fee-remittances")
def list_fee_remittances():
    authenticate(FINANCIAL_READ_ROLES)
    limit, offset = page_params()
    rows = ordered(store.fee_remittances.values())
    rows = _str_filter(rows, "league_id")
    rows = _str_filter(rows, "status")
    return window(rows, limit, offset, serialize.fee_remittance)


@read.get("/lane-pairs")
def list_lane_pairs():
    authenticate(ALL_ROLES)
    limit, offset = page_params()
    rows = ordered(store.lane_pairs.values())
    rows = _str_filter(rows, "league_id")
    wanted = request.args.get("certification_status")
    if wanted is not None:
        rows = [r for r in rows if certification_status(r) == wanted]
    return window(rows, limit, offset, serialize.lane_pair)


@read.get("/matches")
def list_matches():
    authenticate(ALL_ROLES)
    limit, offset = page_params()
    rows = ordered(store.matches.values())
    rows = _str_filter(rows, "league_id")
    rows = _int_filter(rows, "week_number")
    rows = _str_filter(rows, "home_team_id")
    rows = _str_filter(rows, "away_team_id")
    rows = _str_filter(rows, "lane_pair_id")
    rows = _str_filter(rows, "forfeiting_team_id")
    rows = _str_filter(rows, "status")
    return window(rows, limit, offset, serialize.match)


@read.get("/series-entries")
def list_series_entries():
    authenticate(ALL_ROLES)
    limit, offset = page_params()
    rows = sorted(store.series_entries.values(),
                  key=lambda r: (r["team_id"], r["position"], r["_seq"]))
    rows = _str_filter(rows, "match_id")
    rows = _str_filter(rows, "team_id")
    rows = _str_filter(rows, "membership_id")
    rows = _str_filter(rows, "entry_type")
    rows = _bool_filter(rows, "certified")
    return window(rows, limit, offset, serialize.series_entry)


@read.get("/dues-payments")
def list_dues_payments():
    authenticate(FINANCIAL_READ_ROLES)
    limit, offset = page_params()
    rows = ordered(store.dues_payments.values())
    rows = _str_filter(rows, "membership_id")
    rows = _int_filter(rows, "week_number")
    return window(rows, limit, offset, serialize.dues_payment)


@read.get("/prize-funds")
def list_prize_funds():
    authenticate(ALL_ROLES)
    limit, offset = page_params()
    rows = ordered(store.prize_funds.values())
    rows = _str_filter(rows, "league_id")
    rows = _str_filter(rows, "status")
    return window(rows, limit, offset, serialize.prize_fund)


@read.get("/prize-awards")
def list_prize_awards():
    authenticate(ALL_ROLES)
    limit, offset = page_params()
    rows = sorted(store.prize_awards.values(),
                  key=lambda r: (r["place"], r["_seq"]))
    rows = _str_filter(rows, "prize_fund_id")
    rows = _str_filter(rows, "team_id")
    rows = _str_filter(rows, "status")
    return window(rows, limit, offset, serialize.prize_award)


@read.get("/award-applications")
def list_award_applications():
    authenticate(ALL_ROLES)
    limit, offset = page_params()
    rows = ordered(store.award_applications.values())
    rows = _str_filter(rows, "league_id")
    rows = _str_filter(rows, "membership_id")
    rows = _str_filter(rows, "series_entry_id")
    rows = _str_filter(rows, "award_type")
    rows = _str_filter(rows, "status")
    return window(rows, limit, offset, serialize.award_application)


@read.get("/protests")
def list_protests():
    authenticate(ALL_ROLES)
    limit, offset = page_params()
    rows = ordered(store.protests.values())
    rows = _str_filter(rows, "league_id")
    rows = _str_filter(rows, "match_id")
    rows = _str_filter(rows, "filed_by_membership_id")
    rows = _str_filter(rows, "category")
    rows = _str_filter(rows, "status")
    return window(rows, limit, offset, serialize.protest)
