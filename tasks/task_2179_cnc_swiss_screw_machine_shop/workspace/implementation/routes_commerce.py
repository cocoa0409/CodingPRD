"""Quotes, blanket purchase orders and kanban releases."""
from datetime import timedelta

from flask import Blueprint, request

import calc
import services
from core import (db, dec, fail, now, parse_dt, public, respond_list, respond_object,
                  sorted_rows, stamp_new, touch)
from guards import (ALL_ROLES, authenticate, body, f_dt, f_enum, f_int, f_num, f_str,
                    lookup, paginate, pagination)

bp = Blueprint("commerce", __name__)


# ==========================================================================
# quotes
# ==========================================================================
@bp.post("/swiss-shop/quotes")
def create_quote():
    authenticate(("ShopPlanner",))
    payload = body()
    part_id = f_str(payload, "part_id")
    customer_code = f_str(payload, "customer_code")
    lot_qty = f_int(payload, "lot_qty", minimum=1)
    requested_lights_out_hours = f_num(payload, "requested_lights_out_hours",
                                       required=False, default=dec(0), minimum=0)
    lookup("parts", part_id)
    row = stamp_new({
        "part_id": part_id,
        "customer_code": customer_code,
        "lot_qty": lot_qty,
        "requested_lights_out_hours": requested_lights_out_hours,
        "costing_basis": None,
        "cycle_time_used_sec": None,
        "effective_qty": None,
        "run_cost_cents": None,
        "setup_cost_cents": None,
        "secondary_cost_cents": None,
        "material_cost_cents": None,
        "quoted_lot_cost_cents": None,
        "quoted_unit_price_cents": None,
        "status": "DRAFT",
    })
    db.quotes[row["id"]] = row
    return respond_object(public(row), 201)


@bp.get("/swiss-shop/quotes/<qid>")
def get_quote(qid):
    authenticate(ALL_ROLES)
    return respond_object(public(lookup("quotes", qid)))


@bp.get("/swiss-shop/quotes")
def list_quotes():
    authenticate(ALL_ROLES)
    limit, offset = pagination()
    rows = list(db.quotes.values())
    part_id = request.args.get("part_id")
    if part_id:
        rows = [r for r in rows if r["part_id"] == part_id]
    rows = sorted_rows(rows)
    window, total = paginate(rows, limit, offset)
    return respond_list([public(r) for r in window], limit, offset, total)


@bp.post("/swiss-shop/quotes/<qid>/price")
def price_quote(qid):
    authenticate(("ShopPlanner",))
    payload = body()
    costing_basis = f_enum(payload, "costing_basis", ("STANDARD_CYCLE", "HISTORICAL_CYCLE"))
    quote = lookup("quotes", qid)
    if quote["status"] not in ("DRAFT", "PRICED"):
        fail("ERR_INVALID_STATE")
    part = db.parts.get(quote["part_id"])
    if part is None:
        fail("ERR_PART_NOT_FOUND")
    quote.update(calc.price_quote(quote, part, costing_basis))
    quote["status"] = "PRICED"
    touch(quote)
    return respond_object(public(quote))


@bp.post("/swiss-shop/quotes/<qid>/accept")
def accept_quote(qid):
    authenticate(("ShopPlanner",))
    payload = body()
    customer_po_number = f_str(payload, "customer_po_number")
    total_committed_qty = f_int(payload, "total_committed_qty", minimum=1)
    expires_on, expires_dt = f_dt(payload, "expires_on")
    quote = lookup("quotes", qid)
    if quote["status"] != "PRICED":
        fail("ERR_INVALID_STATE")
    if expires_dt <= now():
        fail("ERR_INVALID_STATE", "expires_on must be strictly after the logical clock.")
    created_dt = parse_dt(quote["created_at"])
    if now() >= created_dt + timedelta(days=calc.QUOTE_VALID_UNTIL_DAYS):
        quote["status"] = "EXPIRED"
        touch(quote)
        fail("ERR_INVALID_STATE", "The quote is no longer valid.")

    quote["status"] = "ACCEPTED"
    touch(quote)

    rebate = calc.blanket_rebate(quote["quoted_unit_price_cents"], total_committed_qty)
    row = stamp_new({
        "quote_id": quote["id"],
        "part_id": quote["part_id"],
        "customer_po_number": customer_po_number,
        "total_committed_qty": total_committed_qty,
        "expires_on": expires_on,
        "list_unit_price_cents": rebate["list_unit_price_cents"],
        "pre_rebate_total_cents": rebate["pre_rebate_total_cents"],
        "rebate_pct": rebate["rebate_pct"],
        "net_unit_price_cents": rebate["net_unit_price_cents"],
        "committed_value_cents": rebate["committed_value_cents"],
        "remaining_qty": total_committed_qty,
        "open_released_qty": 0,
        "fulfilled_qty": 0,
        "status": "ACTIVE",
        "suspension_reason": None,
        "_expires_dt": expires_dt,
    })
    db.blanket_pos[row["id"]] = row
    return respond_object(public(row), 201)


