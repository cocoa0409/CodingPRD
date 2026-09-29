"""Customer complaints, the remedy formula and driver clawbacks (PRD 3.12)."""
from flask import Blueprint

import auth
import calc
import clock
import db
import listing
import response
import serialize
import validate
from errors import fail

bp = Blueprint("complaints", __name__)

CATEGORIES = ("LATE", "FEE_DISCLOSURE", "QUALITY", "DRIVER_CONDUCT")
STATUSES = ("OPEN", "REMEDY_PROPOSED", "REMEDY_ISSUED", "DISMISSED")
READ_ROLES = ("StoreManager", "Dispatcher", "CustomerCareAgent")
RESOLVE_ACTIONS = ("APPROVE", "REJECT", "DISMISS")


def _settling_dispatch(order_id):
    """The route that carried this order to a paid door, if any."""
    stops = [
        s
        for s in db.stops.values()
        if s["order_id"] == order_id and s["status"] in ("DELIVERED", "REMADE")
    ]
    for stop in db.ordered(stops, descending=True):
        dispatch = db.dispatches.get(stop["dispatch_id"])
        if dispatch is not None:
            return dispatch
    return None


def _actual_line_amount(order_id):
    lines = [
        line
        for line in db.lines.values()
        if line["order_id"] == order_id and line["line_type"] == "ACTUAL_STOP"
    ]
    for line in db.ordered(lines, descending=True):
        return line["amount_cents"]
    return 0


@bp.post("/store-ops/complaints")
def log_complaint():
    actor = auth.authenticate(["CustomerCareAgent", "StoreManager"])
    auth.guard(actor, [], [("order_id", "order")])
    body = validate.body()
    raw_order_id = body.get("order_id")
    if isinstance(raw_order_id, str) and raw_order_id != "":
        order = auth.body_fk("order", raw_order_id)
    validate.string(body, "order_id")
    category = validate.enum(body, "category", CATEGORIES)
    description = validate.string(body, "description")
    record = {
        "order_id": order["id"],
        "category": category,
        "description": description,
        "status": "OPEN",
        "proposed_remedy_cents": None,
        "remedy_basis": None,
        "driver_chargeable": False,
        "clawback_cents": 0,
        "logged_by_user_id": actor.user_id,
        "resolved_by_user_id": None,
        "resolved_at": None,
    }
    db.insert(db.complaints, record)
    return response.created(serialize.complaint(record))


@bp.post("/store-ops/complaints/<complaint_id>/propose-remedy")
def propose_remedy(complaint_id):
    actor = auth.authenticate(["CustomerCareAgent"])
    (complaint,) = auth.guard(actor, [("complaint", complaint_id)])
    if complaint["status"] != "OPEN":
        fail("ERR_INVALID_COMPLAINT_STATE", "A remedy is sized only from OPEN.")
    order = db.orders.get(complaint["order_id"])
    if order is None or order["fulfillment_status"] not in (
        "DELIVERED",
        "REMAKE_QUEUED",
        "CLOSED",
    ):
        fail("ERR_INVALID_ORDER_STATE", "The order has not reached a door yet.")
    amount, basis = calc.complaint_remedy(complaint["category"], order)
    complaint["proposed_remedy_cents"] = amount
    complaint["remedy_basis"] = basis
    complaint["status"] = "REMEDY_PROPOSED"
    db.touch(complaint)
    return response.ok(serialize.complaint(complaint))


@bp.post("/store-ops/complaints/<complaint_id>/resolve")
def resolve_complaint(complaint_id):
    actor = auth.authenticate(["StoreManager"])
    (complaint,) = auth.guard(actor, [("complaint", complaint_id)])
    body = validate.body()
    action = validate.enum(body, "action", RESOLVE_ACTIONS)
    driver_chargeable = validate.boolean(
        body, "driver_chargeable", required=False, default=False
    )
    expected = "REMEDY_PROPOSED" if action in ("APPROVE", "REJECT") else "OPEN"
    if complaint["status"] != expected:
        fail("ERR_INVALID_COMPLAINT_STATE", "That decision is not declared from this status.")
    order = db.orders.get(complaint["order_id"])
    if action == "REJECT":
        complaint["status"] = "OPEN"
        complaint["proposed_remedy_cents"] = None
        complaint["remedy_basis"] = None
        complaint["resolved_by_user_id"] = None
        db.touch(complaint)
        return response.ok(serialize.complaint(complaint))
    if action == "DISMISS":
        complaint["status"] = "DISMISSED"
        complaint["resolved_at"] = clock.now()
        complaint["resolved_by_user_id"] = actor.user_id
        db.touch(complaint)
        return response.ok(serialize.complaint(complaint))
    dispatch = _settling_dispatch(complaint["order_id"])
    if driver_chargeable and (dispatch is None or dispatch["status"] != "SETTLED"):
        fail("ERR_CLAWBACK_NOT_SETTLED", "There is no actual-basis line to claw back yet.")
    proposed = complaint["proposed_remedy_cents"] or 0
    remaining = order["total_charge_cents"] - order["remedy_issued_cents"]
    if proposed > remaining:
        fail("ERR_REMEDY_EXCEEDS_TOTAL", "The ticket has no refundable balance left.")
    complaint["status"] = "REMEDY_ISSUED"
    complaint["resolved_at"] = clock.now()
    complaint["resolved_by_user_id"] = actor.user_id
    complaint["driver_chargeable"] = bool(driver_chargeable)
    order["remedy_issued_cents"] = order["remedy_issued_cents"] + proposed
    if order["settlement_status"] in ("CHARGED", "ADJUSTED", "CLOSED_SETTLED"):
        order["settlement_status"] = "ADJUSTED"
    db.touch(order)
    if driver_chargeable:
        amount = -_actual_line_amount(complaint["order_id"])
        db.insert(
            db.lines,
            {
                "dispatch_id": dispatch["id"],
                "driver_id": dispatch["driver_id"],
                "order_id": complaint["order_id"],
                "line_type": "CLAWBACK",
                "basis": "NONE",
                "amount_cents": amount,
                "sequence_snapshot": 0,
                "status": "ACCRUED",
            },
        )
        complaint["clawback_cents"] = abs(amount)
        driver = db.drivers.get(dispatch["driver_id"])
        if driver is not None:
            db.touch(driver)
    db.touch(complaint)
    return response.ok(serialize.complaint(complaint))


@bp.get("/store-ops/complaints/<complaint_id>")
def read_complaint(complaint_id):
    actor = auth.authenticate(READ_ROLES)
    (complaint,) = auth.guard(actor, [("complaint", complaint_id)])
    return response.ok(serialize.complaint(complaint))


@bp.get("/store-ops/complaints")
def list_complaints():
    actor = auth.authenticate(READ_ROLES)
    order_id = validate.filter_string("order_id")
    status = validate.filter_enum("status", STATUSES)
    category = validate.filter_enum("category", CATEGORIES)
    records = list(db.complaints.values())
    if actor.is_manager:
        records = [
            c for c in records if auth.owning_store_id("complaint", c) == actor.user_id
        ]
    if order_id is not None:
        records = [c for c in records if c["order_id"] == order_id]
    if status is not None:
        records = [c for c in records if c["status"] == status]
    if category is not None:
        records = [c for c in records if c["category"] == category]
    return listing.respond(records, serialize.complaint)
