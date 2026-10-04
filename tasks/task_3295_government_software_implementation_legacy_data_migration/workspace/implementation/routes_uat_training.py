"""Routes: UAT cycles, sessions, training sessions, enrollments."""
import math

from flask import Blueprint, request

import db
from errors import (
    raise_error, ERR_NOT_FOUND, ERR_REFERENCE_NOT_FOUND, ERR_INVALID_REQUEST,
    ERR_INVALID_STATE, ERR_TESTER_UNAVAILABLE, ERR_SESSION_FULL, ERR_DUPLICATE_KEY,
)
from middleware import require_roles
from response import success_object, success_list, parse_pagination, paginate
from routes_contracts import get_contract_or_404
from services_common import strip_internal, append_audit, recompute_readiness
from util import new_id, now_ts, touch, require_fields, require_int, parse_date

bp = Blueprint("uat_training", __name__)

LONG_TENURE_YEARS = 10


def get_cycle_or_404(cid):
    c = db.get("uat_cycles", cid)
    if c is None:
        raise_error(ERR_NOT_FOUND, "uat cycle not found")
    return c


def get_session_or_404(sid):
    s = db.get("uat_sessions", sid)
    if s is None:
        raise_error(ERR_NOT_FOUND, "uat session not found")
    return s


def get_training_or_404(tid):
    t = db.get("training_sessions", tid)
    if t is None:
        raise_error(ERR_NOT_FOUND, "training session not found")
    return t


def get_enrollment_or_404(eid):
    e = db.get("training_enrollments", eid)
    if e is None:
        raise_error(ERR_NOT_FOUND, "enrollment not found")
    return e


@bp.route("/programs/contracts/<contract_id>/uat-cycles", methods=["POST"])
def create_cycle(contract_id):
    require_roles("AgencyProjectManager")
    c = get_contract_or_404(contract_id)
    payload = request.get_json(silent=True) or {}
    require_fields(payload, ["label"])
    parallel = payload.get("parallel_operations", False)
    if not isinstance(parallel, bool):
        raise_error(ERR_INVALID_REQUEST, "parallel_operations must be boolean")
    now = now_ts()
    cycle = {
        "id": new_id(),
        "contract_id": c["id"],
        "label": payload["label"],
        "parallel_operations": parallel,
        "status": "PLANNED",
        "created_at": now,
        "updated_at": now,
        "version": 1,
    }
    db.put("uat_cycles", cycle)
    return success_object(strip_internal(cycle), 201)


@bp.route("/programs/contracts/<contract_id>/uat-cycles", methods=["GET"])
def list_cycles(contract_id):
    require_roles("AgencyProjectManager", "ImplementationManager", "VendorProjectManager", "PlatformAdmin")
    c = get_contract_or_404(contract_id)
    limit, offset = parse_pagination(request.args)
    items = db.filter_items("uat_cycles", contract_id=c["id"])
    status = request.args.get("status")
    if status is not None:
        items = [x for x in items if x["status"] == status]
    page, total = paginate(items, limit, offset)
    return success_list([strip_internal(x) for x in page], limit, offset, total)


@bp.route("/programs/uat-cycles/<cid>", methods=["GET"])
def get_cycle(cid):
    require_roles("AgencyProjectManager", "ImplementationManager", "PlatformAdmin")
    return success_object(strip_internal(get_cycle_or_404(cid)), 200)


