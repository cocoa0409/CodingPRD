"""Sites, readiness drills, document audits and leniency applications."""
from flask import Blueprint

import calc
import domain
from api import ok, created, listing
from errors import fail
from ladder import (require_auth, body, touch, lookup, rows, pagination, filter_enum,
                    filter_str, req_str, req_enum, req_int, req_num, req_dt,
                    req_affected_years, ALL_ROLES)
from store import db, new_record, clock_now

bp = Blueprint("ops", __name__)

DRILL_STATUSES = ["SCHEDULED", "IN_PROGRESS", "COMPLETED", "ABORTED"]
MARKER_STATUSES = ["NONE", "MARKER_REQUESTED", "MARKER_GRANTED", "MARKER_DENIED",
                   "MARKER_EXPIRED", "PERFECTED"]
DISCLOSURE_STATUSES = ["DRAFT", "SUBMITTED", "ACCEPTED", "REJECTED", "WITHDRAWN"]


# ======================================================================== Site
@bp.post("/compliance/sites")
def create_site():
    require_auth(["ComplianceAdmin"])
    payload = body()
    name = req_str(payload, "name")
    country_code = req_str(payload, "country_code")
    capacity = req_int(payload, "concurrent_drill_capacity", required=False, default=1,
                       minimum=1)
    row = new_record({
        "name": name,
        "country_code": country_code,
        "concurrent_drill_capacity": capacity,
    })
    db.sites[row["id"]] = row
    return created(row, domain.ser_site)


@bp.get("/compliance/sites/<site_id>")
def read_site(site_id):
    require_auth(ALL_ROLES)
    return ok(lookup("sites", site_id), domain.ser_site)


# ============================================================== ReadinessDrill
@bp.post("/compliance/readiness-drills")
def create_drill():
    require_auth(["ComplianceAdmin", "AntitrustCounsel"])
    payload = body()
    site_id = req_str(payload, "site_id")
    drill_type = req_enum(payload, "drill_type", calc.DRILL_TYPES)
    window_start = req_dt(payload, "window_start")
    window_end = req_dt(payload, "window_end")

    site = lookup("sites", site_id)
    if not window_end > window_start:
        fail("ERR_INVALID_INTERVAL", "window_end must be strictly after window_start")

    occupying = [x for x in rows("drills")
                 if x["site_id"] == site_id and x["status"] in ("SCHEDULED", "IN_PROGRESS")]
    instants = [window_start]
    for other in occupying:
        if window_start < other["window_start"] < window_end:
            instants.append(other["window_start"])
    capacity = site["concurrent_drill_capacity"]
    for instant in instants:
        concurrency = 1 + len([o for o in occupying
                               if o["window_start"] <= instant < o["window_end"]])
        if concurrency > capacity:
            fail("ERR_SITE_DRILL_CAPACITY_EXCEEDED", "site drill capacity exceeded")

    row = new_record({
        "site_id": site_id,
        "drill_type": drill_type,
        "window_start": window_start,
        "window_end": window_end,
        "status": "SCHEDULED",
        "score": None,
        "gaps_found": None,
        "abort_reason": None,
    })
    db.drills[row["id"]] = row
    return created(row, domain.ser_drill)


@bp.get("/compliance/readiness-drills/<drill_id>")
def read_drill(drill_id):
    require_auth(ALL_ROLES)
    return ok(lookup("drills", drill_id), domain.ser_drill)


@bp.get("/compliance/readiness-drills")
def list_drills():
    require_auth(ALL_ROLES)
    site_id = filter_str("site_id")
    status = filter_enum("status", DRILL_STATUSES)
    drill_type = filter_enum("drill_type", calc.DRILL_TYPES)
    limit, offset = pagination()
    items = rows("drills")
    if site_id:
        items = [r for r in items if r["site_id"] == site_id]
    if status:
        items = [r for r in items if r["status"] == status]
    if drill_type:
        items = [r for r in items if r["drill_type"] == drill_type]
    return listing(items, domain.ser_drill, limit, offset)


