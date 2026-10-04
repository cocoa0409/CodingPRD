"""Incident endpoints plus the two nested creators that hang off an incident:
POST /vdr/incidents/{id}/operations and POST /vdr/incidents/{id}/work-orders.
Nested path ids resolve left to right: incident first.
"""
from flask import Blueprint
import db
import errors
import envelope
import validation as V
import auth
import domain
import cascades
from constants import (
    INCIDENT_STATUSES, INCIDENT_TYPES, HAZARDS, CERT_KINDS,
    MAX_TEAM_SIZE, MAX_OPERATION_DURATION_DAYS,
)

bp = Blueprint("incidents", __name__)

INCIDENT_READ_ROLES = ("SystemAdmin", "IncidentCommander", "OperationsLead",
                       "IntakeCoordinator", "SafetyOfficer", "TrainingDirector",
                       "PartnerLiaison", "Volunteer")


@bp.post("/vdr/incidents")
def create_incident():
    body = V.get_body()
    V.check_unknown(body, {"name", "region"})
    name = V.req_str(body, "name")
    region = V.req_str(body, "region")
    auth.require_roles("IncidentCommander")
    inc = db.mint("incidents", {
        "name": name,
        "region": region,
        "status": "REPORTED",
        "severity": None,
        "affected_households": None,
        "incident_type": None,
        "reported_at": db.now_iso(),
    })
    return envelope.ok(domain.public(inc), 201)


@bp.get("/vdr/incidents/<iid>")
def get_incident(iid):
    auth.require_roles(*INCIDENT_READ_ROLES)
    inc = db.get("incidents", iid)
    if inc is None:
        errors.incident_not_found()
    return envelope.ok(domain.public(inc))


@bp.patch("/vdr/incidents/<iid>")
def patch_incident(iid):
    body = V.get_body()
    V.check_unknown(body, {"status", "severity", "affected_households", "incident_type"})
    target = V.req_enum(body, "status", INCIDENT_STATUSES)
    severity = V.opt_int(body, "severity", lo=1, hi=5)
    households = V.opt_int(body, "affected_households", lo=0)
    incident_type = V.opt_enum(body, "incident_type", INCIDENT_TYPES)
    auth.require_roles("IncidentCommander")
    inc = db.get("incidents", iid)
    if inc is None:
        errors.incident_not_found()
    cur = inc["status"]

    if (cur, target) == ("REPORTED", "ASSESSED"):
        if severity is None or households is None:
            errors.validation("assessment requires severity and affected_households")
        inc["status"] = "ASSESSED"
        inc["severity"] = severity
        inc["affected_households"] = households
        db.touch(inc)
    elif (cur, target) == ("ASSESSED", "TYPED"):
        if incident_type is None:
            errors.validation("typing requires incident_type")
        inc["status"] = "TYPED"
        inc["incident_type"] = incident_type
        db.touch(inc)
    elif (cur, target) == ("TYPED", "STANDING_DOWN"):
        inc["status"] = "STANDING_DOWN"
        db.touch(inc)
        cascades.stand_down_incident(inc)
    elif (cur, target) == ("STANDING_DOWN", "CLOSED"):
        ops = [o for o in db.store["operations"].values() if o["incident_id"] == inc["id"]]
        if any(o["status"] not in ("COMPLETE", "CANCELLED") for o in ops):
            errors.invalid_state("every operation must be terminal before closure")
        inc["status"] = "CLOSED"
        db.touch(inc)
    elif target == "CANCELLED" and cur in ("REPORTED", "ASSESSED"):
        inc["status"] = "CANCELLED"
        db.touch(inc)
    else:
        errors.invalid_state("cannot transition incident from %s to %s" % (cur, target))
    return envelope.ok(domain.public(inc))


@bp.post("/vdr/incidents/<iid>/operations")
def create_operation(iid):
    body = V.get_body()
    V.check_unknown(body, {"title", "hazard_focus", "team_size_required",
                           "duration_days", "required_capabilities", "start_date"})
    title = V.req_str(body, "title")
    hazard_focus = V.req_enum(body, "hazard_focus", HAZARDS)
    team_size = V.req_int(body, "team_size_required", lo=2, hi=MAX_TEAM_SIZE)
    duration = V.req_int(body, "duration_days", lo=1, hi=MAX_OPERATION_DURATION_DAYS)
    caps = V.req_list_enum(body, "required_capabilities", CERT_KINDS, allow_empty=False)
    start_date = V.req_date(body, "start_date")
    auth.require_roles("IncidentCommander")
    inc = db.get("incidents", iid)
    if inc is None:
        errors.incident_not_found()
    if inc["status"] != "TYPED":
        errors.err("ERR_INCIDENT_NOT_TYPED", 409,
                   "operations may only be created under a TYPED incident")
    deduped_caps = list(dict.fromkeys(caps))
    op = db.mint("operations", {
        "incident_id": iid,
        "title": title,
        "hazard_focus": hazard_focus,
        "team_size_required": team_size,
        "duration_days": duration,
        "required_capabilities": deduped_caps,
        "start_date": start_date,
        "status": "DRAFT",
        "aar_status": "NONE",
        "aar_notes": None,
        "aar_submitted_by_role": None,
        "rostered_count": 0,
        "capability_gap": {},
    })
    return envelope.ok(domain.public(op), 201)


@bp.post("/vdr/incidents/<iid>/work-orders")
def create_work_order(iid):
    body = V.get_body()
    V.check_unknown(body, {"requester_name", "hazard_kind", "vulnerable_resident",
                           "municipality_sourced", "source_partner_id"})
    requester_name = V.req_str(body, "requester_name")
    hazard_kind = V.req_enum(body, "hazard_kind", HAZARDS)
    vulnerable = V.opt_bool(body, "vulnerable_resident", False)
    municipality = V.opt_bool(body, "municipality_sourced", False)
    source_partner = V.opt_str(body, "source_partner_id", None)
    uid, role = auth.require_roles("IntakeCoordinator", "PartnerLiaison")
    if role == "PartnerLiaison" and source_partner != uid:
        errors.unauthorized("a PartnerLiaison must set source_partner_id to their own agency id")
    inc = db.get("incidents", iid)
    if inc is None:
        errors.incident_not_found()
    if source_partner is not None and db.get("partners", source_partner) is None:
        errors.partner_not_found()
    if inc["status"] not in ("ASSESSED", "TYPED", "STANDING_DOWN"):
        errors.invalid_state("incident is not accepting work orders in status %s" % inc["status"])
    wo = db.mint("work_orders", {
        "incident_id": iid,
        "operation_id": None,
        "source_partner_id": source_partner,
        "requester_name": requester_name,
        "hazard_kind": hazard_kind,
        "vulnerable_resident": vulnerable,
        "municipality_sourced": municipality,
        "status": "INTAKE",
        "priority_score": None,
        "priority_tier": None,
        "blocked_reason": None,
    })
    return envelope.ok(domain.public(wo), 201)
