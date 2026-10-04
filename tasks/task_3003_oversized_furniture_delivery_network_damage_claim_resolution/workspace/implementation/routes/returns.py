"""Return authorizations: request, approve (disposal economics), deny, complete."""
from datetime import timedelta

from flask import Blueprint, request

import clock
from db import db, new_id
from errors import (
    err_invalid_state,
    err_order_not_delivered,
    err_pricing_unavailable,
    err_return_window_closed,
)
from middleware import require_roles
from response import success
from services import calculations as calc
from services.common import get_or_404, list_response, stamp_new, touch
from validation import get_body, req_enum

bp = Blueprint("returns", __name__)


@bp.post("/return-authorizations")
@require_roles("Customer")
def create_return_authorization():
    body = get_body(request)
    raw_order_id = body.get("order_id")
    order = get_or_404(db.orders, raw_order_id if isinstance(raw_order_id, str) else None)
    reason = req_enum(body, "reason", {"DAMAGE", "BUYERS_REMORSE", "WRONG_ITEM"})
    ra = stamp_new(
        {
            "id": new_id(),
            "order_id": order["id"],
            "reason": reason,
            "reverse_haul_cost_cents": None,
            "refurb_value_cents": None,
            "disposition": None,
            "approved_at": None,
            "status": "REQUESTED",
        }
    )
    db.return_authorizations[ra["id"]] = ra
    return success(ra, status=201)


_RA_STATES = {"REQUESTED", "APPROVED", "COMPLETED", "DENIED", "EXPIRED"}


@bp.get("/return-authorizations")
@require_roles("NetworkAdmin", "HubOperator", "Customer")
def list_return_authorizations():
    return list_response(
        db.return_authorizations,
        [
            ("order_id", "order_id", None),
            ("status", "status", _RA_STATES),
        ],
    )


@bp.get("/return-authorizations/<raId>")
@require_roles("NetworkAdmin", "HubOperator", "Customer")
def get_return_authorization(raId):
    return success(get_or_404(db.return_authorizations, raId))


@bp.post("/return-authorizations/<raId>/approve")
@require_roles("NetworkAdmin")
def approve_return_authorization(raId):
    ra = get_or_404(db.return_authorizations, raId)
    if ra["status"] != "REQUESTED":
        raise err_invalid_state("ReturnAuthorization must be REQUESTED to approve")
    order = db.orders.get(ra["order_id"])
    if order is None or order["order_state"] != "DELIVERED":
        raise err_order_not_delivered()
    shipment = None
    for s in db.shipments.values():
        if s["order_id"] == order["id"]:
            shipment = s
            break
    if shipment is None or shipment["delivered_at"] is None:
        raise err_order_not_delivered()
    delivered_at = clock._parse_iso(shipment["delivered_at"])
    if clock.now() > delivered_at + timedelta(days=45):
        raise err_return_window_closed()

    customer = db.customers.get(order["customer_id"])
    item = db.items.get(order["item_id"])
    ltl_lane = calc.find_active_lane(
        db.freight_lanes.values(), "LTL", customer["destination_zone"] if customer else ""
    )
    if ltl_lane is None:
        raise err_pricing_unavailable("No ACTIVE LTL lane for reverse-haul pricing")
    reverse_haul, refurb, disposition = calc.return_disposition(
        ra["reason"], item["declared_value_cents"], ltl_lane["base_rate_cents"]
    )
    ra["reverse_haul_cost_cents"] = reverse_haul
    ra["refurb_value_cents"] = refurb
    ra["disposition"] = disposition
    ra["approved_at"] = clock.now_str()
    ra["status"] = "APPROVED"
    touch(ra)
    return success(ra)


@bp.post("/return-authorizations/<raId>/deny")
@require_roles("NetworkAdmin")
def deny_return_authorization(raId):
    ra = get_or_404(db.return_authorizations, raId)
    if ra["status"] != "REQUESTED":
        raise err_invalid_state("ReturnAuthorization must be REQUESTED to deny")
    ra["status"] = "DENIED"
    touch(ra)
    return success(ra)


@bp.post("/return-authorizations/<raId>/complete")
@require_roles("HubOperator")
def complete_return_authorization(raId):
    ra = get_or_404(db.return_authorizations, raId)
    if ra["status"] != "APPROVED":
        raise err_invalid_state("ReturnAuthorization must be APPROVED to complete")
    ra["status"] = "COMPLETED"
    touch(ra)
    order = db.orders.get(ra["order_id"])
    if order is not None:
        order["fulfillment_state"] = "RETURNED"
        touch(order)
    return success(ra)
