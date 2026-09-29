"""Match night: lineups, opening, scoring, certification, forfeit (PRD 3.4, 3.5)."""

from datetime import timedelta

from flask import Blueprint

import calc
import derive
import serialize
import shape
from auth import (authenticate, body_ref, fetch, require_captain_of_team,
                  require_secretary)
from clock import clock
from envelope import ok
from errors import ApiError
from serialize import certification_status
from store import store, insert, touch, apply_changes

matches = Blueprint("matches", __name__)

SUBMITTABLE = ["REGULAR", "SUBSTITUTE", "VACANCY", "ABSENTEE", "PREBOWL"]
BOWLING_TYPES = ("REGULAR", "SUBSTITUTE", "PREBOWL")
LINEUP_ROLES = ["TeamCaptain", "LeagueSecretary"]
BUFFER = timedelta(minutes=calc.TRAVEL_BUFFER_MINUTES)


def _parse_slot(element):
    if not isinstance(element, dict):
        shape.bad("every element of slots must be an object.")
    entry_type = shape.req_enum(element, "entry_type", SUBMITTABLE)
    position = element.get("position")
    if not shape.present(element, "position"):
        shape.bad("position is required.")
    position = shape.as_int(position, "position")
    if entry_type == "VACANCY":
        shape.forbid(element, "membership_id", "on a VACANCY slot")
        membership_id = None
    else:
        membership_id = shape.req_id(element, "membership_id")
    if entry_type == "PREBOWL":
        prebowled_at = shape.req_instant(element, "prebowled_at")
    else:
        shape.forbid(element, "prebowled_at", "on a slot that is not PREBOWL")
        prebowled_at = None
    return {
        "position": position,
        "entry_type": entry_type,
        "membership_id": membership_id,
        "prebowled_at": prebowled_at,
    }


def _frozen_handicap(league, slot, membership):
    entry_type = slot["entry_type"]
    if entry_type in BOWLING_TYPES:
        return membership["handicap_per_game"]
    if entry_type == "VACANCY":
        return calc.vacancy_handicap(league)
    if entry_type == "ABSENTEE":
        member = store.members[membership["member_id"]]
        return calc.absentee_handicap(league, membership["entering_average"],
                                      membership["current_average"],
                                      member["member_class"])
    return 0


