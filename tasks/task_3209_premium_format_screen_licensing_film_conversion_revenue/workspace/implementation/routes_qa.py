"""QAAlert and TechDispatch endpoints."""
from __future__ import annotations

from flask import Blueprint, request

from db import db
from errors import (
    ERR_ALERT_NOT_FOUND, ERR_DISPATCH_NOT_FOUND, ERR_AUDITORIUM_NOT_FOUND,
    ERR_INVALID_STATE, ERR_INVALID_REQUEST, ERR_CANNOT_DEFER_CRITICAL,
    ERR_RESOLUTION_NOTES_REQUIRED,
    bad_request, conflict, not_found,
)
from util import (
    require_role, get_body, req_str, req_enum, opt_str,
    parse_pagination, paginate, success_object, success_list, stamp_new, touch,
    sort_by_created, parse_iso_datetime, iso_format,
)
from domain import (
    serialize_qa_alert, serialize_tech_dispatch, degrade_auditorium,
)

bp = Blueprint("qa", __name__)

ALERT_CODES = {"LAMP_DEGRADED", "SOUND_DRIFT", "PROJECTOR_TEMP", "NETWORK_LOSS", "CALIBRATION_OVERDUE"}
SEVERITIES = {"INFO", "WARNING", "CRITICAL"}
TECH_SPECIALTIES = {"PROJECTION", "SOUND", "NETWORK", "GENERAL"}


def get_alert_or_404(alert_id):
    a = db.qa_alerts.get(alert_id)
    if a is None:
        raise not_found(ERR_ALERT_NOT_FOUND, f"QA alert {alert_id} not found")
    return a


def get_dispatch_or_404(dispatch_id):
    d = db.tech_dispatches.get(dispatch_id)
    if d is None:
        raise not_found(ERR_DISPATCH_NOT_FOUND, f"Tech dispatch {dispatch_id} not found")
    return d


# -------------------- QAAlert --------------------

@bp.post("/v1/qa-alerts")
def create_alert():
    require_role("FieldEngineer", "NetworkPlanner")
    body = get_body()
    auditorium_id = req_str(body, "auditorium_id")
    alert_code = req_enum(body, "alert_code", ALERT_CODES)
    severity = req_enum(body, "severity", SEVERITIES)
    notes = opt_str(body, "notes")
    if auditorium_id not in db.auditoriums:
        raise not_found(ERR_AUDITORIUM_NOT_FOUND, f"Auditorium {auditorium_id} not found")
    alert = {
        "auditorium_id": auditorium_id,
        "alert_code": alert_code,
        "severity": severity,
        "raised_at": iso_format(db.logical_clock),
        "_raised_at_dt": db.logical_clock,
        "notes": notes,
        "status": "RAISED",
    }
    stamp_new(alert)
    db.qa_alerts[alert["id"]] = alert
    # CRITICAL on OPERATING auditorium -> DEGRADED cascade
    if severity == "CRITICAL":
        aud = db.auditoriums.get(auditorium_id)
        if aud is not None and aud.get("status") == "OPERATING":
            degrade_auditorium(aud)
    return success_object(serialize_qa_alert(alert), 201)


@bp.get("/v1/qa-alerts")
def list_alerts():
    require_role("FieldEngineer", "NetworkPlanner", "PlatformContractManager")
    limit, offset = parse_pagination()
    items = sort_by_created(list(db.qa_alerts.values()))
    auditorium_id = request.args.get("auditorium_id")
    status = request.args.get("status")
    severity = request.args.get("severity")
    if auditorium_id:
        items = [a for a in items if a.get("auditorium_id") == auditorium_id]
    if status:
        items = [a for a in items if a.get("status") == status]
    if severity:
        items = [a for a in items if a.get("severity") == severity]
    page, total = paginate(items, limit, offset)
    return success_list([serialize_qa_alert(a) for a in page], total, limit, offset)


@bp.get("/v1/qa-alerts/<alert_id>")
def get_alert(alert_id):
    require_role("FieldEngineer", "NetworkPlanner", "PlatformContractManager")
    a = get_alert_or_404(alert_id)
    return success_object(serialize_qa_alert(a))


@bp.post("/v1/qa-alerts/<alert_id>/acknowledge")
def acknowledge_alert(alert_id):
    require_role("FieldEngineer")
    a = get_alert_or_404(alert_id)
    if a.get("status") != "RAISED":
        raise conflict(ERR_INVALID_STATE, f"Alert in state {a.get('status')} cannot be acknowledged")
    a["status"] = "ACKNOWLEDGED"
    touch(a)
    return success_object(serialize_qa_alert(a))


@bp.post("/v1/qa-alerts/<alert_id>/defer")
def defer_alert(alert_id):
    require_role("FieldEngineer")
    a = get_alert_or_404(alert_id)
    if a.get("status") not in ("RAISED", "ACKNOWLEDGED"):
        raise conflict(ERR_INVALID_STATE, f"Alert in state {a.get('status')} cannot be deferred")
    if a.get("severity") == "CRITICAL":
        raise conflict(ERR_CANNOT_DEFER_CRITICAL, "CRITICAL alerts cannot be deferred")
    a["status"] = "DEFERRED"
    touch(a)
    return success_object(serialize_qa_alert(a))


@bp.get("/v1/qa-alerts/<alert_id>/dispatches")
def list_alert_dispatches(alert_id):
    require_role("FieldEngineer", "NetworkPlanner")
    a = get_alert_or_404(alert_id)
    limit, offset = parse_pagination()
    items = [d for d in db.tech_dispatches.values() if d.get("qa_alert_id") == a["id"]]
    items = sort_by_created(items)
    page, total = paginate(items, limit, offset)
    return success_list([serialize_tech_dispatch(d) for d in page], total, limit, offset)


