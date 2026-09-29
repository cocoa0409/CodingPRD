"""Outlet checks: opening, pricing at close, and voiding."""
from flask import Blueprint

import db
import response
import shapes
from constants import PREFIX, TICKET_SETTLEMENT_TYPES
from errors import ApiError
from middleware import ALL_ROLES, NIGHT_AUDITOR, OUTLET_MANAGER, authenticate
from money import ZERO, q2
from services import calc, derive, lookup, serial

bp = Blueprint("tickets", __name__, url_prefix=PREFIX)


def _require_scope(role, user_id, outlet_id):
    if role == OUTLET_MANAGER and user_id != outlet_id:
        raise ApiError("ERR_OUTLET_SCOPE_VIOLATION",
                       "An outlet manager may only act on their own outlet.")


@bp.route("/outlet-tickets", methods=["POST"])
def create_ticket():
    user_id, role = authenticate([OUTLET_MANAGER, NIGHT_AUDITOR])
    body = shapes.parse([
        shapes.Field("outlet_id", "string", required=True),
        shapes.Field("business_date_id", "string", required=True),
        shapes.Field("ticket_number", "string", required=True),
        shapes.Field("gross_amount", "number", required=True, gt=0),
        shapes.Field("settlement_type", "string", required=True,
                     enum=TICKET_SETTLEMENT_TYPES),
        shapes.Field("opened_at", "instant", required=True),
        shapes.Field("room_charge_folio_id", "string"),
        shapes.Field("transmitted_at", "instant"),
    ])
    date_row = lookup.get_date(body["business_date_id"])
    folio = (lookup.get_folio(body["room_charge_folio_id"])
             if body["room_charge_folio_id"] else None)
    outlet = lookup.get_outlet(body["outlet_id"])
    lookup.require_not_archived(date_row)
    lookup.require_charges_open(date_row)
    _require_scope(role, user_id, outlet["id"])
    if outlet["property_id"] != date_row["property_id"]:
        raise ApiError("ERR_CROSS_PROPERTY_REFERENCE",
                       "The outlet belongs to a different property.")
    if folio is not None and folio["property_id"] != date_row["property_id"]:
        raise ApiError("ERR_CROSS_PROPERTY_REFERENCE",
                       "The account belongs to a different property.")
    if body["settlement_type"] == "ROOM_CHARGE":
        if folio is None:
            raise ApiError("ERR_TICKET_FOLIO_REQUIRED",
                           "A room-charge check must name a folio.")
    elif folio is not None:
        raise ApiError("ERR_TICKET_FOLIO_REQUIRED",
                       "A cash or card check may not name a folio.")
    for row in db.store.tickets.values():
        if (row["outlet_id"] == outlet["id"]
                and row["business_date_id"] == date_row["id"]
                and row["ticket_number"] == body["ticket_number"]):
            raise ApiError("ERR_DUPLICATE_TICKET_NUMBER",
                           "That ticket number is already used for this outlet and day.")
    if outlet["status"] == "SUSPENDED":
        raise ApiError("ERR_OUTLET_SUSPENDED", "The outlet is suspended.")
    row = db.insert("tickets", {
        "_kind": "OutletTicket",
        "outlet_id": outlet["id"],
        "business_date_id": date_row["id"],
        "room_charge_folio_id": folio["id"] if folio else None,
        "ticket_number": body["ticket_number"],
        "gross_amount": q2(body["gross_amount"]),
        "settlement_type": body["settlement_type"],
        "opened_at": body["opened_at"],
        "transmitted_at": body["transmitted_at"],
        "status": "OPEN",
        "service_charge_amount": ZERO,
        "taxable_base_amount": ZERO,
        "tax_amount": ZERO,
        "large_party_discount_amount": ZERO,
        "total_amount": ZERO,
        "closed_by_user_id": None,
        "closed_at": None,
        "voided_at": None,
    })
    return response.created(serial.ticket_out(row))


