"""Past-date compliance audits and their findings."""
from flask import Blueprint

import calc
import services
from db import db
from errors import ApiError
from middleware import (ROLE_ADMIN, ROLE_AUDITOR, ROLE_MANAGER, actor,
                        authenticate, role)
from records import (audit_by_id, department_by_id, department_of_lot,
                     finding_by_id, findings_of_audit, new_record, touch)
from response import created, ok, public
from routes.common import (DISPOSITION_STATUSES, FINDING_STATUSES,
                           REMEDIATIONS, SEVERITIES, SWEEP_STATUSES, listing,
                           matches)
from util import D, fmt_instant, num, parse_instant, rhu_int
from validate import (MISSING, field_bool, field_enum, field_instant,
                      field_string, json_body, query_enum, query_string)

bp = Blueprint("compliance", __name__)

READ_ROLES = (ROLE_ADMIN, ROLE_MANAGER, ROLE_AUDITOR)
LIVE_DISPOSITIONS = ("PENDING", "ESCALATED")


# --- reads -----------------------------------------------------------------
@bp.get("/fresh/compliance-audits/<audit_id>")
def get_audit(audit_id):
    authenticate(*READ_ROLES)
    return ok(public(audit_by_id(audit_id)))


@bp.get("/fresh/compliance-audits")
def list_audits():
    authenticate(*READ_ROLES)
    department_id = query_string("department_id")
    sweep_status = query_enum("sweep_status", SWEEP_STATUSES)
    disposition = query_enum("disposition_status", DISPOSITION_STATUSES)
    severity = query_enum("severity", SEVERITIES)
    rows = [
        a for a in db.audits.values()
        if matches(a, "department_id", department_id)
        and matches(a, "sweep_status", sweep_status)
        and matches(a, "disposition_status", disposition)
        and matches(a, "severity", severity)
    ]
    return listing(rows)


@bp.get("/fresh/audit-findings/<finding_id>")
def get_finding(finding_id):
    authenticate(*READ_ROLES)
    return ok(public(finding_by_id(finding_id)))


@bp.get("/fresh/audit-findings")
def list_findings():
    authenticate(*READ_ROLES)
    audit_id = query_string("audit_id")
    lot_id = query_string("lot_id")
    status = query_enum("status", FINDING_STATUSES)
    remediation = query_enum("remediation", REMEDIATIONS)
    rows = [
        f for f in db.findings.values()
        if matches(f, "audit_id", audit_id)
        and matches(f, "lot_id", lot_id)
        and matches(f, "status", status)
        and matches(f, "remediation", remediation)
    ]
    return listing(rows)


# --- opening an audit ------------------------------------------------------
@bp.post("/fresh/compliance-audits")
def create_audit():
    authenticate(ROLE_AUDITOR)
    body = json_body()
    department_id = field_string(body, "department_id", required=True,
                                 max_len=200)
    start = field_instant(body, "window_start_at", required=True)
    end = field_instant(body, "window_end_at", required=True)
    if end <= start:
        raise ApiError(
            "ERR_INVALID_REQUEST",
            "window_end_at must be strictly after window_start_at",
            400,
        )
    department = department_by_id(department_id)
    for other in db.audits.values():
        if other["department_id"] != department["id"]:
            continue
        if other["disposition_status"] not in LIVE_DISPOSITIONS:
            continue
        other_start = parse_instant(other["window_start_at"])
        other_end = parse_instant(other["window_end_at"])
        if start < other_end and other_start < end:
            raise ApiError(
                "ERR_AUDIT_WINDOW_OVERLAP",
                "A live audit window on this department already overlaps",
            )
    audit = new_record(db.audits, {
        "department_id": department["id"],
        "window_start_at": fmt_instant(start),
        "window_end_at": fmt_instant(end),
        "sweep_status": "NOT_STARTED",
        "disposition_status": "PENDING",
        "past_date_lot_count": 0,
        "past_date_units_total": 0,
        "severity_points_total": 0,
        "severity": "NONE",
        "opened_by_user_id": actor(),
        "swept_at": None,
    })
    return created(public(audit))


