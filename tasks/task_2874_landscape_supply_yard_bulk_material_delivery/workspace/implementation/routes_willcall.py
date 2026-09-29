"""The will-call loading queue: issue, stage, brief, load, release, cancel."""
from flask import Blueprint

import calc
import serial
from core import (
    D, arg, auth, body, contractor_filter, db, fail, new_record, opt_int,
    pre_scope_order, r2, render_list, req_id, req_instant, req_num, req_str,
    require, respond, scope_via_order, touch,
)

bp = Blueprint("willcall", __name__)

TICKET_READ_ROLES = ("YardLoader", "YardAdmin", "Contractor")
BAY_OCCUPYING = ("STAGED", "LOADING")


# --------------------------------------------------------------------------
# Issuing and reading tickets
# --------------------------------------------------------------------------
@bp.post("/will-call-tickets")
def create_ticket():
    ctx = auth("Contractor")
    data = body()
    pre_scope_order(ctx, data)
    order_id = req_id(data, "material_order_id")
    requested = req_instant(data, "requested_pickup_at")
    order = require(db.get("material_orders", order_id), "material_orders")
    if order["fulfillment_mode"] != "WILL_CALL":
        fail("ERR_WILL_CALL_MODE_REQUIRED",
             "Only a WILL_CALL order may carry a will-call ticket.")

    record = new_record(
        material_order_id=order_id,
        requested_pickup_at=requested,
        inventory_lot_id=None,
        staging_window_start=None,
        staging_window_end=None,
        safety_briefing_code=None,
        ppe_confirmed=False,
        loaded_cubic_yards=None,
        staged_by_user_id=None,
        status="QUEUED",
    )
    db.insert("will_call_tickets", record)
    return respond(serial.will_call_ticket(record), 201)


@bp.get("/will-call-tickets")
def list_tickets():
    ctx = auth(*TICKET_READ_ROLES)
    order_id = arg("material_order_id")
    lot_id = arg("inventory_lot_id")
    status = arg("status")
    rows = []
    for record in db.will_call_tickets.values():
        if order_id is not None and record["material_order_id"] != order_id:
            continue
        if lot_id is not None and record["inventory_lot_id"] != lot_id:
            continue
        if status is not None and record["status"] != status:
            continue
        rows.append(record)
    rows = contractor_filter(
        ctx, rows,
        lambda r: (db.get("material_orders", r["material_order_id"]) or {}).get(
            "contractor_account_id"))
    return render_list(rows, serial.will_call_ticket)


@bp.get("/will-call-tickets/<will_call_ticket_id>")
def read_ticket(will_call_ticket_id):
    ctx = auth(*TICKET_READ_ROLES)
    record = db.get("will_call_tickets", will_call_ticket_id)
    if record is not None:
        scope_via_order(ctx, db.get("material_orders", record["material_order_id"]))
    require(record, "will_call_tickets")
    return respond(serial.will_call_ticket(record))


# --------------------------------------------------------------------------
# Staging (PRD 3.6): the loader offers a bay window and the yard picks a ticket
# --------------------------------------------------------------------------
@bp.post("/will-call-tickets/stage-next")
def stage_next():
    ctx = auth("YardLoader")
    data = body()
    window_start = req_instant(data, "staging_window_start")
    window_end = req_instant(data, "staging_window_end")

    occupied = 0
    for ticket in db.will_call_tickets.values():
        if ticket["status"] not in BAY_OCCUPYING:
            continue
        start = ticket["staging_window_start"]
        end = ticket["staging_window_end"]
        if start is None or end is None:
            continue
        if start <= window_end and window_start <= end:
            occupied += 1
    if occupied >= calc.WILL_CALL_STAGING_CAPACITY:
        fail("ERR_STAGING_CAPACITY_FULL", "Both staging bays are occupied.")

    candidates = calc.stage_candidates()
    if not candidates:
        fail("ERR_WILL_CALL_QUEUE_EMPTY", "No eligible ticket is waiting.")
    if window_end <= window_start:
        fail("ERR_INVALID_WINDOW",
             "staging_window_end must be after staging_window_start.")

    ticket = candidates[0]
    order = db.get("material_orders", ticket["material_order_id"])
    lot = calc.pinned_lot_for_order(order) if order is not None else None
    ticket["status"] = "STAGED"
    ticket["staging_window_start"] = window_start
    ticket["staging_window_end"] = window_end
    ticket["staged_by_user_id"] = ctx.user_id
    ticket["inventory_lot_id"] = None if lot is None else lot["id"]
    touch(ticket)
    if order is not None:
        calc.evaluate_allocate(order)
    return respond(serial.will_call_ticket(ticket))


