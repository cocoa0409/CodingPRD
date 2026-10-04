"""Rosters, the OCC-guarded nomination selector, slot decisions, submission
and confirmation (PRD 3.6, 2.7)."""
from flask import Blueprint, request

import calc
import cascades
import db
import timeutil
from constants import ALL_ROLES_READ, BODY_STANDING_OK
from envelope import respond_list, respond_object
from errors import ApiError, ERR_INVALID_REQUEST, ERR_INVALID_STATE, \
    ERR_PENDING_APPEALS, ERR_PENDING_SLOT_DECISIONS, ERR_RESULTS_NOT_FINAL, \
    ERR_STALE_VERSION, already_terminal, invalid_state, not_found, unauthorized
from routes_selection import get_proc_or_404
from validate import auth, body_json, check_gb_ownership, req_enum, \
    req_version, require_roles

bp = Blueprint("rosters", __name__)

ROSTER_TRANSITION_STATES = ["NOMINATED", "SUBMITTED", "CONFIRMED"]


def get_roster_or_404(roster_id):
    roster = db.get("rosters", roster_id)
    if roster is None:
        raise not_found("roster not found")
    return roster


def proc_of(roster):
    return db.get("selection_procedures", roster["selection_procedure_id"])


def own_roster_or_403(uid, role, roster):
    proc = proc_of(roster)
    check_gb_ownership(uid, role,
                       proc["governing_body_id"] if proc else None)


@bp.route("/api/selection-procedures/<proc_id>/rosters", methods=["POST"])
def create_roster(proc_id):
    uid, role = auth()
    require_roles(role, ["NGBAdmin"])
    proc = get_proc_or_404(proc_id)
    check_gb_ownership(uid, role, proc["governing_body_id"])
    if proc["proc_status"] in ("SUPERSEDED", "COMPLETED"):
        raise ApiError(ERR_INVALID_STATE, 409,
                       "cannot create a roster on a terminal procedure")
    for roster in cascades.rosters_of_proc(proc_id):
        if roster["status"] in ("DRAFT", "NOMINATED", "SUBMITTED"):
            raise ApiError(ERR_INVALID_STATE, 409,
                           "procedure already has a non-terminal roster")
    roster = db.create("rosters", {
        "selection_procedure_id": proc_id,
        "status": "DRAFT",
        "quota_effective": proc["quota_slots"],
        "bonus_slot_applied": False,
        "slots": [],
        "declined_athlete_ids": [],
        "nominated_at": None,
        "submitted_by_user_id": None,
    })
    return respond_object(roster, 201)


@bp.route("/api/rosters", methods=["GET"])
def list_rosters():
    _, role = auth()
    require_roles(role, ALL_ROLES_READ)
    proc_filter = request.args.get("selection_procedure_id") or None
    status = request.args.get("status") or None
    items = [r for r in db.all_of("rosters")
             if (proc_filter is None
                 or r["selection_procedure_id"] == proc_filter)
             and (status is None or r["status"] == status)]
    return respond_list(db.sorted_created(items))


@bp.route("/api/rosters/<roster_id>", methods=["GET"])
def read_roster(roster_id):
    uid, role = auth()
    require_roles(role, ALL_ROLES_READ)
    roster = get_roster_or_404(roster_id)
    own_roster_or_403(uid, role, roster)
    return respond_object(roster)


@bp.route("/api/rosters/<roster_id>/nominations", methods=["POST"])
def run_nominations(roster_id):
    uid, role = auth()
    require_roles(role, ["NGBAdmin"])
    roster = get_roster_or_404(roster_id)
    own_roster_or_403(uid, role, roster)
    if roster["status"] in ("CONFIRMED", "CANCELLED"):
        raise already_terminal("roster is terminal")
    if roster["status"] not in ("DRAFT", "NOMINATED"):
        raise invalid_state("nominations require a DRAFT or NOMINATED roster")
    body = body_json()
    proc = proc_of(roster)
    gb = db.get("governing_bodies", proc["governing_body_id"]) if proc else None
    if gb is None or gb["status"] not in BODY_STANDING_OK:
        raise invalid_state("governing body standing does not permit "
                            "nomination")
    if proc is None or proc["proc_status"] != "LOCKED" \
            or proc["trials_status"] != "RESULTS_FINALIZED":
        raise ApiError(ERR_RESULTS_NOT_FINAL, 409,
                       "nomination requires the procedure LOCKED with trials "
                       "RESULTS_FINALIZED")
    # Tier 7/10: the OCC field is non-optional; the match check is last.
    expected = req_version(body, "expected_roster_version")
    if expected != roster["version"]:
        raise ApiError(ERR_STALE_VERSION, 412,
                       "expected_roster_version does not match the roster's "
                       "current version")
    now = timeutil.now()
    applied, quota_effective, slots = calc.build_slots(proc, roster, now)
    roster["bonus_slot_applied"] = applied
    roster["quota_effective"] = quota_effective
    roster["slots"] = slots
    if roster["status"] == "DRAFT":
        # Only the FIRST nomination anchors the 72h appeal window.
        roster["nominated_at"] = now
        roster["status"] = "NOMINATED"
    db.mark("rosters", roster)
    return respond_object(roster)


