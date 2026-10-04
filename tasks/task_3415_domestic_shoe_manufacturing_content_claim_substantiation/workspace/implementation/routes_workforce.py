"""Workforce endpoints (PRD 3.2): workers, certification suspend/reinstate,
training enrollments, record-assessment."""
from flask import Blueprint, request

import cascade
import constants
import serializers
from errors import ApiError
from middleware import require_roles
from response import ok_obj, list_response
from state import DB, base_fields, touch, sorted_items
from validation import body, req_str, req_enum, req_int

bp = Blueprint("workforce", __name__)


def get_worker(wid):
    w = DB["workers"].get(wid)
    if w is None:
        raise ApiError("ERR_WORKER_NOT_FOUND", "worker id does not resolve")
    return w


def get_enrollment(eid):
    e = DB["enrollments"].get(eid)
    if e is None:
        raise ApiError("ERR_ENROLLMENT_NOT_FOUND", "training enrollment id does not resolve")
    return e


@bp.post("/footwear/workers")
@require_roles("TrainingCoordinator")
def create_worker(_uid, _role):
    b = body()
    # Family 4 (existence) precedes family 5 (schema).
    fid = b.get("factory_id")
    if fid is not None and fid not in DB["factories"]:
        raise ApiError("ERR_FACTORY_NOT_FOUND", "factory id does not resolve")
    fid = req_str(b, "factory_id")
    name = req_str(b, "full_name")
    w = base_fields()
    w.update({
        "factory_id": fid,
        "full_name": name,
        "status": "ACTIVE",
        "certifications": [],
    })
    DB["workers"][w["id"]] = w
    return ok_obj(serializers.pub(w), 201)


@bp.get("/footwear/workers")
@require_roles(*constants.ALL_ROLES)
def list_workers(_uid, _role):
    items = sorted_items(DB["workers"])
    fid = request.args.get("factory_id")
    status = request.args.get("status")
    if fid is not None:
        items = [w for w in items if w["factory_id"] == fid]
    if status is not None:
        items = [w for w in items if w["status"] == status]
    return list_response([serializers.pub(w) for w in items])


@bp.get("/footwear/workers/<wid>")
@require_roles(*constants.ALL_ROLES)
def get_one_worker(wid, _uid, _role):
    return ok_obj(serializers.pub(get_worker(wid)))


@bp.post("/footwear/workers/<wid>/suspend")
@require_roles("TrainingCoordinator")
def suspend_worker(wid, _uid, _role):
    w = get_worker(wid)
    if w["status"] != "ACTIVE":
        raise ApiError("ERR_INVALID_STATE", "only an ACTIVE worker can be suspended")
    w["status"] = "SUSPENDED"
    touch(w)
    # Cascade: in-production runs at the factory that lose required coverage
    # are forced to QUALITY_HOLD.
    cascade.reevaluate_runs_at_factory(w["factory_id"])
    return ok_obj(serializers.pub(w))


@bp.post("/footwear/workers/<wid>/reinstate")
@require_roles("TrainingCoordinator")
def reinstate_worker(wid, _uid, _role):
    w = get_worker(wid)
    if w["status"] != "SUSPENDED":
        raise ApiError("ERR_INVALID_STATE", "only a SUSPENDED worker can be reinstated")
    w["status"] = "ACTIVE"
    touch(w)
    return ok_obj(serializers.pub(w))


def _find_cert(worker, operation):
    if operation not in constants.OPERATIONS:
        raise ApiError(
            "ERR_INVALID_REQUEST",
            "operation must be one of STITCHING, LASTING, ASSEMBLY",
        )
    for c in worker["certifications"]:
        if c["operation"] == operation:
            return c
    raise ApiError(
        "ERR_CERTIFICATION_NOT_FOUND",
        "the worker holds no certification entry for the operation in the path",
    )


@bp.post("/footwear/workers/<wid>/certifications/<operation>/suspend")
@require_roles("TrainingCoordinator")
def suspend_certification(wid, operation, _uid, _role):
    w = get_worker(wid)
    entry = _find_cert(w, operation)
    if entry["cert_status"] != "CERTIFIED":
        raise ApiError("ERR_INVALID_STATE", "only a CERTIFIED certification can be suspended")
    entry["cert_status"] = "SUSPENDED"
    touch(w)
    # Same in-production workforce re-check cascade as a worker suspension.
    cascade.reevaluate_runs_at_factory(w["factory_id"])
    return ok_obj(serializers.pub(w))


