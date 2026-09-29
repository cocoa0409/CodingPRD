"""Registry, charter, bylaws, schedule, teams, enrolment, lanes, clock."""

from decimal import Decimal

from flask import Blueprint

import calc
import derive
import serialize
import shape
from auth import (authenticate, body_ref, fetch, require_secretary)
from clock import clock, parse_instant
from envelope import ok
from errors import ApiError
from store import store, insert, touch, apply_changes

core = Blueprint("core", __name__)

LEAGUE_ROLES = ["LeagueSecretary"]
BYLAW_FIELDS = [
    "handicap_base", "handicap_percentage", "handicap_percentage_youth",
    "max_handicap_per_game", "handicap_average_basis",
    "minimum_games_for_average", "carryover_policy", "vacancy_average",
    "vacancy_score", "absentee_deduction", "lineup_positions",
    "legal_lineup_minimum", "max_vacancy_slots_per_lineup",
    "weekly_dues_cents", "weekly_expense_cents", "max_dues_arrears_weeks",
    "prize_place_weights",
]


# --------------------------------------------------------------- /members ---
@core.post("/members")
def register_member():
    authenticate(["AssociationOfficer"])
    payload = shape.body()
    full_name = shape.req_str(payload, "full_name", 1, 120)
    email = shape.req_str(payload, "email")
    if "@" not in email:
        shape.bad("email must contain an at-sign.")
    member_class = shape.req_enum(payload, "member_class", ["ADULT", "YOUTH"])
    for existing in store.members.values():
        if existing["email"] == email:
            shape.bad("email is already registered.")
    row = insert(store.members, {
        "full_name": full_name,
        "email": email,
        "member_class": member_class,
        "national_member_number": None,
        "sanctioned_membership_count": 0,
    })
    return ok(serialize.member(row), 201)


# --------------------------------------------------------------- /leagues ---
@core.post("/leagues")
def charter_league():
    uid, role = authenticate(LEAGUE_ROLES)
    payload = shape.body()
    secretary = body_ref("member", payload.get("secretary_member_id"))
    body_ref("member", payload.get("treasurer_member_id"))
    if secretary is not None and secretary["id"] != uid:
        raise ApiError("ERR_NOT_LEAGUE_SECRETARY")
    name = shape.req_str(payload, "name", 1, 120)
    season_year = shape.req_int(payload, "season_year", 2000, 2100)
    center_name = shape.req_str(payload, "center_name")
    declared_team_count = shape.req_int(payload, "declared_team_count", 2, 24)
    organizational_meeting_at = shape.req_instant(
        payload, "organizational_meeting_at")
    secretary_member_id = shape.req_id(payload, "secretary_member_id")
    treasurer_member_id = shape.req_id(payload, "treasurer_member_id")
    row = {
        "name": name,
        "season_year": season_year,
        "center_name": center_name,
        "declared_team_count": declared_team_count,
        "organizational_meeting_at": organizational_meeting_at,
        "secretary_member_id": secretary_member_id,
        "treasurer_member_id": treasurer_member_id,
        "status": "FORMING",
        "bylaws_adopted_at": None,
        "total_weeks": 0,
        "sanctioned_member_count": 0,
        "confirmed_team_count": 0,
        "certified_week_high_water": 0,
    }
    for field in BYLAW_FIELDS:
        row[field] = None
    insert(store.leagues, row)
    insert(store.prize_funds, {
        "league_id": row["id"],
        "status": "ACCUMULATING",
        "collected_prize_cents": 0,
        "basis_variant": "PROJECTED_SEASON_END",
        "place_count": 0,
        "plan_basis_cents": 0,
        "reserve_cents": 0,
        "admin_fee_cents": 0,
        "net_distributable_cents": 0,
        "paid_award_total_cents": 0,
        "undistributed_balance_cents": 0,
        "plan_drafted_at": None,
        "plan_approved_by_user_id": None,
        "disbursed_at": None,
    })
    return ok(serialize.league(row), 201)


