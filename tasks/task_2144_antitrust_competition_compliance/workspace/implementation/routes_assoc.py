"""Trade associations, participations, meetings and meeting attendances."""
from datetime import timedelta

from flask import Blueprint

import calc
import domain
from api import ok, created, listing
from errors import fail
from ladder import (require_auth, body, touch, lookup, rows, pagination, filter_enum,
                    filter_str, req_str, req_enum, req_num, req_bool, req_dt,
                    req_enum_array, req_str_array, ALL_ROLES)
from store import db, new_record, clock_now, sort_rows

bp = Blueprint("assoc", __name__)

PARTICIPATION_STATUSES = ["DRAFT", "APPROVAL_PENDING", "PARTIALLY_APPROVED", "ACTIVE",
                          "SUSPENDED", "UNDER_REVIEW", "REJECTED", "TERMINATED"]
ATTENDANCE_STATUSES = ["PLANNED", "ATTENDED", "MINUTES_SUBMITTED", "MINUTES_REVIEWED",
                       "FLAGGED", "CANCELLED"]
TERMINABLE = ("DRAFT", "APPROVAL_PENDING", "PARTIALLY_APPROVED", "ACTIVE",
              "SUSPENDED", "UNDER_REVIEW")


# ============================================================ TradeAssociation
@bp.post("/compliance/trade-associations")
def create_association():
    require_auth(["ComplianceAdmin"])
    payload = body()
    name = req_str(payload, "name")
    tier = req_enum(payload, "approval_tier", calc.APPROVAL_TIERS)
    density = req_num(payload, "competitor_density_pct", minimum=0, maximum=100)
    row = new_record({
        "name": name,
        "approval_tier": tier,
        "competitor_density_pct": density,
        "status": "PROPOSED",
    })
    db.associations[row["id"]] = row
    return created(row, domain.ser_association)


@bp.get("/compliance/trade-associations/<association_id>")
def read_association(association_id):
    require_auth(ALL_ROLES)
    return ok(lookup("associations", association_id), domain.ser_association)


@bp.post("/compliance/trade-associations/<association_id>/approval")
def approve_association(association_id):
    require_auth(["AntitrustCounsel"])
    payload = body()
    decision = req_enum(payload, "decision", ["APPROVED", "PROHIBITED"])
    association = lookup("associations", association_id)
    status = association["status"]
    if decision == "APPROVED":
        if status != "PROPOSED":
            fail("ERR_INVALID_STATE", "association is %s" % status)
        association["status"] = "APPROVED"
        touch(association)
    else:
        if status not in ("PROPOSED", "APPROVED"):
            fail("ERR_INVALID_STATE", "association is %s" % status)
        was_approved = status == "APPROVED"
        association["status"] = "PROHIBITED"
        touch(association)
        if was_approved:
            targets = [p for p in rows("participations")
                       if p["association_id"] == association_id
                       and p["status"] in domain.LIVE_PARTICIPATION_RESERVING]
            for part in sort_rows(targets):
                terminate_participation(part, "trade association prohibited")
    return ok(association, domain.ser_association)


# =================================================== AssociationParticipation
def terminate_participation(part, reason):
    part["status"] = "TERMINATED"
    part["termination_reason"] = reason
    touch(part)
    if int(part.get("review_minutes_reserved") or 0) > 0:
        part["review_minutes_reserved"] = 0
        unit = db.business_units.get(part["business_unit_id"])
        if unit is not None:
            touch(unit)
    domain.cancel_planned_attendances(
        domain.participation_attendances(part["id"]), reason, future_only=False)


