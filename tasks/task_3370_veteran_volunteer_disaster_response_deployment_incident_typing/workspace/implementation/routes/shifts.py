"""Duty shift endpoints: schedule (credential gate, half-open overlap rule,
fatigue cap, in pinned order), list, get.
"""
from flask import Blueprint
import db
import errors
import envelope
import validation as V
import auth
import domain
import calculations
import timeutil
from constants import SHIFT_KINDS, MAX_SHIFT_HOURS, MAX_FATIGUE_HOURS

bp = Blueprint("duty_shifts", __name__)

SHIFT_READ_ROLES = ("SystemAdmin", "OperationsLead", "IncidentCommander",
                    "SafetyOfficer", "Volunteer")


@bp.post("/vdr/operations/<oid>/duty-shifts")
def create_duty_shift(oid):
    body = V.get_body()
    V.check_unknown(body, {"deployment_id", "kind", "starts_at", "ends_at"})
    deployment_id = V.req_str(body, "deployment_id")
    kind = V.req_enum(body, "kind", SHIFT_KINDS)
    starts_at = V.req_dt(body, "starts_at")
    ends_at = V.req_dt(body, "ends_at")
    if ends_at <= starts_at:
        errors.validation("ends_at must be strictly after starts_at")
    if (ends_at - starts_at).total_seconds() > MAX_SHIFT_HOURS * 3600:
        errors.validation("a shift may not exceed %d hours" % MAX_SHIFT_HOURS)
    auth.require_roles("OperationsLead")
    op = db.get("operations", oid)
    if op is None:
        errors.operation_not_found()
    dep = db.get("deployments", deployment_id)
    if dep is None:
        errors.deployment_not_found()
    if dep["operation_id"] != oid:
        errors.validation("deployment does not belong to this operation")
    if dep["status"] != "ON_SITE":
        errors.invalid_state("duty shifts require an ON_SITE deployment")
    vol = db.get("volunteers", dep["volunteer_id"])
    # Safety checks fire in pinned order (PRD 3.5).
    # 1. credential gate: SAFETY_WATCH requires VERIFIED MEDICAL or STRUCTURAL.
    if kind == "SAFETY_WATCH":
        if not (domain.has_verified(vol["id"], "MEDICAL")
                or domain.has_verified(vol["id"], "STRUCTURAL")):
            errors.err("ERR_CERT_NOT_VERIFIED", 422,
                       "SAFETY_WATCH requires a VERIFIED MEDICAL or STRUCTURAL certification")
    # 2. half-open overlap: reject when new.starts < existing.ends AND
    #    new.ends > existing.starts; mere adjacency is admissible.
    for existing in domain.shifts_of_deployment(dep["id"]):
        if existing["status"] not in ("SCHEDULED", "COMPLETED"):
            continue
        e_start = timeutil.parse_iso(existing["starts_at"])
        e_end = timeutil.parse_iso(existing["ends_at"])
        if starts_at < e_end and ends_at > e_start:
            errors.err("ERR_SHIFT_OVERLAP", 409,
                       "shift overlaps an existing shift of the same deployment")
    # 3. fatigue cap: current fatigue + new shift hours <= 40 (equality admitted).
    hours = calculations.shift_hours(timeutil.fmt(starts_at), timeutil.fmt(ends_at))
    if vol["fatigue_hours"] + hours > MAX_FATIGUE_HOURS:
        errors.err("ERR_FATIGUE_LIMIT_EXCEEDED", 422,
                   "shift would exceed the 40-hour fatigue cap")
    shift = db.mint("duty_shifts", {
        "operation_id": oid,
        "deployment_id": deployment_id,
        "kind": kind,
        "starts_at": timeutil.fmt(starts_at),
        "ends_at": timeutil.fmt(ends_at),
        "status": "SCHEDULED",
    })
    now = db.now()
    if starts_at <= now < ends_at and dep["duty_status"] == "RESTING":
        dep["duty_status"] = "ON_DUTY"
        db.touch(dep)
    return envelope.ok(domain.public(shift), 201)


@bp.get("/vdr/duty-shifts")
def list_duty_shifts():
    auth.require_roles(*SHIFT_READ_ROLES)
    items = db.all_of("duty_shifts")
    for param in ("operation_id", "deployment_id", "status"):
        value = V.qparam(param)
        if value is not None:
            items = [s for s in items if s.get(param) == value]
    return envelope.paginate(domain.public_list(items))


@bp.get("/vdr/duty-shifts/<sid>")
def get_duty_shift(sid):
    uid, role = auth.require_roles(*SHIFT_READ_ROLES)
    shift = db.get("duty_shifts", sid)
    if shift is None:
        errors.duty_shift_not_found()
    if role == "Volunteer":
        dep = db.get("deployments", shift["deployment_id"])
        if dep is None or dep["volunteer_id"] != uid:
            errors.unauthorized("a Volunteer may only read their own duty shifts")
    return envelope.ok(domain.public(shift))
