"""Deployment endpoints: call-up offer, list, get, transitions, wellness list."""
from datetime import timedelta
from flask import Blueprint
import db
import errors
import envelope
import validation as V
import auth
import domain
import cascades
import calculations
import timeutil
from constants import DEPLOYMENT_STATUSES, TRAVEL_MODES, REST_BUFFER_HOURS

bp = Blueprint("deployments", __name__)

DEP_READ_ROLES = ("SystemAdmin", "OperationsLead", "IncidentCommander",
                  "SafetyOfficer", "Volunteer")

# Which roles may drive each target status at all (endpoint-level gate).
TARGET_ROLES = {
    "ACCEPTED": ("Volunteer",),
    "DECLINED": ("Volunteer",),
    "ON_SITE": ("OperationsLead", "SafetyOfficer"),
    "DEMOBED": ("OperationsLead",),
}

VALID_TRANSITIONS = {
    ("OFFERED", "ACCEPTED"), ("OFFERED", "DECLINED"),
    ("ACCEPTED", "ON_SITE"), ("SAFETY_HOLD", "ON_SITE"),
    ("ON_SITE", "DEMOBED"), ("SAFETY_HOLD", "DEMOBED"),
}


@bp.post("/vdr/operations/<oid>/deployments")
def offer_deployment(oid):
    body = V.get_body()
    V.check_unknown(body, {"volunteer_id", "travel_mode", "planned_start",
                           "planned_end", "needs_lodging"})
    volunteer_id = V.req_str(body, "volunteer_id")
    travel_mode = V.req_enum(body, "travel_mode", TRAVEL_MODES)
    planned_start = V.req_dt(body, "planned_start")
    planned_end = V.req_dt(body, "planned_end")
    if planned_end <= planned_start:
        errors.validation("planned_end must be strictly after planned_start")
    needs_lodging = V.opt_bool(body, "needs_lodging", True)
    auth.require_roles("OperationsLead")
    op = db.get("operations", oid)
    if op is None:
        errors.operation_not_found()
    vol = db.get("volunteers", volunteer_id)
    if vol is None:
        errors.volunteer_not_found()
    if op["status"] != "OPEN":
        errors.err("ERR_OPERATION_NOT_OPEN", 409,
                   "deployment offers require an OPEN operation")
    if vol["readiness_status"] != "DEPLOYABLE":
        errors.err("ERR_VOLUNTEER_NOT_DEPLOYABLE", 409,
                   "volunteer readiness_status is not DEPLOYABLE")
    active = [d for d in domain.deployments_of_operation(oid)
              if d["status"] in ("OFFERED", "ACCEPTED", "ON_SITE", "SAFETY_HOLD")]
    if len(active) >= op["team_size_required"]:
        errors.err("ERR_TEAM_SIZE_EXCEEDED", 422,
                   "the offer would exceed the operation's team_size_required")
    dep = db.mint("deployments", {
        "operation_id": oid,
        "volunteer_id": volunteer_id,
        "status": "OFFERED",
        "duty_status": "RESTING",
        "travel_mode": travel_mode,
        "needs_lodging": needs_lodging,
        "planned_start": timeutil.fmt(planned_start),
        "planned_end": timeutil.fmt(planned_end),
        "fob_site_id": None,
        "checked_in_at": None,
        "demobed_at": None,
        "stipend_provisional_cents": None,
        "stipend_final_cents": None,
    })
    return envelope.ok(domain.public(dep), 201)


@bp.get("/vdr/deployments")
def list_deployments():
    auth.require_roles(*DEP_READ_ROLES)
    items = db.all_of("deployments")
    for param in ("volunteer_id", "operation_id", "fob_site_id", "status"):
        value = V.qparam(param)
        if value is not None:
            items = [d for d in items if d.get(param) == value]
    return envelope.paginate(domain.public_list(items))


@bp.get("/vdr/deployments/<did>")
def get_deployment(did):
    uid, role = auth.require_roles(*DEP_READ_ROLES)
    dep = db.get("deployments", did)
    if dep is None:
        errors.deployment_not_found()
    if role == "Volunteer" and dep["volunteer_id"] != uid:
        errors.unauthorized("a Volunteer may only read their own deployments")
    return envelope.ok(domain.public(dep))


@bp.patch("/vdr/deployments/<did>")
def patch_deployment(did):
    body = V.get_body()
    V.check_unknown(body, {"status"})
    target = V.req_enum(body, "status", DEPLOYMENT_STATUSES)
    uid, role = auth.require_roles("Volunteer", "OperationsLead", "SafetyOfficer")
    if target not in TARGET_ROLES:
        errors.invalid_state("status %s cannot be set directly" % target)
    if role not in TARGET_ROLES[target]:
        errors.unauthorized("role %s cannot drive a deployment to %s" % (role, target))
    dep = db.get("deployments", did)
    if dep is None:
        errors.deployment_not_found()
    cur = dep["status"]
    if (cur, target) not in VALID_TRANSITIONS:
        errors.invalid_state("cannot transition deployment from %s to %s" % (cur, target))
    if target in ("ACCEPTED", "DECLINED"):
        if uid != dep["volunteer_id"]:
            errors.unauthorized("a Volunteer may only answer their own offers")
    if target == "ON_SITE":
        if cur == "ACCEPTED" and role != "OperationsLead":
            errors.unauthorized("check-in is restricted to OperationsLead")
        if cur == "SAFETY_HOLD" and role != "SafetyOfficer":
            errors.unauthorized("clearing a safety hold is restricted to SafetyOfficer")

    if target == "ACCEPTED":
        return _accept(dep)
    if target == "DECLINED":
        dep["status"] = "DECLINED"
        db.touch(dep)
        return envelope.ok(domain.public(dep))
    if target == "ON_SITE" and cur == "ACCEPTED":
        return _check_in(dep)
    if target == "ON_SITE" and cur == "SAFETY_HOLD":
        return _clear_hold(dep)
    return _demobe(dep)