@bp.post("/compliance/participations")
def create_participation():
    role, user_id = require_auth(["BusinessLead"])
    payload = body()
    unit_id = req_str(payload, "business_unit_id")
    association_id = req_str(payload, "association_id")
    employee_id = req_str(payload, "employee_id")
    purpose = req_str(payload, "purpose")

    unit = lookup("business_units", unit_id)
    association = lookup("associations", association_id)
    employee = lookup("employees", employee_id)

    if unit_id != user_id:
        fail("ERR_NOT_RESOURCE_OWNER", "business unit belongs to another lead")
    if unit["posture"] == "FROZEN":
        fail("ERR_BUSINESS_UNIT_FROZEN", "business unit is frozen")
    if unit["posture"] == "RESTRICTED":
        fail("ERR_BUSINESS_UNIT_RESTRICTED", "business unit is restricted")
    if employee["role_category"] in ("SALES", "PRICING"):
        if domain.training_status(employee) != "CURRENT":
            fail("ERR_TRAINING_NOT_CURRENT", "delegate training is not current")
    if association["status"] != "APPROVED":
        fail("ERR_ASSOCIATION_NOT_APPROVED", "association is not approved")
    for existing in rows("participations"):
        if (existing["business_unit_id"] == unit_id
                and existing["association_id"] == association_id
                and existing["employee_id"] == employee_id
                and existing["status"] not in ("REJECTED", "TERMINATED")):
            fail("ERR_DUPLICATE_PARTICIPATION", "a live participation already exists")

    row = new_record({
        "business_unit_id": unit_id,
        "association_id": association_id,
        "employee_id": employee_id,
        "purpose": purpose,
        "status": "DRAFT",
        "legal_cleared": False,
        "business_justified": False,
        "legal_cleared_by_user_id": None,
        "business_justification": None,
        "review_load_minutes": 0,
        "review_minutes_reserved": 0,
    })
    db.participations[row["id"]] = row
    return created(row, domain.ser_participation)


@bp.get("/compliance/participations/<participation_id>")
def read_participation(participation_id):
    require_auth(ALL_ROLES)
    return ok(lookup("participations", participation_id), domain.ser_participation)


@bp.get("/compliance/participations")
def list_participations():
    require_auth(ALL_ROLES)
    unit_id = filter_str("business_unit_id")
    association_id = filter_str("association_id")
    employee_id = filter_str("employee_id")
    status = filter_enum("status", PARTICIPATION_STATUSES)
    limit, offset = pagination()
    items = rows("participations")
    if unit_id:
        items = [r for r in items if r["business_unit_id"] == unit_id]
    if association_id:
        items = [r for r in items if r["association_id"] == association_id]
    if employee_id:
        items = [r for r in items if r["employee_id"] == employee_id]
    if status:
        items = [r for r in items if r["status"] == status]
    return listing(items, domain.ser_participation, limit, offset)


@bp.post("/compliance/participations/<participation_id>/submission")
def submit_participation(participation_id):
    role, user_id = require_auth(["BusinessLead"])
    body()
    part = lookup("participations", participation_id)
    if part["business_unit_id"] != user_id:
        fail("ERR_NOT_RESOURCE_OWNER", "participation belongs to another unit")
    if part["status"] != "DRAFT":
        fail("ERR_INVALID_STATE", "participation is %s" % part["status"])
    unit = db.business_units[part["business_unit_id"]]
    if unit["posture"] == "FROZEN":
        fail("ERR_BUSINESS_UNIT_FROZEN", "business unit is frozen")
    employee = db.employees[part["employee_id"]]
    if employee["role_category"] in ("SALES", "PRICING"):
        if domain.training_status(employee) != "CURRENT":
            fail("ERR_TRAINING_NOT_CURRENT", "delegate training is not current")
    association = db.associations[part["association_id"]]
    if association["status"] != "APPROVED":
        fail("ERR_ASSOCIATION_NOT_APPROVED", "association is not approved")
    part["status"] = "APPROVAL_PENDING"
    touch(part)
    return ok(part, domain.ser_participation)


@bp.post("/compliance/participations/<participation_id>/legal-clearance")
def legal_clearance(participation_id):
    role, user_id = require_auth(["AntitrustCounsel"])
    payload = body()
    decision = req_enum(payload, "decision", ["CLEARED", "REJECTED"])
    req_str(payload, "notes", required=False)

    part = lookup("participations", participation_id)
    status = part["status"]
    legal_landed = part["legal_cleared"]
    if status == "APPROVAL_PENDING":
        pass
    elif status == "PARTIALLY_APPROVED" and not legal_landed:
        pass
    else:
        fail("ERR_INVALID_STATE", "legal clearance is not available from %s" % status)

    unit = db.business_units[part["business_unit_id"]]
    if unit["posture"] == "FROZEN":
        fail("ERR_BUSINESS_UNIT_FROZEN", "business unit is frozen")

    if decision == "REJECTED":
        part["status"] = "REJECTED"
        touch(part)
        return ok(part, domain.ser_participation)

    association = db.associations[part["association_id"]]
    load = calc.participation_review_load_minutes(association)
    consumed = domain.review_minutes_consumed(unit)
    if consumed + load > unit["review_minutes_budget"]:
        fail("ERR_REVIEW_MINUTES_EXCEEDED", "review minute budget exceeded")

    part["review_load_minutes"] = load
    part["review_minutes_reserved"] = load
    part["legal_cleared"] = True
    part["legal_cleared_by_user_id"] = user_id
    part["status"] = "ACTIVE" if part["business_justified"] else "PARTIALLY_APPROVED"
    touch(part)
    touch(unit)
    return ok(part, domain.ser_participation)