@matches.post("/matches/<match_id>/lineups")
def submit_lineup(match_id):
    uid, role = authenticate(LINEUP_ROLES)
    match = fetch("match", match_id)
    league = store.leagues[match["league_id"]]
    payload = shape.body()
    team = body_ref("team", payload.get("team_id"))
    raw_slots = payload.get("slots")
    if isinstance(raw_slots, list):
        for element in raw_slots:
            if isinstance(element, dict):
                body_ref("membership", element.get("membership_id"))
    require_secretary(league, uid, role)
    if role == "TeamCaptain" and team is not None:
        require_captain_of_team(uid, league["id"], team["id"])
    expected = shape.req_int(payload, "expected_match_version", 0)
    team_id = shape.req_id(payload, "team_id")
    elements = shape.req_list(payload, "slots", 1)
    slots = [_parse_slot(element) for element in elements]
    team = fetch("team", team_id)
    named = {}
    for slot in slots:
        if slot["membership_id"] is not None:
            named[slot["membership_id"]] = fetch("membership",
                                                 slot["membership_id"])
    if team["league_id"] != league["id"]:
        raise ApiError("ERR_CROSS_LEAGUE_REFERENCE")
    for membership in named.values():
        if membership["league_id"] != league["id"]:
            raise ApiError("ERR_CROSS_LEAGUE_REFERENCE")
    if team_id not in (match["home_team_id"], match["away_team_id"]):
        raise ApiError("ERR_REFERENCE_MISMATCH")
    if expected != match["version"]:
        raise ApiError("ERR_STALE_MATCH_VERSION")
    if league["status"] not in ("SANCTIONED", "IN_SEASON"):
        raise ApiError("ERR_LEAGUE_STATE_INVALID")
    if match["status"] not in ("DRAFT", "SCHEDULED", "LINEUPS_SUBMITTED"):
        raise ApiError("ERR_MATCH_STATE_INVALID")
    opponent_id = (match["away_team_id"] if team_id == match["home_team_id"]
                   else match["home_team_id"])
    opponent = store.teams[opponent_id]
    if team["status"] != "CONFIRMED" or opponent["status"] != "CONFIRMED":
        raise ApiError("ERR_TEAM_NOT_CONFIRMED")
    for slot in slots:
        if slot["entry_type"] in BOWLING_TYPES:
            membership = named[slot["membership_id"]]
            if membership["sanction_status"] != "SANCTIONED":
                raise ApiError("ERR_BOWLER_NOT_SANCTIONED")
    # check 28 - the travel-buffer double-booking gate
    for membership_id in named:
        for other in store.series_entries.values():
            if other["membership_id"] != membership_id:
                continue
            if other["match_id"] == match["id"]:
                continue
            other_match = store.matches.get(other["match_id"])
            if other_match is None or other_match["status"] == "VOID":
                continue
            widened_start = other_match["starts_at"] - BUFFER
            widened_end = other_match["ends_at"] + BUFFER
            if widened_start <= match["ends_at"] and \
                    match["starts_at"] <= widened_end:
                raise ApiError("ERR_BOWLER_SCHEDULE_CONFLICT")
    for slot in slots:
        if slot["entry_type"] == "PREBOWL":
            if slot["prebowled_at"] >= match["starts_at"]:
                raise ApiError("ERR_PREBOWL_NOT_BEFORE_MATCH")
    positions = league["lineup_positions"]
    if len(slots) != positions:
        raise ApiError("ERR_ILLEGAL_LINEUP")
    if sorted(s["position"] for s in slots) != list(range(1, positions + 1)):
        raise ApiError("ERR_ILLEGAL_LINEUP")
    bowling = len([s for s in slots if s["entry_type"] in BOWLING_TYPES])
    if bowling < league["legal_lineup_minimum"]:
        raise ApiError("ERR_ILLEGAL_LINEUP")
    empties = len([s for s in slots
                   if s["entry_type"] in ("VACANCY", "ABSENTEE")])
    if empties > league["max_vacancy_slots_per_lineup"]:
        raise ApiError("ERR_VACANCY_LIMIT_EXCEEDED")
    listed = [s["membership_id"] for s in slots if s["membership_id"]]
    if len(set(listed)) != len(listed):
        raise ApiError("ERR_DUPLICATE_BOWLER_IN_LINEUP")
    opposing_slots = derive.side_slots(match["id"], opponent_id)
    opposing_members = set(s["membership_id"] for s in opposing_slots
                           if s["membership_id"])
    for membership_id in listed:
        if membership_id in opposing_members:
            raise ApiError("ERR_DUPLICATE_BOWLER_IN_LINEUP")
    for slot in slots:
        if slot["entry_type"] != "SUBSTITUTE":
            continue
        membership = named[slot["membership_id"]]
        if membership["league_id"] != league["id"] \
                or membership["sanction_status"] != "SANCTIONED":
            raise ApiError("ERR_SUBSTITUTE_NOT_ELIGIBLE")
        if membership["team_id"] is not None \
                and membership["team_id"] == opponent_id:
            raise ApiError("ERR_SUBSTITUTE_NOT_ELIGIBLE")
    for membership in named.values():
        if membership["dues_arrears_weeks"] > league["max_dues_arrears_weeks"]:
            raise ApiError("ERR_DUES_ARREARS_BLOCK")
    # side effects
    for existing in derive.side_slots(match["id"], team_id):
        del store.series_entries[existing["id"]]
    for slot in sorted(slots, key=lambda s: s["position"]):
        membership = named.get(slot["membership_id"])
        insert(store.series_entries, {
            "match_id": match["id"],
            "team_id": team_id,
            "membership_id": slot["membership_id"],
            "position": slot["position"],
            "entry_type": slot["entry_type"],
            "prebowled_at": slot["prebowled_at"],
            "game1_pins": None,
            "game2_pins": None,
            "game3_pins": None,
            "games_recorded": 0,
            "scratch_series": 0,
            "handicap_per_game_applied": _frozen_handicap(league, slot,
                                                          membership),
            "counts_toward_average": (slot["entry_type"] in BOWLING_TYPES
                                      and slot["membership_id"] is not None),
            "certified": False,
        })
    side = "home" if team_id == match["home_team_id"] else "away"
    match[side + "_team_handicap_per_game"] = sum(
        s["handicap_per_game_applied"]
        for s in derive.side_slots(match["id"], team_id))
    if match["status"] in ("DRAFT", "SCHEDULED") and opposing_slots:
        match["status"] = "LINEUPS_SUBMITTED"
    touch(match)
    return ok(serialize.match(match))


