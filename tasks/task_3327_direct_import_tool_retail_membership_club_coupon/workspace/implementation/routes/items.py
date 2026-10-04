"""Item endpoints."""
from flask import Blueprint, request
from db import DB
from response import success, success_list, parse_pagination, paginate
from middleware import require_roles
from entities import stamp_new, touch, get_or_404
from errors import raise_err
from calc import margin_floor_ok

bp = Blueprint("items", __name__)

ALL_ROLES = ("OpsAdmin", "PurchasingManager", "LogisticsCoordinator",
             "ComplianceOfficer", "InventoryPlanner", "MarketingManager",
             "StoreClerk", "WarrantyAdjuster", "Customer")


def item_view(it):
    return dict(it)


@bp.route("/items", methods=["POST"])
@require_roles("PurchasingManager")
def create_item():
    b = request.get_json(silent=True) or {}
    required = ["sku", "name", "brand_tier", "origin_country", "unit_retail_cents",
                "member_price_cents", "floor_margin_pct", "lead_time_days", "unit_weight_kg"]
    for f in required:
        if b.get(f) is None:
            raise_err("ERR_VALIDATION", f"Missing field: {f}")
    if b["brand_tier"] not in ("VALUE", "MID", "PROFESSIONAL"):
        raise_err("ERR_VALIDATION", "Invalid brand_tier")
    if not isinstance(b["unit_retail_cents"], int) or b["unit_retail_cents"] <= 0:
        raise_err("ERR_VALIDATION", "unit_retail_cents must be > 0")
    if not isinstance(b["member_price_cents"], int) or b["member_price_cents"] <= 0:
        raise_err("ERR_VALIDATION", "member_price_cents must be > 0")
    if b["member_price_cents"] > b["unit_retail_cents"]:
        raise_err("ERR_VALIDATION", "member_price_cents must be <= unit_retail_cents")
    if not isinstance(b["lead_time_days"], int) or b["lead_time_days"] < 1:
        raise_err("ERR_VALIDATION", "lead_time_days must be >= 1")
    if not (isinstance(b["unit_weight_kg"], (int, float)) and b["unit_weight_kg"] > 0):
        raise_err("ERR_VALIDATION", "unit_weight_kg must be > 0")
    if not (isinstance(b["floor_margin_pct"], (int, float))):
        raise_err("ERR_VALIDATION", "floor_margin_pct must be a number")
    for it in DB.items.values():
        if it["sku"] == b["sku"]:
            raise_err("ERR_VALIDATION", "Duplicate sku")
    rec = stamp_new({
        "sku": b["sku"],
        "name": b["name"],
        "brand_tier": b["brand_tier"],
        "origin_country": b["origin_country"],
        "unit_retail_cents": b["unit_retail_cents"],
        "member_price_cents": b["member_price_cents"],
        "floor_margin_pct": b["floor_margin_pct"],
        "lead_time_days": b["lead_time_days"],
        "unit_weight_kg": b["unit_weight_kg"],
        "lifecycle_status": "DRAFT",
        "open_recall_count": 0,
        "warranty_claim_rate": 0.0,
        "current_landed_unit_cost_cents": None,
    })
    DB.items[rec["id"]] = rec
    return success(item_view(rec), status=201)


@bp.route("/items", methods=["GET"])
@require_roles(*ALL_ROLES)
def list_items():
    limit, offset = parse_pagination(request.args)
    rows = sorted(DB.items.values(), key=lambda r: r["created_at"])
    bt = request.args.get("brand_tier")
    ls = request.args.get("lifecycle_status")
    if bt:
        rows = [r for r in rows if r["brand_tier"] == bt]
    if ls:
        rows = [r for r in rows if r["lifecycle_status"] == ls]
    page, total = paginate(rows, limit, offset)
    return success_list([item_view(r) for r in page], limit, offset, total)


@bp.route("/items/<itemId>", methods=["GET"])
@require_roles(*ALL_ROLES)
def get_item(itemId):
    return success(item_view(get_or_404(DB.items, itemId)))


@bp.route("/items/<itemId>/activate", methods=["POST"])
@require_roles("PurchasingManager")
def activate_item(itemId):
    it = get_or_404(DB.items, itemId)
    if it["lifecycle_status"] != "DRAFT":
        raise_err("ERR_INVALID_STATE", "Item not in DRAFT")
    it["lifecycle_status"] = "ACTIVE"
    touch(it)
    return success(item_view(it))


@bp.route("/items/<itemId>/reprice", methods=["POST"])
@require_roles("PurchasingManager")
def reprice_item(itemId):
    it = get_or_404(DB.items, itemId)
    b = request.get_json(silent=True) or {}
    retail_given = "unit_retail_cents" in b
    member_given = "member_price_cents" in b
    new_retail = b.get("unit_retail_cents", it["unit_retail_cents"])
    new_member = b.get("member_price_cents", it["member_price_cents"])
    if not isinstance(new_retail, int) or new_retail <= 0:
        raise_err("ERR_VALIDATION", "unit_retail_cents must be > 0")
    if not isinstance(new_member, int) or new_member <= 0:
        raise_err("ERR_VALIDATION", "member_price_cents must be > 0")
    # margin floor gate: a reprice lowering the retail price below the floor
    # is rejected (member-only reductions do not engage the floor)
    if not margin_floor_ok(it, new_retail):
        raise_err("ERR_MARGIN_FLOOR_VIOLATION", "Price below margin floor")
    if new_member > new_retail:
        # Repricing may update either price or both; an unspecified side is
        # not dragged across the other side's new value. When both were
        # supplied the conflict is a genuine violation.
        if retail_given and member_given:
            raise_err("ERR_VALIDATION", "member_price_cents must be <= unit_retail_cents")
        if retail_given:
            new_member = new_retail
        else:
            new_retail = new_member
    it["unit_retail_cents"] = new_retail
    it["member_price_cents"] = new_member
    touch(it)
    return success(item_view(it))


@bp.route("/items/<itemId>/discontinue", methods=["POST"])
@require_roles("PurchasingManager")
def discontinue_item(itemId):
    it = get_or_404(DB.items, itemId)
    if it["lifecycle_status"] not in ("ACTIVE", "QUARANTINED"):
        raise_err("ERR_INVALID_STATE", "Item cannot be discontinued from this state")
    it["lifecycle_status"] = "DISCONTINUED"
    touch(it)
    return success(item_view(it))