@bp.route("/programs/uat-cycles/<cid>/sessions", methods=["POST"])
def create_session(cid):
    require_roles("AgencyProjectManager")
    cycle = get_cycle_or_404(cid)
    payload = request.get_json(silent=True) or {}
    require_fields(payload, ["scenario_code", "assigned_tester_id", "scheduled_on"])
    tester = db.get("staff", payload["assigned_tester_id"])
    if tester is None:
        raise_error(ERR_REFERENCE_NOT_FOUND, "assigned_tester_id does not exist")
    if tester["staff_function"] != "UAT_TESTER":
        raise_error(ERR_INVALID_REQUEST, "assigned tester must hold UAT_TESTER function")
    sched = parse_date(payload["scheduled_on"], "scheduled_on")
    # unavailability windows: closed interval
    for w in db.filter_items("unavailability_windows", staff_member_id=tester["id"]):
        if parse_date(w["starts_on"]) <= sched <= parse_date(w["ends_on"]):
            raise_error(ERR_TESTER_UNAVAILABLE, "tester unavailable on scheduled date")
    # per-day cap: 1 under parallel_operations else 2; count non-terminal sessions
    same_day = [s for s in db.filter_items("uat_sessions", assigned_tester_id=tester["id"])
                if s["scheduled_on"] == payload["scheduled_on"]
                and s["result"] == "SCHEDULED"]
    cap = 1 if cycle["parallel_operations"] else 2
    if len(same_day) >= cap:
        raise_error(ERR_TESTER_UNAVAILABLE, "tester per-day session cap exceeded")
    now = now_ts()
    session = {
        "id": new_id(),
        "uat_cycle_id": cycle["id"],
        "scenario_code": payload["scenario_code"],
        "assigned_tester_id": tester["id"],
        "scheduled_on": payload["scheduled_on"],
        "result": "SCHEDULED",
        "created_at": now,
        "updated_at": now,
        "version": 1,
    }
    db.put("uat_sessions", session)
    return success_object(strip_internal(session), 201)


@bp.route("/programs/uat-cycles/<cid>/sessions", methods=["GET"])
def list_sessions(cid):
    require_roles("AgencyProjectManager", "ImplementationManager", "PlatformAdmin")
    cycle = get_cycle_or_404(cid)
    limit, offset = parse_pagination(request.args)
    items = db.filter_items("uat_sessions", uat_cycle_id=cycle["id"])
    tester = request.args.get("assigned_tester_id")
    if tester is not None:
        items = [s for s in items if s["assigned_tester_id"] == tester]
    result = request.args.get("result")
    if result is not None:
        items = [s for s in items if s["result"] == result]
    page, total = paginate(items, limit, offset)
    return success_list([strip_internal(s) for s in page], limit, offset, total)


@bp.route("/programs/uat-sessions/<sid>/record-result", methods=["POST"])
def record_session_result(sid):
    require_roles("AgencyProjectManager")
    session = get_session_or_404(sid)
    payload = request.get_json(silent=True) or {}
    require_fields(payload, ["result"])
    result = payload["result"]
    if result not in ("PASSED", "FAILED", "BLOCKED", "SKIPPED"):
        raise_error(ERR_INVALID_REQUEST, "invalid result")
    session["result"] = result
    touch(session)
    return success_object(strip_internal(session), 200)


@bp.route("/programs/uat-cycles/<cid>/start", methods=["POST"])
def start_cycle(cid):
    require_roles("AgencyProjectManager")
    cycle = get_cycle_or_404(cid)
    if cycle["status"] != "PLANNED":
        raise_error(ERR_INVALID_STATE, "cycle not PLANNED")
    if not any(s["result"] == "SCHEDULED"
               for s in db.filter_items("uat_sessions", uat_cycle_id=cycle["id"])):
        raise_error(ERR_INVALID_STATE, "no SCHEDULED sessions")
    cycle["status"] = "IN_PROGRESS"
    touch(cycle)
    return success_object(strip_internal(cycle), 200)


