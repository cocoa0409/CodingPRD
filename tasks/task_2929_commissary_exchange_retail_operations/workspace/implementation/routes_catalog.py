"""The worldwide item file and shelf assortment allocations (PRD 3.4)."""

from flask import Blueprint

import constants as C
import lookups
import serialize
import validation as V
from db import db, new_record, sorted_records, touch
from envelope import array_response, object_response
from errors import ApiError

bp = Blueprint("catalog", __name__)


# --------------------------------------------------------------------------
# products
# --------------------------------------------------------------------------


@bp.post("/products")
def create_product():
    V.authenticate(("AssortmentPlanner",))
    body = V.raw_body()
    sku = V.want_string(body, "sku", required=True, min_len=3, max_len=32)
    name = V.want_string(body, "name", required=True, min_len=1, max_len=200)
    category = V.want_enum(body, "category", C.PRODUCT_CATEGORIES, required=True)
    unit_cost_cents = V.want_int(body, "unit_cost_cents", required=True, minimum=1)
    unit_weight_grams = V.want_int(body, "unit_weight_grams", required=False, minimum=1,
                                   default=500)
    resale_restricted = V.want_bool(body, "resale_restricted", required=False, default=False)
    quantity_limit = V.want_int(body, "quantity_limit_per_visit", required=False, minimum=1,
                                default=None)

    # Doctrine step 7: uniqueness of the worldwide item number.
    for existing in db.products.values():
        if existing["sku"] == sku:
            raise ApiError("ERR_DUPLICATE_SKU")

    product = new_record()
    product.update({
        "sku": sku,
        "name": name,
        "category": category,
        "unit_cost_cents": unit_cost_cents,
        "unit_weight_grams": unit_weight_grams,
        "resale_restricted": resale_restricted,
        "quantity_limit_per_visit": quantity_limit,
    })
    db.products[product["id"]] = product
    return object_response(serialize.product_out(product), 201)


@bp.get("/products")
def list_products():
    V.authenticate(("AssortmentPlanner", "StoreCashier"))
    limit, offset = V.pagination()
    category = V.query_enum("category", C.PRODUCT_CATEGORIES)
    resale_restricted = V.query_bool("resale_restricted")
    rows = sorted_records(db.products)
    if category is not None:
        rows = [r for r in rows if r["category"] == category]
    if resale_restricted is not None:
        rows = [r for r in rows if r["resale_restricted"] == resale_restricted]
    page, total = V.paginate(rows, limit, offset)
    return array_response([serialize.product_out(r) for r in page], limit, offset, total)


@bp.get("/products/<product_id>")
def read_product(product_id):
    # Reading one product carries no ownership dimension (PRD 2.1).
    V.authenticate(("AssortmentPlanner", "StoreCashier", "Patron"))
    product = lookups.product(product_id)
    return object_response(serialize.product_out(product), 200)


# --------------------------------------------------------------------------
# assortment allocations
# --------------------------------------------------------------------------


def _closed_windows_intersect(a_from, a_to, b_from, b_to):
    """The shelf window is CLOSED, so windows touching at one endpoint DO
    overlap: that shared instant belongs to both of them."""
    return a_from <= b_to and b_from <= a_to


