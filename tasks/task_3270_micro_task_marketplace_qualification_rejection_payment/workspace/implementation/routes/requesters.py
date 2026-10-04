"""Requester, deposit, abuse-review and review-listing routes."""

from flask import Blueprint, request

from db import db, common_fields, touch
from errors import fail
from middleware import is_admin, require_owner, resolve
from response import array, success
from rounding import sort_key_created, sort_key_review_created
from serializers import deposit as serialize_deposit
from serializers import hit as serialize_hit
from serializers import requester as serialize_requester
from serializers import review as serialize_review
from services import hit_service, requester_service
from services.common import body, get_requester, paginate, require_int, require_str

bp = Blueprint("requesters", __name__, url_prefix="/mkt")

REQUESTER_ROLES = ["Requester", "PlatformAdmin"]
ADMIN_ONLY = ["PlatformAdmin"]


def _create():
    """POST /mkt/requesters - register a requester account (Anonymous)."""
    resolve(request, None, auth_exempt=True)
    payload = body(request)
    name = require_str(payload, "name")
    row = common_fields()
    row.update(
        {
            "name": name,
            "prepaid_balance_cents": 0,
            "escrowed_cents": 0,
            "lifetime_spent_cents": 0,
            "approved_count": 0,
            "rejected_count": 0,
            "abuse_score": 0,
            "task_abuse_flag": False,
            "suspension_reason": None,
            "status": "ACTIVE",
        }
    )
    db.requesters[row["id"]] = row
    return success(serialize_requester(row)), 201


def _get(requester_id):
    """GET /mkt/requesters/{requester_id} - profile with the lifetime rate."""
    resolve(request, REQUESTER_ROLES)
    row = get_requester(requester_id)
    return success(serialize_requester(row)), 200


def _create_deposit(requester_id):
    """POST /mkt/requesters/{requester_id}/deposits - a PENDING prepayment."""
    principal = resolve(request, REQUESTER_ROLES)
    row = get_requester(requester_id)
    if not is_admin(principal):
        require_owner(principal, row["id"])
    payload = body(request)
    amount = require_int(payload, "amount_cents")
    if amount <= 0:
        fail("ERR_INVALID_REQUEST", "amount_cents must be a positive integer.")
    deposit_row = common_fields()
    deposit_row.update(
        {
            "requester_id": row["id"],
            "amount_cents": amount,
            "status": "PENDING",
            "refunded_cents": 0,
        }
    )
    db.deposits[deposit_row["id"]] = deposit_row
    return success(serialize_deposit(deposit_row)), 201


def _list_deposits():
    """GET /mkt/requester-deposits - optionally filtered by requester."""
    resolve(request, REQUESTER_ROLES)
    requester_id = request.args.get("requester_id")
    rows = list(db.deposits.values())
    if requester_id:
        rows = [d for d in rows if d["requester_id"] == requester_id]
    rows.sort(key=sort_key_created)
    page, meta = paginate(rows, request.args)
    return array([serialize_deposit(d) for d in page], meta), 200


def _get_deposit(deposit_id):
    """GET /mkt/requester-deposits/{id} - a deposit by id."""
    resolve(request, REQUESTER_ROLES)
    row = db.deposits.get(deposit_id)
    if row is None:
        fail("ERR_NOT_FOUND", "Deposit not found.")
    return success(serialize_deposit(row)), 200


def _settle_deposit(deposit_id):
    """POST /mkt/requester-deposits/{deposit_id}/settle - platform admin only.

    Only a settlement that succeeds credits the requester's balance; a failing
    settlement leaves the balance untouched.
    """
    resolve(request, ADMIN_ONLY)
    row = db.deposits.get(deposit_id)
    if row is None:
        fail("ERR_NOT_FOUND", "Deposit not found.")
    if row["status"] != "PENDING":
        fail("ERR_INVALID_STATE")
    payload = body(request)
    outcome = require_str(payload, "outcome").upper()
    if outcome in {"SUCCEEDED", "SUCCESS"}:
        row["status"] = "SUCCEEDED"
    elif outcome in {"FAILED", "FAILURE"}:
        row["status"] = "FAILED"
    else:
        fail("ERR_INVALID_REQUEST", "outcome must be SUCCEEDED or FAILED.")
    touch(row)

    requester_row = db.requesters[row["requester_id"]]
    hit_service.resync_requester(requester_row)
    touch(requester_row)
    return success(serialize_deposit(row)), 200


def _abuse_review(requester_id):
    """POST /mkt/requesters/{requester_id}/abuse-review."""
    resolve(request, ADMIN_ONLY)
    row = get_requester(requester_id)
    requester_service.abuse_review(row)
    return success(serialize_requester(row)), 200


def _reinstate(requester_id):
    """POST /mkt/requesters/{requester_id}/reinstate."""
    resolve(request, ADMIN_ONLY)
    row = get_requester(requester_id)
    if row["status"] != "SUSPENDED":
        fail("ERR_INVALID_STATE")
    requester_service.reinstate(row)
    return success(serialize_requester(row)), 200


def _list_hits(requester_id):
    """GET /mkt/requesters/{requester_id}/hits - FK reverse-reachability."""
    resolve(request, ["Requester", "Worker", "PlatformAdmin"])
    get_requester(requester_id)
    rows = [h for h in db.hits.values() if h["requester_id"] == requester_id]
    status = request.args.get("status")
    if status:
        rows = [h for h in rows if h["status"] == status]
    rows.sort(key=sort_key_created)
    page, meta = paginate(rows, request.args)
    return array([serialize_hit(h) for h in page], meta), 200


def _list_reviews(requester_id):
    """GET /mkt/requesters/{id}/reviews - reviews authored by a requester."""
    resolve(request, REQUESTER_ROLES)
    get_requester(requester_id)
    rows = [
        r
        for r in db.reviews.values()
        if r["actor_requester_id"] == requester_id
    ]
    rows.sort(key=sort_key_review_created)
    page, meta = paginate(rows, request.args)
    return array([serialize_review(r) for r in page], meta), 200


bp.add_url_rule("/requesters", "create_requester", _create, methods=["POST"])
bp.add_url_rule("/requesters/<requester_id>", "get_requester", _get, methods=["GET"])
bp.add_url_rule(
    "/requesters/<requester_id>/deposits",
    "create_deposit",
    _create_deposit,
    methods=["POST"],
)
bp.add_url_rule(
    "/requester-deposits", "list_deposits", _list_deposits, methods=["GET"]
)
bp.add_url_rule(
    "/requester-deposits/<deposit_id>", "get_deposit", _get_deposit, methods=["GET"]
)
bp.add_url_rule(
    "/requester-deposits/<deposit_id>/settle",
    "settle_deposit",
    _settle_deposit,
    methods=["POST"],
)
bp.add_url_rule(
    "/requesters/<requester_id>/abuse-review",
    "abuse_review",
    _abuse_review,
    methods=["POST"],
)
bp.add_url_rule(
    "/requesters/<requester_id>/reinstate",
    "reinstate_requester",
    _reinstate,
    methods=["POST"],
)
bp.add_url_rule(
    "/requesters/<requester_id>/hits", "list_requester_hits", _list_hits, methods=["GET"]
)
bp.add_url_rule(
    "/requesters/<requester_id>/reviews",
    "list_requester_reviews",
    _list_reviews,
    methods=["GET"],
)