@bp.route("/programs/uat-cycles/<cid>/block", methods=["POST"])
def block_cycle(cid):
    require_roles("AgencyProjectManager")
    cycle = get_cycle_or_404(cid)
    payload = request.get_json(silent=True) or {}
    if cycle["status"] == "IN_PROGRESS":
        reason = payload.get("block_reason")
        if not isinstance(reason, str) or not reason.strip():
            raise_error(ERR_INVALID_REQUEST, "block_reason required when entering BLOCKED")
        cycle["status"] = "BLOCKED"
    elif cycle["status"] == "BLOCKED":
        cycle["status"] = "IN_PROGRESS"
    else:
        raise_error(ERR_INVALID_STATE, "cycle not IN_PROGRESS or BLOCKED")
    touch(cycle)
    return success_object(strip_internal(cycle), 200)


@bp.route("/programs/uat-cycles/<cid>/complete", methods=["POST"])
def complete_cycle(cid):
    user_id, role = require_roles("AgencyProjectManager")
    cycle = get_cycle_or_404(cid)
    if cycle["status"] != "IN_PROGRESS":
        raise_error(ERR_INVALID_STATE, "cycle not IN_PROGRESS")
    sessions = db.filter_items("uat_sessions", uat_cycle_id=cycle["id"])
    all_ok = all(s["result"] in ("PASSED", "SKIPPED") for s in sessions)
    passed = sum(1 for s in sessions if s["result"] == "PASSED")
    threshold = math.ceil(0.8 * len(sessions)) if sessions else 0
    if sessions and all_ok and passed >= threshold:
        cycle["status"] = "PASSED"
    else:
        cycle["status"] = "FAILED"
    touch(cycle)
    recompute_readiness(cycle["contract_id"])
    append_audit(cycle["contract_id"], role, user_id, "POST /programs/uat-cycles/{id}/complete",
                 "UatCycle", cycle["id"], f"IN_PROGRESS -> {cycle['status']}")
    return success_object(strip_internal(cycle), 200)


# ---------------- training ----------------

@bp.route("/programs/contracts/<contract_id>/training-sessions", methods=["POST"])
def create_training(contract_id):
    require_roles("ImplementationManager")
    c = get_contract_or_404(contract_id)
    payload = request.get_json(silent=True) or {}
    require_fields(payload, ["title", "delivery_mode", "scheduled_on", "capacity"])
    if payload["delivery_mode"] not in ("INSTRUCTOR_LED", "SELF_PACED", "TRAIN_THE_TRAINER"):
        raise_error(ERR_INVALID_REQUEST, "invalid delivery_mode")
    parse_date(payload["scheduled_on"], "scheduled_on")
    capacity = require_int(payload, "capacity")
    now = now_ts()
    session = {
        "id": new_id(),
        "contract_id": c["id"],
        "title": payload["title"],
        "delivery_mode": payload["delivery_mode"],
        "scheduled_on": payload["scheduled_on"],
        "capacity": capacity,
        "status": "SCHEDULED",
        "created_at": now,
        "updated_at": now,
        "version": 1,
    }
    db.put("training_sessions", session)
    return success_object(strip_internal(session), 201)


@bp.route("/programs/contracts/<contract_id>/training-sessions", methods=["GET"])
def list_training(contract_id):
    require_roles("ImplementationManager", "AgencyProjectManager", "PlatformAdmin")
    c = get_contract_or_404(contract_id)
    limit, offset = parse_pagination(request.args)
    items = db.filter_items("training_sessions", contract_id=c["id"])
    status = request.args.get("status")
    if status is not None:
        items = [t for t in items if t["status"] == status]
    page, total = paginate(items, limit, offset)
    return success_list([strip_internal(t) for t in page], limit, offset, total)


@bp.route("/programs/training-sessions/<tid>", methods=["GET"])
def get_training(tid):
    require_roles("ImplementationManager", "AgencyProjectManager", "PlatformAdmin")
    return success_object(strip_internal(get_training_or_404(tid)), 200)


