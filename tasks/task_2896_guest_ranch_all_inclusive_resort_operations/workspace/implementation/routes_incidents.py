"""Equine-activity incidents: filing, disposition and closure (PRD 3.11)."""

from flask import Blueprint

import derive
import fields
from auth import auth
from derive import Touch, incident_json
from envelope import created, listing, ok
from errors import ApiError
from fields import body, require
from lookup import find, find_body_ref
from store import db

bp = Blueprint("incidents", __name__)

SEVERITIES = ("MINOR", "SERIOUS", "CRITICAL")
DISPOSITIONS = ("CLEARED", "REMEDIATION_REQUIRED")
INCIDENT_STATUSES = ("FILED", "CLEARED", "REMEDIATION_REQUIRED", "CLOSED")
INCIDENT_READERS = ("RanchManager", "SafetyOfficer", "ActivityGuide", "HorseProgramDirector")


@bp.post("/activity-reservations/<reservation_id>/incident-reports")
def file_incident(reservation_id):
    from routes_slots import assigned_guide_or_403

    user_id, role = auth("ActivityGuide")
    seat = find("activity_reservations", reservation_id)
    slot = db.activity_slots.get(seat["slot_id"])
    assigned_guide_or_403(slot, user_id)

    data = body()
    horse = find_body_ref("horses", data, "horse_id")
    require(data, "severity", "equine_activity_statute_notice_given", "narrative", "occurred_at")
    severity = fields.as_enum(data, "severity", SEVERITIES)
    notice = fields.as_bool(data, "equine_activity_statute_notice_given")
    narrative = fields.as_str(data, "narrative")
    occurred_at = fields.as_instant(data, "occurred_at")
    fields.as_str(data, "horse_id")

    if horse is not None and notice is not True:
        raise ApiError(
            "ERR_STATUTE_NOTICE_REQUIRED",
            "A report naming a horse must record that the statutory notice was given.",
        )

    row = db.insert(
        "incident_reports",
        {
            "reservation_id": seat["id"],
            "guest_id": seat["guest_id"],
            "horse_id": horse["id"] if horse is not None else None,
            "reported_by_staff_member_id": user_id,
            "severity": severity,
            "equine_activity_statute_notice_given": notice,
            "narrative": narrative,
            "occurred_at": occurred_at,
            "incident_status": "FILED",
            "disposition_note": None,
            "disposed_by_user_id": None,
            "closed_by_user_id": None,
            "remediation_completed": False,
        },
    )

    touch = Touch()
    if horse is not None and horse["horse_status"] == "IN_SERVICE":
        horse["horse_status"] = "REVIEW_HOLD"
        touch.add(horse)
    if severity == "CRITICAL":
        guest = db.guests.get(seat["guest_id"])
        if guest is not None and guest["guest_standing"] != "SUSPENDED":
            derive.apply_standing(guest, "SUSPENDED", touch)
    touch.finalize()
    return created(incident_json(row))


@bp.get("/incident-reports/<incident_id>")
def read_incident(incident_id):
    auth(*INCIDENT_READERS)
    return ok(incident_json(find("incident_reports", incident_id)))


@bp.get("/incident-reports")
def list_incidents():
    auth(*INCIDENT_READERS)
    rows = derive.rows_of(
        "incident_reports",
        reservation_id=fields.query_filter("reservation_id"),
        guest_id=fields.query_filter("guest_id"),
        horse_id=fields.query_filter("horse_id"),
        reported_by_staff_member_id=fields.query_filter("reported_by_staff_member_id"),
        incident_status=fields.query_enum("incident_status", INCIDENT_STATUSES),
    )
    return listing(rows, incident_json)


@bp.post("/incident-reports/<incident_id>/dispose")
def dispose_incident(incident_id):
    user_id, role = auth("SafetyOfficer")
    report = find("incident_reports", incident_id)
    data = body()
    require(data, "disposition", "disposition_note")
    disposition = fields.as_enum(data, "disposition", DISPOSITIONS)
    note = fields.as_str(data, "disposition_note")

    if report["incident_status"] != "FILED":
        raise ApiError(
            "ERR_INCIDENT_STATE_INVALID",
            "Only a FILED report may be disposed; this one is %s."
            % report["incident_status"],
        )
    if report["equine_activity_statute_notice_given"] is not True:
        raise ApiError(
            "ERR_STATUTE_NOTICE_REQUIRED",
            "The statutory equine notice is checked again at disposition.",
        )

    report["disposition_note"] = note
    report["disposed_by_user_id"] = user_id
    report["incident_status"] = disposition

    touch = Touch()
    horse = db.horses.get(report.get("horse_id"))
    if disposition == "CLEARED":
        if horse is not None and horse["horse_status"] == "REVIEW_HOLD":
            horse["horse_status"] = "IN_SERVICE"
            touch.add(horse)
    else:
        if horse is not None and horse["horse_status"] == "REVIEW_HOLD":
            horse["horse_status"] = "REHAB"
            touch.add(horse)
        guest = db.guests.get(report["guest_id"])
        if guest is not None and guest["guest_standing"] == "GOOD":
            derive.apply_standing(guest, "RESTRICTED", touch)
    touch.add(report)
    touch.finalize()
    return ok(incident_json(report))


@bp.post("/incident-reports/<incident_id>/close")
def close_incident(incident_id):
    user_id, role = auth("SafetyOfficer")
    report = find("incident_reports", incident_id)
    if report.get("disposed_by_user_id") == user_id:
        raise ApiError(
            "ERR_SEGREGATION_OF_DUTIES",
            "The officer who disposed a report may not also close it.",
        )
    data = body()
    require(data, "remediation_completed")
    completed = fields.as_bool(data, "remediation_completed")

    if report["incident_status"] not in DISPOSITIONS:
        raise ApiError(
            "ERR_INCIDENT_STATE_INVALID",
            "A %s report cannot be closed." % report["incident_status"],
        )
    if report["incident_status"] == "REMEDIATION_REQUIRED" and completed is not True:
        raise ApiError(
            "ERR_INCIDENT_STATE_INVALID",
            "The remediation branch requires remediation_completed to be true.",
        )

    report["closed_by_user_id"] = user_id
    report["remediation_completed"] = completed
    report["incident_status"] = "CLOSED"

    touch = Touch()
    if completed is True:
        guest = db.guests.get(report["guest_id"])
        if guest is not None and guest["guest_standing"] in ("RESTRICTED", "SUSPENDED"):
            guest["guest_standing"] = "GOOD"
            touch.add(guest)
    touch.add(report)
    touch.finalize()
    return ok(incident_json(report))