@matches.post("/matches/<match_id>/open")
def open_match(match_id):
    uid, role = authenticate(["LeagueSecretary"])
    match = fetch("match", match_id)
    league = store.leagues[match["league_id"]]
    require_secretary(league, uid, role)
    if league["status"] not in ("SANCTIONED", "IN_SEASON"):
        raise ApiError("ERR_LEAGUE_STATE_INVALID")
    if match["status"] != "LINEUPS_SUBMITTED":
        raise ApiError("ERR_MATCH_STATE_INVALID")
    pair = store.lane_pairs[match["lane_pair_id"]]
    if certification_status(pair) != "CERTIFIED":
        raise ApiError("ERR_LANE_PAIR_NOT_CERTIFIED")
    if pair["certified_through"] < match["starts_at"]:
        raise ApiError("ERR_LANE_CERTIFICATION_EXPIRED")
    match["status"] = "OPEN"
    touch(match)
    if league["status"] == "SANCTIONED":
        league["status"] = "IN_SEASON"
        touch(league)
    return ok(serialize.match(match))


def _side_total(match, league, team_id, game_field):
    total = 0
    for slot in derive.side_slots(match["id"], team_id):
        if slot["entry_type"] == "VACANCY":
            total += league["vacancy_score"]
        elif slot["entry_type"] == "FORFEIT":
            total += 0
        else:
            total += slot[game_field] or 0
    side = "home" if team_id == match["home_team_id"] else "away"
    return total + match[side + "_team_handicap_per_game"]


def _compute_points(match, league):
    home_points = 0.0
    away_points = 0.0
    home_series = 0
    away_series = 0
    for index in (1, 2, 3):
        field = "game%d_pins" % index
        home_total = _side_total(match, league, match["home_team_id"], field)
        away_total = _side_total(match, league, match["away_team_id"], field)
        home_series += home_total
        away_series += away_total
        if home_total > away_total:
            home_points += 1
        elif away_total > home_total:
            away_points += 1
        else:
            home_points += 0.5
            away_points += 0.5
    if home_series > away_series:
        home_points += 1
    elif away_series > home_series:
        away_points += 1
    else:
        home_points += 0.5
        away_points += 0.5
    return round(home_points, 1), round(away_points, 1)


@matches.post("/matches/<match_id>/scores")
def enter_scores(match_id):
    uid, role = authenticate(["LeagueSecretary"])
    match = fetch("match", match_id)
    league = store.leagues[match["league_id"]]
    require_secretary(league, uid, role)
    payload = shape.body()
    elements = shape.req_list(payload, "entries", 1)
    parsed = []
    for element in elements:
        if not isinstance(element, dict):
            shape.bad("every element of entries must be an object.")
        entry_id = shape.req_id(element, "series_entry_id")
        pins = []
        for field in ("game1_pins", "game2_pins", "game3_pins"):
            if shape.present(element, field):
                pins.append(shape.as_int(element[field], field, 0))
            else:
                pins.append(None)
        parsed.append((entry_id, pins))
    if league["status"] != "IN_SEASON":
        raise ApiError("ERR_LEAGUE_STATE_INVALID")
    if match["status"] != "OPEN":
        raise ApiError("ERR_MATCH_STATE_INVALID")
    slots = derive.slots_of_match(match["id"])
    by_id = dict((slot["id"], slot) for slot in slots)
    seen = set()
    for entry_id, pins in parsed:
        slot = by_id.get(entry_id)
        if slot is None or entry_id in seen:
            raise ApiError("ERR_SCORE_SET_INVALID")
        seen.add(entry_id)
        if slot["entry_type"] == "VACANCY":
            raise ApiError("ERR_SCORE_SET_INVALID")
        for value in pins:
            if value is not None and value > 300:
                raise ApiError("ERR_SCORE_SET_INVALID")
    for slot in slots:
        if slot["entry_type"] in ("REGULAR", "SUBSTITUTE", "ABSENTEE") \
                and slot["id"] not in seen:
            raise ApiError("ERR_SCORE_SET_INVALID")
    supplied = dict(parsed)
    for slot in slots:
        if slot["entry_type"] not in BOWLING_TYPES:
            continue
        pins = supplied.get(slot["id"])
        if pins is None or any(value is None for value in pins):
            raise ApiError("ERR_SCORE_SET_INVALID")
    for slot in slots:
        if slot["id"] not in supplied:
            continue
        pins = supplied[slot["id"]]
        recorded = len([value for value in pins if value is not None])
        apply_changes(slot, {
            "game1_pins": pins[0],
            "game2_pins": pins[1],
            "game3_pins": pins[2],
            "games_recorded": recorded,
            "scratch_series": sum(value for value in pins if value is not None),
        })
    home_points, away_points = _compute_points(match, league)
    match["home_points"] = home_points
    match["away_points"] = away_points
    match["status"] = "SCORES_ENTERED"
    touch(match)
    return ok(serialize.match(match))