@bp.route("/programs/training-sessions/<tid>/enrollments", methods=["POST"])
def enroll(tid):
    require_roles("ImplementationManager", "AgencyProjectManager")
    session = get_training_or_404(tid)
    payload = request.get_json(silent=True) or {}
    require_fields(payload, ["staff_member_id"])
    staff = db.get("staff", payload["staff_member_id"])
    if staff is None:
        raise_error(ERR_REFERENCE_NOT_FOUND, "staff_member_id does not exist")
    for e in db.filter_items("training_enrollments", training_session_id=session["id"]):
        if e["staff_member_id"] == staff["id"]:
            raise_error(ERR_DUPLICATE_KEY, "staff already enrolled in session")
    seat_weight = 2 if staff["tenure_years"] >= LONG_TENURE_YEARS else 1
    consumed = sum(e["seat_weight"]
                   for e in db.filter_items("training_enrollments",
                                            training_session_id=session["id"])
                   if e["outcome"] in ("ENROLLED", "COMPLETED"))
    if consumed + seat_weight > session["capacity"]:
        raise_error(ERR_SESSION_FULL, "session capacity exceeded")
    enrollment = {
        "id": new_id(),
        "training_session_id": session["id"],
        "staff_member_id": staff["id"],
        "outcome": "ENROLLED",
        "seat_weight": seat_weight,
        "created_at": now_ts(),
    }
    db.put("training_enrollments", enrollment)
    return success_object(strip_internal(enrollment), 201)


@bp.route("/programs/training-sessions/<tid>/enrollments", methods=["GET"])
def list_enrollments(tid):
    require_roles("ImplementationManager", "AgencyProjectManager", "PlatformAdmin")
    session = get_training_or_404(tid)
    limit, offset = parse_pagination(request.args)
    items = db.filter_items("training_enrollments", training_session_id=session["id"])
    staff_id = request.args.get("staff_member_id")
    if staff_id is not None:
        items = [e for e in items if e["staff_member_id"] == staff_id]
    outcome = request.args.get("outcome")
    if outcome is not None:
        items = [e for e in items if e["outcome"] == outcome]
    page, total = paginate(items, limit, offset)
    return success_list([strip_internal(e) for e in page], limit, offset, total)


@bp.route("/programs/training-enrollments/<eid>/record-outcome", methods=["POST"])
def record_outcome(eid):
    require_roles("ImplementationManager")
    e = get_enrollment_or_404(eid)
    payload = request.get_json(silent=True) or {}
    require_fields(payload, ["outcome"])
    outcome = payload["outcome"]
    if outcome not in ("COMPLETED", "NO_SHOW", "WITHDRAWN"):
        raise_error(ERR_INVALID_REQUEST, "invalid outcome")
    if e["outcome"] != "ENROLLED":
        raise_error(ERR_INVALID_STATE, "enrollment not ENROLLED")
    e["outcome"] = outcome
    session = get_training_or_404(e["training_session_id"])
    if outcome == "COMPLETED":
        recompute_readiness(session["contract_id"])
    return success_object(strip_internal(e), 200)


@bp.route("/programs/training-sessions/<tid>/mark-delivered", methods=["POST"])
def mark_delivered(tid):
    require_roles("ImplementationManager")
    session = get_training_or_404(tid)
    if session["status"] != "SCHEDULED":
        raise_error(ERR_INVALID_STATE, "session not SCHEDULED")
    session["status"] = "DELIVERED"
    touch(session)
    return success_object(strip_internal(session), 200)


@bp.route("/programs/training-sessions/<tid>/cancel", methods=["POST"])
def cancel_training(tid):
    require_roles("ImplementationManager")
    session = get_training_or_404(tid)
    if session["status"] != "SCHEDULED":
        raise_error(ERR_INVALID_STATE, "session not SCHEDULED")
    session["status"] = "CANCELLED"
    touch(session)
    for e in db.filter_items("training_enrollments", training_session_id=session["id"]):
        if e["outcome"] in ("ENROLLED", "COMPLETED"):
            e["outcome"] = "WITHDRAWN"
    return success_object(strip_internal(session), 200)
