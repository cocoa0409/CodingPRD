"""Shipping legs: creation under cadence, dispatch, delivery, exception, receipt."""
from flask import Blueprint

import calc
import core
import serialize
import services
from core import (DB, SHIPMENT_DIRECTIONS, SHIPMENT_STATES, SHIPMENT_TERMINAL,
                  SHIPMENT_EXCEPTION_CAP, date_add, fail, now_iso, ok, ok_list,
                  today_str)
from guards import (begin, body_json, enum_query, fk, lookup, pagination, paginate,
                    require_owner, sort_rows, str_query, tech_active, validate)

bp = Blueprint("shipments", __name__)

READ_ROLES = ["Member", "WarehouseTech", "InventoryPlanner", "PlatformAdmin"]
ACT_ROLES = ["WarehouseTech", "PlatformAdmin"]


def _shipments_of_reservation(reservation_id):
    return [s for s in DB["shipments"].values()
            if s["reservation_id"] == reservation_id]


# ---------------------------------------------------------------------------
# Create
# ---------------------------------------------------------------------------
@bp.post("/shipments")
def create_shipment():
    ctx = begin(ACT_ROLES)
    body = body_json()
    res = fk(body, "reservation_id", "reservations", "ERR_RESERVATION_NOT_FOUND")
    data = validate(body, [
        {"name": "reservation_id", "kind": "str", "required": True},
        {"name": "direction", "kind": "enum", "required": True,
         "values": SHIPMENT_DIRECTIONS},
        {"name": "planned_ship_date", "kind": "date", "required": True},
        {"name": "carrier_reference", "kind": "str", "default": None},
    ])
    member = DB["members"][res["member_id"]]
    tech_active(ctx)
    # Rank 14
    if member["status"] != "ACTIVE":
        fail("ERR_MEMBER_NOT_ACTIVE", "Membership is not ACTIVE")
    direction = data["direction"]
    # Rank 39
    for s in _shipments_of_reservation(res["id"]):
        if s["direction"] == "INBOUND":
            fail("ERR_SHIPMENT_ALREADY_EXISTS",
                 "An inbound leg already exists for this reservation")
        if (direction == "OUTBOUND" and s["direction"] == "OUTBOUND"
                and s["state"] != "EXCEPTION"):
            fail("ERR_SHIPMENT_ALREADY_EXISTS",
                 "An outbound leg already exists for this reservation")
    # Rank 43 — shipping cadence, closed window on both endpoints
    if direction == "OUTBOUND":
        plan = DB["membership_plans"][member["membership_plan_id"]]
        cadence = plan["shipping_cadence_days"]
        planned = data["planned_ship_date"]
        for s in DB["shipments"].values():
            if s["member_id"] != member["id"]:
                continue
            if s["direction"] != "OUTBOUND" or s["state"] == "EXCEPTION":
                continue
            lo = s["planned_ship_date"]
            hi = date_add(lo, cadence)
            if lo <= planned <= hi:
                fail("ERR_SHIPPING_CADENCE_COLLISION",
                     "planned_ship_date falls inside the plan's shipping cadence "
                     "window of another outbound leg")

    row = services.base_row("shipments")
    row.update({
        "member_id": member["id"],
        "reservation_id": res["id"],
        "direction": direction,
        "planned_ship_date": data["planned_ship_date"],
        "state": "CREATED",
        "carrier_reference": data.get("carrier_reference"),
        "dispatched_at": None,
        "delivered_at": None,
        "received_at": None,
        "exception_count": 0,
        "exception_reason": None,
    })
    DB["shipments"][row["id"]] = row
    return ok(serialize.shipment_out(row), 201)


# ---------------------------------------------------------------------------
# Reads
# ---------------------------------------------------------------------------
@bp.get("/shipments/<shipment_id>")
def get_shipment(shipment_id):
    ctx = begin(READ_ROLES)
    row = lookup("shipments", shipment_id, "ERR_SHIPMENT_NOT_FOUND")
    require_owner(ctx, row["member_id"])
    return ok(serialize.shipment_out(row))


