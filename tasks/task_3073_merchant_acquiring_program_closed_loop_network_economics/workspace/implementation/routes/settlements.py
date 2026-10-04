"""Settlements and funding (collection reads plus the settlement transitions)."""

from flask import Blueprint, request

from auth import authenticate, require_owned_by_caller, require_role
from db import STORE
from paging import filter_arg, paginate, pagination, sort_rows
from response import ok_array, ok_object
from routes import _common
from services import merchant as merchant_service

bp = Blueprint("settlements", __name__)

SETTLEMENT_STATUSES = ("CAPTURED", "IN_FUNDING", "SETTLED", "REVERSED")
OPS = ["NetworkSettlementOps"]
OPS_OR_MERCHANT = ["NetworkSettlementOps", "Merchant"]


@bp.get("/settlements/<settlement_id>")
def get_settlement(settlement_id):
    caller = authenticate(STORE, request.headers)
    require_role(caller, OPS_OR_MERCHANT)
    row = _common.settlement(settlement_id)
    if caller.role == "Merchant":
        require_owned_by_caller(caller, row["merchant_id"])
    return ok_object(_common.render(row))


@bp.get("/settlements")
def list_settlements():
    caller = authenticate(STORE, request.headers)
    require_role(caller, OPS_OR_MERCHANT)
    limit, offset = pagination(request.args)
    merchant_id = filter_arg(request.args, "merchant_id")
    settlement_status = filter_arg(request.args, "settlement_status", SETTLEMENT_STATUSES)

    rows = list(STORE.settlements.values())
    if merchant_id is not None:
        rows = [row for row in rows if row["merchant_id"] == merchant_id]
    if settlement_status is not None:
        rows = [row for row in rows if row["settlement_status"] == settlement_status]
    if caller.role == "Merchant":
        rows = [row for row in rows if row["merchant_id"] == caller.user_id]
    rows = sort_rows(rows, "created_at")
    total = len(rows)
    page = paginate(rows, limit, offset)
    return ok_array([_common.render(row) for row in page], total, limit, offset)


@bp.post("/settlements/<settlement_id>/posting-reversal")
def posting_reversal(settlement_id):
    caller = authenticate(STORE, request.headers)
    require_role(caller, OPS)
    request.get_json(silent=True)
    row = _common.settlement(settlement_id)
    with STORE.lock:
        merchant_service.posting_reversal(STORE, row)
    return ok_object(_common.render(row))


@bp.post("/settlements/<settlement_id>/reinstate")
def reinstate(settlement_id):
    caller = authenticate(STORE, request.headers)
    require_role(caller, OPS)
    request.get_json(silent=True)
    row = _common.settlement(settlement_id)
    with STORE.lock:
        merchant_service.reinstate(STORE, row)
    return ok_object(_common.render(row))