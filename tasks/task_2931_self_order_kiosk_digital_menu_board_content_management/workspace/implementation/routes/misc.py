"""The store projection, the audit trail and the logical clock (PRD 3.5, 2.10, 2.4)."""
from flask import Blueprint, request

import auth
import calc
import constants as C
import derive
import logical_clock as clockmod
import response
import serialize
import shapes
from db import DB, ordered
from errors import fail
from routes.common import apply_filters, path_row

bp = Blueprint("misc", __name__)

PROJECTION_ROLES = ("PlatformAdmin", "ContentManager", "PricingAnalyst", "ComplianceOfficer",
                    "StoreOperator", "DeviceAgent")
AUDIT_ROLES = ("PlatformAdmin", "ComplianceOfficer", "PricingApprover")


def _query_int(name, low, high):
    raw = request.args.get(name)
    if raw is None:
        return None
    text = str(raw).strip()
    if not text.lstrip("-").isdigit():
        fail("ERR_INVALID_REQUEST", "%s must be an integer" % name)
    value = int(text)
    if value < low or value > high:
        fail("ERR_INVALID_REQUEST", "%s is out of range" % name)
    return value


def _cart_item_ids():
    ids = []
    for raw in request.args.getlist("cart_item_ids"):
        for piece in str(raw).split(","):
            piece = piece.strip()
            if piece and piece not in ids:
                ids.append(piece)
    return ids


@bp.get("/stores/<store_id>/menu-projection")
def menu_projection(store_id):
    ctx = auth.enter(PROJECTION_ROLES)
    auth.require_store_scope(ctx, store_id)
    store = path_row("stores", store_id)
    minute_override = _query_int("at_minute_of_day", 0, C.MINUTES_PER_DAY - 1)
    device = DB.devices.get(request.args.get("device_id") or "")
    cart_ids = _cart_item_ids()
    resolution = calc.resolve_daypart(store, minute_override)
    bundle = calc.resolved_bundle_for_store(store)
    zone_id = store.get("price_zone_id")
    items = []
    if bundle is not None:
        for item_id in bundle.get("snapshot_item_ids", []):
            item = DB.menu_items.get(item_id)
            if item is None:
                continue
            price = None
            for entry in bundle.get("price_snapshot", []):
                if entry["menu_item_id"] == item_id and entry["price_zone_id"] == zone_id:
                    price = entry["price_cents"]
                    break
            row = calc.availability_row(store["id"], item_id)
            items.append({
                "menu_item_id": item_id,
                "sku": item.get("sku"),
                "display_name": item.get("display_name"),
                "category": item.get("category"),
                # PRD 3.5: the board display price is read out of the bundle's frozen
                # price_snapshot, whose entries hold `price_cents`.
                "price_cents": price,
                "availability_state": row.get("availability_state") if row else "UNAVAILABLE",
            })
    campaign = calc.select_campaign(store)
    cart = [(item_id, 1) for item_id in cart_ids]
    suggestions = calc.eligible_upsell_rules(
        store, cart, bool(device.get("screen_reader_ok")) if device else False)
    data = {
        "store_id": store["id"],
        "local_minute_of_day": resolution["local_minute_of_day"],
        "daypart_code": resolution["daypart_code"],
        "layout_code": resolution["layout_code"],
        "phase": resolution["phase"],
        "resolved_bundle_id": bundle["id"] if bundle is not None else None,
        "resolved_bundle_version": bundle["bundle_version"] if bundle is not None else 0,
        "items": items,
        "stale_prices": bool(bundle.get("stale_flag")) if bundle is not None else False,
        "selected_campaign_version_id": campaign["id"] if campaign is not None else None,
        "suggested_upsell_rule_ids": [r["id"] for r in suggestions],
    }
    return response.ok(data)


@bp.get("/audit-events")
def list_audit_events():
    auth.enter(AUDIT_ROLES)
    limit, offset = response.read_pagination(request.args)
    rows = apply_filters(list(DB.audit_events), "audit_events")
    rows = sorted(rows, key=lambda r: r.get("sequence_no") or 0)
    return response.collection(serialize.dump_audits(rows), limit, offset)


@bp.post("/_clock/set_current_utc")
def set_clock():
    auth.enter(["PlatformAdmin"])
    data = shapes.body()
    current = shapes.req_instant(data, "current_utc")
    clockmod.set_now(current)
    # PRD 3.3: the system applies an approved request of its own accord once the
    # clock reaches its effective instant.  It is not one of the three counters.
    derive.auto_apply_due_requests()
    rescored = derive.rescore_all_devices()
    released = derive.release_expired_holds()
    advanced = derive.advance_all_campaigns()
    derive.reconcile()
    return response.ok({
        "current_utc": clockmod.now_iso(),
        "devices_rescored": rescored,
        "campaign_versions_advanced": advanced,
        "availabilities_released": released,
    })
