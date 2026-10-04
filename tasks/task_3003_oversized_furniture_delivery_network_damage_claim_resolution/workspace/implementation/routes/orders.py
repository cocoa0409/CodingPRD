"""Orders and shipments: routing, pricing, fee split, cancel, depart, deliver."""
from datetime import timedelta

from flask import Blueprint, request

import clock
from db import db, new_id
from errors import (
    err_invalid_request,
    err_invalid_state,
    err_item_not_listed,
    err_linehaul_capacity_exceeded,
    err_pricing_unavailable,
    err_service_level_not_available,
)
from middleware import require_roles
from response import success
from services import calculations as calc
from services import supplier_metrics
from services.common import get_or_404, list_response, shipment_for_order, stamp_new, touch
from validation import get_body, req_enum, req_string

bp = Blueprint("orders", __name__)


def _bind_shipment_to_linehaul(shipment, linehaul):
    shipment["linehaul_id"] = linehaul["id"]
    linehaul["committed_count"] += 1
    touch(linehaul)


def try_auto_bind_unbound_shipments(hub_id):
    """On linehaul creation: unbound OWNED_FINAL_MILE shipments for this hub
    bind to a suitable PLANNED linehaul (earliest planned_arrival_date,
    created_at ASC tie-break)."""
    changed = True
    while changed:
        changed = False
        unbound = [
            s
            for s in db.shipments.values()
            if s["fulfillment_mode"] == "OWNED_FINAL_MILE"
            and s["hub_id"] == hub_id
            and s["linehaul_id"] is None
            and s["current_state"] not in ("DELIVERED", "EXCEPTION")
        ]
        unbound.sort(key=lambda s: (s["created_at"], s["id"]))
        for shipment in unbound:
            linehaul = calc.select_linehaul(db.linehauls.values(), hub_id, db.shipments.values())
            if linehaul is None:
                break
            _bind_shipment_to_linehaul(shipment, linehaul)
            touch(shipment)
            changed = True


@bp.post("/orders")
@require_roles("Customer")
def create_order():
    body = get_body(request)
    # Existence: body fields in declared input order (customer_id, item_id, ...).
    # Absent or mistyped identifiers are not resolvable references; they fall
    # through to the required-field presence/well-typedness check, which must
    # surface ERR_INVALID_REQUEST rather than ERR_NOT_FOUND.
    raw_customer_id = body.get("customer_id")
    raw_item_id = body.get("item_id")
    customer = get_or_404(db.customers, raw_customer_id if isinstance(raw_customer_id, str) else None)
    item = get_or_404(db.items, raw_item_id) if isinstance(raw_item_id, str) else None
    if item is None:
        raise err_invalid_request("Field 'item_id' is required")
    service_level = req_enum(body, "service_level", {"THRESHOLD", "ROOM_OF_CHOICE"})

    supplier = get_or_404(db.suppliers, item["supplier_id"])

    # Business checks in declared relative order (PRD §3.3).
    if service_level == "ROOM_OF_CHOICE" and not item["white_glove_eligible"]:
        raise err_service_level_not_available()
    if item["status"] != "LISTED" or supplier["status"] == "SUSPENDED":
        raise err_item_not_listed()

    route = calc.routing_decision(
        item, supplier, customer, service_level, db.hubs.values(), db.freight_lanes.values()
    )

    lane = calc.find_active_lane(db.freight_lanes.values(), route["leg_mode"], customer["destination_zone"])
    if lane is None:
        raise err_pricing_unavailable()

    linehaul = None
    if route["fulfillment_mode"] == "OWNED_FINAL_MILE":
        linehaul = calc.select_linehaul(
            db.linehauls.values(), route["hub"]["id"], db.shipments.values()
        )
        if linehaul is None:
            raise err_linehaul_capacity_exceeded()

    shipping_amount = calc.shipping_price(lane, item["weight_lb"])
    order_total, surcharge, handling = calc.order_fee_split(
        item["declared_value_cents"], shipping_amount, item["freight_class"]
    )

    creation_date = clock.today_date()
    order = stamp_new(
        {
            "id": new_id(),
            "customer_id": customer["id"],
            "item_id": item["id"],
            "service_level": service_level,
            "shipping_amount_cents": shipping_amount,
            "oversized_surcharge_cents": surcharge,
            "handling_fee_cents": handling,
            "order_total_cents": order_total,
            "order_state": "ROUTED",
            "fulfillment_state": "NONE",
        }
    )
    db.orders[order["id"]] = order

    promised_ship_date = None
    if route["fulfillment_mode"] == "DROP_SHIP":
        promised_ship_date = (creation_date + timedelta(days=int(supplier["lead_time_days"]))).isoformat()

    shipment = stamp_new(
        {
            "id": new_id(),
            "order_id": order["id"],
            "item_id": item["id"],
            "supplier_id": supplier["id"],
            "hub_id": route["hub"]["id"] if route["hub"] is not None else None,
            "linehaul_id": None,
            "fulfillment_mode": route["fulfillment_mode"],
            "leg_mode": route["leg_mode"],
            "promised_date": calc.promised_date(
                creation_date, lane["transit_days"], route["fulfillment_mode"], 0
            ),
            "actual_ship_date": None,
            "promised_ship_date": promised_ship_date,
            "linehaul_misses": 0,
            "current_state": "TENDERED",
            "delivered_at": None,
        }
    )
    db.shipments[shipment["id"]] = shipment
    if linehaul is not None:
        _bind_shipment_to_linehaul(shipment, linehaul)

    return success(order, status=201)