@bp.get("/shipments")
def list_shipments():
    ctx = begin(READ_ROLES)
    direction = enum_query("direction", SHIPMENT_DIRECTIONS)
    state = enum_query("state", SHIPMENT_STATES)
    member_id = str_query("member_id")
    reservation_id = str_query("reservation_id")
    if ctx.role == "Member":
        if member_id is not None and member_id != ctx.user_id:
            fail("ERR_NOT_RESOURCE_OWNER", "Members may only read their own rows")
        member_id = ctx.user_id
    limit, offset = pagination()
    rows = []
    for s in DB["shipments"].values():
        if member_id is not None and s["member_id"] != member_id:
            continue
        if reservation_id is not None and s["reservation_id"] != reservation_id:
            continue
        if direction is not None and s["direction"] != direction:
            continue
        if state is not None and s["state"] != state:
            continue
        rows.append(s)
    rows = sort_rows(rows)
    items, total = paginate(rows, limit, offset, serialize.shipment_out)
    return ok_list(items, limit, offset, total)


# ---------------------------------------------------------------------------
# Dispatch
# ---------------------------------------------------------------------------
@bp.post("/shipments/<shipment_id>/dispatch")
def dispatch_shipment(shipment_id):
    ctx = begin(ACT_ROLES)
    leg = lookup("shipments", shipment_id, "ERR_SHIPMENT_NOT_FOUND")
    body = body_json()
    data = validate(body, [
        {"name": "carrier_reference", "kind": "str", "default": None},
    ])
    res = DB["reservations"].get(leg["reservation_id"])
    member = DB["members"].get(leg["member_id"])
    # Rank 14 — OUTBOUND legs only
    if (leg["direction"] == "OUTBOUND" and member is not None
            and member["status"] != "ACTIVE"):
        fail("ERR_MEMBER_NOT_ACTIVE", "Membership is not ACTIVE")
    # Rank 16 / 15
    if leg["state"] in SHIPMENT_TERMINAL:
        fail("ERR_RESOURCE_TERMINAL", "Shipment leg is %s" % leg["state"])
    if leg["state"] not in ("CREATED", "EXCEPTION"):
        fail("ERR_INVALID_STATE_TRANSITION",
             "Dispatch is not declared from %s" % leg["state"])
    tech_active(ctx)
    # Rank 38 — recovery path only
    if (leg["state"] == "EXCEPTION"
            and leg["exception_count"] >= SHIPMENT_EXCEPTION_CAP):
        fail("ERR_SHIPMENT_EXCEPTION_CAP_REACHED",
             "This leg has absorbed its maximum number of carrier exceptions")
    # Linked reservation precondition — evaluated after rank 38.  It guards the
    # first dispatch out of CREATED, which is the hop that drives the reservation
    # forward.  On the EXCEPTION recovery path the reservation has already been
    # advanced by the dispatch that preceded the exception, so re-imposing the
    # precondition there would make the declared IN_TRANSIT -> EXCEPTION ->
    # IN_TRANSIT cycle, and the SHIPPED -> WAITLISTED loss branch it leads to,
    # unreachable.
    if leg["state"] == "CREATED":
        required = ("MATCHED" if leg["direction"] == "OUTBOUND"
                    else "RETURN_INITIATED")
        if res is None or res["state"] != required:
            fail("ERR_INVALID_STATE_TRANSITION",
                 "The linked reservation must be %s to dispatch this leg"
                 % required)

    leg["state"] = "IN_TRANSIT"
    leg["dispatched_at"] = now_iso()
    if data.get("carrier_reference") is not None:
        leg["carrier_reference"] = data["carrier_reference"]
    services.touch(leg)
    if leg["direction"] == "OUTBOUND" and res is not None:
        # MATCHED -> SHIPPED is the declared cascade edge, so a re-dispatch of a
        # reservation already SHIPPED leaves it, and its shipped_at, alone.
        if res["state"] == "MATCHED":
            res["state"] = "SHIPPED"
            res["shipped_at"] = now_iso()
            services.touch(res)
        unit = DB["rental_units"].get(res["allocated_unit_id"])
        if unit is not None and unit["availability_state"] == "RESERVED":
            unit["availability_state"] = "OUT"
            services.touch(unit)
    return ok(serialize.shipment_out(leg))