@bp.post("/compliance/participations/<participation_id>/business-justification")
def business_justification(participation_id):
    role, user_id = require_auth(["BusinessLead"])
    payload = body()
    justification = req_str(payload, "justification")

    part = lookup("participations", participation_id)
    if part["business_unit_id"] != user_id:
        fail("ERR_NOT_RESOURCE_OWNER", "participation belongs to another unit")
    status = part["status"]
    if not (status == "APPROVAL_PENDING"
            or (status == "PARTIALLY_APPROVED" and not part["business_justified"])):
        fail("ERR_INVALID_STATE", "business justification is not available from %s" % status)

    unit = db.business_units[part["business_unit_id"]]
    if unit["posture"] == "FROZEN":
        fail("ERR_BUSINESS_UNIT_FROZEN", "business unit is frozen")

    part["business_justified"] = True
    part["business_justification"] = justification
    part["status"] = "ACTIVE" if part["legal_cleared"] else "PARTIALLY_APPROVED"
    touch(part)
    return ok(part, domain.ser_participation)


@bp.post("/compliance/participations/<participation_id>/reinstatement")
def reinstate_participation(participation_id):
    require_auth(["AntitrustCounsel"])
    body()
    part = lookup("participations", participation_id)
    status = part["status"]
    if status not in ("SUSPENDED", "UNDER_REVIEW"):
        fail("ERR_INVALID_STATE", "participation is %s" % status)
    unit = db.business_units[part["business_unit_id"]]
    if unit["posture"] == "FROZEN":
        fail("ERR_BUSINESS_UNIT_FROZEN", "business unit is frozen")
    if status == "SUSPENDED":
        if not (part["legal_cleared"] and part["business_justified"]):
            fail("ERR_INVALID_STATE", "both approval branches must have landed")
    else:
        for att in domain.participation_attendances(part["id"]):
            if att["status"] == "FLAGGED":
                fail("ERR_INVALID_STATE", "an attendance is still flagged")
    part["status"] = "ACTIVE"
    touch(part)
    return ok(part, domain.ser_participation)


@bp.post("/compliance/participations/<participation_id>/termination")
def terminate_participation_route(participation_id):
    role, user_id = require_auth(["BusinessLead", "AntitrustCounsel"])
    payload = body()
    reason = req_str(payload, "reason")
    part = lookup("participations", participation_id)
    if role == "BusinessLead" and part["business_unit_id"] != user_id:
        fail("ERR_NOT_RESOURCE_OWNER", "participation belongs to another unit")
    if part["status"] not in TERMINABLE:
        fail("ERR_INVALID_STATE", "participation is %s" % part["status"])
    terminate_participation(part, reason)
    return ok(part, domain.ser_participation)


# ============================================================ AssociationMeeting
@bp.post("/compliance/association-meetings")
def create_meeting():
    require_auth(["ComplianceAdmin"])
    payload = body()
    association_id = req_str(payload, "association_id")
    meeting_type = req_enum(payload, "meeting_type", calc.MEETING_TYPES)
    start = req_dt(payload, "scheduled_start")
    end = req_dt(payload, "scheduled_end")
    agenda = req_bool(payload, "agenda_received", required=False, default=False)

    association = lookup("associations", association_id)
    if association["status"] != "APPROVED":
        fail("ERR_ASSOCIATION_NOT_APPROVED", "association is not approved")
    if not end > start:
        fail("ERR_INVALID_INTERVAL", "scheduled_end must be strictly after scheduled_start")

    row = new_record({
        "association_id": association_id,
        "meeting_type": meeting_type,
        "scheduled_start": start,
        "scheduled_end": end,
        "agenda_received": agenda,
    })
    db.meetings[row["id"]] = row
    return created(row, domain.ser_meeting)


@bp.get("/compliance/association-meetings/<meeting_id>")
def read_meeting(meeting_id):
    require_auth(ALL_ROLES)
    return ok(lookup("meetings", meeting_id), domain.ser_meeting)