@bp.post("/compliance/readiness-drills/<drill_id>/start")
def start_drill(drill_id):
    require_auth(["ComplianceAdmin", "AntitrustCounsel"])
    body()
    drill = lookup("drills", drill_id)
    if drill["status"] != "SCHEDULED":
        fail("ERR_INVALID_STATE", "drill is %s" % drill["status"])
    if clock_now() < drill["window_start"]:
        fail("ERR_INVALID_STATE", "the drill window has not opened yet")
    drill["status"] = "IN_PROGRESS"
    touch(drill)
    return ok(drill, domain.ser_drill)


@bp.post("/compliance/readiness-drills/<drill_id>/completion")
def complete_drill(drill_id):
    require_auth(["ComplianceAdmin", "AntitrustCounsel"])
    payload = body()
    score = req_int(payload, "score", minimum=0, maximum=100)
    gaps = req_int(payload, "gaps_found", minimum=0)
    drill = lookup("drills", drill_id)
    if drill["status"] != "IN_PROGRESS":
        fail("ERR_INVALID_STATE", "drill is %s" % drill["status"])
    drill["status"] = "COMPLETED"
    drill["score"] = score
    drill["gaps_found"] = gaps
    touch(drill)
    site = db.sites.get(drill["site_id"])
    if site is not None:
        touch(site)
    return ok(drill, domain.ser_drill)


@bp.post("/compliance/readiness-drills/<drill_id>/abort")
def abort_drill(drill_id):
    require_auth(["ComplianceAdmin", "AntitrustCounsel"])
    payload = body()
    reason = req_str(payload, "reason")
    drill = lookup("drills", drill_id)
    if drill["status"] not in ("SCHEDULED", "IN_PROGRESS"):
        fail("ERR_INVALID_STATE", "drill is %s" % drill["status"])
    drill["status"] = "ABORTED"
    drill["abort_reason"] = reason
    touch(drill)
    return ok(drill, domain.ser_drill)


# =============================================================== DocumentAudit
@bp.post("/compliance/document-audits")
def create_audit():
    require_auth(["AntitrustCounsel"])
    payload = body()
    unit_id = req_str(payload, "business_unit_id")
    sample_size = req_int(payload, "sample_size", minimum=1)
    scope_note = req_str(payload, "scope_note")
    lookup("business_units", unit_id)
    row = new_record({
        "business_unit_id": unit_id,
        "sample_size": sample_size,
        "scope_note": scope_note,
        "status": "OPEN",
        "violation_count": None,
        "high_risk_phrase_count": None,
        "guideline_score": None,
    })
    db.document_audits[row["id"]] = row
    return created(row, domain.ser_audit)


@bp.get("/compliance/document-audits/<audit_id>")
def read_audit(audit_id):
    require_auth(ALL_ROLES)
    return ok(lookup("document_audits", audit_id), domain.ser_audit)


@bp.get("/compliance/document-audits")
def list_audits():
    require_auth(ALL_ROLES)
    unit_id = filter_str("business_unit_id")
    status = filter_enum("status", ["OPEN", "COMPLETED"])
    limit, offset = pagination()
    items = rows("document_audits")
    if unit_id:
        items = [r for r in items if r["business_unit_id"] == unit_id]
    if status:
        items = [r for r in items if r["status"] == status]
    return listing(items, domain.ser_audit, limit, offset)


@bp.post("/compliance/document-audits/<audit_id>/findings")
def record_findings(audit_id):
    require_auth(["AntitrustCounsel"])
    payload = body()
    violations = req_int(payload, "violation_count", minimum=0)
    phrases = req_int(payload, "high_risk_phrase_count", minimum=0)
    audit = lookup("document_audits", audit_id)
    if audit["status"] != "OPEN":
        fail("ERR_INVALID_STATE", "audit is %s" % audit["status"])
    if violations > audit["sample_size"]:
        fail("ERR_INVALID_REQUEST", "violation_count may not exceed sample_size")
    audit["status"] = "COMPLETED"
    audit["violation_count"] = violations
    audit["high_risk_phrase_count"] = phrases
    audit["guideline_score"] = calc.document_guideline_score(
        audit["sample_size"], violations, phrases)
    touch(audit)
    unit = db.business_units.get(audit["business_unit_id"])
    if unit is not None:
        touch(unit)
    return ok(audit, domain.ser_audit)


