"""Product catalogue endpoints."""

from flask import Blueprint

import auth
import clock
import envelope
import lookup
import store
from errors import fail

bp = Blueprint("products", __name__, url_prefix="/retail")

CATEGORIES = ("DIAGNOSTICS", "TOOL_STORAGE", "POWER_TOOLS")


def _sku_taken(sku, exclude_id=None):
    for product in store.products.values():
        if product.get("sku") == sku and product["id"] != exclude_id:
            return True
    return False


@bp.post("/products")
def create_product():
    auth.require("PlatformAdmin")
    payload = envelope.body()
    sku = envelope.as_str(payload, "sku")
    product_name = envelope.as_str(payload, "product_name")
    category = envelope.as_enum(payload, "category", CATEGORIES)
    unit_cost_cents = envelope.as_int(payload, "unit_cost_cents", minimum=0)
    retail_price_cents = envelope.as_int(payload, "retail_price_cents", minimum=0)
    default_warranty_months = envelope.as_int(payload, "default_warranty_months", minimum=0)
    is_new_launch = envelope.as_bool(payload, "is_new_launch")
    if _sku_taken(sku):
        fail("ERR_SKU_DUPLICATE")
    launch_iso_week = None
    if payload.get("launch_iso_week") is not None:
        launch_iso_week = clock.fmt_week(clock.week_start(clock.parse_utc(payload["launch_iso_week"])))
    product = store.create(
        store.products,
        sku=sku,
        product_name=product_name,
        category=category,
        unit_cost_cents=unit_cost_cents,
        retail_price_cents=retail_price_cents,
        default_warranty_months=default_warranty_months,
        is_new_launch=is_new_launch,
        launch_iso_week=launch_iso_week,
        launch_status="ANNOUNCED" if is_new_launch else "LIVE",
    )
    return envelope.ok(product, 201)


@bp.get("/products")
def list_products():
    auth.require(*auth.ROLES)
    rows = envelope.filter_query(store.ordered(store.products), {
        "category": "category",
        "is_new_launch": "is_new_launch",
    })
    page, pagination = envelope.paginate(rows)
    return envelope.ok_list(page, pagination=pagination)


@bp.get("/products/<product_id>")
def get_product(product_id):
    auth.require(*auth.ROLES)
    return envelope.ok(lookup.product(product_id))


@bp.put("/products/<product_id>")
def update_product(product_id):
    auth.require("PlatformAdmin")
    product = lookup.product(product_id)
    payload = envelope.body()
    if payload.get("sku") is not None:
        sku = envelope.as_str(payload, "sku")
        if _sku_taken(sku, exclude_id=product["id"]):
            fail("ERR_SKU_DUPLICATE")
        store.set_field(product, "sku", sku)
    if payload.get("product_name") is not None:
        store.set_field(product, "product_name", envelope.as_str(payload, "product_name"))
    if payload.get("category") is not None:
        store.set_field(product, "category", envelope.as_enum(payload, "category", CATEGORIES))
    if payload.get("unit_cost_cents") is not None:
        store.set_field(product, "unit_cost_cents",
                        envelope.as_int(payload, "unit_cost_cents", minimum=0))
    if payload.get("retail_price_cents") is not None:
        store.set_field(product, "retail_price_cents",
                        envelope.as_int(payload, "retail_price_cents", minimum=0))
    if payload.get("default_warranty_months") is not None:
        store.set_field(product, "default_warranty_months",
                        envelope.as_int(payload, "default_warranty_months", minimum=0))
    if payload.get("launch_iso_week") is not None:
        store.set_field(product, "launch_iso_week",
                        clock.fmt_week(clock.week_start(clock.parse_utc(payload["launch_iso_week"]))))
    return envelope.ok(product)
