"""Protests, the hearing cycle and escalation to the association (PRD 3.9)."""

from flask import Blueprint

import calc
import derive
import serialize
import shape
from auth import (authenticate, body_ref, fetch, memberships_of_member,
                  require_own_membership, require_secretary)
from clock import clock, plus_hours
from envelope import ok
from errors import ApiError
from store import store, insert, touch, apply_changes

protests = Blueprint("protests", __name__)

CATEGORIES = ["LINEUP_LEGALITY", "SCORE_ERROR", "RULES_INTERPRETATION",
              "ELIGIBILITY"]
MATCH_CATEGORIES = ("LINEUP_LEGALITY", "SCORE_ERROR", "ELIGIBILITY")
REMEDIES = ["NONE", "VOID_MATCH", "FORFEIT_AWARD"]


@protests.post("/protests")
def file_protest():
    uid, role = authenticate(["Bowler", "TeamCaptain"])
    payload = shape.body()
    league = body_ref("league", payload.get("league_id"))
    match = body_ref("match", payload.get("match_id"))
    membership = body_ref("membership", payload.get("filed_by_membership_id"))
    if membership is not None:
        if role == "Bowler":
            require_own_membership(uid, membership)
        else:
            held = memberships_of_member(uid, membership["league_id"])
            if membership["team_id"] is not None:
                held = [m for m in held if m["team_id"] == membership["team_id"]]
            if not held:
                raise ApiError("ERR_NOT_RESOURCE_OWNER")
    league_id = shape.req_id(payload, "league_id")
    membership_id = shape.req_id(payload, "filed_by_membership_id")
    category = shape.req_enum(payload, "category", CATEGORIES)
    if category in MATCH_CATEGORIES:
        match_id = shape.req_id(payload, "match_id")
    else:
        match_id = shape.opt_id(payload, "match_id")
    protest_note = shape.req_str(payload, "protest_note", 1, 1000)
    if membership["league_id"] != league_id:
        raise ApiError("ERR_CROSS_LEAGUE_REFERENCE")
    if match is not None and match["league_id"] != league_id:
        raise ApiError("ERR_REFERENCE_MISMATCH")
    if membership["sanction_status"] != "SANCTIONED":
        raise ApiError("ERR_BOWLER_NOT_SANCTIONED")
    deadline = None
    if match is not None:
        deadline = plus_hours(match["certified_at"], calc.PROTEST_WINDOW_HOURS)
        if deadline is not None and clock.now() > deadline:
            raise ApiError("ERR_FILING_WINDOW_CLOSED")
    row = insert(store.protests, {
        "league_id": league_id,
        "match_id": match_id,
        "filed_by_membership_id": membership_id,
        "category": category,
        "protest_note": protest_note,
        "status": "FILED",
        "remedy": "NONE",
        "review_round": 0,
        "filed_at": clock.now(),
        "deadline_at": deadline,
        "ruling_note": None,
        "association_ruling": None,
    })
    return ok(serialize.protest(row), 201)


def _not_the_filer(league, protest):
    """PRD 2.10: the reviewing or ruling secretary may not be the filer."""
    membership = store.memberships.get(protest["filed_by_membership_id"])
    if membership is not None \
            and league["secretary_member_id"] == membership["member_id"]:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES")


@protests.post("/protests/<protest_id>/review")
def open_hearing(protest_id):
    uid, role = authenticate(["LeagueSecretary"])
    protest = fetch("protest", protest_id)
    league = store.leagues[protest["league_id"]]
    require_secretary(league, uid, role)
    if protest["status"] not in ("FILED", "REMANDED"):
        raise ApiError("ERR_PROTEST_STATE_INVALID")
    _not_the_filer(league, protest)
    protest["status"] = "UNDER_REVIEW"
    protest["review_round"] = protest["review_round"] + 1
    touch(protest)
    return ok(serialize.protest(protest))


def _affected(slots):
    """The memberships and teams a match's slots touch."""
    membership_ids = []
    team_ids = []
    for slot in slots:
        if slot["membership_id"] and slot["membership_id"] not in membership_ids:
            membership_ids.append(slot["membership_id"])
            membership = store.memberships.get(slot["membership_id"])
            if membership and membership["team_id"] \
                    and membership["team_id"] not in team_ids:
                team_ids.append(membership["team_id"])
    return membership_ids, team_ids


def _void_match(protest, match, league, remedy):
    """The four-hop decertification cascade of PRD 3.9."""
    slots = derive.slots_of_match(match["id"])
    membership_ids, team_ids = _affected(slots)
    for team_id in (match["home_team_id"], match["away_team_id"]):
        if team_id not in team_ids:
            team_ids.append(team_id)
    match["status"] = "VOID"
    match["certified_at"] = None
    match["home_points"] = 0.0
    match["away_points"] = 0.0
    match["void_reason"] = "%s:%s" % (protest["id"], remedy)
    touch(match)
    for slot in slots:
        apply_changes(slot, {"certified": False})
    derive.cascade_certification_change(league, membership_ids, team_ids)


