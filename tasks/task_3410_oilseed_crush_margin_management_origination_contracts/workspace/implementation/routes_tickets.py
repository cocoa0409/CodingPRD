"""Delivery tickets (create/read/list/apply) and storage positions (read/list)."""
from decimal import Decimal

from flask import Blueprint, request

from auth import require_roles
from calc import (delivery_accrual, grade_ticket, provisional_estimate)
from envelope import success_list, success_obj
from errors import fail
from store import db, get_clock, new_id, stamp_new, to_jsonable, touch
from validate import body_dict, paginate, req_decimal, sort_created

bp = Blueprint("tickets", __name__)


@bp.post("/api/delivery-tickets")
def create_ticket():
    require_roles("OriginationMerchandiser")
    body = body_dict()
    # Body FK (priority 4).
    contract = None
    if body.get("contract_id") is not None:
        contract = db["contracts"].get(body["contract_id"])
        if contract is None:
            fail("ERR_CONTRACT_NOT_FOUND", "contract_id does not resolve")
    if contract is None:
        fail("ERR_INVALID_REQUEST", "contract_id is required")
    # State (priority 6): contract fulfillment must be OPEN or DELIVERING.
    if contract["fulfillment_status"] not in ("OPEN", "DELIVERING"):
        fail("ERR_INVALID_STATE",
             "contract fulfillment does not accept new delivery tickets")
    # Shape (priority 9).
    gross = req_decimal(body, "gross_bushels")
    if gross <= 0:
        fail("ERR_INVALID_REQUEST", "gross_bushels must be > 0")
    moisture = req_decimal(body, "moisture_pct")
    damage = req_decimal(body, "damage_pct")
    fm = req_decimal(body, "foreign_material_pct")
    if moisture < 0 or damage < 0 or fm < 0:
        fail("ERR_INVALID_REQUEST", "quality percentages must be >= 0")
    # Capacity (priority 10): the elevator receiving gate.
    elevator = db["elevators"][contract["elevator_id"]]
    if not elevator["receiving_open"]:
        fail("ERR_ELEVATOR_AT_CAPACITY", "elevator receiving gate is closed")
    rec = {
        "id": new_id(),
        "contract_id": contract["id"],
        "elevator_id": contract["elevator_id"],
        "program_id": contract["program_id"],
        "gross_bushels": gross,
        "moisture_pct": moisture,
        "damage_pct": damage,
        "foreign_material_pct": fm,
        "schedule_id": None,
        "shrink_bushels": None,
        "net_bushels": None,
        "discount_cents_per_bushel": None,
        "premium_cents_per_bushel": None,
        "applied_date": None,
        "status": "RECEIVED",
    }
    stamp_new(rec)
    db["tickets"][rec["id"]] = rec
    return success_obj(to_jsonable(rec), 201)


@bp.get("/api/delivery-tickets/<tid>")
def get_ticket(tid):
    require_roles("PlatformAdmin", "OriginationMerchandiser")
    rec = db["tickets"].get(tid)
    if rec is None:
        fail("ERR_TICKET_NOT_FOUND", "delivery ticket not found")
    return success_obj(to_jsonable(rec))


@bp.get("/api/delivery-tickets")
def list_tickets():
    require_roles("PlatformAdmin", "OriginationMerchandiser")
    items = sort_created(list(db["tickets"].values()))
    contract_id = request.args.get("contract_id")
    elevator_id = request.args.get("elevator_id")
    schedule_id = request.args.get("schedule_id")
    program_id = request.args.get("program_id")
    if contract_id is not None:
        items = [t for t in items if t["contract_id"] == contract_id]
    if elevator_id is not None:
        items = [t for t in items if t["elevator_id"] == elevator_id]
    if schedule_id is not None:
        items = [t for t in items if t["schedule_id"] == schedule_id]
    if program_id is not None:
        items = [t for t in items if t["program_id"] == program_id]
    page, limit, offset, total = paginate(items)
    return success_list([to_jsonable(t) for t in page], limit, offset, total)


