"""Order creation: pricing, seat runs, holds and queue consumption."""

from clock import CLOCK, parse_iso
from db import DB
from errors import ApiError
from services import calc, engine, holds

ADMIT_WINDOW_MINUTES = 20


def locate_admitted_position(performance_id, patron_id):
    """The patron's live admission for this performance, if any."""
    for position in DB.all("queue_position"):
        if position["performance_id"] != performance_id:
            continue
        if position["patron_id"] != patron_id:
            continue
        if position["status"] == "ADMITTED":
            return position
    return None


def has_active_position(performance_id, patron_id):
    for position in DB.all("queue_position"):
        if position["performance_id"] != performance_id:
            continue
        if position["patron_id"] != patron_id:
            continue
        if position["status"] in ("WAITING", "ADMITTED"):
            return True
    return False


def resolve_admission(performance_id, patron_id, allocation):
    """A purchase needs a live admission; a drawn win is claimed, not bought here."""
    position = locate_admitted_position(performance_id, patron_id)
    if position is not None:
        expires = position.get("admit_expires_at")
        if expires is not None and parse_iso(expires) < CLOCK.now:
            raise ApiError("ERR_QUEUE_ADMISSION_EXPIRED")
        return position
    raise ApiError("ERR_RUSH_NOT_RELEASED")


def build_purchase(performance, allocation, patron_id, quantity, idempotency_key=None):
    """Mint an order priced by per_seat_price and purchase_line_subtotal."""
    unit_price_cents, _base, surge_bp = calc.per_seat_price(
        performance, allocation, billable=quantity
    )
    subtotal_cents = calc.purchase_line_subtotal(unit_price_cents, quantity)
    quoted_total_cents = calc.producer_quote(unit_price_cents, quantity)

    purchase = {
        "performance_id": performance["id"],
        "allocation_id": allocation["id"],
        "patron_id": patron_id,
        "quantity": int(quantity),
        "idempotency_key": idempotency_key,
        "unit_price_cents": unit_price_cents,
        "surge_multiplier_bp": surge_bp,
        "subtotal_cents": subtotal_cents,
        "quoted_total_cents": quoted_total_cents,
        "payment_status": "PENDING",
        "logistics_status": "AWAITING_HANDOFF",
        "handoff_status": "NOT_REQUIRED",
        "handoff_token": None,
        "handoff_verified_at": None,
        "handoff_failed_at": None,
        "assign_by": None,
        "seat_labels": [],
        "refunded_cents": 0,
    }
    DB.insert("purchase", purchase)
    engine.dispatch_handoff(purchase, performance)
    return purchase


def assign_seats(purchase, performance, allocation):
    """Every order occupies a contiguous run; adjacent runs are permitted."""
    run = holds.next_run(performance["id"], purchase["quantity"])
    if len(run) < int(purchase["quantity"]):
        raise ApiError("ERR_ORDER_BLOCK_CAPACITY")
    if holds.run_intersects_existing(performance["id"], run):
        raise ApiError("ERR_ORDER_BLOCK_CAPACITY")
    purchase["seat_labels"] = run
    DB.touch("purchase", purchase, bump=False)
    holds.create_allocation_hold(performance["id"], allocation["id"], run)
    return run


def open_order(performance, allocation, patron_id, quantity, idempotency_key=None):
    """Create the order, advance the sold counter and consume the admission."""
    purchase = build_purchase(
        performance, allocation, patron_id, quantity, idempotency_key=idempotency_key
    )
    assign_seats(purchase, performance, allocation)

    allocation["quantity_sold_today"] = int(allocation.get("quantity_sold_today") or 0) + int(
        quantity
    )
    DB.touch("allocation", allocation)
    engine.maybe_allocation_exhausted(allocation, performance)

    position = locate_admitted_position(performance["id"], patron_id)
    if position is not None:
        position["status"] = "PURCHASED"
        DB.touch("queue_position", position)
    return purchase