def parse_bylaws(payload):
    values = {}
    values["handicap_base"] = shape.req_int(payload, "handicap_base", 180, 300)
    values["handicap_percentage"] = shape.req_percentage(
        payload, "handicap_percentage", "0.50", "1.00")
    values["handicap_percentage_youth"] = shape.req_percentage(
        payload, "handicap_percentage_youth", "0.50", "1.00")
    values["max_handicap_per_game"] = shape.req_int(
        payload, "max_handicap_per_game", 0, 120)
    values["handicap_average_basis"] = shape.req_enum(
        payload, "handicap_average_basis", ["ENTERING", "CURRENT"])
    values["minimum_games_for_average"] = shape.req_int(
        payload, "minimum_games_for_average", 1, 30)
    values["carryover_policy"] = shape.req_enum(
        payload, "carryover_policy", ["NONE", "PRIOR_SEASON_FULL", "BLENDED"])
    values["vacancy_average"] = shape.req_int(payload, "vacancy_average", 0, 300)
    values["vacancy_score"] = shape.req_int(payload, "vacancy_score", 0, 300)
    values["absentee_deduction"] = shape.req_int(
        payload, "absentee_deduction", 0, 50)
    values["lineup_positions"] = shape.req_int(payload, "lineup_positions", 2, 6)
    values["legal_lineup_minimum"] = shape.req_int(
        payload, "legal_lineup_minimum", 1, 6)
    values["max_vacancy_slots_per_lineup"] = shape.req_int(
        payload, "max_vacancy_slots_per_lineup", 0, 3)
    values["weekly_dues_cents"] = shape.req_int(
        payload, "weekly_dues_cents", 0, 10000)
    values["weekly_expense_cents"] = shape.req_int(
        payload, "weekly_expense_cents", 0, 10000)
    values["max_dues_arrears_weeks"] = shape.req_int(
        payload, "max_dues_arrears_weeks", 0, 10)
    raw_weights = shape.req_list(payload, "prize_place_weights", 1, 12)
    weights = []
    for element in raw_weights:
        weight = shape.to_decimal(element, "prize_place_weights")
        if weight < Decimal("0.01") or weight > Decimal("1.00"):
            shape.bad("every prize_place_weights element is 0.01 through 1.00.")
        if -weight.as_tuple().exponent > 2:
            shape.bad("prize_place_weights elements carry two decimal places.")
        weights.append(weight)
    if sum(weights) != Decimal("1.00"):
        shape.bad("prize_place_weights must sum to exactly 1.00.")
    values["prize_place_weights"] = weights
    # cross-field bylaw coherence (PRD 2.7)
    if values["legal_lineup_minimum"] > values["lineup_positions"]:
        shape.bad("legal_lineup_minimum must not exceed lineup_positions.")
    if values["max_vacancy_slots_per_lineup"] >= values["lineup_positions"]:
        shape.bad("max_vacancy_slots_per_lineup must be below lineup_positions.")
    if values["weekly_expense_cents"] > values["weekly_dues_cents"]:
        shape.bad("weekly_expense_cents must not exceed weekly_dues_cents.")
    if values["vacancy_average"] > values["handicap_base"]:
        shape.bad("vacancy_average must not exceed handicap_base.")
    return values


@core.post("/leagues/<league_id>/bylaws")
def adopt_bylaws(league_id):
    uid, role = authenticate(LEAGUE_ROLES)
    league = fetch("league", league_id)
    require_secretary(league, uid, role)
    payload = shape.body()
    expected = shape.req_int(payload, "expected_league_version", 0)
    values = parse_bylaws(payload)
    if expected != league["version"]:
        raise ApiError("ERR_STALE_LEAGUE_VERSION")
    if league["status"] not in ("FORMING", "BYLAWS_ADOPTED", "IN_SEASON"):
        raise ApiError("ERR_LEAGUE_STATE_INVALID")
    for field, value in values.items():
        league[field] = value
    league["bylaws_adopted_at"] = clock.now()
    if league["status"] == "FORMING":
        league["status"] = "BYLAWS_ADOPTED"
    touch(league)
    derive.recompute_whole_league(league)
    return ok(serialize.league(league))


# ------------------------------------------------------------- /schedule ----
def _parse_match_element(element):
    if not isinstance(element, dict):
        shape.bad("every element of matches must be an object.")
    parsed = {
        "week_number": shape.req_int(element, "week_number", 1, 40),
        "home_team_id": shape.req_id(element, "home_team_id"),
        "away_team_id": shape.req_id(element, "away_team_id"),
        "lane_pair_id": shape.req_id(element, "lane_pair_id"),
        "starts_at": shape.req_instant(element, "starts_at"),
        "ends_at": shape.req_instant(element, "ends_at"),
    }
    if parsed["ends_at"] <= parsed["starts_at"]:
        shape.bad("ends_at must be strictly later than starts_at.")
    return parsed


def _overlaps(a_start, a_end, b_start, b_end):
    return a_start < b_end and b_start < a_end


