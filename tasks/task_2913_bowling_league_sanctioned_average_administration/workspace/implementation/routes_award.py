"""Honor-score award applications and their verification chain (PRD 3.8)."""

from flask import Blueprint

import calc
import derive
import serialize
import shape
from auth import (authenticate, body_ref, fetch, require_own_membership,
                  require_secretary)
from clock import clock, plus_hours
from envelope import ok
from errors import ApiError
from store import store, insert, touch

awards = Blueprint("awards", __name__)

GAME_TYPES = ("PERFECT_GAME_300", "HIGH_GAME_298_PLUS")
SERIES_TYPES = ("SERIES_800_SCRATCH", "HANDICAP_SERIES_700")
AWARD_TYPES = list(GAME_TYPES) + list(SERIES_TYPES)


def claimed_pins_for(award_type, game_number, slot):
    """PRD 3.8: each award type has its own arithmetic for claimed_pins."""
    if award_type in GAME_TYPES:
        return slot["game%d_pins" % game_number] or 0
    if award_type == "SERIES_800_SCRATCH":
        return slot["scratch_series"] or 0
    return (slot["scratch_series"] or 0) + 3 * (slot["handicap_per_game_applied"] or 0)


def threshold_met(award_type, claimed_pins):
    if award_type == "PERFECT_GAME_300":
        return claimed_pins == 300
    if award_type == "HIGH_GAME_298_PLUS":
        return 298 <= claimed_pins <= 299
    if award_type == "SERIES_800_SCRATCH":
        return claimed_pins >= 800
    return claimed_pins >= 700


def lane_flag(match):
    """PRD 3.8: the lane pair has revoked_at null and a certified_through at
    or after the match's starts_at."""
    pair = store.lane_pairs.get(match["lane_pair_id"])
    if pair is None or pair["revoked_at"] is not None:
        return False
    through = pair["certified_through"]
    return through is not None and through >= match["starts_at"]


def sanction_flag(membership, slot):
    return membership["sanction_status"] == "SANCTIONED" and bool(slot["certified"])


@awards.post("/award-applications")
def file_application():
    uid, role = authenticate(["Bowler"])
    payload = shape.body()
    league = body_ref("league", payload.get("league_id"))
    membership = body_ref("membership", payload.get("membership_id"))
    slot = body_ref("series_entry", payload.get("series_entry_id"))
    if membership is not None:
        require_own_membership(uid, membership)
    league_id = shape.req_id(payload, "league_id")
    membership_id = shape.req_id(payload, "membership_id")
    series_entry_id = shape.req_id(payload, "series_entry_id")
    award_type = shape.req_enum(payload, "award_type", AWARD_TYPES)
    if award_type in GAME_TYPES:
        game_number = shape.req_int(payload, "claimed_game_number", 1, 3)
    else:
        game_number = None
        shape.forbid(payload, "claimed_game_number",
                     "claimed_game_number is forbidden for a series award.")
    evidence_note = shape.opt_str(payload, "evidence_note")
    match = store.matches[slot["match_id"]]
    if membership["league_id"] != league_id or match["league_id"] != league_id:
        raise ApiError("ERR_CROSS_LEAGUE_REFERENCE")
    if slot["membership_id"] != membership_id:
        raise ApiError("ERR_REFERENCE_MISMATCH")
    if slot["entry_type"] not in derive.AVERAGE_BEARING or not slot["certified"]:
        raise ApiError("ERR_REFERENCE_MISMATCH")
    if membership["sanction_status"] != "SANCTIONED":
        raise ApiError("ERR_BOWLER_NOT_SANCTIONED")
    deadline = plus_hours(match["certified_at"], calc.AWARD_WINDOW_HOURS)
    if deadline is None or clock.now() > deadline:
        raise ApiError("ERR_FILING_WINDOW_CLOSED")
    claimed_pins = claimed_pins_for(award_type, game_number, slot)
    if not threshold_met(award_type, claimed_pins):
        raise ApiError("ERR_AWARD_THRESHOLD_NOT_MET")
    for other in store.award_applications.values():
        if (other["series_entry_id"] == series_entry_id
                and other["award_type"] == award_type
                and other["status"] != "ASSOCIATION_DENIED"):
            raise ApiError("ERR_AWARD_THRESHOLD_NOT_MET")
    row = insert(store.award_applications, {
        "league_id": league_id,
        "membership_id": membership_id,
        "series_entry_id": series_entry_id,
        "award_type": award_type,
        "claimed_game_number": game_number,
        "claimed_pins": claimed_pins,
        "status": "SUBMITTED",
        "lane_certification_verified": lane_flag(match),
        "sanctioned_at_game_time": sanction_flag(membership, slot),
        "evidence_note": evidence_note,
        "verified_by_user_id": None,
        "association_ruling_note": None,
        "round_count": 1,
    })
    return ok(serialize.award_application(row), 201)


