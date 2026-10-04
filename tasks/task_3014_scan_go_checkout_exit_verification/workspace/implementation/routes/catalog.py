"""Catalog item endpoints."""

from flask import Blueprint, request

from db import STORE, new_entity, touch
from errors import ApiError, ERR_INVALID_REQUEST
from logic import get_club, get_catalog_item, is_int, serialize, sort_items
from middleware import get_context, get_body, require_role, require_fields, get_pagination, paginate
from response import success

bp = Blueprint("catalog", __name__)

PRICING_MODES = {"UNIT", "WEIGHTED"}
RESTRICTED = {"NONE", "ALCOHOL", "TOBACCO", "PHARMACY"}


def _validate_pricing_payload(body, existing=None):
    """Validate pricing-mode-consistent price fields. `existing` is the stored
    item for PATCH (fields default from it), None for POST."""
    mode = body.get("pricing_mode", existing["pricing_mode"] if existing else None)
    if mode not in PRICING_MODES:
        raise ApiError(ERR_INVALID_REQUEST, "pricing_mode must be UNIT or WEIGHTED.", 400)

    if mode == "UNIT":
        if existing is None and "unit_price_cents" not in body:
            raise ApiError(ERR_INVALID_REQUEST,
                           "unit_price_cents is required for a UNIT item.", 400)
        if "unit_price_cents" in body and not is_int(body["unit_price_cents"]):
            raise ApiError(ERR_INVALID_REQUEST, "unit_price_cents must be an integer.", 400)
        if "price_per_pound_cents" in body and body["price_per_pound_cents"] is not None:
            raise ApiError(ERR_INVALID_REQUEST,
                           "price_per_pound_cents is inconsistent with pricing_mode UNIT.", 400)
    else:  # WEIGHTED
        if existing is None and "price_per_pound_cents" not in body:
            raise ApiError(ERR_INVALID_REQUEST,
                           "price_per_pound_cents is required for a WEIGHTED item.", 400)
        if "price_per_pound_cents" in body and not is_int(body["price_per_pound_cents"]):
            raise ApiError(ERR_INVALID_REQUEST, "price_per_pound_cents must be an integer.", 400)
        if "unit_price_cents" in body and body["unit_price_cents"] is not None:
            raise ApiError(ERR_INVALID_REQUEST,
                           "unit_price_cents is inconsistent with pricing_mode WEIGHTED.", 400)


@bp.post("/clubs/<club_id>/catalog-items")
def create_item(club_id):
    _, role = get_context()
    require_role(role, ["PlatformAdmin"])
    club = get_club(club_id)
    body = get_body()
    require_fields(body, ["sku", "item_name", "pricing_mode"])
    if not isinstance(body["sku"], str) or not body["sku"]:
        raise ApiError(ERR_INVALID_REQUEST, "sku must be a non-empty string.", 400)
    if not isinstance(body["item_name"], str) or not body["item_name"]:
        raise ApiError(ERR_INVALID_REQUEST, "item_name must be a non-empty string.", 400)
    _validate_pricing_payload(body)

    restricted = body.get("restricted_class", "NONE")
    if restricted not in RESTRICTED:
        raise ApiError(ERR_INVALID_REQUEST,
                       "restricted_class must be NONE, ALCOHOL, TOBACCO, or PHARMACY.", 400)
    early_eligible = body.get("early_hours_eligible", True)
    if not isinstance(early_eligible, bool):
        raise ApiError(ERR_INVALID_REQUEST, "early_hours_eligible must be a boolean.", 400)

    # sku unique per club
    for it in STORE.catalog_items.values():
        if it["club_id"] == club["id"] and it["sku"] == body["sku"]:
            raise ApiError(ERR_INVALID_REQUEST, "sku must be unique within the club.", 400)

    item = new_entity()
    item.update({
        "club_id": club["id"],
        "sku": body["sku"],
        "item_name": body["item_name"],
        "pricing_mode": body["pricing_mode"],
        "unit_price_cents": body.get("unit_price_cents"),
        "price_per_pound_cents": body.get("price_per_pound_cents"),
        "restricted_class": restricted,
        "early_hours_eligible": early_eligible,
        "status": "ACTIVE",
    })
    STORE.catalog_items[item["id"]] = item
    return success(serialize(item), status=201)


@bp.get("/catalog-items/<item_id>")
def get_item(item_id):
    get_context()
    return success(serialize(get_catalog_item(item_id)))


@bp.patch("/catalog-items/<item_id>")
def patch_item(item_id):
    _, role = get_context()
    require_role(role, ["PlatformAdmin"])
    item = get_catalog_item(item_id)
    body = get_body()

    if "pricing_mode" in body:
        raise ApiError(ERR_INVALID_REQUEST, "pricing_mode cannot be changed.", 400)
    _validate_pricing_payload(body, existing=item)

    if "unit_price_cents" in body:
        item["unit_price_cents"] = body["unit_price_cents"]
    if "price_per_pound_cents" in body:
        item["price_per_pound_cents"] = body["price_per_pound_cents"]
    if "status" in body:
        if body["status"] not in ("ACTIVE", "DELISTED"):
            raise ApiError(ERR_INVALID_REQUEST, "status must be ACTIVE or DELISTED.", 400)
        item["status"] = body["status"]
    touch(item)
    return success(serialize(item))


@bp.get("/clubs/<club_id>/catalog-items")
def list_items(club_id):
    get_context()
    club = get_club(club_id)
    limit, offset = get_pagination(request.args)
    items = [it for it in STORE.catalog_items.values() if it["club_id"] == club["id"]]
    for f in ("pricing_mode", "restricted_class", "status"):
        v = request.args.get(f)
        if v is not None:
            items = [it for it in items if it[f] == v]
    items = sort_items(items)
    page, page_meta = paginate(items, limit, offset)
    return success([serialize(it) for it in page], response_type="array", pagination=page_meta)


@bp.get("/catalog-items/<item_id>/scan-lines")
def item_scan_lines(item_id):
    get_context()
    item = get_catalog_item(item_id)
    limit, offset = get_pagination(request.args)
    lines = [l for l in STORE.scan_lines.values() if l["catalog_item_id"] == item["id"]]
    lines = sort_items(lines)
    page, page_meta = paginate(lines, limit, offset)
    return success([serialize(l) for l in page], response_type="array", pagination=page_meta)