@bp.route("/outlet-tickets/<row_id>/close", methods=["POST"])
def close_ticket(row_id):
    user_id, role = authenticate([OUTLET_MANAGER, NIGHT_AUDITOR])
    body = shapes.parse([shapes.Field("transmitted_at", "instant")])
    ticket = lookup.get_ticket(row_id)
    date_row = lookup.get_date(ticket["business_date_id"])
    lookup.require_not_archived(date_row)
    lookup.require_charges_open(date_row)
    if ticket["status"] != "OPEN":
        raise ApiError("ERR_TICKET_NOT_OPEN", "The check is not open.")
    _require_scope(role, user_id, ticket["outlet_id"])
    prop = db.store.properties[date_row["property_id"]]
    figures = calc.ticket_figures(
        ticket["gross_amount"], prop["service_charge_pct"], prop["fb_tax_rate_pct"],
        prop["large_ticket_threshold_amount"], prop["large_party_discount_pct"],
    )
    folio = (db.store.folios.get(ticket["room_charge_folio_id"])
             if ticket["room_charge_folio_id"] else None)
    if folio is not None:
        projected = q2(derive.folio_balance(folio) + figures["total_amount"])
        if projected > folio["credit_limit_amount"]:
            raise ApiError("ERR_CREDIT_LIMIT_EXCEEDED",
                           "The transfer would carry the account past its credit limit.")
    closed_at = db.now()
    ticket.update(figures)
    ticket["status"] = "CLOSED"
    ticket["closed_at"] = closed_at
    ticket["closed_by_user_id"] = user_id
    if body["transmitted_at"] is not None:
        ticket["transmitted_at"] = body["transmitted_at"]
    elif ticket["transmitted_at"] is None:
        ticket["transmitted_at"] = closed_at
    derive.touch(ticket)
    if folio is not None:
        derive.append_posting("OUTLET_TRANSFER", figures["total_amount"], date_row,
                              "OUTLET_POS", user_id, folio=folio,
                              outlet_ticket_id=ticket["id"])
    derive.touch(date_row)
    derive.supersede_reports(date_row)
    return response.ok(serial.ticket_out(ticket))


@bp.route("/outlet-tickets/<row_id>/void", methods=["POST"])
def void_ticket(row_id):
    user_id, role = authenticate([OUTLET_MANAGER, NIGHT_AUDITOR])
    ticket = lookup.get_ticket(row_id)
    date_row = lookup.get_date(ticket["business_date_id"])
    lookup.require_not_archived(date_row)
    lookup.require_charges_open(date_row)
    if ticket["status"] != "CLOSED":
        raise ApiError("ERR_TICKET_NOT_CLOSED", "The check is not closed.")
    _require_scope(role, user_id, ticket["outlet_id"])
    total = q2(ticket["total_amount"])
    folio = (db.store.folios.get(ticket["room_charge_folio_id"])
             if ticket["room_charge_folio_id"] else None)
    ticket["status"] = "VOID"
    ticket["voided_at"] = db.now()
    ticket["total_amount"] = ZERO
    derive.touch(ticket)
    if folio is not None:
        original = None
        for row in derive.postings():
            if (row["outlet_ticket_id"] == ticket["id"]
                    and row["charge_type"] == "OUTLET_TRANSFER"
                    and not row["reverses_posting_id"]):
                original = row
        derive.append_posting("OUTLET_TRANSFER", -total, date_row, "OUTLET_POS",
                              user_id, folio=folio, outlet_ticket_id=ticket["id"],
                              reverses_posting_id=original["id"] if original else None)
    derive.touch(date_row)
    derive.supersede_reports(date_row)
    return response.ok(serial.ticket_out(ticket))


@bp.route("/outlet-tickets/<row_id>", methods=["GET"])
def get_ticket(row_id):
    authenticate(ALL_ROLES)
    return response.ok(serial.ticket_out(lookup.get_ticket(row_id)))


@bp.route("/outlet-tickets", methods=["GET"])
def list_tickets():
    authenticate(ALL_ROLES)
    rows = db.all_of("tickets")
    for key in ("outlet_id", "business_date_id", "room_charge_folio_id", "status",
                "settlement_type"):
        value = shapes.q(key)
        if value is not None:
            rows = [r for r in rows if r[key] == value]
    items, meta = shapes.page(rows, serial.ticket_out)
    return response.collection(items, meta)
