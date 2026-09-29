"""TicketOrder — frozen money, buyout mirror pair, attendance and the refund
ladder (PRD §3.6)."""

from datetime import timedelta

from flask import Blueprint, request

from db import db, new_row, now, now_iso, public, touch
from errors import ApiError
from middleware import EP, GSA, GUEST, LM, caller_id, caller_role, roles
from response import list_response, object_response
from services import calc, derive
from services.validate import Body, fail

bp = Blueprint("orders", __name__)

ORDER_TYPES = ("SINGLE", "GROUP", "PRIVATE_BUYOUT")
ACCOMMODATIONS = ("QUIET_ROUTE", "WHEELCHAIR", "ASL_INTERPRETER", "LOW_STIM_HOURS")
ATTENDANCE_DECISIONS = ("CHECK_IN", "NO_SHOW")


def _grace_end(slot_row):
    return slot_row["_end"] + timedelta(minutes=calc.CHECKIN_GRACE_MIN)


@bp.post("/ticket-orders")
@roles(GUEST, GSA)
def place_order():
    body = Body(require_body=True)
    slot_id = body.reference("slot_id")
    guest_id = body.reference("guest_account_id")
    order_type = body.enum("order_type", ORDER_TYPES, required=False,
                           default="SINGLE")
    party_size = body.integer("party_size", minimum=1)
    wheelchair = body.integer("wheelchair_party_count", required=False, default=0,
                              minimum=0)
    accommodations = body.enum_array("sensory_accommodations", ACCOMMODATIONS,
                                     required=False, default=[])
    merch = body.integer("merch_amount_cents", required=False, default=0,
                         minimum=0, maximum=500000)
    if wheelchair > party_size:
        fail("wheelchair_party_count may not exceed party_size.")

    # rung 5 — body foreign keys
    slot_row = derive.slot(slot_id)
    guest_row = derive.guest(guest_id)
    run_row = derive.run(slot_row["run_id"])

    # rung 8/9 — the window must be on sale and the account must be usable
    if slot_row["status"] != "OPEN":
        raise ApiError("ERR_SLOT_INVALID_STATE")
    if guest_row["status"] != "ACTIVE":
        raise ApiError("ERR_GUEST_RESTRICTED")
    # rung 10 — a Guest may act only on its own account
    if caller_role() == GUEST and guest_row["id"] != caller_id():
        raise ApiError("ERR_GUEST_OWNERSHIP_MISMATCH")
    # rung 14 — accessibility promises about the physical run
    derive.check_accommodations(run_row, slot_row, accommodations, wheelchair)
    # rung 15 — party shape, then the seats
    if order_type == "PRIVATE_BUYOUT":
        if party_size != slot_row["base_capacity"]:
            raise ApiError("ERR_BUYOUT_PARTY_MISMATCH")
    else:
        if party_size > run_row["max_group_size"]:
            raise ApiError("ERR_PARTY_SIZE_ABOVE_GROUP_MAX")
        if order_type == "SINGLE" and party_size > calc.SINGLE_MAX_PARTY:
            raise ApiError("ERR_PARTY_SIZE_ABOVE_GROUP_MAX")
    if party_size > slot_row["available_capacity"]:
        raise ApiError("ERR_SLOT_CAPACITY_EXCEEDED")

    lead_days = calc.lead_days_between(slot_row["_start"], now())
    unit_price = calc.slot_unit_price_cents(run_row["base_ticket_price_cents"],
                                            slot_row["pricing_tier"], lead_days)
    figures = calc.order_money(unit_price, order_type, guest_row["loyalty_tier"],
                               party_size, wheelchair)

    row = new_row()
    row.update({
        "slot_id": slot_row["id"],
        "run_id": run_row["id"],
        "guest_account_id": guest_row["id"],
        "order_type": order_type,
        "party_size": party_size,
        "wheelchair_party_count": wheelchair,
        "sensory_accommodations": accommodations,
        "merch_amount_cents": merch,
        "net_collected_cents": 0,
        "refunded_cents": 0,
        "credit_issued_cents": 0,
        "refund_pct": 0.00,
        "checked_in_at": None,
        "refund_settled_at": None,
        "status": "PENDING",
    })
    row.update(figures)
    db.orders[row["id"]] = row

    # the seats are taken as a hold
    if order_type == "PRIVATE_BUYOUT":
        slot_row["held_capacity"] = slot_row["released_capacity"]
        slot_row["buyout_order_id"] = row["id"]
        slot_row["status"] = "HELD_FOR_BUYOUT"
    else:
        slot_row["held_capacity"] += party_size
    derive.recompute_available(slot_row)
    touch(slot_row)
    return object_response(public(row), 201)