@bp.post("/assortments")
def create_assortment():
    V.authenticate(("AssortmentPlanner",))
    body = V.raw_body()
    store_id = V.want_string(body, "store_id", required=True)
    product_id = V.want_string(body, "product_id", required=True)
    shelf_block = V.want_string(body, "shelf_block", required=True, min_len=1, max_len=8)
    facings = V.want_int(body, "facings", required=True, minimum=1)
    supply_mode = V.want_enum(body, "supply_mode", C.SUPPLY_MODES, required=True)
    vendor_name = V.want_string(body, "vendor_name", required=False, default=None)
    promo_allowance_bp = V.want_int(body, "promo_allowance_bp", required=False, minimum=0,
                                    maximum=2000, default=0)
    promo_window_start = V.want_instant(body, "promo_window_start", required=False, default=None)
    promo_window_end = V.want_instant(body, "promo_window_end", required=False, default=None)
    effective_from = V.want_instant(body, "effective_from", required=True)
    effective_to = V.want_instant(body, "effective_to", required=True)
    shipping_allowance = V.want_int(body, "overseas_shipping_allowance_cents", required=False,
                                    minimum=0, default=0)
    expected_store_version = V.want_int(body, "expected_store_version", required=True)
    if effective_to < effective_from:
        raise ApiError(
            "ERR_INVALID_REQUEST", "Field 'effective_to' must not be earlier than 'effective_from'."
        )

    store = lookups.store(store_id)
    lookups.product(product_id)

    # Doctrine step 6: the tightly coupled direct-store-delivery terms.
    if supply_mode == "DSD":
        if vendor_name is None:
            raise ApiError("ERR_VENDOR_REQUIRED_FOR_DSD")
    else:
        if vendor_name is not None or promo_allowance_bp != 0:
            raise ApiError("ERR_VENDOR_REQUIRED_FOR_DSD")
    if promo_allowance_bp > 0 and (promo_window_start is None or promo_window_end is None):
        raise ApiError("ERR_VENDOR_REQUIRED_FOR_DSD")

    # Doctrine step 8: the stale-view check precedes the capacity test.
    if store["version"] != expected_store_version:
        raise ApiError("ERR_STALE_STORE_VERSION")

    # Doctrine step 13: shelf-block capacity is the last check performed.
    committed = 0
    for existing in db.assortments.values():
        if existing["store_id"] != store_id or existing["shelf_block"] != shelf_block:
            continue
        if existing["status"] != "ACTIVE":
            continue
        if _closed_windows_intersect(effective_from, effective_to,
                                     existing["effective_from"], existing["effective_to"]):
            committed += existing["facings"]
    if committed + facings > store["shelf_block_capacity_facings"]:
        raise ApiError("ERR_SHELF_CAPACITY_EXCEEDED")

    assortment = new_record()
    assortment.update({
        "store_id": store_id,
        "product_id": product_id,
        "shelf_block": shelf_block,
        "facings": facings,
        "supply_mode": supply_mode,
        "vendor_name": vendor_name,
        "promo_allowance_bp": promo_allowance_bp,
        "promo_window_start": promo_window_start,
        "promo_window_end": promo_window_end,
        "effective_from": effective_from,
        "effective_to": effective_to,
        "overseas_shipping_allowance_cents": shipping_allowance,
        "status": "ACTIVE",
    })
    db.assortments[assortment["id"]] = assortment
    # A successful allocation itself increments the store's version by 1.
    touch(store)
    return object_response(serialize.assortment_out(assortment), 201)


@bp.get("/assortments")
def list_assortments():
    V.authenticate(("AssortmentPlanner", "StoreCashier"))
    limit, offset = V.pagination()
    store_id = V.query_string("store_id")
    product_id = V.query_string("product_id")
    shelf_block = V.query_string("shelf_block")
    status = V.query_enum("status", C.ASSORTMENT_STATUSES)
    supply_mode = V.query_enum("supply_mode", C.SUPPLY_MODES)
    rows = sorted_records(db.assortments)
    if store_id is not None:
        rows = [r for r in rows if r["store_id"] == store_id]
    if product_id is not None:
        rows = [r for r in rows if r["product_id"] == product_id]
    if shelf_block is not None:
        rows = [r for r in rows if r["shelf_block"] == shelf_block]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    if supply_mode is not None:
        rows = [r for r in rows if r["supply_mode"] == supply_mode]
    page, total = V.paginate(rows, limit, offset)
    return array_response([serialize.assortment_out(r) for r in page], limit, offset, total)


@bp.get("/assortments/<assortment_id>")
def read_assortment(assortment_id):
    V.authenticate(("AssortmentPlanner", "StoreCashier"))
    assortment = lookups.assortment(assortment_id)
    return object_response(serialize.assortment_out(assortment), 200)


@bp.post("/assortments/<assortment_id>/retire")
def retire_assortment(assortment_id):
    V.authenticate(("AssortmentPlanner",))
    assortment = lookups.assortment(assortment_id)
    body = V.raw_body()
    V.want_string(body, "reason", required=False)
    if assortment["status"] != "ACTIVE":
        raise ApiError("ERR_ASSORTMENT_NOT_ACTIVE")

    assortment["status"] = "RETIRED"
    touch(assortment)

    # Hop 1: the store/product's pending overseas orders lose their fill source.
    cancelled = 0
    orders = sorted_records(db.special_orders)
    for order in orders:
        if (
            order["store_id"] == assortment["store_id"]
            and order["product_id"] == assortment["product_id"]
            and order["state"] == "OVERSEAS_SHIP_PENDING"
        ):
            order["state"] = "CANCELLED"
            order["cancelled_reason"] = "ASSORTMENT_RETIRED"
            touch(order)
            cancelled += 1
    if cancelled:
        # Hop 2 is the recomputation of shipping_allowance_committed_cents,
        # which is a derived figure and therefore already correct.  Hop 3:
        store = db.stores.get(assortment["store_id"])
        if store is not None:
            touch(store)

    return object_response(serialize.assortment_out(assortment), 200)