@bp.get("/compliance/association-meetings")
def list_meetings():
    require_auth(ALL_ROLES)
    association_id = filter_str("association_id")
    meeting_type = filter_enum("meeting_type", calc.MEETING_TYPES)
    limit, offset = pagination()
    items = rows("meetings")
    if association_id:
        items = [r for r in items if r["association_id"] == association_id]
    if meeting_type:
        items = [r for r in items if r["meeting_type"] == meeting_type]
    return listing(items, domain.ser_meeting, limit, offset)


# ============================================================ MeetingAttendance
@bp.post("/compliance/meeting-attendances")
def create_attendance():
    role, user_id = require_auth(["BusinessLead"])
    payload = body()
    meeting_id = req_str(payload, "meeting_id")
    participation_id = req_str(payload, "participation_id")

    meeting = lookup("meetings", meeting_id)
    part = lookup("participations", participation_id)

    if part["business_unit_id"] != user_id:
        fail("ERR_NOT_RESOURCE_OWNER", "participation belongs to another unit")
    unit = db.business_units[part["business_unit_id"]]
    if unit["posture"] == "FROZEN":
        fail("ERR_BUSINESS_UNIT_FROZEN", "business unit is frozen")
    if part["status"] != "ACTIVE":
        fail("ERR_PARTICIPATION_NOT_ACTIVE", "participation is %s" % part["status"])
    employee = db.employees[part["employee_id"]]
    if employee["clearance_status"] != "GRANTED":
        fail("ERR_CLEARANCE_NOT_GRANTED", "delegate clearance is not granted")

    now = clock_now()
    lead = meeting["scheduled_start"] - now
    if (not meeting["agenda_received"]) or lead < timedelta(hours=calc.AGENDA_LEAD_HOURS):
        fail("ERR_AGENDA_DEADLINE_MISSED", "agenda not received or lead time too short")

    occupied_start = meeting["scheduled_start"] - timedelta(
        minutes=calc.COUNSEL_BRIEFING_BUFFER_MINUTES)
    occupied_end = meeting["scheduled_end"]
    for other in domain.employee_attendances(part["employee_id"]):
        if other["status"] not in domain.OCCUPYING_ATTENDANCE:
            continue
        if occupied_start <= other["occupied_end"] and other["occupied_start"] <= occupied_end:
            fail("ERR_ATTENDEE_WINDOW_CONFLICT", "the delegate is already occupied")

    row = new_record({
        "meeting_id": meeting_id,
        "participation_id": participation_id,
        "status": "PLANNED",
        "occupied_start": occupied_start,
        "occupied_end": occupied_end,
        "minutes_summary": None,
        "topics_discussed": None,
        "minutes_verdict": None,
        "minutes_findings": None,
        "minutes_reviewed_by_user_id": None,
        "exposure_points_assessed": calc.d(0),
        "cancellation_reason": None,
    })
    db.attendances[row["id"]] = row
    return created(row, domain.ser_attendance)


@bp.get("/compliance/meeting-attendances/<attendance_id>")
def read_attendance(attendance_id):
    require_auth(ALL_ROLES)
    return ok(lookup("attendances", attendance_id), domain.ser_attendance)


@bp.get("/compliance/meeting-attendances")
def list_attendances():
    require_auth(ALL_ROLES)
    meeting_id = filter_str("meeting_id")
    participation_id = filter_str("participation_id")
    status = filter_enum("status", ATTENDANCE_STATUSES)
    limit, offset = pagination()
    items = rows("attendances")
    if meeting_id:
        items = [r for r in items if r["meeting_id"] == meeting_id]
    if participation_id:
        items = [r for r in items if r["participation_id"] == participation_id]
    if status:
        items = [r for r in items if r["status"] == status]
    return listing(items, domain.ser_attendance, limit, offset)


@bp.post("/compliance/meeting-attendances/<attendance_id>/cancellation")
def cancel_attendance(attendance_id):
    role, user_id = require_auth(["BusinessLead"])
    payload = body()
    reason = req_str(payload, "reason")
    att = lookup("attendances", attendance_id)
    part = db.participations[att["participation_id"]]
    if part["business_unit_id"] != user_id:
        fail("ERR_NOT_RESOURCE_OWNER", "attendance belongs to another unit")
    if att["status"] != "PLANNED":
        fail("ERR_INVALID_STATE", "attendance is %s" % att["status"])
    att["status"] = "CANCELLED"
    att["cancellation_reason"] = reason
    touch(att)
    return ok(att, domain.ser_attendance)


