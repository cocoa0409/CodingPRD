"""Operation endpoints: list, get, status ladder + AAR dimension (PATCH),
and the OCC-guarded retype write.
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
    OPERATION_STATUSES, AAR_STATUSES, CERT_KINDS,
    MAX_TEAM_SIZE, MAX_OPERATION_DURATION_DAYS,
)

bp = Blueprint("operations", __name__)

OP_READ_ROLES = ("SystemAdmin", "IncidentCommander", "OperationsLead",
                 "IntakeCoordinator", "SafetyOfficer", "Volunteer")


@bp.get("/vdr/operations")
def list_operations():
    auth.require_roles(*OP_READ_ROLES)
    items = db.all_of("operations")
    incident_id = V.qparam("incident_id")
    status = V.qparam("status")
    if incident_id is not None:
        items = [o for o in items if o["incident_id"] == incident_id]
    if status is not None:
        items = [o for o in items if o["status"] == status]
    return envelope.paginate(domain.public_list(items))


@bp.get("/vdr/operations/<oid>")
def get_operation(oid):
    auth.require_roles(*OP_READ_ROLES)
    op = db.get("operations", oid)
    if op is None:
        errors.operation_not_found()
    return envelope.ok(domain.public(op))


@bp.patch("/vdr/operations/<oid>")
def patch_operation(oid):
    body = V.get_body()
    V.check_unknown(body, {"status", "aar_status", "aar_notes"})
    status = V.opt_enum(body, "status", OPERATION_STATUSES)
    aar_status = V.opt_enum(body, "aar_status", AAR_STATUSES)
    aar_notes = V.opt_str(body, "aar_notes", None)
    if status is not None and aar_status is not None:
        errors.validation("status and aar_status cannot be patched together")
    if status is None and aar_status is None:
        errors.validation("status or aar_status is required")
    if aar_notes is not None and aar_status != "SUBMITTED":
        errors.validation("aar_notes is only accepted with aar_status=SUBMITTED")
    if aar_status == "SUBMITTED" and (aar_notes is None or aar_notes == ""):
        errors.validation("aar_status=SUBMITTED requires non-empty aar_notes")
    uid, role = auth.require_roles("OperationsLead", "IncidentCommander")
    if status is not None and role != "OperationsLead":
        errors.unauthorized("operation status transitions are restricted to OperationsLead")
    if aar_status == "SUBMITTED" and role != "OperationsLead":
        errors.unauthorized("after-action reviews are submitted by OperationsLead")
    if aar_status == "ADOPTED" and role != "IncidentCommander":
        errors.unauthorized("after-action reviews are adopted by IncidentCommander")
    op = db.get("operations", oid)
    if op is None:
        errors.operation_not_found()
    if status is not None:
        return _status_transition(op, status)
    return _aar_transition(op, aar_status, aar_notes, role)


def _status_transition(op, target):
    cur = op["status"]
    if (cur, target) == ("DRAFT", "OPEN"):
        inc = db.get("incidents", op["incident_id"])
        if inc is None or inc["status"] != "TYPED":
            errors.err("ERR_INCIDENT_NOT_TYPED", 409,
                       "operation may open only while its incident is TYPED")
        op["status"] = "OPEN"
        db.touch(op)
    elif (cur, target) == ("OPEN", "MUSTERED"):
        if op["rostered_count"] != op["team_size_required"]:
            errors.invalid_state(
                "rostered_count must equal team_size_required exactly to muster")
        if op["capability_gap"]:
            errors.err("ERR_CAPABILITY_GAP", 422,
                       "capability_gap must be empty to muster")
        op["status"] = "MUSTERED"
        db.touch(op)
    elif (cur, target) == ("MUSTERED", "ACTIVE"):
        on_site = [d for d in domain.deployments_of_operation(op["id"])
                   if d["status"] == "ON_SITE"]
        if not on_site:
            errors.invalid_state("at least one deployment must be ON_SITE to activate")
        op["status"] = "ACTIVE"
        db.touch(op)
    elif (cur, target) == ("ACTIVE", "DEMOBILIZING"):
        blocking = [w for w in db.store["work_orders"].values()
                    if w["operation_id"] == op["id"] and w["status"] == "IN_PROGRESS"]
        if blocking:
            errors.err("ERR_WORK_ORDER_BLOCKING", 409,
                       "work orders still IN_PROGRESS block demobilization")
        op["status"] = "DEMOBILIZING"
        db.touch(op)
    elif (cur, target) == ("DEMOBILIZING", "COMPLETE"):
        if op["aar_status"] != "ADOPTED":
            errors.err("ERR_AAR_NOT_ADOPTED", 409,
                       "completion requires an ADOPTED after-action review")
        remaining = [d for d in domain.deployments_of_operation(op["id"])
                     if d["status"] in ("ON_SITE", "SAFETY_HOLD")]
        if remaining:
            errors.invalid_state("deployments remain on site or on safety hold")
        op["status"] = "COMPLETE"
        db.touch(op)
    elif target == "CANCELLED" and cur in ("DRAFT", "OPEN"):
        cascades.cancel_operation(op)
    else:
        errors.invalid_state("cannot transition operation from %s to %s" % (cur, target))
    return envelope.ok(domain.public(op))


def _aar_transition(op, target, aar_notes, role):
    cur = op["aar_status"]
    if (cur, target) == ("NONE", "SUBMITTED"):
        if op["status"] not in ("ACTIVE", "DEMOBILIZING"):
            errors.invalid_state("an after-action review requires an ACTIVE or DEMOBILIZING operation")
        op["aar_status"] = "SUBMITTED"
        op["aar_notes"] = aar_notes
        op["aar_submitted_by_role"] = role
        db.touch(op)
    elif (cur, target) == ("SUBMITTED", "ADOPTED"):
        if op["aar_submitted_by_role"] == role:
            errors.unauthorized("segregation of duties: the submitter cannot adopt the review")
        op["aar_status"] = "ADOPTED"
        db.touch(op)
    else:
        errors.invalid_state("cannot transition aar_status from %s to %s" % (cur, target))
    return envelope.ok(domain.public(op))


@bp.post("/vdr/operations/<oid>/retype")
def retype_operation(oid):
    body = V.get_body()
    V.check_unknown(body, {"expected_operation_version", "team_size_required",
                           "duration_days", "required_capabilities"})
    expected = V.req_int(body, "expected_operation_version")
    team_size = V.req_int(body, "team_size_required", lo=2, hi=MAX_TEAM_SIZE)
    duration = V.req_int(body, "duration_days", lo=1, hi=MAX_OPERATION_DURATION_DAYS)
    caps = V.req_list_enum(body, "required_capabilities", CERT_KINDS, allow_empty=False)
    auth.require_roles("OperationsLead")
    op = db.get("operations", oid)
    if op is None:
        errors.operation_not_found()
    if expected != op["version"]:
        errors.stale_version("expected_operation_version does not match the operation version")
    if op["status"] not in ("DRAFT", "OPEN"):
        errors.invalid_state("only a DRAFT or OPEN operation can be retyped")
    op["team_size_required"] = team_size
    op["duration_days"] = duration
    op["required_capabilities"] = list(dict.fromkeys(caps))
    # Retype + capability-gap recompute is one logical write: version +1 total.
    rostered = [d for d in domain.deployments_of_operation(op["id"])
                if d["status"] in ("ACCEPTED", "ON_SITE")]
    op["rostered_count"] = len(rostered)
    gap = {}
    for cap in op["required_capabilities"]:
        covered = sum(1 for d in rostered if domain.has_verified(d["volunteer_id"], cap))
        shortfall = max(0, 1 - covered)
        if shortfall > 0:
            gap[cap] = shortfall
    op["capability_gap"] = gap
    db.touch(op)
    return envelope.ok(domain.public(op))