def _accept(dep):
    """OFFERED -> ACCEPTED: gates fire in the PRD's pinned order."""
    op = db.get("operations", dep["operation_id"])
    vol = db.get("volunteers", dep["volunteer_id"])
    # 1. safety-credential gate (priority 7)
    caps = op["required_capabilities"]
    if not any(domain.has_verified(vol["id"], cap) for cap in caps):
        errors.err("ERR_CERT_NOT_VERIFIED", 422,
                   "volunteer holds no VERIFIED certification of a required kind")
    # 2. readiness gate (priority 8)
    if vol["readiness_status"] != "DEPLOYABLE":
        errors.err("ERR_VOLUNTEER_NOT_DEPLOYABLE", 409,
                   "volunteer readiness_status is not DEPLOYABLE")
    # 3. availability containment (priority 11)
    ps = timeutil.parse_iso(dep["planned_start"])
    pe = timeutil.parse_iso(dep["planned_end"])
    contained = False
    for w in vol["availability_windows"]:
        ws = timeutil.parse_iso(w["start_iso8601"])
        we = timeutil.parse_iso(w["end_iso8601"])
        if ws <= ps and pe <= we:
            contained = True
            break
    if not contained:
        errors.err("ERR_AVAILABILITY_WINDOW_MISMATCH", 422,
                   "deployment window is not contained in one availability window")
    # 4. rest buffer (priority 12): gap >= 24h; exactly 24h is admissible.
    for other in db.store["deployments"].values():
        if other["id"] == dep["id"] or other["volunteer_id"] != vol["id"]:
            continue
        if other["status"] not in ("ACCEPTED", "ON_SITE", "SAFETY_HOLD", "DEMOBED"):
            continue
        end_iso = other["demobed_at"] or other["planned_end"]
        gap = ps - timeutil.parse_iso(end_iso)
        if gap < timedelta(hours=REST_BUFFER_HOURS):
            errors.err("ERR_DEPLOYMENT_WINDOW_CONFLICT", 409,
                       "another deployment ends less than 24h before planned_start")
    # 5. operation-state gate (priority 19)
    if op["status"] not in ("OPEN", "MUSTERED"):
        errors.err("ERR_OPERATION_NOT_OPEN", 409,
                   "acceptance requires an OPEN or MUSTERED operation")
    dep["status"] = "ACCEPTED"
    dep["stipend_provisional_cents"] = calculations.stipend_for_days(op["duration_days"])
    db.touch(dep)
    domain.recompute_operation(op)
    return envelope.ok(domain.public(dep))


def _check_in(dep):
    """ACCEPTED -> ON_SITE: bunk allocation from the FOB with the most free
    bunks (tie-break earliest created_at), then counter recompute."""
    op = db.get("operations", dep["operation_id"])
    if dep["needs_lodging"]:
        candidates = [f for f in db.store["fob_sites"].values()
                      if f["operation_id"] == op["id"] and f["bunks_occupied"] < f["bunks_total"]]
        if not candidates:
            errors.err("ERR_FOB_CAPACITY_EXCEEDED", 422,
                       "every FOB site of the operation is at capacity")
        candidates.sort(key=lambda f: (-(f["bunks_total"] - f["bunks_occupied"]),
                                       f["created_at"], f["_seq"]))
        fob = candidates[0]
        dep["fob_site_id"] = fob["id"]
        fob["bunks_occupied"] += 1
        db.touch(fob)
    dep["status"] = "ON_SITE"
    dep["checked_in_at"] = db.now_iso()
    db.touch(dep)
    domain.recompute_operation(op)
    return envelope.ok(domain.public(dep))


def _clear_hold(dep):
    """SAFETY_HOLD -> ON_SITE: volunteer must again cover every required capability."""
    op = db.get("operations", dep["operation_id"])
    vol = db.get("volunteers", dep["volunteer_id"])
    for cap in op["required_capabilities"]:
        if not domain.has_verified(vol["id"], cap):
            errors.err("ERR_CERT_NOT_VERIFIED", 422,
                       "volunteer does not hold VERIFIED certs for all required capabilities")
    dep["status"] = "ON_SITE"
    db.touch(dep)
    domain.recompute_operation(op)
    return envelope.ok(domain.public(dep))


def _demobe(dep):
    """ON_SITE/SAFETY_HOLD -> DEMOBED (OperationsLead). Blocked while a
    SCHEDULED shift ends in the future; the full bundle runs on success."""
    now = db.now()
    for shift in domain.shifts_of_deployment(dep["id"]):
        if shift["status"] == "SCHEDULED" and timeutil.parse_iso(shift["ends_at"]) > now:
            errors.invalid_state("a scheduled shift still ends in the future")
    cascades.demobe_deployment(dep)
    return envelope.ok(domain.public(dep))


@bp.get("/vdr/deployments/<did>/wellness-checks")
def list_wellness_checks(did):
    auth.require_roles("SystemAdmin", "SafetyOfficer", "OperationsLead", "IncidentCommander")
    dep = db.get("deployments", did)
    if dep is None:
        errors.deployment_not_found()
    items = [w for w in db.all_of("wellness_checks") if w["deployment_id"] == did]
    return envelope.paginate(domain.public_list(items))
