"""Abuse reports routed to the independent body (PRD 3.3)."""
from flask import Blueprint, request

import cascades
import db
import timeutil
from envelope import respond_list, respond_object
from errors import already_terminal, invalid_state, not_found
from routes_athletes import get_athlete_or_404
from validate import auth, body_json, check_athlete_ownership, req_enum, \
    req_str, require_roles

bp = Blueprint("safety", __name__)

REPORTER_ROLES = ["ATHLETE", "NGB_STAFF", "PUBLIC"]
ABUSE_TRANSITION_STATES = ["FORWARDED", "ADJUDICATED_SUBSTANTIATED",
                           "ADJUDICATED_UNSUBSTANTIATED"]


def get_report_or_404(report_id):
    report = db.get("abuse_reports", report_id)
    if report is None:
        raise not_found("abuse report not found")
    return report


@bp.route("/api/athletes/<athlete_id>/abuse-reports", methods=["POST"])
def create_report(athlete_id):
    _, role = auth()
    require_roles(role, ["Athlete", "NGBAdmin", "SafeSportOfficer",
                         "CommitteeAdmin"])
    get_athlete_or_404(athlete_id)
    body = body_json()
    reporter_role = req_enum(body, "reporter_role", REPORTER_ROLES)
    allegation = req_str(body, "allegation")
    report = db.create("abuse_reports", {
        "athlete_id": athlete_id,
        "reporter_role": reporter_role,
        "allegation": allegation,
        "status": "REPORTED",
        "forwarded_at": None,
        "adjudicated_at": None,
    })
    return respond_object(report, 201)


@bp.route("/api/athletes/<athlete_id>/abuse-reports", methods=["GET"])
def list_reports(athlete_id):
    uid, role = auth()
    require_roles(role, ["SafeSportOfficer", "CommitteeAdmin", "Athlete"])
    check_athlete_ownership(uid, role, athlete_id)  # restricted read: subject
    get_athlete_or_404(athlete_id)
    status = request.args.get("status") or None
    items = [r for r in db.all_of("abuse_reports")
             if r["athlete_id"] == athlete_id
             and (status is None or r["status"] == status)]
    return respond_list(db.sorted_created(items))


@bp.route("/api/abuse-reports/<report_id>/transitions", methods=["POST"])
def report_transition(report_id):
    _, role = auth()
    require_roles(role, ["SafeSportOfficer"])
    report = get_report_or_404(report_id)
    if report["status"] in ("ADJUDICATED_SUBSTANTIATED",
                            "ADJUDICATED_UNSUBSTANTIATED"):
        raise already_terminal("abuse report is already adjudicated")
    body = body_json()
    to_state = req_enum(body, "to_state", ABUSE_TRANSITION_STATES)

    if to_state == "FORWARDED":
        if report["status"] != "REPORTED":
            raise invalid_state("FORWARDED is only reachable from REPORTED")
        report["forwarded_at"] = timeutil.now()
        report["status"] = "FORWARDED"
        db.mark("abuse_reports", report)
        return respond_object(report)

    # ADJUDICATED_*
    if report["status"] != "FORWARDED":
        raise invalid_state("adjudication is only reachable from FORWARDED")
    report["adjudicated_at"] = timeutil.now()
    report["status"] = to_state
    db.mark("abuse_reports", report)
    if to_state == "ADJUDICATED_SUBSTANTIATED":
        cascades.abuse_substantiated_cascade(report)
    return respond_object(report)
