"""Worker, qualification-register, exam and worker-qualification routes."""

from flask import Blueprint, request

from config import WORKER_COUNTRIES
from db import db, common_fields, touch
from errors import fail
from middleware import require_owner, resolve
from response import array, success
from rounding import sort_key_created, sort_key_worker_qualification
from serializers import exam_attempt as serialize_attempt
from serializers import qualification_exam as serialize_exam
from serializers import qualification_type as serialize_qtype
from serializers import worker as serialize_worker
from serializers import worker_qualification as serialize_wqual
from services import qualification_service
from services.common import (
    body,
    coerce_int,
    get_exam,
    get_qualification_type,
    get_worker,
    optional_int,
    paginate,
    require_enum,
    require_int,
    require_str,
)

bp = Blueprint("workers", __name__, url_prefix="/mkt")

REGISTER_ANY = ["Worker", "Requester", "PlatformAdmin"]
WORKER_ROLES = ["Worker", "PlatformAdmin"]


# --- workers ---------------------------------------------------------------
def _create():
    """POST /mkt/workers - register a worker account (Anonymous)."""
    resolve(request, None, auth_exempt=True)
    payload = body(request)
    display_name = require_str(payload, "display_name")
    country = require_enum(payload, "country", WORKER_COUNTRIES)
    row = common_fields()
    row.update(
        {
            "display_name": display_name,
            "country": country,
            "approved_count": 0,
            "rejected_count": 0,
            "returned_count": 0,
            "expired_count": 0,
            "identity_verified": False,
            "status": "ACTIVE",
        }
    )
    db.workers[row["id"]] = row
    return success(serialize_worker(row)), 201


def _get(worker_id):
    """GET /mkt/workers/{worker_id}."""
    principal = resolve(request, WORKER_ROLES)
    row = get_worker(worker_id)
    require_owner(principal, row["id"])
    return success(serialize_worker(row)), 200


def _identity_verification(worker_id):
    """POST /mkt/workers/{worker_id}/identity-verifications - operator only."""
    resolve(request, ["PlatformAdmin"])
    row = get_worker(worker_id)
    payload = body(request)
    outcome = require_str(payload, "outcome").upper()
    if outcome in {"VERIFIED", "VERIFY", "SUCCESS", "PASSED"}:
        row["identity_verified"] = True
    elif outcome in {"FAILED", "FAILURE", "DENIED", "REJECTED"}:
        row["identity_verified"] = False
    else:
        fail("ERR_INVALID_REQUEST", "outcome must be VERIFIED or FAILED.")
    touch(row)
    return success(serialize_worker(row)), 200


def _suspend(worker_id):
    """POST /mkt/workers/{worker_id}/suspend."""
    resolve(request, ["PlatformAdmin"])
    row = get_worker(worker_id)
    row["status"] = "SUSPENDED"
    touch(row)
    return success(serialize_worker(row)), 200


def _reinstate(worker_id):
    """POST /mkt/workers/{worker_id}/reinstate."""
    resolve(request, ["PlatformAdmin"])
    row = get_worker(worker_id)
    row["status"] = "ACTIVE"
    touch(row)
    return success(serialize_worker(row)), 200


# --- qualification types ---------------------------------------------------
def _create_qtype():
    """POST /mkt/qualification-types - PlatformAdmin and Requester."""
    resolve(request, ["PlatformAdmin", "Requester"])
    payload = body(request)
    name = require_str(payload, "name")
    kind = require_enum(payload, "kind", {"SYSTEM", "REQUESTER"})
    threshold = require_int(payload, "auto_assign_threshold_pct")
    if threshold < 0 or threshold > 100:
        fail("ERR_INVALID_REQUEST", "auto_assign_threshold_pct must be 0..100.")
    exam_available = bool(payload.get("exam_available", False))
    default_score = optional_int(payload, "default_score", 0)
    row = common_fields()
    row.update(
        {
            "name": name,
            "kind": kind,
            "exam_available": exam_available,
            "auto_assign_threshold_pct": threshold,
            "default_score": default_score,
        }
    )
    db.qualification_types[row["id"]] = row
    return success(serialize_qtype(row)), 201


def _get_qtype(qualification_type_id):
    """GET /mkt/qualification-types/{qualification_type_id}."""
    resolve(request, REGISTER_ANY)
    row = get_qualification_type(qualification_type_id)
    return success(serialize_qtype(row)), 200


# --- exams -----------------------------------------------------------------
def _create_exam(qualification_type_id):
    """POST /mkt/qualification-types/{id}/exams - operator authoring.

    An exam may only be authored against a type whose exam_available is TRUE.
    """
    resolve(request, ["PlatformAdmin"])
    qtype = get_qualification_type(qualification_type_id)
    if not qtype.get("exam_available"):
        fail("ERR_EXAM_NOT_AVAILABLE")
    payload = body(request)
    passing_score = require_int(payload, "passing_score")
    if passing_score < 0 or passing_score > 100:
        fail("ERR_INVALID_REQUEST", "passing_score must be 0..100.")
    row = common_fields()
    row.update(
        {
            "qualification_type_id": qtype["id"],
            "passing_score": passing_score,
            "max_attempts": optional_int(payload, "max_attempts", 3),
            "retake_cooldown_days": optional_int(payload, "retake_cooldown_days", 0),
        }
    )
    db.qualification_exams[row["id"]] = row
    return success(serialize_exam(row)), 201