@matches.post("/matches/<match_id>/certify")
def certify_match(match_id):
    uid, role = authenticate(["LeagueSecretary"])
    match = fetch("match", match_id)
    league = store.leagues[match["league_id"]]
    require_secretary(league, uid, role)
    if league["status"] != "IN_SEASON":
        raise ApiError("ERR_LEAGUE_STATE_INVALID")
    if match["status"] != "SCORES_ENTERED":
        raise ApiError("ERR_MATCH_STATE_INVALID")
    slots = derive.slots_of_match(match["id"])
    for slot in slots:
        apply_changes(slot, {"certified": True})
    match["status"] = "CERTIFIED"
    match["certified_at"] = clock.now()
    touch(match)
    membership_ids = []
    team_ids = [match["home_team_id"], match["away_team_id"]]
    for slot in slots:
        if slot["counts_toward_average"] and slot["membership_id"]:
            if slot["membership_id"] not in membership_ids:
                membership_ids.append(slot["membership_id"])
            membership = store.memberships.get(slot["membership_id"])
            if membership and membership["team_id"] \
                    and membership["team_id"] not in team_ids:
                team_ids.append(membership["team_id"])
    derive.cascade_certification_change(league, membership_ids, team_ids)
    return ok(serialize.match(match))


def _write_forfeit_rows(match, league, team_id):
    """The preallocation procedure of PRD 3.5."""
    affected = []
    for existing in derive.side_slots(match["id"], team_id):
        if existing["membership_id"]:
            affected.append(existing["membership_id"])
        del store.series_entries[existing["id"]]
    for position in range(1, league["lineup_positions"] + 1):
        insert(store.series_entries, {
            "match_id": match["id"],
            "team_id": team_id,
            "membership_id": None,
            "position": position,
            "entry_type": "FORFEIT",
            "prebowled_at": None,
            "game1_pins": 0,
            "game2_pins": 0,
            "game3_pins": 0,
            "games_recorded": 0,
            "scratch_series": 0,
            "handicap_per_game_applied": 0,
            "counts_toward_average": False,
            "certified": False,
        })
    side = "home" if team_id == match["home_team_id"] else "away"
    match[side + "_team_handicap_per_game"] = 0
    return affected


@matches.post("/matches/<match_id>/forfeit")
def declare_forfeit(match_id):
    uid, role = authenticate(["LeagueSecretary"])
    match = fetch("match", match_id)
    league = store.leagues[match["league_id"]]
    require_secretary(league, uid, role)
    payload = shape.body()
    forfeiting_team_id = shape.req_id(payload, "forfeiting_team_id")
    if forfeiting_team_id not in (match["home_team_id"], match["away_team_id"]):
        raise ApiError("ERR_REFERENCE_MISMATCH")
    if match["status"] not in ("SCHEDULED", "LINEUPS_SUBMITTED", "OPEN"):
        raise ApiError("ERR_MATCH_STATE_INVALID")
    affected = _write_forfeit_rows(match, league, forfeiting_team_id)
    if forfeiting_team_id == match["home_team_id"]:
        match["home_points"] = 0.0
        match["away_points"] = float(calc.POINTS_PER_MATCH)
    else:
        match["away_points"] = 0.0
        match["home_points"] = float(calc.POINTS_PER_MATCH)
    match["status"] = "FORFEITED"
    match["forfeiting_team_id"] = forfeiting_team_id
    touch(match)
    derive.cascade_certification_change(
        league, affected, [match["home_team_id"], match["away_team_id"]])
    return ok(serialize.match(match))