# ==========================================================================
# blanket purchase orders
# ==========================================================================
@bp.get("/swiss-shop/blanket-pos/<bid>")
def get_blanket_po(bid):
    authenticate(ALL_ROLES)
    return respond_object(public(lookup("blanket_pos", bid)))


@bp.get("/swiss-shop/blanket-pos")
def list_blanket_pos():
    authenticate(ALL_ROLES)
    limit, offset = pagination()
    rows = list(db.blanket_pos.values())
    quote_id = request.args.get("quote_id")
    part_id = request.args.get("part_id")
    if quote_id:
        rows = [r for r in rows if r["quote_id"] == quote_id]
    if part_id:
        rows = [r for r in rows if r["part_id"] == part_id]
    rows = sorted_rows(rows)
    window, total = paginate(rows, limit, offset)
    return respond_list([public(r) for r in window], limit, offset, total)


@bp.post("/swiss-shop/blanket-pos/<bid>/suspend")
def suspend_blanket_po(bid):
    authenticate(("ShopPlanner",))
    payload = body()
    reason = f_str(payload, "reason")
    order = lookup("blanket_pos", bid)
    if order["status"] != "ACTIVE":
        fail("ERR_INVALID_STATE")
    order["status"] = "SUSPENDED"
    order["suspension_reason"] = reason
    touch(order)
    return respond_object(public(order))


@bp.post("/swiss-shop/blanket-pos/<bid>/reinstate")
def reinstate_blanket_po(bid):
    authenticate(("ShopPlanner",))
    body()
    order = lookup("blanket_pos", bid)
    if order["status"] != "SUSPENDED":
        fail("ERR_INVALID_STATE")
    if order["_expires_dt"] is not None and now() >= order["_expires_dt"]:
        fail("ERR_INVALID_STATE", "The blanket order has passed its expiry instant.")
    order["status"] = "ACTIVE"
    order["suspension_reason"] = None
    touch(order)
    return respond_object(public(order))


# ==========================================================================
# kanban releases
# ==========================================================================
@bp.post("/swiss-shop/kanban-releases")
def create_kanban_release():
    authenticate(("ShopPlanner",))
    payload = body()
    blanket_po_id = f_str(payload, "blanket_po_id")
    qty = f_int(payload, "qty", minimum=1)
    due_at, _due_dt = f_dt(payload, "due_at")
    expected_blanket_po_version = f_int(payload, "expected_blanket_po_version")
    order = lookup("blanket_pos", blanket_po_id)

    if expected_blanket_po_version != int(order["version"]):
        fail("ERR_STALE_PO_VERSION")
    if order["status"] != "ACTIVE":
        fail("ERR_PO_NOT_ACTIVE")
    if services.po_expire_if_lapsed(order):
        fail("ERR_PO_EXPIRED")
    if qty > int(order["remaining_qty"]):
        fail("ERR_PO_QTY_EXCEEDED")

    row = stamp_new({
        "blanket_po_id": blanket_po_id,
        "qty": qty,
        "due_at": due_at,
        "fulfilled_qty": 0,
        "close_reason": None,
        "status": "RELEASED",
    })
    db.kanban_releases[row["id"]] = row
    order["remaining_qty"] = int(order["remaining_qty"]) - qty
    order["open_released_qty"] = int(order["open_released_qty"]) + qty
    touch(order)
    return respond_object(public(row), 201)


@bp.get("/swiss-shop/kanban-releases/<rid>")
def get_kanban_release(rid):
    authenticate(ALL_ROLES)
    return respond_object(public(lookup("kanban_releases", rid)))


@bp.get("/swiss-shop/kanban-releases")
def list_kanban_releases():
    authenticate(ALL_ROLES)
    limit, offset = pagination()
    rows = list(db.kanban_releases.values())
    blanket_po_id = request.args.get("blanket_po_id")
    if blanket_po_id:
        rows = [r for r in rows if r["blanket_po_id"] == blanket_po_id]
    rows = sorted_rows(rows)
    window, total = paginate(rows, limit, offset)
    return respond_list([public(r) for r in window], limit, offset, total)


@bp.post("/swiss-shop/kanban-releases/<rid>/short-close")
def short_close_release(rid):
    authenticate(("ShopPlanner",))
    payload = body()
    reason = f_str(payload, "reason")
    release = lookup("kanban_releases", rid)
    jobs = services.work_orders_of_release(release["id"])
    if release["status"] == "RELEASED":
        for job in jobs:
            if job["machining_status"] in ("RUNNING", "INTERRUPTED", "MACHINING_COMPLETE"):
                fail("ERR_INVALID_STATE")
    elif release["status"] == "IN_PRODUCTION":
        for job in jobs:
            if job["machining_status"] != "CANCELLED":
                fail("ERR_INVALID_STATE")
    else:
        fail("ERR_INVALID_STATE")

    release["status"] = "SHORT_CLOSED"
    release["close_reason"] = reason
    touch(release)
    order = db.blanket_pos.get(release["blanket_po_id"])
    if order is not None:
        services.po_return_quantity(order, release["qty"])
    return respond_object(public(release))
