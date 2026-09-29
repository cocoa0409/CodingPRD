"""The menu catalogue and its accessibility copy (PRD 3.2)."""
from flask import Blueprint

import auth
import constants as C
import derive
import response
import serialize
import shapes
from db import DB, append_audit, new_row, touch
from errors import fail
from routes.common import listing, path_row, unique_or_conflict

bp = Blueprint("menu", __name__)


@bp.post("/menu-items")
def create_menu_item():
    auth.enter(["PlatformAdmin", "ContentManager"])
    data = shapes.body()
    sku = shapes.req_str(data, "sku", 1, 24)
    display_name = shapes.req_str(data, "display_name", 1, 80)
    category = shapes.req_enum(data, "category", C.CATEGORIES)
    base_price = shapes.req_int(data, "base_price_cents", 1, 100000)
    allergens = shapes.opt_enum_array(data, "allergen_tags", C.ALLERGENS, [])
    text = shapes.opt_str(data, "screen_reader_text", 0, 240, "")
    contrast = shapes.opt_number(data, "contrast_ratio", 0, 21, 0)
    unique_or_conflict("menu_items", "sku", sku)
    row = new_row({
        "sku": sku,
        "display_name": display_name,
        "category": category,
        "base_price_cents": base_price,
        "allergen_tags": allergens,
        "screen_reader_text": text,
        "contrast_ratio": contrast,
        "accessibility_state": "MISSING_ALT_TEXT",
        "zone_price_overrides": [],
        "zone_override_total_cents": 0,
        "pending_price_request_count": 0,
        "pricing_lock_state": "UNLOCKED",
        "chainwide_availability_state": "UNAVAILABLE",
    })
    DB.menu_items[row["id"]] = row
    derive.recompute_item(row, bump=False)
    return response.created(serialize.dump("menu_item", row))


@bp.get("/menu-items")
def list_menu_items():
    auth.enter(auth.ALL_READ_ROLES)
    return listing("menu_items", "menu_item")


@bp.get("/menu-items/<menu_item_id>")
def get_menu_item(menu_item_id):
    auth.enter(auth.ALL_READ_ROLES)
    row = path_row("menu_items", menu_item_id)
    derive.recompute_item(row)
    return response.ok(serialize.dump("menu_item", row))


@bp.post("/menu-items/<menu_item_id>/accessibility-copy")
def rewrite_accessibility_copy(menu_item_id):
    ctx = auth.enter(["ContentManager", "ComplianceOfficer"])
    item = path_row("menu_items", menu_item_id)
    data = shapes.body()
    expected = shapes.req_int(data, "expected_menu_item_version", 0, None)
    text = shapes.req_str(data, "screen_reader_text", 0, 240)
    contrast = shapes.req_number(data, "contrast_ratio", 0, 21)
    if expected != item.get("version"):
        fail("ERR_STALE_MENU_ITEM_VERSION", "expected_menu_item_version does not match")
    item["screen_reader_text"] = text
    item["contrast_ratio"] = contrast
    touch(item)
    derive.recompute_item(item, bump=False)
    for bundle in list(DB.bundles.values()):
        if bundle.get("state") == "ROLLED_BACK":
            continue
        if menu_item_id in (bundle.get("snapshot_item_ids") or []):
            derive.apply_changes(bundle, {"accessibility_audit_state": "PENDING"})
    append_audit("MENU_ITEM", item["id"], "ACCESSIBILITY_COPY_UPDATED", ctx["role"],
                 ctx["user_id"], detail="ACCESSIBILITY_COPY_REWRITTEN")
    derive.reconcile()
    return response.ok(serialize.dump("menu_item", item))
