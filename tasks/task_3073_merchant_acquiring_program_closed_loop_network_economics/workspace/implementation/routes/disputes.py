"""Closed-loop dispute handling."""

from flask import Blueprint, request

from auth import authenticate, require_owned_by_caller, require_role
from db import STORE
from paging import filter_arg, paginate, pagination, sort_rows
from response import ok_array, ok_object
from routes import _common
from services import disputes as dispute_service, risk
from validation import body_object, require_enum, require_int, require_string

bp = Blueprint("disputes", __name__)

DISPUTE_STATUSES = (
    "OPEN",
    "MERCHANT_RESPONDED",
    "AUTO_ACCEPTED",
    "WON",
    "LOST",
    "WITHDRAWN",
)
OUTCOMES = ("WON", "LOST", "LOST_WITH_MEMBER_CREDIT", "MERCHANT_WIN_CARDMEMBER_CREDIT")

DISPUTE_OPS = ["NetworkDisputeOps"]
DISPUTE_OPS_OR_MEMBER = ["NetworkDisputeOps", "CardMember"]
DISPUTE_OPS_MEMBER_OR_MERCHANT = ["NetworkDisputeOps", "CardMember", "Merchant"]


@bp.post("/disputes")
def open_dispute():
    caller = authenticate(STORE, request.headers)
    require_role(caller, ["CardMember"])
    body = body_object(
        request.get_json(silent=True) or {},
        {"cardmember_id", "original_merchant_id", "final_merchant_id", "amount_cents"},
    )
    cardmember_id = require_string(body, "cardmember_id")
    original_merchant_id = require_string(body, "original_merchant_id")
    final_merchant_id = require_string(body, "final_merchant_id")
    amount_cents = require_int(body, "amount_cents", minimum=1)

    member = _common.cardmember(cardmember_id)
    require_owned_by_caller(caller, member["id"])
    _common.merchant(original_merchant_id)
    _common.merchant(final_merchant_id)

    with STORE.lock:
        dispute_id = STORE.new_id()
        now = STORE.clock.now()
        row = {
            "id": dispute_id,
            "created_at": now,
            "updated_at": now,
            "version": 0,
            "_seq": STORE.next_created_seq(),
            "cardmember_id": cardmember_id,
            "original_merchant_id": original_merchant_id,
            "final_merchant_id": final_merchant_id,
            "amount_cents": amount_cents,
            "dispute_status": "OPEN",
            "representment_stage": "NONE",
            "network_settled_cents": 0,
            "chargeback_count_reserved": 1,
            "priority": "HIGH" if amount_cents >= 50000 else "STANDARD",
            "occurred_at": now,
        }
        STORE.disputes[dispute_id] = row
        original_risk = STORE.risk_state_for(original_merchant_id)
        if original_risk is not None:
            risk.recompute(STORE, original_risk)
    return ok_object(_common.render(row)), 201


@bp.get("/disputes/<dispute_id>")
def get_dispute(dispute_id):
    caller = authenticate(STORE, request.headers)
    require_role(caller, DISPUTE_OPS_MEMBER_OR_MERCHANT)
    row = _common.dispute(dispute_id)
    if caller.role == "CardMember":
        require_owned_by_caller(caller, row["cardmember_id"])
    return ok_object(_common.render(row))


@bp.get("/disputes")
def list_disputes():
    caller = authenticate(STORE, request.headers)
    require_role(caller, ["NetworkDisputeOps", "Merchant"])
    limit, offset = pagination(request.args)
    merchant_id = filter_arg(request.args, "merchant_id")
    original_merchant_id = filter_arg(request.args, "original_merchant_id")
    final_merchant_id = filter_arg(request.args, "final_merchant_id")
    cardmember_id = filter_arg(request.args, "cardmember_id")
    dispute_status = filter_arg(request.args, "dispute_status", DISPUTE_STATUSES)

    rows = list(STORE.disputes.values())
    if merchant_id is not None:
        rows = [row for row in rows
                if merchant_id in (row["original_merchant_id"], row["final_merchant_id"])]
    if original_merchant_id is not None:
        rows = [row for row in rows if row["original_merchant_id"] == original_merchant_id]
    if final_merchant_id is not None:
        rows = [row for row in rows if row["final_merchant_id"] == final_merchant_id]
    if cardmember_id is not None:
        rows = [row for row in rows if row["cardmember_id"] == cardmember_id]
    if dispute_status is not None:
        rows = [row for row in rows if row["dispute_status"] == dispute_status]
    if caller.role == "Merchant":
        rows = [row for row in rows
                if caller.user_id in (row["original_merchant_id"], row["final_merchant_id"])]
    rows = sort_rows(rows, "created_at")
    total = len(rows)
    page = paginate(rows, limit, offset)
    return ok_array([_common.render(row) for row in page], total, limit, offset)


@bp.post("/disputes/<dispute_id>/respond")
def respond(dispute_id):
    caller = authenticate(STORE, request.headers)
    require_role(caller, ["Merchant"])
    body_object(request.get_json(silent=True) or {}, set())
    row = _common.dispute(dispute_id)
    with STORE.lock:
        dispute_service.respond(STORE, row, caller)
        _recompute(row["original_merchant_id"])
    return ok_object(_common.render(row))


@bp.post("/disputes/<dispute_id>/resolve")
def resolve(dispute_id):
    caller = authenticate(STORE, request.headers)
    require_role(caller, DISPUTE_OPS)
    body = body_object(request.get_json(silent=True) or {}, {"outcome"})
    outcome = require_enum(body, "outcome", OUTCOMES)
    row = _common.dispute(dispute_id)
    with STORE.lock:
        dispute_service.resolve(STORE, row, outcome, caller)
    return ok_object(_common.render(row))


@bp.post("/disputes/<dispute_id>/withdraw")
def withdraw(dispute_id):
    caller = authenticate(STORE, request.headers)
    require_role(caller, ["CardMember"])
    body_object(request.get_json(silent=True) or {}, set())
    row = _common.dispute(dispute_id)
    with STORE.lock:
        dispute_service.withdraw(STORE, row, caller)
        _recompute(row["original_merchant_id"])
    return ok_object(_common.render(row))


def _recompute(merchant_id):
    risk_state = STORE.risk_state_for(merchant_id)
    if risk_state is not None:
        risk.recompute(STORE, risk_state)
