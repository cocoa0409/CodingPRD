"""Selection procedures and trials entries (PRD 3.6)."""
from decimal import Decimal

from flask import Blueprint, request

import calc
import cascades
import db
import timeutil
from constants import ALL_ROLES_READ, BODY_STANDING_OK, MIN_PUBLISH_LEAD_DAYS, \
    REGISTRATION_CLOSE_BEFORE_TRIALS_DAYS
from envelope import respond_list, respond_object
from errors import ApiError, ERR_ATHLETE_NOT_ELIGIBLE, ERR_DUPLICATE_ENTRY, \
    ERR_CYCLE_WINDOW_INVALID, ERR_INVALID_REQUEST, ERR_PUBLISH_LEAD_TIME, \
    ERR_REGISTRATION_CLOSED, ERR_SCREENING_NOT_CLEARED, ERR_TRAINING_EXPIRED, \
    ERR_TRIALS_NOT_OPEN, already_terminal, invalid_state, not_found
from validate import auth, body_json, check_gb_ownership, req_datetime, \
    req_enum, req_int, req_num, req_str, require_roles

bp = Blueprint("selection", __name__)

PROC_TRANSITION_STATES = ["PUBLISHED", "LOCKED", "SUPERSEDED",
                          "REGISTRATION_OPEN", "HELD", "RESULTS_FINALIZED"]


def get_proc_or_404(proc_id):
    proc = db.get("selection_procedures", proc_id)
    if proc is None:
        raise not_found("selection procedure not found")
    return proc


def own_proc_or_403(uid, role, proc):
    check_gb_ownership(uid, role, proc["governing_body_id"])


@bp.route("/api/governing-bodies/<gb_id>/selection-procedures", methods=["POST"])
def create_procedure(gb_id):
    uid, role = auth()
    require_roles(role, ["NGBAdmin"])
    check_gb_ownership(uid, role, gb_id)
    if db.get("governing_bodies", gb_id) is None:
        raise not_found("governing body not found")
    body = body_json()
    games_name = req_str(body, "games_name")
    trials_start = req_datetime(body, "trials_start")
    trials_end = req_datetime(body, "trials_end")
    registration_deadline = req_datetime(body, "registration_deadline")
    qualifying_score = req_num(body, "qualifying_score")
    quota_slots = req_int(body, "quota_slots")
    if trials_end <= trials_start:
        raise ApiError(ERR_CYCLE_WINDOW_INVALID, 422,
                       "trials_end must be strictly after trials_start")
    if quota_slots < 1:
        raise ApiError(ERR_INVALID_REQUEST, 400, "quota_slots must be >= 1")
    if registration_deadline + timeutil.days(
            REGISTRATION_CLOSE_BEFORE_TRIALS_DAYS) > trials_start:
        raise ApiError(ERR_INVALID_REQUEST, 400,
                       "registration_deadline must fall at least 14 days "
                       "before trials_start")
    proc = db.create("selection_procedures", {
        "governing_body_id": gb_id,
        "games_name": games_name,
        "trials_start": trials_start,
        "trials_end": trials_end,
        "registration_deadline": registration_deadline,
        "qualifying_score": qualifying_score,
        "quota_slots": quota_slots,
        "proc_status": "DRAFT",
        "trials_status": "TRIALS_NOT_OPEN",
        "published_at": None,
        "locked_at": None,
        "entries": [],
    })
    return respond_object(proc, 201)


@bp.route("/api/governing-bodies/<gb_id>/selection-procedures", methods=["GET"])
def list_procedures(gb_id):
    uid, role = auth()
    require_roles(role, ALL_ROLES_READ)
    check_gb_ownership(uid, role, gb_id)
    if db.get("governing_bodies", gb_id) is None:
        raise not_found("governing body not found")
    proc_status = request.args.get("proc_status") or None
    items = [p for p in db.all_of("selection_procedures")
             if p["governing_body_id"] == gb_id
             and (proc_status is None or p["proc_status"] == proc_status)]
    return respond_list(db.sorted_created(items))


