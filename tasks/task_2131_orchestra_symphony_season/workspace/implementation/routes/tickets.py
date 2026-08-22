"""Single-ticket orders: demand-priced holds and settlement."""

from flask import Blueprint, request

from calc import single_ticket_price
from db import db
from domain import (base_fields, inventory_element, refresh_concerts,
                    season_of_concert, serialize, touch)
from errors import raise_err
from middleware import endpoint, own
from response import ok, ok_list
from validate import (body, check_body_fks, opt_bool, paginate, present,
                      req_int, req_str)

bp = Blueprint("tickets", __name__)


def get_order_or_404(order_id):
    order = db.orders.get(order_id)
    if order is None:
        raise_err("ERR_TICKET_ORDER_NOT_FOUND")
    return order


@bp.route("/orchestra/ticket-orders", methods=["POST"])
@endpoint(["BoxOfficeAgent", "Patron"])
def create_ticket_order():
    data = body()
    check_body_fks(data, ["concert_id", "seat_section_id", "patron_id"])   # rung 4

    if present(data, "patron_id"):                             # rung 5
        own(data["patron_id"], "Patron")

    concert_id = req_str(data, "concert_id")                   # rung 6
    patron_id = req_str(data, "patron_id")
    seat_section_id = req_str(data, "seat_section_id")
    seat_count = req_int(data, "seat_count", minv=1)
    expected_version = req_int(data, "expected_concert_version")

    concert = db.concerts[concert_id]
    patron = db.patrons[patron_id]
    section = db.sections[seat_section_id]

    if concert["sale_status"] != "PUBLIC_ONSALE":              # rung 7
        raise_err("ERR_CONCERT_NOT_ON_SALE")

    if expected_version != concert["version"]:                 # rung 9
        raise_err("ERR_STALE_CONCERT_VERSION")

    if concert["venue_id"] != section["venue_id"]:             # rung 20
        raise_err("ERR_SEAT_SECTION_VENUE_MISMATCH")

    element = inventory_element(concert, seat_section_id)      # rung 22
    if element is None or element["available_count"] < seat_count:
        raise_err("ERR_INSUFFICIENT_SEATS")

    season = season_of_concert(concert)
    unit, band, _fill, _donor_bp, amount_due = single_ticket_price(
        season["base_ticket_price_cents"], section["price_multiplier_bp"],
        element["held_count"], element["sold_count"], element["capacity"],
        patron["donor_level"], seat_count)

    order = base_fields()
    order.update({
        "concert_id": concert_id,
        "patron_id": patron_id,
        "seat_section_id": seat_section_id,
        "seat_count": seat_count,
        "status": "HELD",
        "quoted_unit_price_cents": unit,
        "amount_due_cents": amount_due,
        "amount_paid_cents": 0,
        "credit_applied_cents": 0,
        "demand_band_at_hold": band,
        "hold_expires_at_ops_run": season["ops_run_index"] + 2,
    })
    db.orders[order["id"]] = order

    refresh_concerts([concert_id])
    return ok(serialize(order), 201)


@bp.route("/orchestra/ticket-orders/<order_id>", methods=["GET"])
@endpoint(["ArtisticAdmin", "BoxOfficeAgent", "Patron"])
def read_order(order_id):
    return ok(serialize(get_order_or_404(order_id)))


@bp.route("/orchestra/ticket-orders", methods=["GET"])
@endpoint(["ArtisticAdmin", "BoxOfficeAgent", "Patron"])
def list_orders():
    filters = {
        "concert_id": request.args.get("concert_id"),
        "patron_id": request.args.get("patron_id"),
        "seat_section_id": request.args.get("seat_section_id"),
        "status": request.args.get("status"),
    }
    records = []
    for order in db.orders.values():
        if any(value is not None and order[key] != value
               for key, value in filters.items()):
            continue
        records.append(order)
    items, limit, offset, total = paginate(records, serialize)
    return ok_list(items, limit, offset, total)


@bp.route("/orchestra/ticket-orders/<order_id>/pay", methods=["POST"])
@endpoint(["BoxOfficeAgent", "Patron"])
def pay_order(order_id):
    order = get_order_or_404(order_id)                        # rung 3
    own(order["patron_id"], "Patron")                         # rung 5
    data = body()
    use_credit = opt_bool(data, "use_credit", False)          # rung 6

    if order["status"] != "HELD":                             # rung 7
        raise_err("ERR_TICKET_ORDER_NOT_HELD")
    concert = db.concerts.get(order["concert_id"])
    if concert is None or concert["performance_status"] != "SCHEDULED":
        raise_err("ERR_CONCERT_ALREADY_CANCELLED")

    patron = db.patrons.get(order["patron_id"])
    credit_applied = 0
    if use_credit and patron is not None:
        credit_applied = min(patron["credit_balance_cents"], order["amount_due_cents"])

    with touch(order):
        order["status"] = "PAID"
        order["credit_applied_cents"] = credit_applied
        order["amount_paid_cents"] = order["amount_due_cents"]

    if patron is not None:
        with touch(patron):
            patron["credit_balance_cents"] -= credit_applied
            patron["lifetime_cash_in_cents"] += (order["amount_due_cents"] - credit_applied)

    refresh_concerts([order["concert_id"]])
    return ok(serialize(order))
