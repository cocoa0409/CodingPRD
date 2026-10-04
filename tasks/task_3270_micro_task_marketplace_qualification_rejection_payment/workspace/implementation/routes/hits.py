"""HIT (task) routes: drafting, funding, publication, cancellation and sweeps."""

from flask import Blueprint, request

from db import db, common_fields, touch
from errors import fail
from middleware import require_owner, resolve
from response import array, success
from rounding import sort_key_created
from serializers import assignment as serialize_assignment
from serializers import hit as serialize_hit
from services import assignment_service, hit_service
from services.common import (
    body,
    get_hit,
    get_requester,
    optional_int,
    optional_list,
    paginate,
    require_int,
    require_str,
)

bp = Blueprint("hits", __name__, url_prefix="/mkt")

HIT_READERS = ["Requester", "Worker", "PlatformAdmin"]


def _create():
    """POST /mkt/hits - draft a task (Requester).

    Malformed pricing is refused with ERR_REWARD_INVALID: reward_cents must be a
    positive whole number of cents and the three pool/time-limit fields must all
    be positive. funds_required_cents is computed immediately.
    """
    principal = resolve(request, ["Requester"])
    payload = body(request)
    requester_id = require_str(payload, "requester_id")
    requester_row = get_requester(requester_id)
    require_owner(principal, requester_row["id"])

    title = require_str(payload, "title")
    reward_cents = require_int(payload, "reward_cents")
    max_assignments = require_int(payload, "max_assignments")
    duration = require_int(payload, "assignment_duration_minutes")
    time_limit = require_int(payload, "time_limit_minutes")
    bonus_budget = optional_int(payload, "bonus_budget_cents", 0)

    if (
        reward_cents <= 0
        or max_assignments <= 0
        or duration <= 0
        or time_limit <= 0
    ):
        fail("ERR_REWARD_INVALID")
    if bonus_budget < 0:
        fail("ERR_INVALID_REQUEST", "bonus_budget_cents must not be negative.")

    required_ids = optional_list(payload, "required_qualification_ids")
    for type_id in required_ids:
        if type_id not in db.qualification_types:
            fail("ERR_NOT_FOUND", "Required qualification type not found.")

    row = common_fields()
    row.update(
        {
            "requester_id": requester_row["id"],
            "title": title,
            "reward_cents": reward_cents,
            "required_qualification_ids": required_ids,
            "max_assignments": max_assignments,
            "assignment_duration_minutes": duration,
            "time_limit_minutes": time_limit,
            "bonus_budget_cents": bonus_budget,
            "funds_required_cents": 0,
            "escrowed_cents": 0,
            "accepted_count": 0,
            "assignment_count": 0,
            "committed_assignments": 0,
            "spent_rewards_cents": 0,
            "spent_bonus_cents": 0,
            "status": "DRAFT",
        }
    )
    hit_service.recompute_funds(row)
    db.hits[row["id"]] = row
    return success(serialize_hit(row)), 201


def _get(hit_id):
    """GET /mkt/hits/{hit_id}."""
    resolve(request, HIT_READERS)
    row = get_hit(hit_id)
    return success(serialize_hit(row)), 200


def _list():
    """GET /mkt/hits - filters requester_id and status."""
    resolve(request, HIT_READERS)
    rows = list(db.hits.values())
    requester_id = request.args.get("requester_id")
    status = request.args.get("status")
    if requester_id:
        rows = [h for h in rows if h["requester_id"] == requester_id]
    if status:
        rows = [h for h in rows if h["status"] == status]
    rows.sort(key=sort_key_created)
    page, meta = paginate(rows, request.args)
    return array([serialize_hit(h) for h in page], meta), 200


