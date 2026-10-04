"""Catalog item endpoints: create and list (PRD 3.6)."""
import uuid

from flask import Blueprint, request

import db as dbmod
import domain as D
from errors import ApiError
from middleware import authenticate, get_body
from response import paginate, success
from util import is_int

bp = Blueprint("catalog", __name__)


@bp.post("/lab/catalog-items")
def create_catalog_item():
    authenticate({"SupplyOps", "PlatformAdmin"})
    body = get_body()
    sku = body.get("sku")
    name = body.get("name")
    if not isinstance(sku, str) or not sku.strip():
        raise ApiError("ERR_INVALID_REQUEST", 400, "sku is required")
    if not isinstance(name, str) or not name.strip():
        raise ApiError("ERR_INVALID_REQUEST", 400, "name is required")
    item_class = body.get("item_class")
    if item_class not in D.ITEM_CLASSES:
        raise ApiError(
            "ERR_INVALID_REQUEST", 400,
            "item_class must be one of STANDARD, COLD_CHAIN, HAZARDOUS, CONTROLLED",
        )
    allocation_group = body.get("allocation_group")
    if allocation_group not in D.ALLOCATION_GROUPS:
        raise ApiError(
            "ERR_INVALID_REQUEST", 400,
            "allocation_group must be one of GROUP_A, GROUP_B, GROUP_C",
        )
    base_price = body.get("base_price_cents")
    if not is_int(base_price) or base_price <= 0:
        raise ApiError(
            "ERR_INVALID_REQUEST", 400, "base_price_cents must be an integer > 0"
        )
    stock = body.get("stock_on_hand")
    if not is_int(stock) or stock < 0:
        raise ApiError(
            "ERR_INVALID_REQUEST", 400, "stock_on_hand must be a non-negative integer"
        )
    if sku in dbmod.store.catalog_by_sku:
        raise ApiError("ERR_DUPLICATE_SKU", 409, "A catalog item with this sku exists")
    now = dbmod.now()
    item = {
        "id": str(uuid.uuid4()),
        "sku": sku,
        "name": name,
        "item_class": item_class,
        "allocation_group": allocation_group,
        "base_price_cents": base_price,
        "stock_on_hand": stock,
        "reserved_quantity": 0,
        "created_at": now,
        "updated_at": now,
        "version": 1,
        "seq": dbmod.store.next_seq(),
    }
    with dbmod.store.lock:
        dbmod.store.catalog_items[item["id"]] = item
        dbmod.store.catalog_by_sku[sku] = item["id"]
    return success(D.catalog_item_json(item), code=201)


@bp.get("/lab/catalog-items")
def list_catalog_items():
    authenticate({"SupplyOps", "AccountManager", "LabProcurement", "PlatformAdmin"})
    items = list(dbmod.store.catalog_items.values())
    f_sku = request.args.get("sku")
    if f_sku is not None:
        items = [c for c in items if c["sku"] == f_sku]
    f_class = request.args.get("item_class")
    if f_class is not None:
        items = [c for c in items if c["item_class"] == f_class]
    f_group = request.args.get("allocation_group")
    if f_group is not None:
        items = [c for c in items if c["allocation_group"] == f_group]
    items = D.created_sorted(items)
    page, meta = paginate(items)
    return success(
        [D.catalog_item_json(c) for c in page], response_type="array", pagination=meta
    )
