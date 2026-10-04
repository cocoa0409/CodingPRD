"""Payout routes and the logical-clock controls."""

from flask import Blueprint, request

from config import PAYOUT_METHODS
from db import db
from errors import fail
from middleware import require_owner, resolve
from response import array, success
from rounding import sort_key_created
from serializers import payout as serialize_payout
from services import clock_service, payout_service
from services.common import (
    body,
    optional_int,
    paginate,
    require_enum,
    require_int,
    require_str,
)

bp = Blueprint("payouts", __name__, url_prefix="/mkt")

PAYOUT_ROLES = ["Worker", "PlatformAdmin"]


def _request_payout(worker_id):
    """POST /mkt/workers/{id}/payouts - mint a HELD_FOR_VETTING payout."""
    principal = resolve(request, ["Worker"])
    worker_row = db.workers.get(worker_id)
    if worker_row is None:
        fail("ERR_NOT_FOUND", "Worker not found.")
    require_owner(principal, worker_row["id"])
    payload = body(request)
    payment_method = require_enum(payload, "payment_method", PAYOUT_METHODS)
    amount_cents = require_int(payload, "amount_cents")
    row = payout_service.request_payout(worker_row, payment_method, amount_cents)
    return success(serialize_payout(row)), 201


def _get_payout(payout_id):
    """GET /mkt/payouts/{payout_id}."""
    principal = resolve(request, PAYOUT_ROLES)
    row = db.payouts.get(payout_id)
    if row is None:
        fail("ERR_NOT_FOUND", "Payout request not found.")
    if principal["role"] == "Worker":
        require_owner(principal, row["worker_id"])
    return success(serialize_payout(row)), 200


def _list_payouts(worker_id):
    """GET /mkt/workers/{id}/payouts - FK reverse-reachability."""
    principal = resolve(request, PAYOUT_ROLES)
    worker_row = db.workers.get(worker_id)
    if worker_row is None:
        fail("ERR_NOT_FOUND", "Worker not found.")
    if principal["role"] == "Worker":
        require_owner(principal, worker_row["id"])
    rows = [p for p in db.payouts.values() if p["worker_id"] == worker_id]
    status = request.args.get("status")
    if status:
        rows = [p for p in rows if p["status"] == status]
    rows.sort(key=sort_key_created)
    page, meta = paginate(rows, request.args)
    return array([serialize_payout(p) for p in page], meta), 200


def _verify_payout(payout_id):
    """POST /mkt/payouts/{payout_id}/verify - operator release."""
    resolve(request, ["PlatformAdmin"])
    row = db.payouts.get(payout_id)
    if row is None:
        fail("ERR_NOT_FOUND", "Payout request not found.")
    worker_row = db.workers.get(row["worker_id"])
    if worker_row is None:
        fail("ERR_NOT_FOUND", "Worker not found.")
    expected = optional_int(body(request), "expected_payout_request_version")
    payout_service.verify_payout(row, worker_row, expected)
    return success(serialize_payout(row)), 200


def _reject_payout(payout_id):
    """POST /mkt/payouts/{payout_id}/reject - release the reserved funds."""
    resolve(request, ["PlatformAdmin"])
    row = db.payouts.get(payout_id)
    if row is None:
        fail("ERR_NOT_FOUND", "Payout request not found.")
    worker_row = db.workers.get(row["worker_id"])
    if worker_row is None:
        fail("ERR_NOT_FOUND", "Worker not found.")
    payload = body(request)
    payout_service.reject_payout(row, worker_row, payload.get("rejection_reason"))
    return success(serialize_payout(row)), 200


# --- logical clock ---------------------------------------------------------
def _set_clock():
    """POST /mkt/_clock/set_current_utc - move the clock, run no sweeps."""
    resolve(request, ["PlatformAdmin"])
    payload = body(request)
    clock_service.set_current_utc(require_str(payload, "current_utc"))
    return success(None), 200


def _advance_clock():
    """POST /mkt/_clock/advance_to - advance and run every due sweep."""
    resolve(request, ["PlatformAdmin"])
    payload = body(request)
    clock_service.advance_to(require_str(payload, "target_utc"))
    return success(None), 200


bp.add_url_rule(
    "/workers/<worker_id>/payouts", "request_payout", _request_payout, methods=["POST"]
)
bp.add_url_rule(
    "/workers/<worker_id>/payouts", "list_payouts", _list_payouts, methods=["GET"]
)
bp.add_url_rule("/payouts/<payout_id>", "get_payout", _get_payout, methods=["GET"])
bp.add_url_rule(
    "/payouts/<payout_id>/verify", "verify_payout", _verify_payout, methods=["POST"]
)
bp.add_url_rule(
    "/payouts/<payout_id>/reject", "reject_payout", _reject_payout, methods=["POST"]
)
bp.add_url_rule(
    "/_clock/set_current_utc", "set_clock", _set_clock, methods=["POST"]
)
bp.add_url_rule("/_clock/advance_to", "advance_clock", _advance_clock, methods=["POST"])