# ========================================================== LeniencyApplication
@bp.post("/compliance/leniency-applications")
def create_application():
    require_auth(["AntitrustCounsel"])
    payload = body()
    unit_id = req_str(payload, "business_unit_id")
    cartel_code = req_str(payload, "cartel_code")
    affected_years = req_affected_years(payload)
    source_contact_id = req_str(payload, "source_contact_id", required=False)

    lookup("business_units", unit_id)
    if source_contact_id is not None:
        lookup("contacts", source_contact_id)

    row = new_record({
        "business_unit_id": unit_id,
        "source_contact_id": source_contact_id,
        "cartel_code": cartel_code,
        "affected_years": affected_years,
        "gravity_pct": None,
        "marker_status": "NONE",
        "disclosure_status": "DRAFT",
        "marker_requested_at": None,
        "marker_granted_at": None,
        "priority_rank": None,
        "estimated_penalty_cents": None,
        "withdrawal_reason": None,
    })
    db.leniency_applications[row["id"]] = row
    return created(row, domain.ser_leniency)


@bp.get("/compliance/leniency-applications/<application_id>")
def read_application(application_id):
    require_auth(ALL_ROLES)
    return ok(lookup("leniency_applications", application_id), domain.ser_leniency)


@bp.get("/compliance/leniency-applications")
def list_applications():
    require_auth(ALL_ROLES)
    unit_id = filter_str("business_unit_id")
    cartel_code = filter_str("cartel_code")
    source_contact_id = filter_str("source_contact_id")
    marker_status = filter_enum("marker_status", MARKER_STATUSES)
    disclosure_status = filter_enum("disclosure_status", DISCLOSURE_STATUSES)
    limit, offset = pagination()
    items = rows("leniency_applications")
    if unit_id:
        items = [r for r in items if r["business_unit_id"] == unit_id]
    if cartel_code:
        items = [r for r in items if r["cartel_code"] == cartel_code]
    if source_contact_id:
        items = [r for r in items if r.get("source_contact_id") == source_contact_id]
    if marker_status:
        items = [r for r in items if r["marker_status"] == marker_status]
    if disclosure_status:
        items = [r for r in items if r["disclosure_status"] == disclosure_status]
    return listing(items, domain.ser_leniency, limit, offset)


@bp.post("/compliance/leniency-applications/<application_id>/marker-request")
def request_marker(application_id):
    require_auth(["AntitrustCounsel"])
    body()
    app_row = lookup("leniency_applications", application_id)
    if app_row["marker_status"] != "NONE":
        fail("ERR_INVALID_STATE", "marker is %s" % app_row["marker_status"])
    assessment = domain.active_assessment(app_row["business_unit_id"])
    if assessment is None or assessment["risk_band"] not in ("HIGH", "SEVERE"):
        fail("ERR_RISK_BAND_TOO_LOW", "the unit's active risk band is too low")
    for other in rows("leniency_applications"):
        if other["id"] == app_row["id"]:
            continue
        if (other["business_unit_id"] == app_row["business_unit_id"]
                and other["cartel_code"] == app_row["cartel_code"]
                and other["marker_status"] in domain.LIVE_MARKER_STATUSES):
            fail("ERR_MARKER_ALREADY_HELD", "a live marker is already held for this cartel")

    app_row["marker_status"] = "MARKER_REQUESTED"
    app_row["marker_requested_at"] = clock_now()
    touch(app_row)
    unit = db.business_units[app_row["business_unit_id"]]
    touch(unit)
    domain.recompute_posture(unit)
    return ok(app_row, domain.ser_leniency)


