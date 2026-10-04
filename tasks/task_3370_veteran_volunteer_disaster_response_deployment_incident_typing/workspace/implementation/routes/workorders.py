"""Work order endpoints: list, get, OCC-guarded triage, and the transition
lattice. Scheduling gate order is pinned (PRD 3.6): capability, then hazard
alignment, then operation state, then incident typing.
"""
from flask import Blueprint
import db
import errors
import envelope
import validation as V
import auth
import domain
import calculations
from constants import WORK_ORDER_STATUSES, HAZARD_TO_CAPABILITY

bp = Blueprint("work_orders", __name__)

WO_READ_ROLES = ("SystemAdmin", "IncidentCommander", "OperationsLead",
                 "IntakeCoordinator", "PartnerLiaison")

TARGET_ROLES = {
    "SCHEDULED": ("IntakeCoordinator", "OperationsLead"),
    "IN_PROGRESS": ("OperationsLead",),
    "BLOCKED": ("OperationsLead",),
    "DONE_PENDING_VERIFICATION": ("OperationsLead",),
    "VERIFIED_DONE": ("IntakeCoordinator",),
    "CANCELLED": ("IntakeCoordinator",),
}


@bp.get("/vdr/work-orders")
def list_work_orders():
    auth.require_roles(*WO_READ_ROLES)
    items = db.all_of("work_orders")
    for param in ("incident_id", "operation_id", "source_partner_id", "status", "priority_tier"):
        value = V.qparam(param)
        if value is not None:
            items = [w for w in items if w.get(param) == value]
    return envelope.paginate(domain.public_list(items))


@bp.get("/vdr/work-orders/<wid>")
def get_work_order(wid):
    auth.require_roles(*WO_READ_ROLES)
    wo = db.get("work_orders", wid)
    if wo is None:
        errors.work_order_not_found()
    return envelope.ok(domain.public(wo))


@bp.post("/vdr/work-orders/<wid>/triage")
def triage_work_order(wid):
    body = V.get_body()
    V.check_unknown(body, {"expected_work_order_version"})
    expected = V.req_int(body, "expected_work_order_version")
    auth.require_roles("IntakeCoordinator")
    wo = db.get("work_orders", wid)
    if wo is None:
        errors.work_order_not_found()
    if expected != wo["version"]:
        errors.stale_version("expected_work_order_version does not match the work order version")
    if wo["status"] != "INTAKE":
        errors.invalid_state("only an INTAKE work order can be triaged")
    score, tier = calculations.priority_score_and_tier(wo, db.now())
    wo["status"] = "TRIAGED"
    wo["priority_score"] = score
    wo["priority_tier"] = tier
    db.touch(wo)
    return envelope.ok(domain.public(wo))


@bp.patch("/vdr/work-orders/<wid>")
def patch_work_order(wid):
    body = V.get_body()
    V.check_unknown(body, {"status", "operation_id", "blocked_reason"})
    target = V.req_enum(body, "status", WORK_ORDER_STATUSES)
    operation_id = V.opt_str(body, "operation_id", None)
    blocked_reason = V.opt_str(body, "blocked_reason", None)
    uid, role = auth.require_roles("IntakeCoordinator", "OperationsLead")
    if target not in TARGET_ROLES:
        errors.invalid_state("status %s cannot be set directly" % target)
    if role not in TARGET_ROLES[target]:
        errors.unauthorized("role %s cannot drive a work order to %s" % (role, target))
    wo = db.get("work_orders", wid)
    if wo is None:
        errors.work_order_not_found()
    cur = wo["status"]

    if (cur, target) == ("TRIAGED", "SCHEDULED"):
        if role != "IntakeCoordinator":
            errors.unauthorized("scheduling is restricted to IntakeCoordinator")
        if operation_id is None:
            errors.validation("scheduling requires operation_id")
        op = db.get("operations", operation_id)
        if op is None:
            errors.operation_not_found()
        _schedule_gates(wo, op)
        wo["operation_id"] = op["id"]
        wo["status"] = "SCHEDULED"
        db.touch(wo)
    elif (cur, target) == ("SCHEDULED", "IN_PROGRESS"):
        op = db.get("operations", wo["operation_id"])
        if op is None or op["status"] != "ACTIVE":
            errors.invalid_state("work may start only while the operation is ACTIVE")
        wo["status"] = "IN_PROGRESS"
        db.touch(wo)
    elif (cur, target) == ("IN_PROGRESS", "BLOCKED"):
        if not blocked_reason:
            errors.validation("blocking requires a non-empty blocked_reason")
        wo["status"] = "BLOCKED"
        wo["blocked_reason"] = blocked_reason
        db.touch(wo)
    elif (cur, target) == ("BLOCKED", "SCHEDULED"):
        op = db.get("operations", wo["operation_id"])
        cap = HAZARD_TO_CAPABILITY.get(wo["hazard_kind"])
        if cap is not None and op is not None and op["capability_gap"].get(cap, 0) > 0:
            errors.err("ERR_CAPABILITY_GAP", 422,
                           "capability gap for the hazard's capability blocks unblocking")
        wo["status"] = "SCHEDULED"
        wo["blocked_reason"] = None
        db.touch(wo)
    elif (cur, target) == ("IN_PROGRESS", "DONE_PENDING_VERIFICATION"):
        wo["status"] = "DONE_PENDING_VERIFICATION"
        db.touch(wo)
    elif (cur, target) == ("DONE_PENDING_VERIFICATION", "VERIFIED_DONE"):
        wo["status"] = "VERIFIED_DONE"
        db.touch(wo)
    elif target == "CANCELLED" and cur in ("INTAKE", "TRIAGED", "SCHEDULED"):
        wo["status"] = "CANCELLED"
        db.touch(wo)
    else:
        errors.invalid_state("cannot transition work order from %s to %s" % (cur, target))
    return envelope.ok(domain.public(wo))


def _schedule_gates(wo, op):
    """TRIAGED -> SCHEDULED business rules in the pinned order:
    capability coverage, hazard alignment, operation state, incident typing."""
    cap = HAZARD_TO_CAPABILITY.get(wo["hazard_kind"])
    if cap is not None and op["capability_gap"].get(cap, 0) > 0:
        errors.err("ERR_CAPABILITY_GAP", 422,
                   "capability gap for the hazard's capability blocks scheduling")
    if op["hazard_focus"] != wo["hazard_kind"]:
        errors.err("ERR_HAZARD_MISMATCH", 422,
                   "operation hazard_focus differs from the work order hazard_kind")
    if op["status"] not in ("MUSTERED", "ACTIVE"):
        errors.err("ERR_OPERATION_NOT_OPEN", 409,
                   "scheduling requires a MUSTERED or ACTIVE operation")
    inc = db.get("incidents", wo["incident_id"])
    if inc is None or inc["status"] != "TYPED":
        errors.err("ERR_INCIDENT_NOT_TYPED", 409,
                   "scheduling requires a TYPED incident")