@bp.route("/api/rosters/<roster_id>/transitions", methods=["POST"])
def roster_transition(roster_id):
    uid, role = auth()
    require_roles(role, ["NGBAdmin", "CommitteeAdmin", "Athlete"])
    roster = get_roster_or_404(roster_id)
    proc = proc_of(roster)
    gb = db.get("governing_bodies", proc["governing_body_id"]) if proc else None
    if role == "NGBAdmin":
        own_roster_or_403(uid, role, roster)
    if roster["status"] in ("CONFIRMED", "CANCELLED"):
        raise already_terminal("roster is terminal")
    body = body_json()
    to_state = req_enum(body, "to_state", ROSTER_TRANSITION_STATES)

    # Per-transition actors (authorization, PRD 2.1/3.6).
    if to_state == "NOMINATED" and role != "Athlete":
        raise unauthorized("slot decisions are answered by the athlete")
    if to_state == "SUBMITTED":
        if role == "Athlete":
            raise unauthorized("athletes may not submit a roster")
        if role == "NGBAdmin" and gb is not None \
                and gb["status"] == "INTERIM_MANAGED":
            raise unauthorized("an NGBAdmin may not submit while the body is "
                               "INTERIM_MANAGED")
    if to_state == "CONFIRMED" and role != "CommitteeAdmin":
        raise unauthorized("only a CommitteeAdmin may confirm a roster")

    if to_state == "NOMINATED":
        if roster["status"] != "NOMINATED":
            raise invalid_state("slot decisions require a NOMINATED roster")
        decisions = body.get("slot_decisions")
        if not isinstance(decisions, list) or not decisions:
            raise ApiError(ERR_INVALID_REQUEST, 400,
                           "slot_decisions must be a non-empty array")
        for decision in decisions:
            if not isinstance(decision, dict):
                raise ApiError(ERR_INVALID_REQUEST, 400,
                               "each slot decision must be an object")
            aid = decision.get("athlete_id")
            verdict = decision.get("decision")
            if not isinstance(aid, str) \
                    or verdict not in ("ACCEPTED", "DECLINED"):
                raise ApiError(ERR_INVALID_REQUEST, 400,
                               "each slot decision needs athlete_id and a "
                               "decision of ACCEPTED or DECLINED")
            if aid != uid:
                raise unauthorized("athletes answer only their own slot")
            slot = next((s for s in roster["slots"]
                         if s["athlete_id"] == aid), None)
            # NOMINATED and PROMOTED slots both await an answer (PRD 3.6's
            # submission gate counts both); a PROMOTED slot must remain
            # answerable or the roster could never be submitted.
            if slot is None or slot["slot_status"] not in ("NOMINATED",
                                                           "PROMOTED"):
                raise ApiError(ERR_INVALID_STATE, 409,
                               "referenced slot does not exist or is not "
                               "awaiting a decision")
        for decision in decisions:
            aid = decision["athlete_id"]
            slot = next(s for s in roster["slots"] if s["athlete_id"] == aid)
            if decision["decision"] == "ACCEPTED":
                slot["slot_status"] = "ACCEPTED"
            else:
                was_primary = slot["slot_type"] == "PRIMARY"
                old_rank = slot["rank"]
                slot["slot_status"] = "DECLINED"
                if aid not in roster["declined_athlete_ids"]:
                    roster["declined_athlete_ids"].append(aid)
                if was_primary:
                    if not cascades.promote_alternate(roster, old_rank):
                        slot["slot_status"] = "REMOVED"
        db.mark("rosters", roster)
        return respond_object(roster)

    if to_state == "SUBMITTED":
        if roster["status"] != "NOMINATED":
            raise invalid_state("SUBMITTED is only reachable from NOMINATED")
        if gb is not None and gb["status"] == "DECERTIFIED":
            raise invalid_state("governing body is DECERTIFIED")
        for appeal in cascades.appeals_of_roster(roster["id"]):
            if appeal["status"] in ("FILED", "HEARING"):
                raise ApiError(ERR_PENDING_APPEALS, 409,
                               "roster has an open appeal")
        for slot in roster["slots"]:
            if slot["slot_type"] == "PRIMARY" \
                    and slot["slot_status"] in ("NOMINATED", "PROMOTED"):
                raise ApiError(ERR_PENDING_SLOT_DECISIONS, 409,
                               "a PRIMARY slot is still awaiting a decision")
        roster["submitted_by_user_id"] = uid
        roster["status"] = "SUBMITTED"
        db.mark("rosters", roster)
        return respond_object(roster)

    # CONFIRMED
    if roster["status"] != "SUBMITTED":
        raise invalid_state("CONFIRMED is only reachable from SUBMITTED")
    if gb is not None and gb["status"] == "DECERTIFIED":
        raise invalid_state("governing body is DECERTIFIED")
    roster["status"] = "CONFIRMED"
    db.mark("rosters", roster)
    if proc is not None and proc["proc_status"] == "LOCKED" \
            and proc["trials_status"] == "RESULTS_FINALIZED":
        proc["proc_status"] = "COMPLETED"
        db.mark("selection_procedures", proc)
    return respond_object(roster)
