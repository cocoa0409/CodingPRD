"""Selection appeals through arbitration (PRD 3.6)."""
from flask import Blueprint, request

import cascades
import db
import timeutil
from constants import ALL_ROLES_READ, APPEAL_WINDOW_HOURS
from envelope import respond_list, respond_object
from errors import ApiError, ERR_APPEAL_WINDOW_EXPIRED, ERR_INVALID_STATE, \
    ERR_UNAUTHORIZED, already_terminal, invalid_state, not_found
from routes_athletes import get_athlete_or_404
from routes_rosters import get_roster_or_404, proc_of
from validate import auth, body_json, check_athlete_ownership, \
    check_gb_ownership, req_enum, req_str, require_roles

bp = Blueprint("appeals", __name__)

APPEAL_GROUNDS = ["SELECTION_PROCESS", "ELIGIBILITY", "SCORING_ERROR"]
APPEAL_TRANSITION_STATES = ["HEARING", "UPHELD", "DENIED", "WITHDRAWN"]


def get_appeal_or_404(appeal_id):
    appeal = db.get("appeals", appeal_id)
    if appeal is None:
        raise not_found("appeal not found")
    return appeal


@bp.route("/api/rosters/<roster_id>/appeals", methods=["POST"])
def create_appeal(roster_id):
    uid, role = auth()
    require_roles(role, ["Athlete"])
    roster = get_roster_or_404(roster_id)
    if roster["status"] not in ("NOMINATED", "SUBMITTED"):
        raise ApiError(ERR_INVALID_STATE, 409,
                       "appeals require a nominated roster")
    now = timeutil.now()
    if roster["nominated_at"] is None or \
            now > roster["nominated_at"] + timeutil.hours(APPEAL_WINDOW_HOURS):
        raise ApiError(ERR_APPEAL_WINDOW_EXPIRED, 422,
                       "appeal window closed (nominated_at + 72 hours)")
    body = body_json()
    grounds = req_enum(body, "grounds", APPEAL_GROUNDS)
    # Referential: appellant must be an Athlete holding an entry on the
    # appealed roster's procedure.
    athlete = db.get("athletes", uid)
    proc = proc_of(roster)
    has_entry = proc is not None and any(
        e["athlete_id"] == uid for e in proc["entries"])
    if athlete is None or not has_entry:
        raise ApiError(ERR_UNAUTHORIZED, 403,
                       "appellant must be an athlete with an entry on the "
                       "appealed roster's procedure")
    appeal = db.create("appeals", {
        "roster_id": roster_id,
        "filed_by_athlete_id": uid,
        "grounds": grounds,
        "status": "FILED",
        "filed_at": now,
        "decision_rationale": None,
    })
    return respond_object(appeal, 201)


@bp.route("/api/rosters/<roster_id>/appeals", methods=["GET"])
def list_roster_appeals(roster_id):
    uid, role = auth()
    require_roles(role, ALL_ROLES_READ)
    roster = get_roster_or_404(roster_id)
    proc = proc_of(roster)
    check_gb_ownership(uid, role,
                       proc["governing_body_id"] if proc else None)
    status = request.args.get("status") or None
    items = [a for a in db.all_of("appeals")
             if a["roster_id"] == roster_id
             and (status is None or a["status"] == status)]
    return respond_list(db.sorted_created(items))


@bp.route("/api/athletes/<athlete_id>/appeals", methods=["GET"])
def list_athlete_appeals(athlete_id):
    uid, role = auth()
    require_roles(role, ALL_ROLES_READ)
    check_athlete_ownership(uid, role, athlete_id)
    athlete = get_athlete_or_404(athlete_id)
    check_gb_ownership(uid, role, athlete["governing_body_id"])
    status = request.args.get("status") or None
    items = [a for a in db.all_of("appeals")
             if a["filed_by_athlete_id"] == athlete_id
             and (status is None or a["status"] == status)]
    return respond_list(db.sorted_created(items))


@bp.route("/api/appeals/<appeal_id>/transitions", methods=["POST"])
def appeal_transition(appeal_id):
    uid, role = auth()
    require_roles(role, ["Arbitrator", "Athlete"])
    appeal = get_appeal_or_404(appeal_id)
    if appeal["status"] in ("UPHELD", "DENIED", "WITHDRAWN"):
        raise already_terminal("appeal is terminal")
    body = body_json()
    to_state = req_enum(body, "to_state", APPEAL_TRANSITION_STATES)
    if to_state == "WITHDRAWN":
        if role != "Athlete" or uid != appeal["filed_by_athlete_id"]:
            raise unauthorized("only the filing athlete may withdraw")
    else:
        if role != "Arbitrator":
            raise unauthorized("only an Arbitrator may move an appeal to %s"
                               % to_state)

    if to_state == "HEARING":
        if appeal["status"] != "FILED":
            raise invalid_state("HEARING is only reachable from FILED")
        appeal["status"] = "HEARING"
        db.mark("appeals", appeal)
        return respond_object(appeal)

    if to_state == "WITHDRAWN":
        if appeal["status"] != "FILED":
            raise invalid_state("WITHDRAWN is only reachable from FILED")
        appeal["status"] = "WITHDRAWN"
        db.mark("appeals", appeal)
        return respond_object(appeal)

    # UPHELD / DENIED from HEARING
    if appeal["status"] != "HEARING":
        raise invalid_state("%s is only reachable from HEARING" % to_state)
    rationale = req_str(body, "decision_rationale")
    appeal["decision_rationale"] = rationale
    appeal["status"] = to_state
    db.mark("appeals", appeal)
    if to_state == "UPHELD":
        roster = db.get("rosters", appeal["roster_id"])
        if roster is not None and roster["status"] in ("NOMINATED", "SUBMITTED"):
            roster["status"] = "DRAFT"
            roster["slots"] = []  # declined_athlete_ids preserved
            db.mark("rosters", roster)
    return respond_object(appeal)