# -------------------- TechDispatch --------------------

@bp.post("/v1/tech-dispatches")
def create_dispatch():
    require_role("FieldEngineer")
    body = get_body()
    qa_alert_id = req_str(body, "qa_alert_id")
    auditorium_id = req_str(body, "auditorium_id")
    scheduled_visit_date = parse_iso_datetime(body.get("scheduled_visit_date"), "scheduled_visit_date")
    tech_specialty = req_enum(body, "tech_specialty", TECH_SPECIALTIES)
    # Body FK existence in declared input order: qa_alert_id, auditorium_id
    alert = db.qa_alerts.get(qa_alert_id)
    if alert is None:
        raise not_found(ERR_ALERT_NOT_FOUND, f"QA alert {qa_alert_id} not found")
    if auditorium_id not in db.auditoriums:
        raise not_found(ERR_AUDITORIUM_NOT_FOUND, f"Auditorium {auditorium_id} not found")
    if alert.get("auditorium_id") != auditorium_id:
        raise bad_request(ERR_INVALID_REQUEST,
                          "auditorium_id must equal the alert's auditorium_id")
    d = {
        "qa_alert_id": qa_alert_id,
        "auditorium_id": auditorium_id,
        "scheduled_visit_date": iso_format(scheduled_visit_date),
        "_scheduled_visit_date_dt": scheduled_visit_date,
        "tech_specialty": tech_specialty,
        "resolution_notes": None,
        "status": "SCHEDULED",
    }
    stamp_new(d)
    db.tech_dispatches[d["id"]] = d
    # auto-advance ACKNOWLEDGED alert -> DISPATCHED
    if alert.get("status") == "ACKNOWLEDGED":
        alert["status"] = "DISPATCHED"
        touch(alert)
    return success_object(serialize_tech_dispatch(d), 201)


@bp.get("/v1/tech-dispatches")
def list_dispatches():
    require_role("FieldEngineer", "NetworkPlanner")
    limit, offset = parse_pagination()
    items = sort_by_created(list(db.tech_dispatches.values()))
    qa_alert_id = request.args.get("qa_alert_id")
    auditorium_id = request.args.get("auditorium_id")
    status = request.args.get("status")
    if qa_alert_id:
        items = [d for d in items if d.get("qa_alert_id") == qa_alert_id]
    if auditorium_id:
        items = [d for d in items if d.get("auditorium_id") == auditorium_id]
    if status:
        items = [d for d in items if d.get("status") == status]
    page, total = paginate(items, limit, offset)
    return success_list([serialize_tech_dispatch(d) for d in page], total, limit, offset)


@bp.get("/v1/tech-dispatches/<dispatch_id>")
def get_dispatch(dispatch_id):
    require_role("FieldEngineer", "NetworkPlanner")
    d = get_dispatch_or_404(dispatch_id)
    return success_object(serialize_tech_dispatch(d))


def _transition_dispatch(dispatch_id, from_states, to_state, pre=None, post=None):
    require_role("FieldEngineer")
    d = get_dispatch_or_404(dispatch_id)
    if d.get("status") not in from_states:
        raise conflict(ERR_INVALID_STATE, f"Dispatch in state {d.get('status')}")
    if pre:
        pre(d)
    d["status"] = to_state
    touch(d)
    if post:
        post(d)
    return success_object(serialize_tech_dispatch(d))


@bp.post("/v1/tech-dispatches/<dispatch_id>/mark-en-route")
def mark_en_route(dispatch_id):
    return _transition_dispatch(dispatch_id, {"SCHEDULED"}, "EN_ROUTE")


@bp.post("/v1/tech-dispatches/<dispatch_id>/mark-on-site")
def mark_on_site(dispatch_id):
    return _transition_dispatch(dispatch_id, {"EN_ROUTE"}, "ON_SITE")


@bp.post("/v1/tech-dispatches/<dispatch_id>/abort")
def abort_dispatch(dispatch_id):
    return _transition_dispatch(dispatch_id, {"SCHEDULED", "EN_ROUTE", "ON_SITE"}, "ABORTED")


@bp.post("/v1/tech-dispatches/<dispatch_id>/complete")
def complete_dispatch(dispatch_id):
    require_role("FieldEngineer")
    d = get_dispatch_or_404(dispatch_id)
    if d.get("status") != "ON_SITE":
        raise conflict(ERR_INVALID_STATE, f"Dispatch in state {d.get('status')}")
    body = get_body()
    notes = body.get("resolution_notes")
    if not isinstance(notes, str) or notes == "":
        raise bad_request(ERR_RESOLUTION_NOTES_REQUIRED, "resolution_notes is required")
    d["resolution_notes"] = notes
    d["status"] = "COMPLETE"
    touch(d)
    # Resolve parent alert if no other non-terminal dispatches remain
    alert = db.qa_alerts.get(d.get("qa_alert_id"))
    if alert is not None:
        others_open = any(
            o["id"] != d["id"] and o.get("qa_alert_id") == alert["id"]
            and o.get("status") not in ("COMPLETE", "ABORTED")
            for o in db.tech_dispatches.values()
        )
        if not others_open and alert.get("status") == "DISPATCHED":
            alert["status"] = "RESOLVED"
            touch(alert)
        if alert.get("alert_code") == "CALIBRATION_OVERDUE":
            aud = db.auditoriums.get(alert.get("auditorium_id"))
            if aud is not None:
                aud["_last_calibration_at_dt"] = db.logical_clock
                aud["last_calibration_at"] = iso_format(db.logical_clock)
                aud["calibration_overdue"] = False
                touch(aud)
    return success_object(serialize_tech_dispatch(d))