@bp.get("/ticket-orders/<order_id>")
@roles(GSA, EP, LM, GUEST)
def read_order(order_id):
    return object_response(public(derive.order(order_id)))


@bp.get("/ticket-orders")
@roles(GSA, EP, LM)
def list_orders():
    rows = list(db.orders.values())
    for field in ("run_id", "slot_id", "guest_account_id", "status"):
        value = request.args.get(field)
        if value:
            rows = [r for r in rows if r[field] == value]
    return list_response(rows)


@bp.post("/ticket-orders/<order_id>/confirm")
@roles(GSA)
def confirm_order(order_id):
    order_row = derive.order(order_id)
    slot_row = derive.slot(order_row["slot_id"])
    run_row = derive.run(order_row["run_id"])
    guest_row = derive.guest(order_row["guest_account_id"])

    # rung 8 — own state
    if order_row["status"] != "PENDING":
        raise ApiError("ERR_ORDER_INVALID_STATE")
    # rung 9 — the window must still be sellable, and this order's hold on it
    # must still be the one recorded
    buyout = (slot_row["status"] == "HELD_FOR_BUYOUT"
              and slot_row["buyout_order_id"] == order_row["id"])
    if slot_row["status"] != "OPEN" and not buyout:
        raise ApiError("ERR_SLOT_INVALID_STATE")
    if run_row["clearance_status"] != "CLEARED":
        raise ApiError("ERR_RUN_NOT_CLEARED")
    if guest_row["status"] != "ACTIVE":
        raise ApiError("ERR_GUEST_RESTRICTED")
    # rung 12 — the window must not have started
    if now() >= slot_row["_start"]:
        raise ApiError("ERR_SLOT_INVALID_STATE")
    # rung 14 — the chairs must still be there. The order's own hold already
    # carries its wheelchair party, so it is measured against wheelchair_sold.
    derive.check_accommodations(run_row, slot_row,
                               order_row["sensory_accommodations"],
                               order_row["wheelchair_party_count"])
    # rung 15 — the seats this order holds must still fit the window. The hold
    # taken at creation is this order's own, so it is not counted against it;
    # PRD §3.6 read literally would make the OPEN -> SOLD_OUT transition of the
    # slot state machine unreachable.
    party = order_row["party_size"]
    if slot_row["released_capacity"] - slot_row["sold_capacity"] < party:
        raise ApiError("ERR_SLOT_CAPACITY_EXCEEDED")

    order_row["status"] = "CONFIRMED"
    order_row["net_collected_cents"] = order_row["net_amount_cents"]
    touch(order_row)

    slot_row["held_capacity"] = max(0, slot_row["held_capacity"] - party)
    slot_row["sold_capacity"] += party
    slot_row["wheelchair_sold"] += order_row["wheelchair_party_count"]
    derive.recompute_available(slot_row)
    if slot_row["available_capacity"] == 0:
        slot_row["status"] = "SOLD_OUT"
    touch(slot_row)
    return object_response(public(order_row))


@bp.post("/ticket-orders/<order_id>/attendance")
@roles(GSA)
def record_attendance(order_id):
    order_row = derive.order(order_id)
    body = Body(require_body=True)
    decision = body.enum("decision", ATTENDANCE_DECISIONS)
    body.string("note", required=False, default=None, min_len=1, max_len=500)
    slot_row = derive.slot(order_row["slot_id"])
    run_row = derive.run(order_row["run_id"])
    guest_row = derive.guest(order_row["guest_account_id"])

    # rung 8 — own state
    if order_row["status"] != "CONFIRMED":
        raise ApiError("ERR_ORDER_INVALID_STATE")
    upper = _grace_end(slot_row)
    instant = now()

    if decision == "CHECK_IN":
        # rung 9 — a suspended run admits nobody
        if run_row["clearance_status"] == "SUSPENDED":
            raise ApiError("ERR_RUN_SUSPENDED")
        # rung 12 — both bounds inclusive
        if instant < slot_row["_start"] or instant > upper:
            raise ApiError("ERR_CHECKIN_WINDOW_CLOSED")
        order_row["status"] = "CHECKED_IN"
        order_row["checked_in_at"] = now_iso()
        touch(order_row)
        guest_row["visit_count"] += 1
        touch(guest_row)
    else:
        # rung 12 — a no-show is only knowable once the grace has run out
        if instant <= upper:
            raise ApiError("ERR_NO_SHOW_TOO_EARLY")
        order_row["status"] = "NO_SHOW"
        touch(order_row)
        guest_row["no_show_strikes"] += 1
        # cumulative and inclusive: the third strike restricts
        if (guest_row["no_show_strikes"] >= calc.NO_SHOW_STRIKE_CAP
                and guest_row["status"] == "ACTIVE"):
            guest_row["status"] = "RESTRICTED"
        touch(guest_row)
    return object_response(public(order_row))


