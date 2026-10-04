"""Categories and products: SKU-cap discipline and product lifecycle."""
from flask import Blueprint

import calc
import svc
from core import (
    ApiError,
    body,
    db,
    dump,
    endpoint,
    f_bool,
    f_enum,
    f_int,
    f_str,
    new_row,
    paginate,
    q_enum,
    q_str,
    respond_object,
    sort_created,
    touch,
)

bp = Blueprint("catalog", __name__)


# ---------------------------------------------------------------------------
# Categories
# ---------------------------------------------------------------------------
@bp.post("/v1/categories")
@endpoint("CategoryManager")
def create_category():
    payload = body()
    code = f_str(payload, "code")
    name = f_str(payload, "name")
    sku_cap = f_int(payload, "sku_cap", required=False, default=2, minimum=1, maximum=5)
    category = new_row(
        "Category",
        code=code,
        name=name,
        sku_cap=sku_cap,
        active_sku_count=0,
        status="OPEN",
    )
    db.categories[category["id"]] = category
    return respond_object(dump(category), 201)


@bp.get("/v1/categories")
@endpoint("CategoryManager", "ProcurementLead", "OperationsAdmin")
def list_categories():
    status = q_enum("status", calc.CATEGORY_STATUSES)
    rows = sort_created(list(db.categories.values()))
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    return paginate(rows)


@bp.get("/v1/categories/<category_id>")
@endpoint("CategoryManager", "ProcurementLead", "OperationsAdmin")
def read_category(category_id):
    return respond_object(dump(svc.need_category(category_id)))


@bp.patch("/v1/categories/<category_id>")
@endpoint("CategoryManager")
def update_category(category_id):
    category = svc.need_category(category_id)
    payload = body()
    sku_cap = f_int(payload, "sku_cap", minimum=1, maximum=5)
    expected = f_int(payload, "expected_category_version", minimum=0)
    if expected != category["version"]:
        raise ApiError("ERR_STALE_VERSION")
    if sku_cap < category["active_sku_count"]:
        raise ApiError("ERR_SKU_CAP_BELOW_CURRENT")
    category["sku_cap"] = sku_cap
    touch(category)
    svc.recompute_category(category)
    return respond_object(dump(category))


# ---------------------------------------------------------------------------
# Products
# ---------------------------------------------------------------------------
@bp.post("/v1/products")
@endpoint("CategoryManager")
def create_product():
    payload = body()
    category_id = f_str(payload, "category_id")
    sku_code = f_str(payload, "sku_code")
    name = f_str(payload, "name")
    kind = f_enum(payload, "kind", calc.PRODUCT_KINDS)
    shelf_ready = f_bool(payload, "shelf_ready_packaging")
    barcode_count = f_int(payload, "barcode_count")
    unit_cost_cents = f_int(payload, "unit_cost_cents", minimum=0)
    price_cents = f_int(payload, "price_cents", minimum=0)
    # tier 4 -- body FK existence
    svc.need_category(category_id)
    # tier 8 -- structural business rules
    if any(p["sku_code"] == sku_code for p in db.products.values()):
        raise ApiError("ERR_DUPLICATE_SKU")
    if barcode_count < 1 or (shelf_ready and barcode_count < 2):
        raise ApiError("ERR_BARCODE_COUNT_INVALID")
    if kind == "FINDS" and not shelf_ready:
        raise ApiError("ERR_SHELF_READY_REQUIRED")
    product = new_row(
        "Product",
        category_id=category_id,
        sku_code=sku_code,
        name=name,
        kind=kind,
        shelf_ready_packaging=shelf_ready,
        barcode_count=barcode_count,
        unit_cost_cents=unit_cost_cents,
        price_cents=price_cents,
        primary_supplier_id=None,
        secondary_supplier_id=None,
        status="PROPOSED",
    )
    db.products[product["id"]] = product
    return respond_object(dump(product), 201)


@bp.get("/v1/products")
@endpoint("CategoryManager", "ProcurementLead", "OperationsAdmin", "CustomerServiceAgent")
def list_products():
    category_id = q_str("category_id")
    kind = q_enum("kind", calc.PRODUCT_KINDS)
    status = q_enum("status", calc.PRODUCT_STATUSES)
    rows = sort_created(list(db.products.values()))
    if category_id is not None:
        rows = [r for r in rows if r["category_id"] == category_id]
    if kind is not None:
        rows = [r for r in rows if r["kind"] == kind]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    return paginate(rows)


@bp.get("/v1/products/<product_id>")
@endpoint("CategoryManager", "ProcurementLead", "OperationsAdmin", "CustomerServiceAgent")
def read_product(product_id):
    return respond_object(dump(svc.need_product(product_id)))


@bp.post("/v1/products/<product_id>/discontinue")
@endpoint("CategoryManager")
def discontinue_product(product_id):
    product = svc.need_product(product_id)
    if product["status"] != "ACTIVE":
        raise ApiError("ERR_INVALID_STATE")
    product["status"] = "DISCONTINUED"
    touch(product)
    svc.recompute_category(db.categories[product["category_id"]])
    return respond_object(dump(product))


@bp.post("/v1/products/<product_id>/reactivate")
@endpoint("CategoryManager")
def reactivate_product(product_id):
    product = svc.need_product(product_id)
    if product["status"] != "DISCONTINUED":
        raise ApiError("ERR_INVALID_STATE")
    category = db.categories[product["category_id"]]
    # PRD §3.2: reactivation requires the category OPEN and, for CORE products,
    # active_sku_count below sku_cap; at-cap is rejected with ERR_SKU_CAP_EXCEEDED.
    if product["kind"] == "CORE" and category["active_sku_count"] >= category["sku_cap"]:
        raise ApiError("ERR_SKU_CAP_EXCEEDED")
    if category["status"] != "OPEN":
        raise ApiError("ERR_INVALID_STATE")
    product["status"] = "ACTIVE"
    touch(product)
    svc.recompute_category(category)
    return respond_object(dump(product))


@bp.get("/v1/products/<product_id>/tenders")
@endpoint("ProcurementLead", "CategoryManager")
def list_product_tenders(product_id):
    svc.need_product(product_id)
    rows = sort_created(
        [t for t in db.tenders.values() if t["product_id"] == product_id]
    )
    return paginate(rows)