_ORDER_STATES = {"PENDING", "ROUTED", "IN_TRANSIT", "OUT_FOR_DELIVERY", "DELIVERED", "CANCELLED"}


@bp.get("/orders")
@require_roles("NetworkAdmin", "Customer", "HubOperator", "ClaimsAdjuster")
def list_orders():
    return list_response(
        db.orders,
        [
            ("customer_id", "customer_id", None),
            ("item_id", "item_id", None),
            ("order_state", "order_state", _ORDER_STATES),
        ],
    )


@bp.get("/orders/<orderId>")
@require_roles("NetworkAdmin", "Customer", "HubOperator", "ClaimsAdjuster")
def get_order(orderId):
    return success(get_or_404(db.orders, orderId))


@bp.post("/orders/<orderId>/cancel")
@require_roles("Customer", "NetworkAdmin")
def cancel_order(orderId):
    order = get_or_404(db.orders, orderId)
    if order["order_state"] not in ("PENDING", "ROUTED"):
        raise err_invalid_state("Order can only be cancelled while PENDING or ROUTED")
    order["order_state"] = "CANCELLED"
    touch(order)
    shipment = shipment_for_order(order["id"])
    if shipment is not None:
        shipment["current_state"] = "EXCEPTION"
        if shipment["linehaul_id"] is not None:
            linehaul = db.linehauls.get(shipment["linehaul_id"])
            if linehaul is not None:
                linehaul["committed_count"] -= 1
                touch(linehaul)
            shipment["linehaul_id"] = None
        touch(shipment)
    return success(order)


# --- Shipments ---------------------------------------------------------------

_SHIPMENT_STATES = {
    "CREATED",
    "TENDERED",
    "IN_TRANSIT",
    "AT_HUB",
    "OUT_FOR_DELIVERY",
    "DELIVERED",
    "EXCEPTION",
}


@bp.get("/shipments")
@require_roles("NetworkAdmin", "HubOperator", "ClaimsAdjuster", "SupplierRep")
def list_shipments():
    return list_response(
        db.shipments,
        [
            ("order_id", "order_id", None),
            ("hub_id", "hub_id", None),
            ("supplier_id", "supplier_id", None),
            ("linehaul_id", "linehaul_id", None),
            ("item_id", "item_id", None),
            ("current_state", "current_state", _SHIPMENT_STATES),
        ],
    )


@bp.get("/shipments/<shipmentId>")
@require_roles("NetworkAdmin", "HubOperator", "ClaimsAdjuster", "SupplierRep", "Customer")
def get_shipment(shipmentId):
    return success(get_or_404(db.shipments, shipmentId))


@bp.post("/shipments/<shipmentId>/depart")
@require_roles("CarrierRep", "SupplierRep")
def depart_shipment(shipmentId):
    shipment = get_or_404(db.shipments, shipmentId)
    if shipment["current_state"] != "TENDERED":
        raise err_invalid_state("Shipment must be TENDERED to depart")
    shipment["actual_ship_date"] = clock.today_date().isoformat()
    shipment["current_state"] = "IN_TRANSIT"
    touch(shipment)
    order = db.orders.get(shipment["order_id"])
    if order is not None and order["order_state"] == "ROUTED":
        order["order_state"] = "IN_TRANSIT"
        touch(order)
    return success(shipment)


@bp.post("/shipments/<shipmentId>/deliver")
@require_roles("CarrierRep", "SupplierRep")
def deliver_shipment(shipmentId):
    shipment = get_or_404(db.shipments, shipmentId)
    if shipment["current_state"] != "IN_TRANSIT":
        raise err_invalid_state("Shipment must be IN_TRANSIT to deliver")
    if shipment["fulfillment_mode"] == "OWNED_FINAL_MILE":
        raise err_invalid_state("Hub shipments deliver via appointment")
    shipment["current_state"] = "DELIVERED"
    shipment["delivered_at"] = clock.now_str()
    touch(shipment)
    order = db.orders.get(shipment["order_id"])
    if order is not None:
        order["order_state"] = "DELIVERED"
        order["fulfillment_state"] = "FULFILLED"
        touch(order)
    if shipment["fulfillment_mode"] == "DROP_SHIP":
        supplier_metrics.recompute_supplier(shipment["supplier_id"])
    return success(shipment)