def _forfeit_award(protest, match, league, forfeiting_team_id):
    """The asymmetric FORFEIT_AWARD branch of PRD 3.9: the protesting side's
    work survives, the forfeiting side's slots become FORFEIT rows that stay
    certified."""
    losing = derive.side_slots(match["id"], forfeiting_team_id)
    membership_ids, team_ids = _affected(losing)
    for team_id in (match["home_team_id"], match["away_team_id"]):
        if team_id not in team_ids:
            team_ids.append(team_id)
    for slot in losing:
        del store.series_entries[slot["id"]]
    for position in range(1, league["lineup_positions"] + 1):
        insert(store.series_entries, {
            "match_id": match["id"],
            "team_id": forfeiting_team_id,
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
            "certified": True,
        })
    side = derive.match_side_of_team(match, forfeiting_team_id)
    match[side + "_team_handicap_per_game"] = 0
    if side == "home":
        match["home_points"] = 0.0
        match["away_points"] = float(calc.POINTS_PER_MATCH)
    else:
        match["away_points"] = 0.0
        match["home_points"] = float(calc.POINTS_PER_MATCH)
    match["status"] = "FORFEITED"
    match["forfeiting_team_id"] = forfeiting_team_id
    touch(match)
    derive.cascade_certification_change(league, membership_ids, team_ids)


def _check_remedy(protest, remedy, forfeiting_team_id, association=False):
    """PRD 2.6 check 41: remedy applicability."""
    if remedy == "NONE":
        return None
    if association and remedy == "FORFEIT_AWARD":
        raise ApiError("ERR_REMEDY_NOT_APPLICABLE")
    match = store.matches.get(protest["match_id"]) if protest["match_id"] else None
    if match is None or match["status"] != "CERTIFIED":
        raise ApiError("ERR_REMEDY_NOT_APPLICABLE")
    if remedy == "FORFEIT_AWARD":
        if protest["category"] != "LINEUP_LEGALITY":
            raise ApiError("ERR_REMEDY_NOT_APPLICABLE")
        if forfeiting_team_id not in (match["home_team_id"],
                                      match["away_team_id"]):
            raise ApiError("ERR_REMEDY_NOT_APPLICABLE")
    return match


@protests.post("/protests/<protest_id>/ruling")
def rule(protest_id):
    uid, role = authenticate(["LeagueSecretary"])
    protest = fetch("protest", protest_id)
    league = store.leagues[protest["league_id"]]
    require_secretary(league, uid, role)
    payload = shape.body()
    decision = shape.req_enum(payload, "decision",
                              ["UPHOLD", "DENY", "REMAND", "ESCALATE"])
    remedy = shape.opt_enum(payload, "remedy", REMEDIES, "NONE")
    ruling_note = shape.req_str(payload, "ruling_note")
    forfeiting_team_id = shape.opt_id(payload, "forfeiting_team_id")
    if protest["status"] != "UNDER_REVIEW":
        raise ApiError("ERR_PROTEST_STATE_INVALID")
    if decision == "ESCALATE" and protest["category"] != "RULES_INTERPRETATION" \
            and protest["review_round"] < 2:
        raise ApiError("ERR_PROTEST_STATE_INVALID")
    _not_the_filer(league, protest)
    if decision == "DENY" and remedy != "NONE":
        raise ApiError("ERR_REMEDY_NOT_APPLICABLE")
    match = None
    if decision == "UPHOLD":
        match = _check_remedy(protest, remedy, forfeiting_team_id)
    if decision == "REMAND" and protest["review_round"] >= calc.MAX_REVIEW_ROUNDS:
        raise ApiError("ERR_REVIEW_ROUND_LIMIT")
    protest["ruling_note"] = ruling_note
    if decision == "DENY":
        protest["status"] = "DENIED"
    elif decision == "REMAND":
        protest["status"] = "REMANDED"
    elif decision == "ESCALATE":
        protest["status"] = "ESCALATED"
    else:
        protest["status"] = "UPHELD"
        protest["remedy"] = remedy
    touch(protest)
    if decision == "UPHOLD" and remedy == "VOID_MATCH":
        _void_match(protest, match, league, remedy)
    elif decision == "UPHOLD" and remedy == "FORFEIT_AWARD":
        _forfeit_award(protest, match, league, forfeiting_team_id)
    return ok(serialize.protest(protest))


@protests.post("/protests/<protest_id>/association-ruling")
def association_rule(protest_id):
    uid, role = authenticate(["AssociationOfficer"])
    protest = fetch("protest", protest_id)
    league = store.leagues[protest["league_id"]]
    payload = shape.body()
    remedy = shape.opt_enum(payload, "remedy", REMEDIES, "NONE")
    association_ruling = shape.req_str(payload, "association_ruling")
    forfeiting_team_id = shape.opt_id(payload, "forfeiting_team_id")
    if protest["status"] != "ESCALATED":
        raise ApiError("ERR_PROTEST_STATE_INVALID")
    match = _check_remedy(protest, remedy, forfeiting_team_id, association=True)
    protest["association_ruling"] = association_ruling
    protest["remedy"] = remedy
    protest["status"] = "ASSOCIATION_RULED"
    touch(protest)
    if remedy == "VOID_MATCH":
        _void_match(protest, match, league, remedy)
    return ok(serialize.protest(protest))