@core.post("/leagues/<league_id>/schedule")
def adopt_schedule(league_id):
    uid, role = authenticate(LEAGUE_ROLES)
    league = fetch("league", league_id)
    require_secretary(league, uid, role)
    payload = shape.body()
    raw = payload.get("matches")
    if isinstance(raw, list):
        for element in raw:
            if isinstance(element, dict):
                body_ref("team", element.get("home_team_id"))
                body_ref("team", element.get("away_team_id"))
                body_ref("lane_pair", element.get("lane_pair_id"))
    total_weeks = shape.req_int(payload, "total_weeks", 0)
    elements = shape.req_list(payload, "matches", 1)
    parsed = [_parse_match_element(element) for element in elements]
    for entry in parsed:
        for field, kind in (("home_team_id", "team"), ("away_team_id", "team"),
                            ("lane_pair_id", "lane_pair")):
            row = fetch(kind, entry[field])
            if row["league_id"] != league["id"]:
                raise ApiError("ERR_CROSS_LEAGUE_REFERENCE")
    if league["status"] != "BYLAWS_ADOPTED":
        raise ApiError("ERR_LEAGUE_STATE_INVALID")
    existing = [m for m in store.matches.values()
                if m["status"] not in ("VOID", "FORFEITED")]
    for index, entry in enumerate(parsed):
        for other in existing:
            if other["lane_pair_id"] == entry["lane_pair_id"] and _overlaps(
                    entry["starts_at"], entry["ends_at"],
                    other["starts_at"], other["ends_at"]):
                raise ApiError("ERR_LANE_PAIR_CONFLICT")
        for other in parsed[index + 1:]:
            if other["lane_pair_id"] == entry["lane_pair_id"] and _overlaps(
                    entry["starts_at"], entry["ends_at"],
                    other["starts_at"], other["ends_at"]):
                raise ApiError("ERR_LANE_PAIR_CONFLICT")
    referenced = set()
    for entry in parsed:
        if entry["home_team_id"] == entry["away_team_id"]:
            raise ApiError("ERR_TEAM_COUNT_MISMATCH")
        referenced.add(entry["home_team_id"])
        referenced.add(entry["away_team_id"])
    if len(referenced) != league["declared_team_count"]:
        raise ApiError("ERR_TEAM_COUNT_MISMATCH")
    created = []
    for entry in parsed:
        created.append(insert(store.matches, {
            "league_id": league["id"],
            "week_number": entry["week_number"],
            "home_team_id": entry["home_team_id"],
            "away_team_id": entry["away_team_id"],
            "lane_pair_id": entry["lane_pair_id"],
            "forfeiting_team_id": None,
            "starts_at": entry["starts_at"],
            "ends_at": entry["ends_at"],
            "status": "DRAFT",
            "home_team_handicap_per_game": 0,
            "away_team_handicap_per_game": 0,
            "home_points": 0.0,
            "away_points": 0.0,
            "certified_at": None,
            "void_reason": None,
        }))
    apply_changes(league, {"total_weeks": total_weeks})
    derive.recompute_league_counters(league)
    return ok([serialize.match(m) for m in created], 201)


@core.post("/leagues/<league_id>/close-season")
def close_season(league_id):
    uid, role = authenticate(LEAGUE_ROLES)
    league = fetch("league", league_id)
    require_secretary(league, uid, role)
    if league["status"] != "IN_SEASON":
        raise ApiError("ERR_LEAGUE_STATE_INVALID")
    for match in derive.matches_of_league(league["id"]):
        if match["status"] not in derive.SETTLED_MATCH:
            raise ApiError("ERR_LEAGUE_STATE_INVALID",
                           "Every match must be settled before the season closes.")
    league["status"] = "SEASON_CLOSED"
    touch(league)
    return ok(serialize.league(league))


# ----------------------------------------------------------------- /teams ---
@core.post("/teams")
def enter_team():
    uid, role = authenticate(LEAGUE_ROLES)
    payload = shape.body()
    league = body_ref("league", payload.get("league_id"))
    if league is not None:
        require_secretary(league, uid, role)
    league_id = shape.req_id(payload, "league_id")
    name = shape.req_str(payload, "name", 1, 80)
    league = fetch("league", league_id)
    for team in store.teams.values():
        if team["league_id"] == league["id"] and team["name"] == name:
            shape.bad("name is already used by a team of this league.")
    if league["status"] not in ("FORMING", "BYLAWS_ADOPTED"):
        raise ApiError("ERR_LEAGUE_STATE_INVALID")
    row = insert(store.teams, {
        "league_id": league["id"],
        "name": name,
        "status": "PROVISIONAL",
        "sanctioned_roster_count": 0,
        "team_handicap_per_game": 0,
        "total_points": 0.0,
        "total_scratch_pins": 0,
    })
    return ok(serialize.team(row), 201)


