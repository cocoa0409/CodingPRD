"""TimedEntrySlot — half-open windows, the aggregate admission load, dynamic
pricing and the administrative moves (PRD §3.5)."""

from datetime import datetime, time, timezone

from flask import Blueprint, request

from db import db, new_row, now, now_iso, public, touch
from errors import ApiError
from middleware import EP, GSA, GUEST, SO, roles
from response import list_response, object_response
from services import calc, derive
from services.validate import Body, fail, query_enum, query_int

bp = Blueprint("slots", __name__)

PRICING_TIERS = ("OFFPEAK", "STANDARD", "PEAK", "PREMIUM")
ORDER_TYPES = ("SINGLE", "GROUP", "PRIVATE_BUYOUT")
LOYALTY_TIERS = ("VISITOR", "MEMBER", "PATRON")
SLOT_DECISIONS = ("SUSPEND", "RESUME", "CANCEL", "CLOSE_OUT")
SLOT_RUN_STATUSES = ("PLANNED", "OPEN", "EXTENDED")


def _run_bounds(run_row):
    lower = datetime.combine(run_row["_open_date"], time(0, 0, 0),
                             tzinfo=timezone.utc)
    upper = datetime.combine(run_row["_close_date"], time(23, 59, 59, 999000),
                             tzinfo=timezone.utc)
    return lower, upper


def _check_capacity_fit(run_row, base_capacity):
    """The single-window ceiling. PRD §3.5 evaluates it before the aggregate
    admission load, both on creation and on release."""
    capacity = derive.refresh_effective_capacity(run_row)
    cap = run_row["effective_capacity_cap"] or 0
    if base_capacity > capacity or (cap > 0 and base_capacity > cap):
        raise ApiError("ERR_SLOT_CAPACITY_ABOVE_RUN")
    return capacity


@bp.post("/timed-entry-slots")
@roles(EP)
def create_slot():
    body = Body(require_body=True)
    run_id = body.reference("run_id")
    start, start_raw = body.instant_field("slot_start_utc")
    end, end_raw = body.instant_field("slot_end_utc")
    tier = body.enum("pricing_tier", PRICING_TIERS, required=False,
                     default="STANDARD")
    base_capacity = body.integer("base_capacity", minimum=1)
    wheelchair_positions = body.integer("wheelchair_positions", required=False,
                                        default=4, minimum=0)
    if wheelchair_positions > base_capacity:
        fail("wheelchair_positions may not exceed base_capacity.")

    # rung 5 — body foreign key
    run_row = derive.run(run_id)
    # rung 8 — the run must still admit new windows
    if run_row["run_status"] not in SLOT_RUN_STATUSES:
        raise ApiError("ERR_RUN_INVALID_STATE")

    # rung 11 — interval and calendar bounds
    if end <= start:
        raise ApiError("ERR_INVALID_WINDOW")
    lower, upper = _run_bounds(run_row)
    if start < lower or end > upper:
        raise ApiError("ERR_SLOT_OUTSIDE_RUN_WINDOW")

    # rung 15 then rung 13 — the single window first, then the aggregate load
    capacity = _check_capacity_fit(run_row, base_capacity)
    derive.check_slot_overlap_load(run_row, start, end, base_capacity, capacity)

    row = new_row()
    row.update({
        "run_id": run_row["id"],
        "slot_start_utc": start_raw,
        "slot_end_utc": end_raw,
        "pricing_tier": tier,
        "base_capacity": base_capacity,
        "released_capacity": 0,
        "held_capacity": 0,
        "sold_capacity": 0,
        "available_capacity": 0,
        "wheelchair_positions": wheelchair_positions,
        "wheelchair_sold": 0,
        "buyout_order_id": None,
        "released_at": None,
        "status": "DRAFT",
        "_start": start,
        "_end": end,
    })
    db.slots[row["id"]] = row
    return object_response(public(row), 201)


@bp.get("/timed-entry-slots/<slot_id>")
@roles(EP, GSA, SO, GUEST)
def read_slot(slot_id):
    return object_response(public(derive.slot(slot_id)))


@bp.get("/timed-entry-slots")
@roles(EP, GSA, SO, GUEST)
def list_slots():
    rows = list(db.slots.values())
    for field in ("run_id", "buyout_order_id", "status"):
        value = request.args.get(field)
        if value:
            rows = [r for r in rows if r[field] == value]
    return list_response(rows)