@bp.route("/api/selection-procedures/<proc_id>/transitions", methods=["POST"])
def procedure_transition(proc_id):
    uid, role = auth()
    require_roles(role, ["NGBAdmin"])
    proc = get_proc_or_404(proc_id)
    own_proc_or_403(uid, role, proc)
    if proc["proc_status"] in ("SUPERSEDED", "COMPLETED"):
        raise already_terminal("selection procedure is terminal")
    body = body_json()
    to_state = req_enum(body, "to_state", PROC_TRANSITION_STATES)
    now = timeutil.now()
    gb = db.get("governing_bodies", proc["governing_body_id"])

    if to_state == "PUBLISHED":
        if proc["proc_status"] != "DRAFT":
            raise invalid_state("PUBLISHED is only reachable from DRAFT")
        if gb is None or gb["status"] not in BODY_STANDING_OK:
            raise invalid_state("governing body standing does not permit "
                                "publication")
        if now + timeutil.days(MIN_PUBLISH_LEAD_DAYS) > proc["trials_start"]:
            raise ApiError(ERR_PUBLISH_LEAD_TIME, 422,
                           "publish requires at least 90 days of lead before "
                           "trials_start")
        if proc["registration_deadline"] + timeutil.days(
                REGISTRATION_CLOSE_BEFORE_TRIALS_DAYS) > proc["trials_start"]:
            raise ApiError(ERR_PUBLISH_LEAD_TIME, 422,
                           "registration_deadline must close at least 14 days "
                           "before trials_start")
        proc["published_at"] = now
        proc["proc_status"] = "PUBLISHED"
        db.mark("selection_procedures", proc)
        return respond_object(proc)

    if to_state == "LOCKED":
        if proc["proc_status"] != "PUBLISHED":
            raise invalid_state("LOCKED is only reachable from PUBLISHED")
        if gb is None or gb["status"] not in BODY_STANDING_OK:
            raise invalid_state("governing body standing does not permit "
                                "locking")
        proc["locked_at"] = now
        proc["proc_status"] = "LOCKED"
        db.mark("selection_procedures", proc)
        return respond_object(proc)

    if to_state == "SUPERSEDED":
        if proc["proc_status"] not in ("DRAFT", "PUBLISHED", "LOCKED"):
            raise invalid_state("SUPERSEDED is only reachable from DRAFT, "
                                "PUBLISHED or LOCKED")
        for roster in cascades.rosters_of_proc(proc["id"]):
            if roster["status"] == "CONFIRMED":
                raise invalid_state("procedure has a CONFIRMED roster")
        cascades.procedure_supersede(proc)
        return respond_object(proc)

    if to_state == "REGISTRATION_OPEN":
        if proc["proc_status"] != "LOCKED" \
                or proc["trials_status"] != "TRIALS_NOT_OPEN":
            raise invalid_state("REGISTRATION_OPEN requires the procedure "
                                "LOCKED with trials not yet open")
        proc["trials_status"] = "REGISTRATION_OPEN"
        db.mark("selection_procedures", proc)
        return respond_object(proc)

    if to_state == "HELD":
        if proc["trials_status"] != "REGISTRATION_OPEN":
            raise invalid_state("HELD is only reachable from REGISTRATION_OPEN")
        if now < proc["trials_start"]:
            raise invalid_state("trials window has not started")
        proc["trials_status"] = "HELD"
        db.mark("selection_procedures", proc)
        return respond_object(proc)

    # RESULTS_FINALIZED — atomic per-athlete score submission
    if proc["trials_status"] != "HELD":
        raise invalid_state("RESULTS_FINALIZED is only reachable from HELD")
    if now < proc["trials_end"]:
        raise invalid_state("trials window has not ended")
    results = body.get("results")
    if not isinstance(results, list):
        raise ApiError(ERR_INVALID_REQUEST, 400,
                       "results must be an array of {athlete_id, score}")
    # Tier-3 existence (§2.6): every body-supplied athlete_id foreign key
    # must resolve to an existing Athlete before any constraint check runs.
    for item in results:
        if isinstance(item, dict) and isinstance(item.get("athlete_id"), str):
            if db.get("athletes", item["athlete_id"]) is None:
                raise not_found("unknown athlete_id in results")
    registered = {e["athlete_id"] for e in proc["entries"]
                  if e["entry_status"] == "REGISTERED"}
    seen = set()
    parsed = {}
    for item in results:
        if not isinstance(item, dict):
            raise ApiError(ERR_INVALID_REQUEST, 400, "result items must be "
                                                     "objects")
        aid = item.get("athlete_id")
        score = item.get("score")
        if not isinstance(aid, str) or isinstance(score, bool) \
                or not isinstance(score, (int, float)):
            raise ApiError(ERR_INVALID_REQUEST, 400,
                           "each result needs athlete_id (string) and score "
                           "(number)")
        if aid in seen:
            raise ApiError(ERR_INVALID_REQUEST, 400,
                           "duplicate athlete_id in results")
        if aid not in registered:
            raise ApiError(ERR_INVALID_REQUEST, 400,
                           "unknown or already-scored athlete_id in results")
        seen.add(aid)
        parsed[aid] = Decimal(str(score))
    if seen != registered:
        raise ApiError(ERR_INVALID_REQUEST, 400,
                       "results must cover every REGISTERED entry")
    qualifying = Decimal(str(proc["qualifying_score"]))
    for entry in proc["entries"]:
        if entry["athlete_id"] in parsed:
            entry["score"] = parsed[entry["athlete_id"]]
            entry["result_recorded_at"] = now
            entry["entry_status"] = "QUALIFIED" \
                if parsed[entry["athlete_id"]] >= qualifying else "UNQUALIFIED"
    proc["trials_status"] = "RESULTS_FINALIZED"
    db.mark("selection_procedures", proc)
    return respond_object(proc)