# ----------------------------------------------------------- /memberships ---
@core.post("/memberships")
def enrol_membership():
    uid, role = authenticate(LEAGUE_ROLES)
    payload = shape.body()
    league = body_ref("league", payload.get("league_id"))
    member = body_ref("member", payload.get("member_id"))
    team = body_ref("team", payload.get("team_id"))
    if league is not None:
        require_secretary(league, uid, role)
    league_id = shape.req_id(payload, "league_id")
    member_id = shape.req_id(payload, "member_id")
    team_id = shape.opt_id(payload, "team_id")
    roster_role = shape.req_enum(payload, "roster_role",
                                 ["REGULAR", "SUBSTITUTE"])
    prior_average = shape.opt_int(payload, "prior_season_average", 0, 300)
    prior_games = shape.opt_int(payload, "prior_season_games", 0, 200, 0)
    league = fetch("league", league_id)
    member = fetch("member", member_id)
    if team_id is not None:
        team = fetch("team", team_id)
        if team["league_id"] != league["id"]:
            raise ApiError("ERR_CROSS_LEAGUE_REFERENCE")
    if league["status"] not in ("FORMING", "BYLAWS_ADOPTED"):
        raise ApiError("ERR_LEAGUE_STATE_INVALID")
    for existing in store.memberships.values():
        if (existing["league_id"] == league["id"]
                and existing["member_id"] == member["id"]):
            raise ApiError("ERR_DUPLICATE_MEMBERSHIP")
    row = insert(store.memberships, {
        "league_id": league["id"],
        "member_id": member["id"],
        "team_id": team_id,
        "roster_role": roster_role,
        "sanction_status": "UNSANCTIONED",
        "remittance_status": "UNPAID",
        "prior_season_average": prior_average,
        "prior_season_games": prior_games,
        "entering_average": calc.entering_average(league, prior_average,
                                                  prior_games),
        "certified_games": 0,
        "certified_pins": 0,
        "current_average": None,
        "average_status": "PROVISIONAL",
        "handicap_per_game": 0,
        "dues_paid_cents": 0,
        "dues_arrears_weeks": 0,
    })
    status, current = calc.bowler_average(league, 0, 0, row["entering_average"],
                                          prior_games)
    row["average_status"] = status
    row["current_average"] = current
    return ok(serialize.membership(row), 201)


# ------------------------------------------------------------ /lane-pairs ---
@core.post("/lane-pairs")
def register_lane_pair():
    authenticate(["AssociationOfficer"])
    payload = shape.body()
    body_ref("league", payload.get("league_id"))
    league_id = shape.req_id(payload, "league_id")
    pair_number = shape.req_int(payload, "pair_number", 1, 60)
    certified_through = shape.req_instant(payload, "certified_through")
    league = fetch("league", league_id)
    for pair in store.lane_pairs.values():
        if pair["league_id"] == league["id"] \
                and pair["pair_number"] == pair_number:
            shape.bad("pair_number is already registered for this league.")
    if league["status"] not in ("FORMING", "BYLAWS_ADOPTED"):
        raise ApiError("ERR_LEAGUE_STATE_INVALID")
    row = insert(store.lane_pairs, {
        "league_id": league["id"],
        "pair_number": pair_number,
        "certified_through": certified_through,
        "revoked_at": None,
        "last_certified_at": clock.now(),
    })
    return ok(serialize.lane_pair(row), 201)


@core.post("/lane-pairs/<pair_id>/certification")
def lane_pair_certification(pair_id):
    authenticate(["AssociationOfficer"])
    pair = fetch("lane_pair", pair_id)
    payload = shape.body()
    action = shape.req_enum(payload, "action", ["RECERTIFY", "REVOKE"])
    certified_through = None
    if action == "RECERTIFY":
        certified_through = shape.req_instant(payload, "certified_through")
        if certified_through <= clock.now():
            shape.bad("certified_through must be strictly later than now.")
    else:
        shape.forbid(payload, "certified_through", "when action is REVOKE")
    if action == "RECERTIFY":
        if pair["revoked_at"] is not None:
            raise ApiError("ERR_LANE_PAIR_NOT_CERTIFIED")
        pair["certified_through"] = certified_through
        pair["last_certified_at"] = clock.now()
    else:
        pair["revoked_at"] = clock.now()
    touch(pair)
    return ok(serialize.lane_pair(pair))


# ---------------------------------------------------------------- /_clock ---
@core.post("/_clock/set_current_utc")
def set_clock():
    authenticate(["AssociationOfficer"])
    payload = shape.body()
    instant = shape.req_instant(payload, "current_utc")
    clock.set(instant)
    return ok({})