@bp.post("/timed-entry-slots/<slot_id>/release")
@roles(EP)
def release_slot(slot_id):
    slot_row = derive.slot(slot_id)
    run_row = derive.run(slot_row["run_id"])

    # rung 8 — own state
    if slot_row["status"] != "DRAFT":
        raise ApiError("ERR_SLOT_INVALID_STATE")
    # rung 9 — cross-entity state
    if run_row["run_status"] not in SLOT_RUN_STATUSES:
        raise ApiError("ERR_RUN_INVALID_STATE")
    if run_row["clearance_status"] == "SUSPENDED":
        raise ApiError("ERR_RUN_SUSPENDED")

    # the world has moved since creation: both ceilings are re-checked
    capacity = _check_capacity_fit(run_row, slot_row["base_capacity"])
    derive.check_slot_overlap_load(run_row, slot_row["_start"], slot_row["_end"],
                                   slot_row["base_capacity"], capacity,
                                   exclude_id=slot_row["id"])

    slot_row["status"] = "OPEN"
    slot_row["released_capacity"] = slot_row["base_capacity"]
    slot_row["released_at"] = now_iso()
    derive.recompute_available(slot_row)
    touch(slot_row)
    return object_response(public(slot_row))


@bp.post("/timed-entry-slots/<slot_id>/status-decisions")
@roles(EP, SO)
def slot_decision(slot_id):
    slot_row = derive.slot(slot_id)
    body = Body(require_body=True)
    decision = body.enum("decision", SLOT_DECISIONS)
    body.string("note", required=False, default=None, min_len=1, max_len=500)
    run_row = derive.run(slot_row["run_id"])

    if decision == "SUSPEND":
        if slot_row["status"] not in ("OPEN", "SOLD_OUT"):
            raise ApiError("ERR_SLOT_INVALID_STATE")
        # the seats stay sold; they are simply not admissible
        slot_row["status"] = "SUSPENDED"

    elif decision == "RESUME":
        if slot_row["status"] != "SUSPENDED":
            raise ApiError("ERR_SLOT_INVALID_STATE")
        if run_row["clearance_status"] == "SUSPENDED":
            raise ApiError("ERR_RUN_SUSPENDED")
        _check_capacity_fit(run_row, slot_row["base_capacity"])
        derive.recompute_available(slot_row)
        slot_row["status"] = ("SOLD_OUT" if slot_row["available_capacity"] == 0
                              else "OPEN")

    elif decision == "CANCEL":
        if slot_row["status"] not in ("DRAFT", "OPEN"):
            raise ApiError("ERR_SLOT_INVALID_STATE")
        # rung 15 — a window carrying money cannot simply be deleted
        if slot_row["sold_capacity"] > 0 or slot_row["held_capacity"] > 0:
            raise ApiError("ERR_SLOT_HAS_SALES")
        slot_row["status"] = "CANCELLED"
        slot_row["released_capacity"] = 0
        slot_row["available_capacity"] = 0

    else:  # CLOSE_OUT
        if slot_row["status"] not in ("OPEN", "SOLD_OUT", "SUSPENDED"):
            raise ApiError("ERR_SLOT_INVALID_STATE")
        slot_row["status"] = "CLOSED_OUT"
        slot_row["held_capacity"] = 0
        slot_row["available_capacity"] = 0

    touch(slot_row)
    return object_response(public(slot_row))


@bp.get("/timed-entry-slots/<slot_id>/price-quote")
@roles(EP, GSA, GUEST)
def price_quote(slot_id):
    slot_row = derive.slot(slot_id)
    run_row = derive.run(slot_row["run_id"])
    order_type = query_enum("order_type", ORDER_TYPES, default="SINGLE")
    loyalty_tier = query_enum("loyalty_tier", LOYALTY_TIERS, default="VISITOR")
    party_size = query_int("party_size", default=1, minimum=1)
    wheelchair = query_int("wheelchair_party_count", default=0, minimum=0)
    if wheelchair > party_size:
        fail("wheelchair_party_count may not exceed party_size.")

    lead_days = calc.lead_days_between(slot_row["_start"], now())
    unit_price = calc.slot_unit_price_cents(run_row["base_ticket_price_cents"],
                                           slot_row["pricing_tier"], lead_days)
    figures = calc.order_money(unit_price, order_type, loyalty_tier, party_size,
                               wheelchair)
    payload = {"slot_id": slot_row["id"],
               "pricing_tier": slot_row["pricing_tier"],
               "lead_days": lead_days}
    payload.update(figures)
    return object_response(payload)