# --------------------------------------------------------------------------
# Safety briefing, loading and release
# --------------------------------------------------------------------------
@bp.post("/will-call-tickets/<will_call_ticket_id>/safety-ack")
def safety_ack(will_call_ticket_id):
    auth("YardLoader")
    data = body()
    code = req_str(data, "safety_briefing_code")
    ticket = require(db.get("will_call_tickets", will_call_ticket_id),
                     "will_call_tickets")
    if ticket["status"] != "STAGED":
        fail("ERR_TICKET_NOT_STAGED", "Ticket is %s." % ticket["status"])
    if data.get("ppe_confirmed") is not True:
        fail("ERR_SAFETY_ACK_REQUIRED",
             "PPE must be confirmed before material moves at the bay.")

    ticket["safety_briefing_code"] = code
    ticket["ppe_confirmed"] = True
    ticket["status"] = "LOADING"
    touch(ticket)
    return respond(serial.will_call_ticket(ticket))


@bp.post("/will-call-tickets/<will_call_ticket_id>/load")
def load_ticket(will_call_ticket_id):
    auth("YardLoader")
    data = body()
    loaded = req_num(data, "loaded_cubic_yards", minimum=0)
    pallet_count = opt_int(data, "pallet_count", default=None, minimum=0)
    ticket = require(db.get("will_call_tickets", will_call_ticket_id),
                     "will_call_tickets")
    if ticket["status"] != "LOADING":
        fail("ERR_TICKET_NOT_LOADING", "Ticket is %s." % ticket["status"])
    if ticket["ppe_confirmed"] is not True:
        fail("ERR_SAFETY_ACK_REQUIRED", "The safety briefing has not been recorded.")

    order = db.get("material_orders", ticket["material_order_id"])
    if order is not None and D(loaded) > calc.outstanding_bulk_balance(order):
        fail("ERR_LOAD_EXCEEDS_ORDER_BALANCE",
             "The loaded volume exceeds the order's undelivered balance.")

    ticket["loaded_cubic_yards"] = r2(loaded)
    ticket["status"] = "LOADED"
    touch(ticket)

    if order is not None:
        calc.distribute_delivered_volume(order, r2(loaded))
        lot = db.get("inventory_lots", ticket["inventory_lot_id"]) \
            if ticket["inventory_lot_id"] else None
        if lot is not None:
            calc.recompute_lot(lot)
            calc.maybe_deplete_lot(lot)
        calc.recompute_lots_of_order(order)
        created = calc.create_container_return(order, issued_count=pallet_count)
        account = calc.account_of_order(order)
        if created is not None and account is not None:
            calc.recompute_account(account)
    return respond(serial.will_call_ticket(ticket))


@bp.post("/will-call-tickets/<will_call_ticket_id>/release")
def release_ticket(will_call_ticket_id):
    auth("YardLoader")
    ticket = require(db.get("will_call_tickets", will_call_ticket_id),
                     "will_call_tickets")
    if ticket["status"] != "LOADED":
        fail("ERR_TICKET_NOT_LOADED", "Ticket is %s." % ticket["status"])

    ticket["status"] = "RELEASED"
    touch(ticket)

    order = db.get("material_orders", ticket["material_order_id"])
    if order is not None:
        instant = ticket["staging_window_start"] or db.clock
        calc.finalize_order_money(order, instant, None)
        if order["fulfillment_status"] == "ALLOCATED" and calc.order_fully_delivered(
                order):
            order["fulfillment_status"] = "FULFILLED"
        touch(order)
        account = calc.account_of_order(order)
        if account is not None:
            calc.recompute_account(account)
            calc.evaluate_credit_posture(account)
    return respond(serial.will_call_ticket(ticket))


@bp.post("/will-call-tickets/<will_call_ticket_id>/cancel")
def cancel_ticket(will_call_ticket_id):
    ctx = auth("Contractor", "YardLoader")
    ticket = db.get("will_call_tickets", will_call_ticket_id)
    if ticket is not None:
        scope_via_order(ctx, db.get("material_orders", ticket["material_order_id"]))
    require(ticket, "will_call_tickets")
    previous = ticket["status"]
    if previous not in ("QUEUED", "STAGED"):
        fail("ERR_TICKET_NOT_CANCELLABLE", "Ticket is %s." % previous)

    ticket["status"] = "CANCELLED"
    touch(ticket)
    if previous == "STAGED":
        order = db.get("material_orders", ticket["material_order_id"])
        if order is not None:
            calc.evaluate_revert(order)
            calc.recompute_lots_of_order(order)
    return respond(serial.will_call_ticket(ticket))
