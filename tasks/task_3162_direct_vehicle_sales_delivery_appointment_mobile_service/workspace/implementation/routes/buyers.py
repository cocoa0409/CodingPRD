"""Buyer and fee-ledger routes."""

from flask import Blueprint, request

from db import DB
from errors import fail
from repository import find, get, matches, serialize
from response import list_response, object_response
from routes.common import (
    acting_user_id, acting_role, body, instant_field, need, paged, require_self,
    string_list, text_field,
    counted,
)
from services import ledger, sales

bp = Blueprint("buyers", __name__)


@bp.post("/buyers")
def create_buyer():
    payload = body()
    buyer = sales.create_buyer(
        text_field(payload, "full_name"),
        text_field(payload, "email"),
        text_field(payload, "residency_state_code"),
    )
    return object_response(serialize(buyer), 201)


@bp.get("/buyers")
def list_buyers():
    rows = [b for b in DB.buyers.values()
            if matches(request.args, "residency_state_code", b["residency_state_code"])
            and matches(request.args, "status", b["status"])]
    page, limit, offset, total = counted(rows)
    return list_response([serialize(r) for r in page], limit, offset,
                         total_count=total)


@bp.get("/buyers/<buyer_id>")
def get_buyer(buyer_id):
    buyer = get("buyer", buyer_id)
    require_self(buyer)
    return object_response(serialize(buyer))


@bp.post("/buyers/<buyer_id>/identity-verification")
def verify_buyer(buyer_id):
    buyer = get("buyer", buyer_id)
    require_self(buyer)
    return object_response(serialize(sales.verify_identity(buyer)))


@bp.post("/buyers/<buyer_id>/suspend")
def suspend_buyer(buyer_id):
    buyer = get("buyer", buyer_id)
    return object_response(serialize(sales.suspend_buyer(buyer)))


@bp.get("/buyers/<buyer_id>/fee-ledger-entries")
def buyer_ledger(buyer_id):
    buyer = get("buyer", buyer_id)
    require_self(buyer)
    rows = ledger.entries_for(buyer_id=buyer["id"],
                              entry_type=request.args.get("entry_type"))
    page, limit, offset, total = counted(rows)
    return list_response([serialize(r) for r in page], limit, offset,
                         total_count=total)


@bp.get("/buyers/<buyer_id>/orders")
def buyer_orders(buyer_id):
    buyer = get("buyer", buyer_id)
    require_self(buyer)
    rows = [o for o in DB.orders.values()
            if o["buyer_id"] == buyer["id"] and matches(request.args, "status", o["status"])]
    page, limit, offset, total = counted(rows)
    return list_response([serialize(r) for r in page], limit, offset,
                         total_count=total)


@bp.get("/buyers/<buyer_id>/trade-in-appraisals")
def buyer_appraisals(buyer_id):
    buyer = get("buyer", buyer_id)
    require_self(buyer)
    order_ids = {o["id"] for o in DB.orders.values() if o["buyer_id"] == buyer["id"]}
    rows = [a for a in DB.appraisals.values()
            if a["order_id"] in order_ids and matches(request.args, "status", a["status"])]
    page, limit, offset, total = counted(rows)
    return list_response([serialize(r) for r in page], limit, offset,
                         total_count=total)


@bp.get("/buyers/<buyer_id>/financing-applications")
def buyer_applications(buyer_id):
    buyer = get("buyer", buyer_id)
    require_self(buyer)
    rows = [a for a in DB.applications.values()
            if a["buyer_id"] == buyer["id"] and matches(request.args, "status", a["status"])]
    page, limit, offset, total = counted(rows)
    return list_response([serialize(r) for r in page], limit, offset,
                         total_count=total)


@bp.get("/fee-ledger-entries")
def all_ledger():
    rows = ledger.entries_for(
        order_id=request.args.get("order_id"),
        buyer_id=request.args.get("buyer_id"),
        entry_type=request.args.get("entry_type"))
    page, limit, offset, total = counted(rows)
    return list_response([serialize(r) for r in page], limit, offset,
                         total_count=total)