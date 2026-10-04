"""Store endpoints."""
from flask import Blueprint, request
from db import DB
from response import success, success_list, parse_pagination, paginate
from middleware import require_roles
from entities import stamp_new, get_or_404
from errors import raise_err

bp = Blueprint("stores", __name__)

READ_ROLES = ("OpsAdmin", "PurchasingManager", "LogisticsCoordinator",
              "ComplianceOfficer", "InventoryPlanner", "StoreClerk")


@bp.route("/stores", methods=["POST"])
@require_roles("OpsAdmin")
def create_store():
    b = request.get_json(silent=True) or {}
    for f in ("store_code", "name", "format", "market_tier",
              "receiving_capacity_units", "assortment_item_ids"):
        if b.get(f) is None:
            raise_err("ERR_VALIDATION", f"Missing field: {f}")
    if b["format"] not in ("SMALL_FORMAT", "STANDARD"):
        raise_err("ERR_VALIDATION", "Invalid format")
    if b["market_tier"] not in ("PRIMARY", "SECONDARY"):
        raise_err("ERR_VALIDATION", "Invalid market_tier")
    if not isinstance(b["receiving_capacity_units"], int) or b["receiving_capacity_units"] < 1:
        raise_err("ERR_VALIDATION", "receiving_capacity_units must be >= 1")
    if not isinstance(b["assortment_item_ids"], list):
        raise_err("ERR_VALIDATION", "assortment_item_ids must be an array")
    if b["format"] == "SMALL_FORMAT" and len(b["assortment_item_ids"]) > 8:
        raise_err("ERR_VALIDATION", "SMALL_FORMAT assortment cap is 8")
    for iid in b["assortment_item_ids"]:
        if iid not in DB.items:
            raise_err("ERR_NOT_FOUND", "assortment item not found")
    for s in DB.stores.values():
        if s["store_code"] == b["store_code"]:
            raise_err("ERR_VALIDATION", "Duplicate store_code")
    rec = stamp_new({
        "store_code": b["store_code"],
        "name": b["name"],
        "format": b["format"],
        "market_tier": b["market_tier"],
        "receiving_capacity_units": b["receiving_capacity_units"],
        "assortment_item_ids": list(b["assortment_item_ids"]),
    })
    DB.stores[rec["id"]] = rec
    return success(dict(rec), status=201)


@bp.route("/stores", methods=["GET"])
@require_roles(*READ_ROLES)
def list_stores():
    limit, offset = parse_pagination(request.args)
    rows = sorted(DB.stores.values(), key=lambda r: r["created_at"])
    fmt = request.args.get("format")
    mt = request.args.get("market_tier")
    if fmt:
        rows = [r for r in rows if r["format"] == fmt]
    if mt:
        rows = [r for r in rows if r["market_tier"] == mt]
    page, total = paginate(rows, limit, offset)
    return success_list([dict(r) for r in page], limit, offset, total)


@bp.route("/stores/<storeId>", methods=["GET"])
@require_roles(*READ_ROLES)
def get_store(storeId):
    return success(dict(get_or_404(DB.stores, storeId)))