@bp.post("/compliance/leniency-applications/<application_id>/marker-decisions")
def decide_marker(application_id):
    require_auth(["ComplianceAdmin"])
    payload = body()
    decision = req_enum(payload, "decision", ["GRANTED", "DENIED"])
    app_row = lookup("leniency_applications", application_id)
    if app_row["marker_status"] != "MARKER_REQUESTED":
        fail("ERR_INVALID_STATE", "marker is %s" % app_row["marker_status"])
    if decision == "GRANTED":
        app_row["marker_status"] = "MARKER_GRANTED"
        app_row["marker_granted_at"] = clock_now()
        domain.recompute_leniency(app_row)
        touch(app_row)
    else:
        app_row["marker_status"] = "MARKER_DENIED"
        app_row["priority_rank"] = None
        touch(app_row)
        unit = db.business_units[app_row["business_unit_id"]]
        touch(unit)
        domain.recompute_posture(unit)
    return ok(app_row, domain.ser_leniency)


@bp.post("/compliance/leniency-applications/<application_id>/disclosure-submission")
def submit_disclosure(application_id):
    require_auth(["AntitrustCounsel"])
    payload = body()
    gravity = req_num(payload, "gravity_pct", minimum=0, maximum=30)
    app_row = lookup("leniency_applications", application_id)
    if app_row["disclosure_status"] != "DRAFT":
        fail("ERR_INVALID_STATE", "disclosure is %s" % app_row["disclosure_status"])
    if app_row["marker_status"] not in ("MARKER_REQUESTED", "MARKER_GRANTED"):
        fail("ERR_MARKER_NOT_GRANTED", "marker is %s" % app_row["marker_status"])
    app_row["disclosure_status"] = "SUBMITTED"
    app_row["gravity_pct"] = gravity
    domain.recompute_leniency(app_row)
    touch(app_row)
    return ok(app_row, domain.ser_leniency)


@bp.post("/compliance/leniency-applications/<application_id>/disclosure-decision")
def decide_disclosure(application_id):
    require_auth(["ComplianceAdmin"])
    payload = body()
    decision = req_enum(payload, "decision", ["ACCEPTED", "REJECTED"])
    app_row = lookup("leniency_applications", application_id)
    if app_row["disclosure_status"] != "SUBMITTED":
        fail("ERR_INVALID_STATE", "disclosure is %s" % app_row["disclosure_status"])
    if decision == "ACCEPTED":
        app_row["disclosure_status"] = "ACCEPTED"
        if app_row["marker_status"] == "MARKER_GRANTED":
            app_row["marker_status"] = "PERFECTED"
    else:
        app_row["disclosure_status"] = "REJECTED"
    domain.recompute_leniency(app_row)
    touch(app_row)
    return ok(app_row, domain.ser_leniency)


@bp.post("/compliance/leniency-applications/<application_id>/withdrawal")
def withdraw_application(application_id):
    require_auth(["AntitrustCounsel"])
    payload = body()
    reason = req_str(payload, "reason")
    app_row = lookup("leniency_applications", application_id)
    if app_row["disclosure_status"] not in ("DRAFT", "SUBMITTED"):
        fail("ERR_INVALID_STATE", "disclosure is %s" % app_row["disclosure_status"])
    app_row["disclosure_status"] = "WITHDRAWN"
    app_row["withdrawal_reason"] = reason
    surrendered = app_row["marker_status"] in ("MARKER_REQUESTED", "MARKER_GRANTED")
    if surrendered:
        app_row["marker_status"] = "MARKER_DENIED"
        app_row["priority_rank"] = None
    touch(app_row)
    if surrendered:
        unit = db.business_units[app_row["business_unit_id"]]
        touch(unit)
        domain.recompute_posture(unit)
    return ok(app_row, domain.ser_leniency)