@bp.post("/footwear/workers/<wid>/certifications/<operation>/reinstate")
@require_roles("TrainingCoordinator")
def reinstate_certification(wid, operation, _uid, _role):
    w = get_worker(wid)
    entry = _find_cert(w, operation)
    if entry["cert_status"] != "SUSPENDED":
        raise ApiError("ERR_INVALID_STATE", "only a SUSPENDED certification can be reinstated")
    entry["cert_status"] = "CERTIFIED"
    touch(w)
    return ok_obj(serializers.pub(w))


@bp.post("/footwear/training-enrollments")
@require_roles("TrainingCoordinator")
def create_enrollment(_uid, _role):
    b = body()
    # Family 4 (existence) precedes family 5 (schema).
    wid = b.get("worker_id")
    if wid is not None and wid not in DB["workers"]:
        raise ApiError("ERR_WORKER_NOT_FOUND", "worker id does not resolve")
    wid = req_str(b, "worker_id")
    op = req_enum(b, "operation", constants.OPERATIONS)
    level = req_int(b, "target_level", min_v=1, max_v=3)
    worker = DB["workers"][wid]
    # Family 6 (state).
    if worker["status"] != "ACTIVE":
        raise ApiError("ERR_WORKER_NOT_ACTIVE", "cannot enroll a SUSPENDED worker")
    # Family 9 (structural): at most one open enrollment per worker+operation.
    if any(e["worker_id"] == wid and e["operation"] == op
           and e["status"] in ("ENROLLED", "REMEDIATION")
           for e in DB["enrollments"].values()):
        raise ApiError(
            "ERR_ENROLLMENT_ALREADY_OPEN",
            "an ENROLLED or REMEDIATION enrollment already exists for this (worker, operation)",
        )
    e = base_fields()
    e.update({
        "worker_id": wid,
        "operation": op,
        "target_level": level,
        "attempt_count": 0,
        "last_score": None,
        "status": "ENROLLED",
    })
    DB["enrollments"][e["id"]] = e
    return ok_obj(serializers.pub(e), 201)


@bp.get("/footwear/workers/<wid>/training-enrollments")
@require_roles(*constants.ALL_ROLES)
def list_worker_enrollments(wid, _uid, _role):
    worker = get_worker(wid)
    items = [e for e in sorted_items(DB["enrollments"]) if e["worker_id"] == worker["id"]]
    status = request.args.get("status")
    if status is not None:
        items = [e for e in items if e["status"] == status]
    return list_response([serializers.pub(e) for e in items])


@bp.post("/footwear/training-enrollments/<eid>/record-assessment")
@require_roles("TrainingCoordinator")
def record_assessment(eid, _uid, _role):
    e = get_enrollment(eid)
    # Family 5 (schema) precedes family 6 (state).
    b = body()
    score = req_int(b, "score", min_v=0, max_v=100)
    if e["status"] not in ("ENROLLED", "REMEDIATION"):
        raise ApiError(
            "ERR_INVALID_STATE",
            "only an ENROLLED or REMEDIATION enrollment can be assessed",
        )
    e["attempt_count"] += 1
    e["last_score"] = score
    if score >= constants.TRAINING_PASS_SCORE:
        e["status"] = "CERTIFIED"
        # Upsert the worker's certification entry for the trained operation.
        worker = DB["workers"][e["worker_id"]]
        entry = None
        for c in worker["certifications"]:
            if c["operation"] == e["operation"]:
                entry = c
                break
        if entry is None:
            worker["certifications"].append({
                "operation": e["operation"],
                "level": e["target_level"],
                "cert_status": "CERTIFIED",
            })
        else:
            entry["level"] = e["target_level"]
            entry["cert_status"] = "CERTIFIED"
        touch(worker)
    else:
        e["status"] = "REMEDIATION" if e["status"] == "ENROLLED" else "FAILED"
    touch(e)
    return ok_obj(serializers.pub(e))
