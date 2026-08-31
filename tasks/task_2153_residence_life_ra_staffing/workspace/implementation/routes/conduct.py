"""Incident reports, triage routing and conduct adjudication."""
from flask import Blueprint, g

import calc
import responses
import services
import store
import validators as V
from auth import endpoint, require_owner
from constants import (
    API_PREFIX, HEARING_WINDOW_DAYS, MAX_RETURN_ROUNDS, POLICY_CODES, SEVERITIES,
)
from errors import ApiError
from store import DB

bp = Blueprint("conduct", __name__)


@bp.route("%s/incident-reports" % API_PREFIX, methods=["POST"])
@endpoint(["ResidentAssistant"])
def create_incident():
    body = V.body()
    room_id = V.s_id(body, "room_id")
    subject_id = V.s_id(body, "subject_student_id")
    occurred_at = V.s_dt(body, "occurred_at")
    severity = V.s_enum(body, "severity", SEVERITIES)
    policy_code = V.s_enum(body, "policy_code", POLICY_CODES)
    narrative = V.s_str(body, "narrative")
    ra = services.acting_ra()
    room = store.get("rooms", room_id)
    if room is None:
        raise ApiError("ERR_ROOM_NOT_FOUND")
    subject = store.get("students", subject_id)
    if subject is None:
        raise ApiError("ERR_STUDENT_NOT_FOUND")
    services.ra_active_gate(ra)
    if ra["student_id"] == subject_id:
        raise ApiError("ERR_SELF_REPORT_FORBIDDEN")
    row = store.insert("incidents", "IncidentReport", {
        "filed_by_ra_id": ra["id"],
        "room_id": room_id,
        "subject_student_id": subject_id,
        "occurred_at": store.fmt_iso(occurred_at),
        "severity": severity,
        "policy_code": policy_code,
        "narrative": narrative,
        "status": "DRAFT",
        "return_count": 0,
        "submitted_at": None,
        "routed_by_user_id": None,
        "conduct_case_id": None,
    })
    return responses.obj(row, 201)


@bp.route("%s/incident-reports/<report_id>/submit" % API_PREFIX, methods=["POST"])
@endpoint(["ResidentAssistant"])
def submit_incident(report_id):
    report = V.must_get("IncidentReport", report_id)
    require_owner(report["filed_by_ra_id"])
    body = V.body()
    narrative = V.s_str(body, "narrative", required=False)
    effective = narrative if narrative is not None else report["narrative"]
    if len(effective or "") < 10:
        raise ApiError("ERR_INVALID_REQUEST", "narrative must be at least 10 characters.")
    if report["status"] not in ("DRAFT", "RETURNED_FOR_DETAIL"):
        raise ApiError("ERR_INCIDENT_STATE_INVALID")
    if narrative is not None:
        report["narrative"] = narrative
    report["status"] = "SUBMITTED"
    report["submitted_at"] = store.now_iso()
    return responses.obj(report)


@bp.route("%s/incident-reports/<report_id>/triage" % API_PREFIX, methods=["POST"])
@endpoint(["ResidenceDirector"])
def triage_incident(report_id):
    report = V.must_get("IncidentReport", report_id)
    body = V.body()
    disposition = V.s_enum(body, "disposition", ("RETURN", "ROUTE", "CLOSE_NO_ACTION"))
    V.s_str(body, "note", required=False)
    if report["status"] != "SUBMITTED":
        raise ApiError("ERR_INCIDENT_STATE_INVALID")
    if disposition == "RETURN":
        if report["return_count"] >= MAX_RETURN_ROUNDS:
            raise ApiError("ERR_RETURN_LIMIT_REACHED")
        report["return_count"] += 1
        report["status"] = "RETURNED_FOR_DETAIL"
    elif disposition == "CLOSE_NO_ACTION":
        report["status"] = "CLOSED_NO_ACTION"
    else:
        case = store.insert("conduct_cases", "ConductCase", {
            "incident_report_id": report["id"],
            "respondent_student_id": report["subject_student_id"],
            "severity": report["severity"],
            "status": "OPEN",
            "opened_at": store.now_iso(),
            "hearing_at": None,
            "scheduled_by_user_id": None,
            "decided_by_user_id": None,
            "prior_sanctioned_count": 0,
            "sanction_points": None,
            "outcome": None,
        })
        report["status"] = "ROUTED_TO_CONDUCT"
        report["conduct_case_id"] = case["id"]
        report["routed_by_user_id"] = g.user_id
    return responses.obj(report)


@bp.route("%s/conduct-cases/<case_id>/hearing" % API_PREFIX, methods=["POST"])
@endpoint(["ConductOfficer"])
def schedule_hearing(case_id):
    case = V.must_get("ConductCase", case_id)
    body = V.body()
    hearing_at = V.s_dt(body, "hearing_at")
    if case["status"] != "OPEN":
        raise ApiError("ERR_CONDUCT_CASE_STATE_INVALID")
    opened_at = store.parse_iso(case["opened_at"])
    if hearing_at <= store.now() or hearing_at > opened_at + store.days(HEARING_WINDOW_DAYS):
        raise ApiError("ERR_HEARING_WINDOW_EXCEEDED")
    case["status"] = "HEARING_SCHEDULED"
    case["hearing_at"] = store.fmt_iso(hearing_at)
    case["scheduled_by_user_id"] = g.user_id
    return responses.obj(case)


@bp.route("%s/conduct-cases/<case_id>/decision" % API_PREFIX, methods=["POST"])
@endpoint(["ConductOfficer"])
def decide_case(case_id):
    case = V.must_get("ConductCase", case_id)
    body = V.body()
    outcome = V.s_enum(body, "outcome", ("SANCTION", "DISMISS"))
    if case["status"] != "HEARING_SCHEDULED":
        raise ApiError("ERR_CONDUCT_CASE_STATE_INVALID")
    if g.user_id == case.get("scheduled_by_user_id"):
        raise ApiError("ERR_SEGREGATION_OF_DUTIES")
    student = DB["students"].get(case["respondent_student_id"])
    if outcome == "SANCTION":
        priors = calc.prior_sanctioned_count(case)
        case["prior_sanctioned_count"] = priors
        case["sanction_points"] = calc.conduct_sanction_points(case["severity"], priors)
        case["status"] = "SANCTIONED"
        case["outcome"] = "SANCTION"
        case["decided_by_user_id"] = g.user_id
        if student is not None:
            services.apply_conduct_cascade(student)
    else:
        case["sanction_points"] = 0
        case["status"] = "DISMISSED"
        case["outcome"] = "DISMISS"
        case["decided_by_user_id"] = g.user_id
    report = DB["incidents"].get(case["incident_report_id"])
    if report is not None and report["status"] == "ROUTED_TO_CONDUCT":
        report["status"] = "CLOSED_ADJUDICATED"
    return responses.obj(case)
