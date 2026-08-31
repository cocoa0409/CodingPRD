"""Flight coupons: append, read, fly and void (PRD section 3.4)."""

from flask import Blueprint

from calculations import coupons_of_ticket, ffp_estimate
from errors import ApiError
from responses import ok, ok_list
from store import db, fmt_dt, must_find, new_row, serialize, touch
import validation as V

bp = Blueprint("coupons", __name__)


@bp.route("/interline/tickets/<ticket_id>/coupons", methods=["POST"])
def create_coupon(ticket_id):
    user_id, role = V.require([V.ROLE_ACCOUNTANT])
    data = V.body()
    coupon_number = V.req_int(data, "coupon_number", minimum=1)
    origin = V.req_str(data, "origin")
    destination = V.req_str(data, "destination")
    operating_carrier_id = V.req_str(data, "operating_carrier_id")
    class_of_service = V.req_enum(data, "class_of_service", V.CLASSES)
    tpm_miles = V.req_int(data, "tpm_miles", minimum=1)

    ticket = must_find("ticket", ticket_id)
    operating = must_find("carrier", operating_carrier_id)

    V.require_ownership(user_id, role, ticket["validating_carrier_id"])

    validating = db.carriers.get(ticket["validating_carrier_id"])
    if validating is not None and validating["status"] != "ACTIVE":
        raise ApiError("ERR_CARRIER_SUSPENDED")

    if coupon_number != ticket["coupon_count"] + 1:
        raise ApiError("ERR_COUPON_SEQUENCE_INVALID")

    coupon = new_row({
        "ticket_id": ticket["id"],
        "coupon_number": coupon_number,
        "origin": origin,
        "destination": destination,
        "operating_carrier_id": operating["id"],
        "class_of_service": class_of_service,
        "tpm_miles": tpm_miles,
        "coupon_status": "OPEN",
        "flown_at": None,
        "weight_units": 0,
        "allocated_amount_minor": 0,
        "allocation_basis": "UNALLOCATED",
        "ffp_miles_awarded": 0,
        "ffp_accrual_cost_minor": 0,
        "ffp_tier": "NONE",
        "billing_invoice_id": None,
        "adjusted_amount_minor": 0,
    })
    coupon["_flown_at"] = None
    db.coupons[coupon["id"]] = coupon

    ticket["coupon_count"] += 1
    touch(ticket)
    return ok(serialize(coupon), 201)


@bp.route("/interline/coupons/<coupon_id>", methods=["GET"])
def get_coupon(coupon_id):
    V.require(V.ALL_ROLES)
    coupon = must_find("coupon", coupon_id)
    return ok(serialize(coupon))


@bp.route("/interline/coupons", methods=["GET"])
def list_coupons():
    V.require(V.ALL_ROLES)
    limit, offset = V.pagination()
    ticket_id = V.filter_str("ticket_id")
    operating_carrier_id = V.filter_str("operating_carrier_id")
    billing_invoice_id = V.filter_str("billing_invoice_id")
    coupon_status = V.filter_enum("coupon_status", V.COUPON_STATUSES)
    rows = list(db.coupons.values())
    if ticket_id is not None:
        rows = [r for r in rows if r["ticket_id"] == ticket_id]
    if operating_carrier_id is not None:
        rows = [r for r in rows
                if r["operating_carrier_id"] == operating_carrier_id]
    if billing_invoice_id is not None:
        rows = [r for r in rows
                if r.get("billing_invoice_id") == billing_invoice_id]
    if coupon_status is not None:
        rows = [r for r in rows if r["coupon_status"] == coupon_status]
    window, total = V.listing(rows, limit, offset)
    return ok_list(window, limit, offset, total)


@bp.route("/interline/coupons/<coupon_id>/fly", methods=["POST"])
def fly_coupon(coupon_id):
    user_id, role = V.require([V.ROLE_ACCOUNTANT])
    V.body()
    coupon = must_find("coupon", coupon_id)
    ticket = db.tickets.get(coupon["ticket_id"])

    V.require_ownership(user_id, role,
                        ticket["validating_carrier_id"] if ticket else None)

    if coupon["coupon_status"] != "OPEN":
        raise ApiError("ERR_COUPON_STATE_INVALID")

    operating = db.carriers.get(coupon["operating_carrier_id"])
    if operating is None or operating["status"] != "ACTIVE":
        raise ApiError("ERR_OPERATING_CARRIER_SUSPENDED")

    coupon["coupon_status"] = "FLOWN"
    coupon["flown_at"] = fmt_dt(db.clock)
    coupon["_flown_at"] = db.clock

    miles, cost = ffp_estimate(coupon, operating)
    operating["period_accrued_miles"] += miles
    operating["period_ffp_cost_estimate_minor"] += cost
    touch(operating)
    touch(coupon)
    return ok(serialize(coupon))


@bp.route("/interline/coupons/<coupon_id>/void", methods=["POST"])
def void_coupon(coupon_id):
    user_id, role = V.require([V.ROLE_ACCOUNTANT])
    V.body()
    coupon = must_find("coupon", coupon_id)
    ticket = db.tickets.get(coupon["ticket_id"])

    V.require_ownership(user_id, role,
                        ticket["validating_carrier_id"] if ticket else None)

    if coupon["coupon_status"] != "OPEN":
        raise ApiError("ERR_COUPON_STATE_INVALID")

    coupon["coupon_status"] = "VOID"
    coupon["allocated_amount_minor"] = 0
    coupon["allocation_basis"] = "UNALLOCATED"
    touch(coupon)

    if ticket is not None:
        ticket["unallocated_residual_minor"] = ticket["total_fare_minor"] - sum(
            c["allocated_amount_minor"] for c in coupons_of_ticket(ticket["id"]))
        touch(ticket)
    return ok(serialize(coupon))