@awards.post("/award-applications/<application_id>/league-verification")
def verify_application(application_id):
    uid, role = authenticate(["LeagueSecretary"])
    application = fetch("award_application", application_id)
    league = store.leagues[application["league_id"]]
    require_secretary(league, uid, role)
    payload = shape.body()
    decision = shape.req_enum(payload, "decision",
                              ["VERIFY", "RETURN_FOR_EVIDENCE"])
    if decision == "RETURN_FOR_EVIDENCE":
        note = shape.req_str(payload, "evidence_note")
    else:
        note = shape.opt_str(payload, "evidence_note")
    if application["status"] != "SUBMITTED":
        raise ApiError("ERR_AWARD_APPLICATION_STATE_INVALID")
    membership = store.memberships[application["membership_id"]]
    slot = store.series_entries[application["series_entry_id"]]
    match = store.matches[slot["match_id"]]
    if decision == "VERIFY":
        lane_ok = lane_flag(match)
        sanction_ok = sanction_flag(membership, slot)
        if not lane_ok or not sanction_ok:
            raise ApiError("ERR_AWARD_EVIDENCE_INCOMPLETE")
        if league["secretary_member_id"] == membership["member_id"]:
            raise ApiError("ERR_SEGREGATION_OF_DUTIES")
        claimed = claimed_pins_for(application["award_type"],
                                   application["claimed_game_number"], slot)
        if not threshold_met(application["award_type"], claimed):
            raise ApiError("ERR_AWARD_THRESHOLD_NOT_MET")
        application["lane_certification_verified"] = lane_ok
        application["sanctioned_at_game_time"] = sanction_ok
        application["status"] = "LEAGUE_VERIFIED"
        application["verified_by_user_id"] = uid
    else:
        application["status"] = "RETURNED_FOR_EVIDENCE"
        application["evidence_note"] = note
    touch(application)
    return ok(serialize.award_application(application))


@awards.post("/award-applications/<application_id>/evidence")
def resupply_evidence(application_id):
    uid, role = authenticate(["Bowler"])
    application = fetch("award_application", application_id)
    membership = store.memberships[application["membership_id"]]
    require_own_membership(uid, membership)
    payload = shape.body()
    note = shape.req_str(payload, "evidence_note")
    if application["status"] != "RETURNED_FOR_EVIDENCE":
        raise ApiError("ERR_AWARD_APPLICATION_STATE_INVALID")
    application["status"] = "SUBMITTED"
    application["evidence_note"] = note
    application["round_count"] = application["round_count"] + 1
    application["verified_by_user_id"] = None
    touch(application)
    return ok(serialize.award_application(application))


@awards.post("/award-applications/<application_id>/association-decision")
def association_decision(application_id):
    uid, role = authenticate(["AssociationOfficer"])
    application = fetch("award_application", application_id)
    payload = shape.body()
    decision = shape.req_enum(payload, "decision", ["CERTIFY", "DENY"])
    if decision == "DENY":
        note = shape.req_str(payload, "association_ruling_note")
    else:
        note = shape.opt_str(payload, "association_ruling_note")
    if application["status"] != "LEAGUE_VERIFIED":
        raise ApiError("ERR_AWARD_APPLICATION_STATE_INVALID")
    if decision == "CERTIFY":
        if not (application["lane_certification_verified"]
                and application["sanctioned_at_game_time"]):
            raise ApiError("ERR_AWARD_EVIDENCE_INCOMPLETE")
        application["status"] = "ASSOCIATION_CERTIFIED"
    else:
        application["status"] = "ASSOCIATION_DENIED"
    if note is not None:
        application["association_ruling_note"] = note
    touch(application)
    return ok(serialize.award_application(application))
