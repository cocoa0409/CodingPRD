"""Order capture, pricing and the kitchen handoff (PRD 3.9)."""
from flask import Blueprint

import auth
import calc
import constants as C
import derive
import logical_clock as clockmod
import response
import serialize
import shapes
from db import DB, append_audit, new_row, ordered, touch
from errors import fail
from routes.common import listing, path_row

bp = Blueprint("orders", __name__)

READ_ROLES = ("PlatformAdmin", "ContentManager", "ComplianceOfficer", "StoreOperator")
VERBS = ("KITCHEN_ACK", "VOID")


def _check_line_references(data):
    """Precedence 6: every ordered line's item and every accepted rule resolves."""
    lines = data.get("line_items")
    if isinstance(lines, list):
        for line in lines:
            if not isinstance(line, dict):
                continue
            item_id = line.get("menu_item_id")
            if isinstance(item_id, str) and item_id not in DB.menu_items:
                fail("ERR_REFERENCED_ENTITY_NOT_FOUND", "an ordered menu_item_id does not resolve")
    accepted = data.get("accepted_upsell_rule_ids")
    if isinstance(accepted, list):
        for rule_id in accepted:
            if isinstance(rule_id, str) and rule_id not in DB.upsell_rules:
                fail("ERR_REFERENCED_ENTITY_NOT_FOUND", "an accepted rule id does not resolve")


def _read_lines(data):
    raw = shapes.req_dict_array(data, "line_items", 1)
    lines = []
    seen = []
    for element in raw:
        item_id = shapes.req_str(element, "menu_item_id", 1, None)
        qty = shapes.req_int(element, "qty", 1, 99)
        if item_id in seen:
            fail("ERR_INVALID_REQUEST", "line_items must not repeat a menu item")
        seen.append(item_id)
        lines.append({"menu_item_id": item_id, "qty": qty})
    return lines


def _next_order_number(store):
    today = clockmod.date_str(clockmod.now())
    if store.get("seq_counter_date") != today:
        store["daily_order_seq_counter"] = 0
        store["seq_counter_date"] = today
    nxt = int(store.get("daily_order_seq_counter", 0)) + 1
    store["daily_order_seq_counter"] = nxt
    return calc.order_number_for(store.get("store_code"), nxt)


@bp.post("/devices/<device_id>/orders")
def capture_order(device_id):
    ctx = auth.enter(["DeviceAgent", "StoreOperator"])
    auth.require_device_identity(ctx, device_id)
    device = DB.devices.get(device_id)
    if device is not None:
        auth.require_store_scope(ctx, device.get("store_id"))
    device = path_row("devices", device_id)
    data = shapes.body()
    _check_line_references(data)
    lines = _read_lines(data)
    tender = shapes.req_enum(data, "tender_kind", C.TENDER_KINDS)
    accepted = shapes.opt_str_array(data, "accepted_upsell_rule_ids", [])
    offline = shapes.opt_bool(data, "created_offline", False)
    store = DB.stores.get(device.get("store_id"))
    zone = DB.price_zones.get(store.get("price_zone_id")) if store is not None else None

    bundle = DB.bundles.get(device.get("cached_bundle_id"))
    if device.get("cached_bundle_id") and (bundle is None or bundle.get("state") != "PUBLISHED"):
        fail("ERR_BUNDLE_NOT_PUBLISHED", "the device's cached bundle is not published")
    if store is not None and store.get("content_posture") == "FROZEN":
        fail("ERR_STORE_CONTENT_FROZEN", "the store's content posture is FROZEN")
    if device.get("health_state") not in ("ONLINE", "DEGRADED") or device.get("cache_state") == "MISSING":
        fail("ERR_DEVICE_NOT_OPERATIONAL", "the device may not take orders")
    if tender == "CARD" and device.get("payment_compliance_state") not in ("COMPLIANT", "EXPIRING"):
        fail("ERR_PAYMENT_DEVICE_NON_COMPLIANT", "the payment device is not compliant")
    if offline and int(device.get("offline_order_count", 0)) >= int(device.get("offline_cache_capacity", 0)):
        fail("ERR_OFFLINE_CACHE_CAPACITY_EXCEEDED", "the device holds too many offline orders")
    snapshot_ids = bundle.get("snapshot_item_ids") if bundle else []
    for line in lines:
        if line["menu_item_id"] not in (snapshot_ids or []):
            fail("ERR_ITEM_NOT_IN_PUBLISHED_BUNDLE", "an ordered item is absent from the snapshot")
    cart_ids = [line["menu_item_id"] for line in lines]
    chain = calc.store_chain_ids(store) if store is not None else []
    for rule_id in accepted:
        rule = DB.upsell_rules.get(rule_id)
        if (rule is None or rule.get("state") != "ACTIVE" or rule.get("cluster_id") not in chain
                or rule.get("trigger_item_id") not in cart_ids
                or rule.get("suggested_item_id") not in cart_ids):
            fail("ERR_UPSELL_RULE_NOT_ELIGIBLE", "an accepted upsell rule is not eligible")
    rows = {}
    for line in lines:
        row = calc.availability_row(store["id"], line["menu_item_id"]) if store else None
        if row is None or row.get("availability_state") == "UNAVAILABLE":
            fail("ERR_ITEM_EIGHTY_SIXED", "an ordered item is unavailable at this store")
        rows[line["menu_item_id"]] = row

    campaign = calc.select_campaign(store) if store is not None else None
    priced = []
    for line in lines:
        item = DB.menu_items[line["menu_item_id"]]
        unit = calc.effective_zone_price(item, zone) if zone is not None else 0
        gross = unit * line["qty"]
        discount = 0
        if campaign is not None:
            if campaign["discount_kind"] == "PERCENT_OFF":
                discount = calc.apply_bp(gross, campaign["discount_value"])
            else:
                discount = min(int(campaign["discount_value"]) * line["qty"], gross)
        priced.append({
            "menu_item_id": line["menu_item_id"],
            "qty": line["qty"],
            "unit_price_cents": unit,
            "gross_line_cents": gross,
            "line_discount_cents": discount,
        })
    subtotal = sum(p["gross_line_cents"] for p in priced)
    discount_total = sum(p["line_discount_cents"] for p in priced)
    net = subtotal - discount_total
    tax = calc.apply_bp(net, zone["tax_rate_bp"]) if zone is not None else 0
    total = net + tax

    order_number = _next_order_number(store)
    touch(store)
    pinned = int(device.get("cached_bundle_version") or 0)
    resolution = calc.resolve_daypart(store)
    order = new_row({
        "device_id": device["id"],
        "applied_campaign_version_id": campaign["id"] if campaign is not None else None,
        "order_number": order_number,
        "line_items": lines,
        "priced_lines": priced,
        "subtotal_cents": subtotal,
        "discount_cents": discount_total,
        "tax_cents": tax,
        "total_cents": total,
        "tender_kind": tender,
        "payment_state": "AUTHORIZED",
        "handoff_state": "CACHED_OFFLINE" if offline else "QUEUED_TO_KITCHEN",
        "created_offline": offline,
        "accepted_upsell_rule_ids": accepted,
        "daypart_code": resolution["daypart_code"],
        "pinned_bundle_version": pinned,
        "receipt_hash": calc.receipt_hash(order_number, subtotal, discount_total, tax, total, pinned),
    })
    DB.orders[order["id"]] = order
    if offline:
        derive.recompute_offline_order_count(device)
    for line in lines:
        row = rows[line["menu_item_id"]]
        derive.adjust_reservation(row, line["qty"])
        if row["available_units"] <= 0 and row.get("listing_state") == "LISTED":
            derive.auto_eighty_six(row, ctx["role"], ctx["user_id"])
        else:
            derive.availability_cascade(row)
    derive.recompute_store(store)
    derive.reconcile()
    return response.created(serialize.dump("order", order))