@bp.route("/api/selection-procedures/<proc_id>/entries", methods=["POST"])
def create_entry(proc_id):
    uid, role = auth()
    require_roles(role, ["NGBAdmin"])
    proc = get_proc_or_404(proc_id)
    own_proc_or_403(uid, role, proc)
    body = body_json()
    athlete_id = req_str(body, "athlete_id")
    athlete = db.get("athletes", athlete_id)
    if athlete is None:
        raise not_found("athlete not found")
    if proc["trials_status"] != "REGISTRATION_OPEN":
        raise ApiError(ERR_TRIALS_NOT_OPEN, 409,
                       "trials entries require REGISTRATION_OPEN")
    now = timeutil.now()
    if not calc.screening_clear(athlete, now):
        raise ApiError(ERR_SCREENING_NOT_CLEARED, 422,
                       "athlete screening is not cleared and current")
    if not calc.training_current(athlete, now):
        raise ApiError(ERR_TRAINING_EXPIRED, 422,
                       "athlete safe-sport training is missing or expired")
    if athlete["eligibility_status"] != "ELIGIBLE":
        raise ApiError(ERR_ATHLETE_NOT_ELIGIBLE, 409,
                       "athlete eligibility_status must be ELIGIBLE")
    if now > proc["registration_deadline"]:
        raise ApiError(ERR_REGISTRATION_CLOSED, 422,
                       "registration deadline has passed")
    for entry in proc["entries"]:
        if entry["athlete_id"] == athlete_id:
            raise ApiError(ERR_DUPLICATE_ENTRY, 409,
                           "athlete already holds an entry on this procedure")
    proc["entries"].append({
        "athlete_id": athlete_id,
        "entry_status": "REGISTERED",
        "score": None,
        "result_recorded_at": None,
    })
    db.mark("selection_procedures", proc)
    return respond_object(proc, 201)
