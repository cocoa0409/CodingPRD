"""Ticket orders: sell, read, list, refund."""
from flask import Blueprint, request

import errors as E
import services as S
from db import STORE
from middleware import require_roles
from response import (new_common, ok_object, ok_array, paginate, require_field,
                      require_int, parse_dt, fmt_dt, get_json_body)

bp = Blueprint("orders", __name__)

ANY = ("HouseManager", "CompanyRep", "BoxOfficeAgent")


def _get_order_or_404(oid):
    o = STORE.ticket_orders.get(oid)
    if not o:
        raise E.not_found("Ticket order not found")
    return o


@bp.post("/theatres/bookings/<bid>/ticket-orders")
def create_order(bid):
    require_roles("BoxOfficeAgent")
    booking = STORE.bookings.get(bid)
    if not booking:
        raise E.not_found("Booking not found")
    if booking["status"] != "ACTIVE":
        raise E.invalid_state("Ticket orders require an ACTIVE booking")
    body = get_json_body()
    perf_raw = require_field(body, "performance_date")
    pd_ = parse_dt(perf_raw, "performance_date")
    count = require_int(require_field(body, "ticket_count"), "ticket_count")
    is_group = require_field(body, "is_group_sale")
    face = require_int(require_field(body, "face_value_cents"), "face_value_cents")
    if count < 1:
        raise E.invalid_request("ticket_count must be >= 1")
    if face <= 0:
        raise E.invalid_request("face_value_cents must be > 0")
    code_id = body.get("discount_code_id")
    percent_off = 0
    if code_id is not None:
        code = STORE.discount_codes.get(code_id)
        if (not code or code["production_id"] != booking["production_id"]
                or not code["active"] or not (0 < code["percent_off"] < 100)):
            raise E.discount_code_invalid()
        percent_off = code["percent_off"]
    factor = body.get("dynamic_pricing_factor", 1.0)
    if isinstance(factor, bool) or not isinstance(factor, (int, float)):
        raise E.invalid_request("dynamic_pricing_factor must be a number")
    if not (0.5 <= factor <= 2.0):
        raise E.dynamic_factor_oob()
    if count >= 8 and not is_group:
        raise E.group_sale_mismatch("Orders of 8+ tickets must set is_group_sale true")
    if count < 8 and is_group:
        raise E.group_sale_mismatch("Orders of fewer than 8 tickets must not set is_group_sale")
    gross = S.compute_order_gross(count, face, factor, percent_off)
    rec = new_common()
    rec.update({"booking_id": bid, "performance_date": fmt_dt(pd_),
                "ticket_count": count, "is_group_sale": bool(is_group),
                "discount_code_id": code_id, "dynamic_pricing_factor": factor,
                "face_value_cents": face, "status": "SOLD",
                "computed_gross_cents": gross, "refunded": False})
    STORE.ticket_orders[rec["id"]] = rec
    # New sale changes the provisional gross of a covering DRAFT/SUBMITTED report
    for r in S._covering_report(bid, rec["performance_date"]):
        S.recompute_report(r)
    return ok_object(rec, 201)


@bp.get("/theatres/ticket-orders/<oid>")
def get_order(oid):
    require_roles(*ANY)
    return ok_object(_get_order_or_404(oid))


@bp.get("/theatres/ticket-orders")
def list_orders():
    require_roles(*ANY)
    items = list(STORE.ticket_orders.values())
    code_id = request.args.get("discount_code_id")
    if code_id:
        items = [o for o in items if o.get("discount_code_id") == code_id]
    page, limit, offset, total = paginate(items, request.args)
    return ok_array(page, limit, offset, total)


@bp.post("/theatres/ticket-orders/<oid>/refund")
def refund_order(oid):
    require_roles("BoxOfficeAgent")
    order = _get_order_or_404(oid)
    if order["status"] != "SOLD":
        raise E.invalid_state("Only a SOLD order can be refunded")
    S.refund_order(order)
    return ok_object(order)