@bp.post("/compliance/meeting-attendances/<attendance_id>/attendance-confirmation")
def confirm_attendance(attendance_id):
    role, user_id = require_auth(["Employee"])
    body()
    att = lookup("attendances", attendance_id)
    part = db.participations[att["participation_id"]]
    if part["employee_id"] != user_id:
        fail("ERR_NOT_RESOURCE_OWNER", "attendance belongs to another delegate")
    if att["status"] != "PLANNED":
        fail("ERR_INVALID_STATE", "attendance is %s" % att["status"])
    meeting = db.meetings[att["meeting_id"]]
    if clock_now() < meeting["scheduled_end"]:
        fail("ERR_INVALID_STATE", "the meeting has not ended yet")
    att["status"] = "ATTENDED"
    touch(att)
    return ok(att, domain.ser_attendance)


@bp.post("/compliance/meeting-attendances/<attendance_id>/minutes")
def submit_minutes(attendance_id):
    role, user_id = require_auth(["Employee"])
    payload = body()
    summary = req_str(payload, "summary")
    topics = req_str_array(payload, "topics_discussed")
    att = lookup("attendances", attendance_id)
    part = db.participations[att["participation_id"]]
    if part["employee_id"] != user_id:
        fail("ERR_NOT_RESOURCE_OWNER", "attendance belongs to another delegate")
    if att["status"] != "ATTENDED":
        fail("ERR_INVALID_STATE", "attendance is %s" % att["status"])
    att["status"] = "MINUTES_SUBMITTED"
    att["minutes_summary"] = summary
    att["topics_discussed"] = topics
    touch(att)
    return ok(att, domain.ser_attendance)


@bp.post("/compliance/meeting-attendances/<attendance_id>/minutes-review")
def review_minutes(attendance_id):
    role, user_id = require_auth(["AntitrustCounsel"])
    payload = body()
    verdict = req_enum(payload, "verdict", calc.VERDICTS)
    findings = req_enum_array(payload, "findings", calc.FINDING_CODES)

    att = lookup("attendances", attendance_id)
    part = db.participations[att["participation_id"]]
    if part.get("legal_cleared_by_user_id") is not None \
            and user_id == part["legal_cleared_by_user_id"]:
        fail("ERR_SEGREGATION_OF_DUTIES", "the clearing counsel may not review these minutes")
    if att["status"] != "MINUTES_SUBMITTED":
        fail("ERR_INVALID_STATE", "attendance is %s" % att["status"])

    unit = db.business_units[part["business_unit_id"]]
    assessed = calc.minutes_review_exposure_points(verdict, findings, unit["risk_band"])
    att["minutes_verdict"] = verdict
    att["minutes_findings"] = findings
    att["minutes_reviewed_by_user_id"] = user_id
    att["exposure_points_assessed"] = assessed
    att["status"] = "FLAGGED" if verdict == "VIOLATION" else "MINUTES_REVIEWED"
    touch(att)

    domain.recompute_ledger(unit)
    touch(unit)
    domain.recompute_posture(unit)

    if verdict == "VIOLATION":
        if part["status"] == "ACTIVE":
            part["status"] = "UNDER_REVIEW"
            touch(part)
        employee = db.employees[part["employee_id"]]
        domain.suspend_employee_clearance(employee, "delegate clearance suspended by minutes violation")
    return ok(att, domain.ser_attendance)


@bp.post("/compliance/meeting-attendances/<attendance_id>/remediation-closure")
def close_remediation(attendance_id):
    role, user_id = require_auth(["AntitrustCounsel"])
    payload = body()
    req_str(payload, "notes")
    att = lookup("attendances", attendance_id)
    if att.get("minutes_reviewed_by_user_id") is not None \
            and user_id == att["minutes_reviewed_by_user_id"]:
        fail("ERR_SEGREGATION_OF_DUTIES", "the reviewing counsel may not close this remediation")
    if att["status"] != "FLAGGED":
        fail("ERR_INVALID_STATE", "attendance is %s" % att["status"])
    att["status"] = "MINUTES_REVIEWED"
    touch(att)
    return ok(att, domain.ser_attendance)