# --- the shelf walk --------------------------------------------------------
@bp.post("/fresh/compliance-audits/<audit_id>/sweep")
def sweep(audit_id):
    authenticate(ROLE_AUDITOR)
    json_body()
    audit = audit_by_id(audit_id)
    if audit["sweep_status"] != "NOT_STARTED":
        raise ApiError("ERR_AUDIT_ALREADY_SWEPT",
                       "This audit has already been swept")
    now = db.now()
    if now < parse_instant(audit["window_start_at"]) or \
            now >= parse_instant(audit["window_end_at"]):
        raise ApiError("ERR_AUDIT_WINDOW_NOT_OPEN",
                       "The logical clock is outside the audit window")
    department = department_by_id(audit["department_id"])
    tolerance = department["past_date_tolerance_hours"]
    units_total = 0
    points_total = 0
    count = 0
    for lot in calc.past_date_lots_on_shelf(department):
        hours = calc.hours_past_date(lot)
        units = lot["quantity_on_hand"]
        multiplier = calc.severity_multiplier(hours, tolerance)
        points = rhu_int(D(units) * D(multiplier))
        new_record(db.findings, {
            "audit_id": audit["id"],
            "lot_id": lot["id"],
            "hours_past_date": hours,
            "units_on_shelf": units,
            "severity_multiplier": num(D(multiplier)),
            "severity_points": points,
            "remediation": "NONE",
            "status": "OPEN",
            "resolved_by_user_id": None,
        })
        lot["past_date_flag"] = True
        units_total += units
        points_total += points
        count += 1
    audit["past_date_lot_count"] = count
    audit["past_date_units_total"] = units_total
    audit["severity_points_total"] = points_total
    audit["severity"] = calc.severity_band(points_total)
    audit["sweep_status"] = "SWEPT"
    audit["swept_at"] = fmt_instant(now)
    touch(audit)
    services.recompute_open_finding_count(department)
    services.recompute_posture(department)
    return ok(public(audit))


@bp.post("/fresh/compliance-audits/<audit_id>/escalate")
def escalate(audit_id):
    authenticate(ROLE_AUDITOR)
    body = json_body()
    field_string(body, "escalation_note", default=None, nullable=True,
                 min_len=1, max_len=240)
    audit = audit_by_id(audit_id)
    findings = findings_of_audit(audit["id"])
    open_findings = [f for f in findings if f["status"] == "OPEN"]
    if audit["sweep_status"] == "SWEPT" and not open_findings:
        raise ApiError("ERR_FINDING_ALREADY_RESOLVED",
                       "Every finding on this audit is already closed")
    if audit["severity"] != "CRITICAL" or \
            audit["disposition_status"] != "PENDING":
        raise ApiError("ERR_ESCALATION_NOT_WARRANTED",
                       "Only a swept CRITICAL audit pending follow-up "
                       "may be escalated")
    audit["disposition_status"] = "ESCALATED"
    touch(audit)
    department = department_by_id(audit["department_id"])
    services.recompute_posture(department)
    return ok(public(audit))


# --- closing a finding -----------------------------------------------------
def _bubble_up(audit, department):
    if audit["sweep_status"] != "SWEPT":
        return
    if any(f["status"] == "OPEN" for f in findings_of_audit(audit["id"])):
        return
    if audit["disposition_status"] in LIVE_DISPOSITIONS:
        audit["disposition_status"] = "REMEDIATED"
        touch(audit)


@bp.post("/fresh/audit-findings/<finding_id>/remediate")
def remediate(finding_id):
    authenticate(ROLE_AUDITOR, ROLE_MANAGER)
    body = json_body()
    remediation = field_enum(body, "remediation", REMEDIATIONS,
                             default=MISSING)
    waive = field_bool(body, "waive", default=MISSING)
    field_string(body, "resolution_note", default=None, nullable=True,
                 min_len=1, max_len=240)
    finding = finding_by_id(finding_id)
    if finding["status"] != "OPEN":
        raise ApiError("ERR_FINDING_ALREADY_RESOLVED",
                       "This finding has already been closed")
    withdrawn = remediation == "WITHDRAWN"
    waiving = waive is True
    lot = db.lots[finding["lot_id"]]
    department = department_of_lot(lot)
    audit = db.audits[finding["audit_id"]]
    if withdrawn:
        if lot["quantity_on_hand"] <= 0:
            raise ApiError("ERR_REMEDIATION_NOT_PERMITTED",
                           "The finding's lot no longer holds any units")
        finding["remediation"] = "WITHDRAWN"
        finding["status"] = "RESOLVED"
        finding["resolved_by_user_id"] = actor()
        touch(finding)
        services.withdraw_lot(lot, actor())
    elif waiving:
        if role() != ROLE_AUDITOR:
            raise ApiError("ERR_UNAUTHORIZED",
                           "Only a ComplianceAuditor may waive a finding", 403)
        if D(finding["severity_multiplier"]) != D(1):
            raise ApiError("ERR_WAIVER_NOT_PERMITTED",
                           "Only a finding scored at multiplier 1 "
                           "may be waived")
        finding["status"] = "WAIVED"
        finding["resolved_by_user_id"] = actor()
        touch(finding)
    else:
        raise ApiError(
            "ERR_REMEDIATION_NOT_PERMITTED",
            "Supply either remediation=WITHDRAWN or waive=true",
        )
    _bubble_up(audit, department)
    services.recompute_open_finding_count(department)
    services.recompute_posture(department)
    return ok(public(finding))