@bp.post("/api/delivery-tickets/<tid>/apply")
def apply_ticket(tid):
    require_roles("OriginationMerchandiser")
    t = db["tickets"].get(tid)
    if t is None:
        fail("ERR_TICKET_NOT_FOUND", "delivery ticket not found")
    # State (priority 6): ticket RECEIVED; contract fulfillment OPEN|DELIVERING.
    if t["status"] != "RECEIVED":
        fail("ERR_INVALID_STATE", "ticket is not in RECEIVED")
    contract = db["contracts"][t["contract_id"]]
    if contract["fulfillment_status"] not in ("OPEN", "DELIVERING"):
        fail("ERR_INVALID_STATE",
             "contract fulfillment does not accept applies")
    elevator = db["elevators"][t["elevator_id"]]
    schedule = db["schedules"][elevator["active_discount_schedule_id"]]
    program = db["programs"].get(t["program_id"]) if t["program_id"] else None
    # Grading always runs, on both branches.
    shrink, net, discount, premium = grade_ticket(t, schedule, program)
    clock = get_clock()
    if Decimal(t["moisture_pct"]) > Decimal(schedule["reject_moisture_pct"]):
        # REJECTED: grading recorded for the record; no other mutations.
        t["schedule_id"] = schedule["id"]
        t["shrink_bushels"] = shrink
        t["net_bushels"] = net
        t["discount_cents_per_bushel"] = discount
        t["premium_cents_per_bushel"] = premium
        t["status"] = "REJECTED"
        touch(t)
        return success_obj(to_jsonable(t))
    # Quantity guards, in this order: over-delivery (9), then headroom (10).
    if contract["delivered_bushels"] + net > contract["quantity_bushels"]:
        fail("ERR_OVER_DELIVERY",
             "apply would push delivered bushels above the contracted quantity")
    if elevator["stored_bushels"] + net > elevator["storage_capacity_bushels"]:
        fail("ERR_ELEVATOR_AT_CAPACITY",
             "apply would push stored bushels above storage capacity")
    # Commit the ticket.
    t["schedule_id"] = schedule["id"]
    t["shrink_bushels"] = shrink
    t["net_bushels"] = net
    t["discount_cents_per_bushel"] = discount
    t["premium_cents_per_bushel"] = premium
    t["applied_date"] = clock
    t["status"] = "APPLIED"
    touch(t)
    # HOP 1: contract delivered pool (+ DEFERRED unpriced pool / accrual).
    delivery_accrual(contract, net, clock)
    contract["delivered_bushels"] = Decimal(contract["delivered_bushels"]) + net
    # HOP 1b: fulfillment auto-transition.
    if contract["delivered_bushels"] == contract["quantity_bushels"]:
        contract["fulfillment_status"] = "DELIVERED"
    else:
        contract["fulfillment_status"] = "DELIVERING"
    # HOP 2: storage position at the elevator.
    pos = {
        "id": new_id(),
        "elevator_id": t["elevator_id"],
        "source_ticket_id": t["id"],
        "program_id": t["program_id"],
        "bushels_initial": net,
        "current_bushels": net,
        "status": "OPEN",
    }
    stamp_new(pos)
    db["positions"][pos["id"]] = pos
    # HOP 3/4: elevator counters + receiving gate re-derivation.
    elevator["stored_bushels"] = Decimal(elevator["stored_bushels"]) + net
    if t["program_id"]:
        elevator["certified_stored_bushels"] = (
            Decimal(elevator["certified_stored_bushels"]) + net)
    elevator["receiving_open"] = (
        elevator["stored_bushels"] < elevator["storage_capacity_bushels"])
    touch(elevator)
    # Provisional settlement recompute, then contract mutation stamp.
    contract["estimated_settlement_cents"] = provisional_estimate(contract)
    touch(contract)
    return success_obj(to_jsonable(t))


# ---------------------------------------------------------------------------
# Storage positions (read-only)
# ---------------------------------------------------------------------------

@bp.get("/api/storage-positions/<pid>")
def get_position(pid):
    require_roles("PlatformAdmin", "OriginationMerchandiser", "LogisticsCoordinator")
    rec = db["positions"].get(pid)
    if rec is None:
        fail("ERR_POSITION_NOT_FOUND", "storage position not found")
    return success_obj(to_jsonable(rec))


@bp.get("/api/storage-positions")
def list_positions():
    require_roles("PlatformAdmin", "OriginationMerchandiser", "LogisticsCoordinator")
    items = sort_created(list(db["positions"].values()))
    elevator_id = request.args.get("elevator_id")
    source_ticket_id = request.args.get("source_ticket_id")
    program_id = request.args.get("program_id")
    if elevator_id is not None:
        items = [p for p in items if p["elevator_id"] == elevator_id]
    if source_ticket_id is not None:
        items = [p for p in items if p["source_ticket_id"] == source_ticket_id]
    if program_id is not None:
        items = [p for p in items if p["program_id"] == program_id]
    page, limit, offset, total = paginate(items)
    return success_list([to_jsonable(p) for p in page], limit, offset, total)