def _publish(hit_id):
    """POST /mkt/hits/{hit_id}/publish - hold funds from the prepaid balance.

    The three gates fire in the platform's fixed order: ownership, then the
    requester's standing, then - because money is checked last - the balance.
    """
    principal = resolve(request, ["Requester"])
    row = get_hit(hit_id)
    require_owner(principal, row["requester_id"])
    if row["status"] != "DRAFT":
        fail("ERR_INVALID_STATE")

    requester_row = db.requesters[row["requester_id"]]
    if requester_row["task_abuse_flag"]:
        fail("ERR_REQUESTER_TASK_BLOCKED")
    if requester_row["status"] != "ACTIVE":
        fail("ERR_REQUESTER_NOT_ACTIVE")

    hit_service.recompute_funds(row)
    if requester_row["prepaid_balance_cents"] < row["funds_required_cents"]:
        fail("ERR_INSUFFICIENT_FUNDS")

    row["status"] = "PUBLISHED"
    hit_service.snapshot_escrow(row)
    hit_service.resync_requester(requester_row)
    touch(row)
    touch(requester_row)
    return success(serialize_hit(row)), 200


def _cancel(hit_id):
    """POST /mkt/hits/{hit_id}/cancel - refund unclaimed escrow.

    Only a task that has never accepted a worker may be cancelled: a task that
    has ever dispatched work must run to completion instead.
    """
    principal = resolve(request, ["Requester"])
    row = get_hit(hit_id)
    require_owner(principal, row["requester_id"])
    if row["status"] not in {"DRAFT", "PUBLISHED"}:
        fail("ERR_INVALID_STATE")
    if row["accepted_count"] != 0:
        fail("ERR_INVALID_STATE")

    expected = optional_int(body(request), "expected_hit_version")
    assignment_service.check_hit_version(row, expected)

    row["status"] = "CANCELLED"
    row["escrowed_cents"] = 0
    touch(row)
    requester_row = db.requesters[row["requester_id"]]
    hit_service.resync_requester(requester_row)
    touch(requester_row)
    return success(serialize_hit(row)), 200


def _sweep_expired(hit_id):
    """POST /mkt/hits/{hit_id}/sweep-expired - collect overdue assignments."""
    principal = resolve(request, ["Requester"])
    row = get_hit(hit_id)
    require_owner(principal, row["requester_id"])
    expected = optional_int(body(request), "expected_hit_version")
    assignment_service.sweep_hit_expired(row, expected)
    return success(serialize_hit(row)), 200


def _list_assignments(hit_id):
    """GET /mkt/hits/{hit_id}/assignments - FK reverse-reachability."""
    resolve(request, HIT_READERS)
    get_hit(hit_id)
    rows = [a for a in db.assignments.values() if a["hit_id"] == hit_id]
    status = request.args.get("status")
    if status:
        rows = [a for a in rows if a["status"] == status]
    rows.sort(key=lambda a: (a.get("created_at") or "", a.get("sequence") or 0))
    page, meta = paginate(rows, request.args)
    return array([serialize_assignment(a) for a in page], meta), 200


def _accept(hit_id):
    """POST /mkt/hits/{hit_id}/assignments - accept a task (Worker)."""
    principal = resolve(request, ["Worker"])
    row = get_hit(hit_id)
    payload = body(request)
    worker_id = require_str(payload, "worker_id")
    worker_row = db.workers.get(worker_id)
    if worker_row is None:
        fail("ERR_NOT_FOUND", "Worker not found.")
    require_owner(principal, worker_row["id"])
    assignment = assignment_service.accept(row, worker_row)
    return success(serialize_assignment(assignment)), 201


bp.add_url_rule("/hits", "create_hit", _create, methods=["POST"])
bp.add_url_rule("/hits", "list_hits", _list, methods=["GET"])
bp.add_url_rule("/hits/<hit_id>", "get_hit", _get, methods=["GET"])
bp.add_url_rule("/hits/<hit_id>/publish", "publish_hit", _publish, methods=["POST"])
bp.add_url_rule("/hits/<hit_id>/cancel", "cancel_hit", _cancel, methods=["POST"])
bp.add_url_rule(
    "/hits/<hit_id>/sweep-expired", "sweep_expired", _sweep_expired, methods=["POST"]
)
bp.add_url_rule(
    "/hits/<hit_id>/assignments", "list_hit_assignments", _list_assignments, methods=["GET"]
)
bp.add_url_rule(
    "/hits/<hit_id>/assignments", "accept_hit", _accept, methods=["POST"]
)