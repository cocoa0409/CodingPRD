"""Assignment routes: listing, the concurrency check, and every transition."""

from flask import Blueprint, request

from db import db
from errors import fail
from middleware import require_owner, resolve
from response import array, success
from rounding import sort_key_created, sort_key_review_created
from serializers import assignment as serialize_assignment
from serializers import review as serialize_review
from services import assignment_service
from services.common import (
    body,
    get_assignment,
    get_hit,
    optional_int,
    optional_str,
    paginate,
    require_int,
    require_str,
)

bp = Blueprint("assignments", __name__, url_prefix="/mkt")

READERS = ["Requester", "Worker", "PlatformAdmin"]


def _owning_requester(assignment):
    """Resolve the requester who owns the HIT behind an assignment."""
    hit_row = db.hits.get(assignment["hit_id"])
    if hit_row is None:
        fail("ERR_NOT_FOUND", "HIT not found.")
    return db.requesters.get(hit_row["requester_id"]), hit_row


def _list():
    """GET /mkt/assignments - filters hit_id, worker_id and status."""
    resolve(request, READERS)
    rows = list(db.assignments.values())
    hit_id = request.args.get("hit_id")
    worker_id = request.args.get("worker_id")
    status = request.args.get("status")
    if hit_id:
        rows = [a for a in rows if a["hit_id"] == hit_id]
    if worker_id:
        rows = [a for a in rows if a["worker_id"] == worker_id]
    if status:
        rows = [a for a in rows if a["status"] == status]
    rows.sort(key=sort_key_created)
    page, meta = paginate(rows, request.args)
    return array([serialize_assignment(a) for a in page], meta), 200


def _get(assignment_id):
    """GET /mkt/assignments/{assignment_id}."""
    resolve(request, READERS)
    row = get_assignment(assignment_id)
    return success(serialize_assignment(row)), 200


def _concurrency_check(worker_id):
    """POST /mkt/workers/{worker_id}/assignments/concurrency-check."""
    principal = resolve(request, ["Worker", "PlatformAdmin"])
    worker_row = db.workers.get(worker_id)
    if worker_row is None:
        fail("ERR_NOT_FOUND", "Worker not found.")
    if principal["role"] == "Worker":
        require_owner(principal, worker_row["id"])
    payload = body(request)
    hit_row = get_hit(require_str(payload, "hit_id"))
    row = assignment_service.concurrency_check(hit_row, worker_row)
    return success(serialize_assignment(row)), 200


def _submit(assignment_id):
    """POST /mkt/assignments/{assignment_id}/submit."""
    principal = resolve(request, ["Worker"])
    row = get_assignment(assignment_id)
    require_owner(principal, row["worker_id"])
    worker_row = db.workers[row["worker_id"]]
    expected = optional_int(body(request), "expected_assignment_version")
    assignment_service.submit(row, worker_row, expected)
    return success(serialize_assignment(row)), 200


def _return(assignment_id):
    """POST /mkt/assignments/{assignment_id}/return."""
    principal = resolve(request, ["Worker"])
    row = get_assignment(assignment_id)
    require_owner(principal, row["worker_id"])
    worker_row = db.workers[row["worker_id"]]
    assignment_service.return_assignment(row, worker_row)
    return success(serialize_assignment(row)), 200


def _approve(assignment_id):
    """POST /mkt/assignments/{assignment_id}/approve."""
    principal = resolve(request, ["Requester"])
    row = get_assignment(assignment_id)
    requester_row, _hit = _owning_requester(row)
    if requester_row is None:
        fail("ERR_NOT_FOUND", "Requester not found.")
    require_owner(principal, requester_row["id"])
    assignment_service.approve(row, requester_row, principal["id"])
    return success(serialize_assignment(row)), 200


def _reject(assignment_id):
    """POST /mkt/assignments/{assignment_id}/reject."""
    principal = resolve(request, ["Requester"])
    row = get_assignment(assignment_id)
    requester_row, _hit = _owning_requester(row)
    if requester_row is None:
        fail("ERR_NOT_FOUND", "Requester not found.")
    require_owner(principal, requester_row["id"])
    payload = body(request)
    assignment_service.reject(row, requester_row, principal["id"], payload.get("reason"))
    return success(serialize_assignment(row)), 200


def _bonus(assignment_id):
    """POST /mkt/assignments/{assignment_id}/bonus."""
    principal = resolve(request, ["Requester"])
    row = get_assignment(assignment_id)
    requester_row, _hit = _owning_requester(row)
    if requester_row is None:
        fail("ERR_NOT_FOUND", "Requester not found.")
    require_owner(principal, requester_row["id"])
    payload = body(request)
    amount = require_int(payload, "bonus_cents")
    if amount <= 0:
        fail("ERR_INVALID_REQUEST", "bonus_cents must be a positive integer.")
    assignment_service.bonus(row, requester_row, principal["id"], amount)
    return success(serialize_assignment(row)), 200


def _dispute(assignment_id):
    """POST /mkt/assignments/{assignment_id}/dispute."""
    principal = resolve(request, ["Worker"])
    row = get_assignment(assignment_id)
    require_owner(principal, row["worker_id"])
    worker_row = db.workers[row["worker_id"]]
    payload = body(request)
    assignment_service.dispute(row, worker_row, payload.get("reason"))
    return success(serialize_assignment(row)), 200


def _admin_resolve(assignment_id):
    """POST /mkt/assignments/{assignment_id}/admin-resolve."""
    principal = resolve(request, ["PlatformAdmin"])
    row = get_assignment(assignment_id)
    payload = body(request)
    decision = require_str(payload, "decision").upper()
    assignment_service.admin_resolve(
        row, decision, optional_str(payload, "reason"), principal["id"]
    )
    return success(serialize_assignment(row)), 200


def _list_reviews(assignment_id):
    """GET /mkt/assignments/{id}/reviews."""
    resolve(request, READERS)
    get_assignment(assignment_id)
    rows = [r for r in db.reviews.values() if r["assignment_id"] == assignment_id]
    rows.sort(key=sort_key_review_created)
    page, meta = paginate(rows, request.args)
    return array([serialize_review(r) for r in page], meta), 200


bp.add_url_rule("/assignments", "list_assignments", _list, methods=["GET"])
bp.add_url_rule(
    "/assignments/<assignment_id>", "get_assignment", _get, methods=["GET"]
)
bp.add_url_rule(
    "/workers/<worker_id>/assignments/concurrency-check",
    "concurrency_check",
    _concurrency_check,
    methods=["POST"],
)
bp.add_url_rule(
    "/assignments/<assignment_id>/submit", "submit_assignment", _submit, methods=["POST"]
)
bp.add_url_rule(
    "/assignments/<assignment_id>/return", "return_assignment", _return, methods=["POST"]
)
bp.add_url_rule(
    "/assignments/<assignment_id>/approve", "approve_assignment", _approve, methods=["POST"]
)
bp.add_url_rule(
    "/assignments/<assignment_id>/reject", "reject_assignment", _reject, methods=["POST"]
)
bp.add_url_rule(
    "/assignments/<assignment_id>/bonus", "bonus_assignment", _bonus, methods=["POST"]
)
bp.add_url_rule(
    "/assignments/<assignment_id>/dispute",
    "dispute_assignment",
    _dispute,
    methods=["POST"],
)
bp.add_url_rule(
    "/assignments/<assignment_id>/admin-resolve",
    "admin_resolve",
    _admin_resolve,
    methods=["POST"],
)
bp.add_url_rule(
    "/assignments/<assignment_id>/reviews",
    "list_assignment_reviews",
    _list_reviews,
    methods=["GET"],
)