def _list_exams(qualification_type_id):
    """GET /mkt/qualification-types/{id}/exams."""
    resolve(request, REGISTER_ANY)
    qtype = get_qualification_type(qualification_type_id)
    rows = [
        e for e in db.qualification_exams.values() if e["qualification_type_id"] == qtype["id"]
    ]
    rows.sort(key=sort_key_created)
    return success([serialize_exam(e) for e in rows], response_type="array"), 200


def _get_exam(exam_id):
    """GET /mkt/qualification-exams/{exam_id}."""
    resolve(request, WORKER_ROLES)
    row = get_exam(exam_id)
    return success(serialize_exam(row)), 200


def _create_attempt(exam_id):
    """POST /mkt/qualification-exams/{exam_id}/attempts - a scored attempt."""
    principal = resolve(request, ["Worker"])
    exam = get_exam(exam_id)
    worker_row = db.workers.get(principal["id"])
    if worker_row is None:
        fail("ERR_UNAUTHENTICATED")
    payload = body(request)
    score = coerce_int(payload.get("score"), "score")
    if score < 0 or score > 100:
        fail("ERR_INVALID_REQUEST", "score must be 0..100.")
    row = qualification_service.submit_attempt(exam, worker_row, score)
    return success(serialize_attempt(row)), 201


def _list_attempts(exam_id):
    """GET /mkt/qualification-exams/{id}/attempts - optionally by worker."""
    resolve(request, WORKER_ROLES)
    exam = get_exam(exam_id)
    rows = [a for a in db.exam_attempts.values() if a["exam_id"] == exam["id"]]
    worker_id = request.args.get("worker_id")
    if worker_id:
        rows = [a for a in rows if a["worker_id"] == worker_id]
    rows.sort(key=lambda a: (a.get("created_at") or "", a.get("id") or ""))
    page, meta = paginate(rows, request.args)
    return array([serialize_attempt(a) for a in page], meta), 200


# --- worker qualifications -------------------------------------------------
def _list_wqual():
    """GET /mkt/worker-qualifications - optionally filtered by worker or type."""
    resolve(request, REGISTER_ANY)
    rows = list(db.worker_qualifications.values())
    worker_id = request.args.get("worker_id")
    type_id = request.args.get("qualification_type_id")
    if worker_id:
        rows = [w for w in rows if w["worker_id"] == worker_id]
    if type_id:
        rows = [w for w in rows if w["qualification_type_id"] == type_id]
    rows.sort(key=sort_key_worker_qualification)
    page, meta = paginate(rows, request.args)
    return array([serialize_wqual(w) for w in page], meta), 200


def _get_wqual(wqual_id):
    """GET /mkt/worker-qualifications/{id}."""
    resolve(request, REGISTER_ANY)
    row = db.worker_qualifications.get(wqual_id)
    if row is None:
        fail("ERR_NOT_FOUND", "Worker qualification not found.")
    return success(serialize_wqual(row)), 200


bp.add_url_rule("/workers", "create_worker", _create, methods=["POST"])
bp.add_url_rule("/workers/<worker_id>", "get_worker", _get, methods=["GET"])
bp.add_url_rule(
    "/workers/<worker_id>/identity-verifications",
    "identity_verification",
    _identity_verification,
    methods=["POST"],
)
bp.add_url_rule("/workers/<worker_id>/suspend", "suspend_worker", _suspend, methods=["POST"])
bp.add_url_rule(
    "/workers/<worker_id>/reinstate", "reinstate_worker", _reinstate, methods=["POST"]
)
bp.add_url_rule(
    "/qualification-types", "create_qtype", _create_qtype, methods=["POST"]
)
bp.add_url_rule(
    "/qualification-types/<qualification_type_id>",
    "get_qtype",
    _get_qtype,
    methods=["GET"],
)
bp.add_url_rule(
    "/qualification-types/<qualification_type_id>/exams",
    "create_exam",
    _create_exam,
    methods=["POST"],
)
bp.add_url_rule(
    "/qualification-types/<qualification_type_id>/exams",
    "list_exams",
    _list_exams,
    methods=["GET"],
)
bp.add_url_rule(
    "/qualification-exams/<exam_id>", "get_exam", _get_exam, methods=["GET"]
)
bp.add_url_rule(
    "/qualification-exams/<exam_id>/attempts",
    "create_attempt",
    _create_attempt,
    methods=["POST"],
)
bp.add_url_rule(
    "/qualification-exams/<exam_id>/attempts",
    "list_attempts",
    _list_attempts,
    methods=["GET"],
)
bp.add_url_rule(
    "/worker-qualifications", "list_wqual", _list_wqual, methods=["GET"]
)
bp.add_url_rule(
    "/worker-qualifications/<wqual_id>", "get_wqual", _get_wqual, methods=["GET"]
)