# ---------------------------------------------------------------------------
# Delivery
# ---------------------------------------------------------------------------
@bp.post("/shipments/<shipment_id>/delivery")
def deliver_shipment(shipment_id):
    ctx = begin(ACT_ROLES)
    leg = lookup("shipments", shipment_id, "ERR_SHIPMENT_NOT_FOUND")
    body_json()
    if leg["state"] in SHIPMENT_TERMINAL:
        fail("ERR_RESOURCE_TERMINAL", "Shipment leg is %s" % leg["state"])
    if leg["state"] != "IN_TRANSIT" or leg["direction"] != "OUTBOUND":
        fail("ERR_INVALID_STATE_TRANSITION",
             "Delivery is only declared on an IN_TRANSIT OUTBOUND leg")
    tech_active(ctx)
    stamp = now_iso()
    leg["state"] = "DELIVERED"
    leg["delivered_at"] = stamp
    services.touch(leg)
    res = DB["reservations"].get(leg["reservation_id"])
    if res is not None and res["state"] == "SHIPPED":
        res["state"] = "IN_POSSESSION"
        res["delivered_at"] = stamp
        services.touch(res)
        member = DB["members"].get(res["member_id"])
        if member is not None:
            services.touch(member)
    return ok(serialize.shipment_out(leg))


# ---------------------------------------------------------------------------
# Exception
# ---------------------------------------------------------------------------
@bp.post("/shipments/<shipment_id>/exception")
def exception_shipment(shipment_id):
    ctx = begin(ACT_ROLES)
    leg = lookup("shipments", shipment_id, "ERR_SHIPMENT_NOT_FOUND")
    body = body_json()
    data = validate(body, [
        {"name": "exception_reason", "kind": "str", "required": True, "minlen": 1},
    ])
    if leg["state"] in SHIPMENT_TERMINAL:
        fail("ERR_RESOURCE_TERMINAL", "Shipment leg is %s" % leg["state"])
    if leg["state"] != "IN_TRANSIT":
        fail("ERR_INVALID_STATE_TRANSITION",
             "An exception is not declared from %s" % leg["state"])
    tech_active(ctx)
    # Rank 38
    if leg["exception_count"] >= SHIPMENT_EXCEPTION_CAP:
        fail("ERR_SHIPMENT_EXCEPTION_CAP_REACHED",
             "This leg has absorbed its maximum number of carrier exceptions")
    leg["state"] = "EXCEPTION"
    leg["exception_count"] += 1
    leg["exception_reason"] = data["exception_reason"]
    services.touch(leg)
    if leg["exception_count"] >= SHIPMENT_EXCEPTION_CAP:
        services.shipment_loss(leg)
    return ok(serialize.shipment_out(leg))


# ---------------------------------------------------------------------------
# Receipt
# ---------------------------------------------------------------------------
@bp.post("/shipments/<shipment_id>/receipt")
def receive_shipment(shipment_id):
    ctx = begin(["WarehouseTech"])
    leg = lookup("shipments", shipment_id, "ERR_SHIPMENT_NOT_FOUND")
    body_json()
    if leg["state"] in SHIPMENT_TERMINAL:
        fail("ERR_RESOURCE_TERMINAL", "Shipment leg is %s" % leg["state"])
    if leg["state"] != "IN_TRANSIT" or leg["direction"] != "INBOUND":
        fail("ERR_INVALID_STATE_TRANSITION",
             "Receipt is only declared on an IN_TRANSIT INBOUND leg")
    tech_active(ctx)
    leg["state"] = "RECEIVED"
    leg["received_at"] = now_iso()
    services.touch(leg)
    services.receipt_cascade(leg)
    return ok(serialize.shipment_out(leg))
