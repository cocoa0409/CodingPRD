"""Special orders for deployed and remote sites (PRD 3.8)."""

from flask import Blueprint

import calculations as calc
import constants as C
import lookups
import service_sale
import serialize
import validation as V
from db import clock_now, db, new_record, sorted_records, touch
from envelope import array_response, object_response
from errors import ApiError

bp = Blueprint("special_orders", __name__)


@bp.post("/special-orders")
def place_order():
    caller = V.authenticate(("StoreCashier", "Patron"))
    body = V.raw_body()
    # A patron placing their own order must match the patron_id in the body,
    # and that ownership check precedes the payload schema (PRD 2.1, 2.8).
    if caller.role == "Patron":
        claimed = body.get("patron_id") if isinstance(body, dict) else None
        if isinstance(claimed, str) and claimed != caller.user_id:
            raise ApiError("ERR_PATRON_SCOPE_VIOLATION")

    store_id = V.want_string(body, "store_id", required=True)
    patron_id = V.want_string(body, "patron_id", required=True)
    product_id = V.want_string(body, "product_id", required=True)
    quantity = V.want_int(body, "quantity", required=True, minimum=1)

    store = lookups.store(store_id)
    patron = lookups.patron(patron_id)
    lookups.product(product_id)

    # The same eligibility gate as opening a visit, in the same order.
    service_sale.require_card_valid(patron)
    service_sale.require_sponsor_card_valid(patron)
    service_sale.require_channel_and_region(patron, store)

    order = new_record()
    order.update({
        "store_id": store_id,
        "patron_id": patron_id,
        "product_id": product_id,
        "quantity": quantity,
        "route": None,
        "state": "SUBMITTED",
        "billable_weight_kg": 0,
        "gross_ship_cents": 0,
        "patron_share_cents": 0,
        "shipping_allowance_cents": 0,
        "cancelled_reason": None,
    })
    db.special_orders[order["id"]] = order
    return object_response(serialize.special_order_out(order), 201)


@bp.get("/special-orders")
def list_orders():
    V.authenticate(("StoreCashier", "ComplianceOfficer"))
    limit, offset = V.pagination()
    store_id = V.query_string("store_id")
    patron_id = V.query_string("patron_id")
    product_id = V.query_string("product_id")
    state = V.query_enum("state", C.SPECIAL_ORDER_STATES)
    route = V.query_enum("route", C.SPECIAL_ORDER_ROUTES)
    rows = sorted_records(db.special_orders)
    if store_id is not None:
        rows = [r for r in rows if r["store_id"] == store_id]
    if patron_id is not None:
        rows = [r for r in rows if r["patron_id"] == patron_id]
    if product_id is not None:
        rows = [r for r in rows if r["product_id"] == product_id]
    if state is not None:
        rows = [r for r in rows if r["state"] == state]
    if route is not None:
        rows = [r for r in rows if r["route"] == route]
    page, total = V.paginate(rows, limit, offset)
    return array_response([serialize.special_order_out(r) for r in page], limit, offset, total)


@bp.get("/special-orders/<order_id>")
def read_order(order_id):
    caller = V.authenticate(("StoreCashier", "ComplianceOfficer", "Patron"))
    order = lookups.special_order(order_id)
    if caller.role == "Patron" and order["patron_id"] != caller.user_id:
        raise ApiError("ERR_PATRON_SCOPE_VIOLATION")
    return object_response(serialize.special_order_out(order), 200)


@bp.post("/special-orders/<order_id>/route")
def route_order(order_id):
    V.authenticate(("StoreCashier",))
    order = lookups.special_order(order_id)
    body = V.raw_body()
    route = V.want_enum(body, "route", C.SPECIAL_ORDER_ROUTES, required=True)

    if order["state"] != "SUBMITTED":
        raise ApiError("ERR_SPECIAL_ORDER_NOT_ROUTABLE")

    store = db.stores[order["store_id"]]
    product = db.products[order["product_id"]]

    # Two referential checks, in this order.
    governing = service_sale.governing_for(order["store_id"], order["product_id"], clock_now())
    if governing is None:
        raise ApiError("ERR_ITEM_NOT_IN_ASSORTMENT")
    if route == "OVERSEAS_SHIP" and store["region"] not in ("OVERSEAS", "DEPLOYED"):
        raise ApiError("ERR_ROUTE_NOT_AVAILABLE_IN_REGION")

    figures = calc.special_order_shipping(store, product, order["quantity"], route)
    order.update(figures)
    order["route"] = route
    if route == "LOCAL_FILL":
        order["state"] = "LOCAL_FILL_PENDING"
        touch(order)
    else:
        # The allowance joins the store's committed total, which is derived
        # from the pending/fulfilled orders themselves.
        order["state"] = "OVERSEAS_SHIP_PENDING"
        touch(order)
        touch(store)
    return object_response(serialize.special_order_out(order), 200)


@bp.post("/special-orders/<order_id>/cancel")
def cancel_order(order_id):
    caller = V.authenticate(("StoreCashier", "Patron"))
    order = lookups.special_order(order_id)
    if caller.role == "Patron" and order["patron_id"] != caller.user_id:
        raise ApiError("ERR_PATRON_SCOPE_VIOLATION")
    body = V.raw_body()
    cancelled_reason = V.want_enum(body, "cancelled_reason", C.CANCELLED_REASONS, required=True)

    if order["state"] not in ("SUBMITTED", "LOCAL_FILL_PENDING", "OVERSEAS_SHIP_PENDING"):
        raise ApiError("ERR_SPECIAL_ORDER_TERMINAL")

    released = order["state"] == "OVERSEAS_SHIP_PENDING"
    order["state"] = "CANCELLED"
    order["cancelled_reason"] = cancelled_reason
    touch(order)
    if released:
        store = db.stores.get(order["store_id"])
        if store is not None:
            touch(store)
    return object_response(serialize.special_order_out(order), 200)