@bp.get("/order-handoffs")
def list_orders():
    auth.enter(READ_ROLES)
    return listing("orders", "order")


@bp.get("/order-handoffs/<order_id>")
def get_order(order_id):
    ctx = auth.enter(READ_ROLES + ("DeviceAgent",))
    row = DB.orders.get(order_id)
    if row is not None:
        auth.require_store_scope(ctx, auth.store_of_device(row.get("device_id")))
    row = path_row("orders", order_id)
    return response.ok(serialize.dump("order", row))


@bp.post("/order-handoffs/<order_id>/actions")
def drive_order(order_id):
    ctx = auth.enter(["StoreOperator", "PlatformAdmin"])
    row = DB.orders.get(order_id)
    if row is not None:
        auth.require_store_scope(ctx, auth.store_of_device(row.get("device_id")))
    row = path_row("orders", order_id)
    data = shapes.body()
    action = shapes.req_enum(data, "action", VERBS)
    if row.get("handoff_state") == "VOIDED":
        fail("ERR_ALREADY_TERMINAL", "the order handoff is already voided")
    device = DB.devices.get(row.get("device_id"))
    store = DB.stores.get(device.get("store_id")) if device is not None else None

    if action == "KITCHEN_ACK":
        if row.get("handoff_state") != "QUEUED_TO_KITCHEN":
            fail("ERR_INVALID_STATE_TRANSITION",
                 "KITCHEN_ACK is not declared out of %s" % row.get("handoff_state"))
        derive.apply_changes(row, {"handoff_state": "ACCEPTED", "payment_state": "CAPTURED"})
        append_audit("ORDER_HANDOFF", row["id"], "ORDER_ACCEPTED_BY_KITCHEN", ctx["role"],
                     ctx["user_id"], detail="KITCHEN_ACKNOWLEDGED")
        if store is not None:
            derive.recompute_store(store)
    else:  # VOID
        reason = shapes.opt_str(data, "void_reason", 1, 280, None)
        if row.get("handoff_state") not in ("QUEUED_TO_KITCHEN", "CACHED_OFFLINE", "ACCEPTED"):
            fail("ERR_INVALID_STATE_TRANSITION",
                 "VOID is not declared out of %s" % row.get("handoff_state"))
        was_offline = row.get("handoff_state") == "CACHED_OFFLINE"
        derive.apply_changes(row, {"handoff_state": "VOIDED", "payment_state": "VOIDED"})
        for line in row.get("priced_lines", []):
            availability = calc.availability_row(
                store["id"], line["menu_item_id"]) if store is not None else None
            if availability is None:
                continue
            derive.adjust_reservation(availability, -int(line["qty"]))
            derive.availability_cascade(availability)
        if was_offline and device is not None:
            derive.recompute_offline_order_count(device)
        append_audit("ORDER_HANDOFF", row["id"], "ORDER_VOIDED", ctx["role"], ctx["user_id"],
                     detail=reason, before_value_cents=row.get("total_cents"),
                     after_value_cents=0)
        if store is not None:
            derive.recompute_store(store)
        derive.reconcile()

    return response.ok(serialize.dump("order", row))