def release_sold_seats(order_row, slot_row):
    """A paid order gives its seats back. A SOLD_OUT window returns to OPEN and
    a buyout window is handed back to general sale."""
    slot_row["sold_capacity"] = max(0, slot_row["sold_capacity"]
                                    - order_row["party_size"])
    slot_row["wheelchair_sold"] = max(0, slot_row["wheelchair_sold"]
                                      - order_row["wheelchair_party_count"])
    if slot_row["buyout_order_id"] == order_row["id"]:
        slot_row["buyout_order_id"] = None
        slot_row["held_capacity"] = 0
    derive.recompute_available(slot_row)
    if slot_row["status"] in ("SOLD_OUT", "HELD_FOR_BUYOUT"):
        slot_row["status"] = "OPEN"
    touch(slot_row)


def move_to_refund_due(order_row, refund_pct):
    """Fix the refund split once and for all. Used by guest cancellation and by
    the failed-inspection cascade alike."""
    refunded, credit = calc.refund_legs(order_row["net_collected_cents"],
                                        refund_pct)
    order_row["refund_pct"] = float(refund_pct)
    order_row["refunded_cents"] = refunded
    order_row["credit_issued_cents"] = credit
    order_row["net_collected_cents"] = 0
    order_row["status"] = "REFUND_DUE"
    touch(order_row)


@bp.post("/ticket-orders/<order_id>/cancel")
@roles(GUEST, GSA)
def cancel_order(order_id):
    order_row = derive.order(order_id)
    body = Body()
    body.string("reason", required=False, default=None, min_len=1, max_len=500)
    slot_row = derive.slot(order_row["slot_id"])

    # rung 8 — own state
    if order_row["status"] not in ("PENDING", "CONFIRMED"):
        raise ApiError("ERR_ORDER_INVALID_STATE")
    # rung 10 — a Guest may cancel only its own order
    if caller_role() == GUEST and order_row["guest_account_id"] != caller_id():
        raise ApiError("ERR_GUEST_OWNERSHIP_MISMATCH")

    if order_row["status"] == "PENDING":
        order_row["status"] = "CANCELLED"
        order_row["refund_pct"] = 0.00
        order_row["refunded_cents"] = 0
        order_row["credit_issued_cents"] = 0
        order_row["net_collected_cents"] = 0
        touch(order_row)

        slot_row["held_capacity"] = max(0, slot_row["held_capacity"]
                                        - order_row["party_size"])
        if slot_row["buyout_order_id"] == order_row["id"]:
            slot_row["buyout_order_id"] = None
            slot_row["held_capacity"] = 0
        derive.recompute_available(slot_row)
        if slot_row["status"] == "HELD_FOR_BUYOUT":
            slot_row["status"] = "OPEN"
        touch(slot_row)
        return object_response(public(order_row))

    # rung 12 — money may only be given back before the doors open
    instant = now()
    if instant >= slot_row["_start"]:
        raise ApiError("ERR_CANCEL_WINDOW_CLOSED")
    hours = calc.exact_seconds(slot_row["_start"] - instant) / calc.dec(3600)
    move_to_refund_due(order_row, calc.refund_pct_for_hours(hours))
    release_sold_seats(order_row, slot_row)
    return object_response(public(order_row))


@bp.post("/ticket-orders/<order_id>/settle-refund")
@roles(GSA)
def settle_refund(order_id):
    order_row = derive.order(order_id)
    body = Body()
    body.string("note", required=False, default=None, min_len=1, max_len=500)

    # rung 8 — own state
    if order_row["status"] != "REFUND_DUE":
        raise ApiError("ERR_ORDER_INVALID_STATE")

    # nothing is recomputed: the split was fixed on entering REFUND_DUE
    order_row["status"] = "REFUNDED"
    order_row["refund_settled_at"] = now_iso()
    touch(order_row)

    guest_row = derive.guest(order_row["guest_account_id"])
    guest_row["experience_credit_cents"] += order_row["credit_issued_cents"]
    touch(guest_row)
    return object_response(public(order_row))
