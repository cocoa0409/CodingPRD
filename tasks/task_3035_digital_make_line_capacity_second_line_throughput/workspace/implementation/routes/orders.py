"""Order placement, lifecycle transitions, accuracy verification, and queries."""

from decimal import Decimal
from datetime import timedelta

from flask import Blueprint, request

from db import db
from errors import (
    raise_error, ERR_INVALID_REQUEST, ERR_INVALID_STATE, ERR_ALREADY_TERMINAL,
    ERR_ITEM_SUPPRESSED, ERR_INSUFFICIENT_INGREDIENT, ERR_LINE_CAPACITY_EXCEEDED,
    ERR_ACCURACY_UNVERIFIED, ERR_MARKETPLACE_REFERENCE_INVALID, ERR_CHANNEL_NOT_FOUND,
    ERR_NOT_FOUND,
)
from middleware import require_roles
from response import success_object, success_list
from services.core import (
    new_resource, touch, parse_iso, iso_str, round_half_up,
    parse_pagination, paginate, require_fields, require_int,
    get_store_or_404, get_order_or_404, get_menu_item_or_404,
    current_window, recompute_throttle, sync_interval_loads,
    line_required_grams, available_grams, consume_fifo,
    evaluate_shortage, update_food_cost_variance,
)

bp = Blueprint("orders", __name__)

ALL_READ_ROLES = ("PlatformAdmin", "StoreManager", "GeneralManager", "LineWorker")
VALID_CHANNELS = ("FIRST_PARTY_DIGITAL", "IN_STORE", "MARKETPLACE")
TERMINAL_FULFILLMENT = ("PICKED_UP", "CANCELLED", "EXPIRED")

_lid_counter = [0]


def _mint_lid_label():
    _lid_counter[0] += 1
    return f"LID-{_lid_counter[0]:06d}"


# ---------------------------------------------------------------------------
# Order placement
# ---------------------------------------------------------------------------

@bp.post("/stores/<store_id>/orders")
def place_order(store_id):
    user_id, role = require_roles("LineWorker", "StoreManager", "MarketplaceChannel")
    store = get_store_or_404(store_id)
    payload = request.get_json(silent=True) or {}
    require_fields(payload, ["channel", "lines"])
    channel = payload["channel"]
    if channel not in VALID_CHANNELS:
        raise_error(ERR_INVALID_REQUEST, f"channel must be one of {VALID_CHANNELS}")

    # LineWorker may only place IN_STORE orders.
    if role == "LineWorker" and channel != "IN_STORE":
        from errors import ERR_FORBIDDEN_ROLE
        raise_error(ERR_FORBIDDEN_ROLE, "LineWorker may only place IN_STORE orders")
    # MarketplaceChannel injects marketplace orders under its own identity.
    if role == "MarketplaceChannel" and channel != "MARKETPLACE":
        from errors import ERR_FORBIDDEN_ROLE
        raise_error(ERR_FORBIDDEN_ROLE, "MarketplaceChannel may only place MARKETPLACE orders")

    lines_payload = payload["lines"]
    if not isinstance(lines_payload, list) or not lines_payload:
        raise_error(ERR_INVALID_REQUEST, "lines must be a non-empty array")

    # Marketplace identity + reference validation (priority 13 in scaffold, but
    # must occur before business checks since it determines pricing/identity).
    marketplace_channel = None
    external_ref = None
    if channel == "MARKETPLACE":
        mcid = payload.get("marketplace_channel_id")
        external_ref = payload.get("external_order_ref")
        if not mcid or not isinstance(mcid, str):
            raise_error(ERR_MARKETPLACE_REFERENCE_INVALID,
                        "MARKETPLACE order requires marketplace_channel_id")
        marketplace_channel = db.marketplace_channels.get(mcid)
        if marketplace_channel is None:
            raise_error(ERR_CHANNEL_NOT_FOUND, f"Marketplace channel {mcid} not found")
        if role == "MarketplaceChannel" and user_id != mcid:
            from errors import ERR_FORBIDDEN_ROLE
            raise_error(ERR_FORBIDDEN_ROLE,
                        "MarketplaceChannel may only inject orders under its own channel identity")
        if not external_ref or not isinstance(external_ref, str):
            raise_error(ERR_MARKETPLACE_REFERENCE_INVALID,
                        "MARKETPLACE order requires external_order_ref")
        if not marketplace_channel.get("active", True):
            raise_error(ERR_MARKETPLACE_REFERENCE_INVALID,
                        "Marketplace channel is not active")
        for o in db.orders.values():
            if (o["channel"] == "MARKETPLACE"
                    and o.get("marketplace_channel_id") == mcid
                    and o.get("external_order_ref") == external_ref):
                raise_error(ERR_MARKETPLACE_REFERENCE_INVALID,
                            "external_order_ref duplicated within channel")
    else:
        if payload.get("marketplace_channel_id") is not None or payload.get("external_order_ref") is not None:
            raise_error(ERR_MARKETPLACE_REFERENCE_INVALID,
                        "marketplace_channel_id and external_order_ref are only valid for MARKETPLACE orders")

    # Build and validate lines.
    order_lines = []
    for idx, lp in enumerate(lines_payload):
        if not isinstance(lp, dict):
            raise_error(ERR_INVALID_REQUEST, f"lines[{idx}] must be an object")
        if "menu_item_id" not in lp or "quantity" not in lp:
            raise_error(ERR_INVALID_REQUEST, f"lines[{idx}] requires menu_item_id and quantity")
        item = db.menu_items.get(lp["menu_item_id"])
        if item is None or item["store_id"] != store["id"]:
            from errors import ERR_MENU_ITEM_NOT_FOUND
            raise_error(ERR_MENU_ITEM_NOT_FOUND, f"Menu item {lp['menu_item_id']} not found")
        qty = lp["quantity"]
        if isinstance(qty, bool) or not isinstance(qty, int) or qty < 1:
            raise_error(ERR_INVALID_REQUEST, f"lines[{idx}].quantity must be an integer >= 1")
        customizations = lp.get("customizations", [])
        if not isinstance(customizations, list):
            raise_error(ERR_INVALID_REQUEST, f"lines[{idx}].customizations must be an array")
        for c in customizations:
            if not isinstance(c, dict) or "ingredient_id" not in c or "action" not in c:
                raise_error(ERR_INVALID_REQUEST, "customization entries require ingredient_id and action")
            if c["action"] not in ("EXTRA", "LIGHT", "NONE", "SUB"):
                raise_error(ERR_INVALID_REQUEST, "customization action must be EXTRA, LIGHT, NONE, or SUB")
            if c["action"] == "SUB" and not c.get("sub_ingredient_id"):
                raise_error(ERR_INVALID_REQUEST, "SUB customization requires sub_ingredient_id")
        order_lines.append({"item": item, "quantity": qty, "customizations": customizations})

    # Digital eligibility check for digital-channel orders.
    line_kind = "DIGITAL" if channel in ("FIRST_PARTY_DIGITAL", "MARKETPLACE") else "IN_STORE"
    if line_kind == "DIGITAL":
        for ol in order_lines:
            if not ol["item"].get("is_digital_eligible", True):
                raise_error(ERR_ITEM_SUPPRESSED,
                            f"Menu item {ol['item']['item_code']} is not digital eligible")

    entree_count = sum(ol["quantity"] for ol in order_lines)

    # --- Acceptance chain (priority: suppression -> ingredient -> capacity) ---

    # 1. Suppression screening
    for ol in order_lines:
        state = ol["item"]["suppression_state"]
        blocked = False
        if state == "SUPPRESSED_ALL":
            blocked = True
        elif state == "SUPPRESSED_MARKETPLACE" and channel == "MARKETPLACE":
            blocked = True
        elif state == "SUPPRESSED_DIGITAL" and line_kind == "DIGITAL":
            blocked = True
        if blocked:
            raise_error(ERR_ITEM_SUPPRESSED,
                        f"Menu item {ol['item']['item_code']} is suppressed for channel {channel}")

    # 2. Ingredient sufficiency (aggregate requirements across all lines)
    required_total = {}
    line_requirements = []
    for ol in order_lines:
        req = line_required_grams({
            "menu_item_id": ol["item"]["id"],
            "quantity": ol["quantity"],
            "customizations": ol["customizations"],
        })
        line_requirements.append(req)
        for ing_id, grams in req.items():
            required_total[ing_id] = required_total.get(ing_id, 0) + grams
    for ing_id, grams in required_total.items():
        if available_grams(ing_id) < grams:
            raise_error(ERR_INSUFFICIENT_INGREDIENT,
                        f"Insufficient grams for ingredient {ing_id}")

    # 3. Capacity waterfall / in-store capacity check
    placed_at = db.clock
    selected_window = None
    promised_at = None
    if line_kind == "DIGITAL":
        throttled = store["throttle_state"] in ("THROTTLED", "CLOSED")
        cw = current_window(store)
        candidates = [
            w for w in db.production_windows.values()
            if w["store_id"] == store["id"] and w["status"] == "OPEN"
            and parse_iso(w["interval_end"]) > placed_at
            and w["digital_committed"] + entree_count <= w["digital_capacity"]
        ]
        candidates.sort(key=lambda w: (parse_iso(w["interval_start"]), w["created_at"], w["id"]))
        if throttled and cw is not None:
            candidates = [w for w in candidates if w["id"] != cw["id"]]
        if not candidates:
            raise_error(ERR_LINE_CAPACITY_EXCEEDED,
                        "No OPEN production window can absorb this order")
        selected_window = candidates[0]
        promised_at = selected_window["interval_end"]
    else:
        # IN_STORE: no waterfall; promise = placed_at + instore_promise_minutes.
        promised_dt = placed_at + timedelta(minutes=store["instore_promise_minutes"])
        promised_at = iso_str(promised_dt)
        # In-store orders count against the current window's instore_committed.
        cw = current_window(store)
        if cw is not None:
            if cw["instore_committed"] + entree_count > store["instore_line_capacity_per_interval"]:
                raise_error(ERR_LINE_CAPACITY_EXCEEDED,
                            "In-store line capacity exceeded in current window")
            selected_window = cw

    # --- Commit ---
    order = new_resource()
    order.update({
        "store_id": store["id"],
        "channel": channel,
        "marketplace_channel_id": marketplace_channel["id"] if marketplace_channel else None,
        "external_order_ref": external_ref,
        "promised_at": promised_at,
        "placed_at": iso_str(placed_at),
        "line": line_kind,
        "production_window_id": selected_window["id"] if selected_window else None,
        "subtotal_cents": 0,
        "commission_cents": 0,
        "net_revenue_cents": 0,
        "theoretical_cost_cents": 0,
        "entree_count": entree_count,
        "payment_status": "AUTHORIZED",
        "fulfillment_status": "ACCEPTED",
        "accuracy_status": "UNVERIFIED",
    })

    # Pricing per PRD 3.2 / calc marketplace_net_revenue
    subtotal = 0
    commission = 0
    theoretical = 0
    persisted_lines = []
    for ol in order_lines:
        item = ol["item"]
        qty = ol["quantity"]
        if channel == "MARKETPLACE":
            unit_price = round_half_up(
                Decimal(str(item["base_price_cents"])) * (Decimal("1") + Decimal(str(marketplace_channel["markup_pct"])))
            )
            gross_line = unit_price * qty
            commission_line = round_half_up(
                Decimal(str(gross_line)) * Decimal(str(marketplace_channel["commission_pct"]))
            )
        else:
            unit_price = item["base_price_cents"]
            gross_line = unit_price * qty
            commission_line = 0
        subtotal += gross_line
        commission += commission_line
        theoretical += item["theoretical_cost_cents"] * qty

        line = new_resource()
        line.update({
            "order_id": order["id"],
            "menu_item_id": item["id"],
            "quantity": qty,
            "unit_price_cents": unit_price,
            "customizations": ol["customizations"],
            "lid_label_code": _mint_lid_label(),
            "accuracy_check": "PENDING",
        })
        db.order_lines[line["id"]] = line
        persisted_lines.append(line)

    order["subtotal_cents"] = subtotal
    order["commission_cents"] = commission
    order["net_revenue_cents"] = subtotal - commission
    order["theoretical_cost_cents"] = theoretical
    db.orders[order["id"]] = order

    # FIFO consumption + window/store commitment
    consumed = {}  # ingredient_id -> grams consumed (for pickup actual-cost and cancel restore)
    for req in line_requirements:
        for ing_id, grams in req.items():
            consume_fifo(ing_id, grams)
            ingredient = db.ingredients[ing_id]
            ingredient["on_hand_grams"] -= grams
            touch(ingredient)
            consumed[ing_id] = consumed.get(ing_id, 0) + grams
    order["_consumed_grams"] = consumed

    if selected_window is not None:
        if line_kind == "DIGITAL":
            selected_window["digital_committed"] += entree_count
        else:
            selected_window["instore_committed"] += entree_count
        touch(selected_window)

    sync_interval_loads(store)
    recompute_throttle(store)
    # Threshold crossings may fire suppression cascade.
    for ing_id in consumed:
        evaluate_shortage(db.ingredients[ing_id])

    return success_object(_public_order(order), 201)


# ---------------------------------------------------------------------------
# Order queries
# ---------------------------------------------------------------------------

@bp.get("/stores/<store_id>/orders")
def list_orders_for_store(store_id):
    require_roles(*ALL_READ_ROLES)
    store = get_store_or_404(store_id)
    limit, offset = parse_pagination(request.args)
    items = [o for o in db.orders.values() if o["store_id"] == store["id"]]
    items = _filter_orders(items, request.args)
    items, total = paginate(items, limit, offset)
    return success_list([_public_order(o) for o in items], total, limit, offset)


@bp.get("/orders/<order_id>")
def get_order(order_id):
    require_roles(*ALL_READ_ROLES)
    order = get_order_or_404(order_id)
    return success_object(_public_order(order))


@bp.get("/orders")
def list_orders():
    require_roles(*ALL_READ_ROLES)
    limit, offset = parse_pagination(request.args)
    items = list(db.orders.values())
    store_id = request.args.get("store_id")
    if store_id:
        items = [o for o in items if o["store_id"] == store_id]
    mcid = request.args.get("marketplace_channel_id")
    if mcid:
        items = [o for o in items if o.get("marketplace_channel_id") == mcid]
    pwid = request.args.get("production_window_id")
    if pwid:
        items = [o for o in items if o.get("production_window_id") == pwid]
    items = _filter_orders(items, request.args)
    items, total = paginate(items, limit, offset)
    return success_list([_public_order(o) for o in items], total, limit, offset)


def _filter_orders(items, args):
    channel = args.get("channel")
    if channel:
        items = [o for o in items if o["channel"] == channel]
    fulfillment = args.get("fulfillment_status")
    if fulfillment:
        items = [o for o in items if o["fulfillment_status"] == fulfillment]
    payment = args.get("payment_status")
    if payment:
        items = [o for o in items if o["payment_status"] == payment]
    return items


def _public_order(order):
    return {k: v for k, v in order.items() if not k.startswith("_")}


@bp.get("/orders/<order_id>/lines")
def list_order_lines(order_id):
    require_roles(*ALL_READ_ROLES)
    order = get_order_or_404(order_id)
    limit, offset = parse_pagination(request.args)
    items = [l for l in db.order_lines.values() if l["order_id"] == order["id"]]
    items, total = paginate(items, limit, offset)
    return success_list(items, total, limit, offset)


@bp.get("/order-lines")
def list_all_order_lines():
    require_roles(*ALL_READ_ROLES)
    limit, offset = parse_pagination(request.args)
    items = list(db.order_lines.values())
    order_id = request.args.get("order_id")
    menu_item_id = request.args.get("menu_item_id")
    if order_id:
        items = [l for l in items if l["order_id"] == order_id]
    if menu_item_id:
        items = [l for l in items if l["menu_item_id"] == menu_item_id]
    items, total = paginate(items, limit, offset)
    return success_list(items, total, limit, offset)


@bp.get("/order-lines/<line_id>")
def get_order_line(line_id):
    require_roles(*ALL_READ_ROLES)
    line = db.order_lines.get(line_id)
    if line is None:
        raise_error(ERR_NOT_FOUND, f"Order line {line_id} not found")
    return success_object(line)


# ---------------------------------------------------------------------------
# Order lifecycle transitions
# ---------------------------------------------------------------------------

def _order_transition(store_id, order_id, allowed_from, terminal_check=True):
    store = get_store_or_404(store_id)
    order = get_order_or_404(order_id, store_id=store["id"])
    status = order["fulfillment_status"]
    if terminal_check and status in TERMINAL_FULFILLMENT:
        raise_error(ERR_ALREADY_TERMINAL, f"Order is in terminal state {status}")
    if status not in allowed_from:
        raise_error(ERR_INVALID_STATE,
                    f"Order must be in {allowed_from}, is {status}")
    return store, order


@bp.post("/stores/<store_id>/orders/<order_id>/start-production")
def start_production(store_id, order_id):
    require_roles("LineWorker")
    store, order = _order_transition(store_id, order_id, ("ACCEPTED",))
    # Staffing deployment gate
    dep = None
    for d in db.deployments.values():
        if (d["store_id"] == store["id"]
                and d["shift_date"] == store["current_business_day"]
                and d["status"] in ("PUBLISHED", "LOCKED")):
            dep = d
            break
    if dep is None:
        from errors import ERR_DEPLOYMENT_MISSING
        raise_error(ERR_DEPLOYMENT_MISSING,
                    "No PUBLISHED/LOCKED staffing deployment for the current business day")
    order["fulfillment_status"] = "IN_PRODUCTION"
    if order["payment_status"] == "AUTHORIZED":
        order["payment_status"] = "CAPTURED"
    touch(order)
    return success_object(_public_order(order), 200)


@bp.post("/stores/<store_id>/orders/<order_id>/verify-accuracy")
def verify_accuracy(store_id, order_id):
    user_id, _ = require_roles("LineWorker")
    store, order = _order_transition(store_id, order_id, ("IN_PRODUCTION",))
    payload = request.get_json(silent=True) or {}
    require_fields(payload, ["line_results"])
    line_results = payload["line_results"]
    if not isinstance(line_results, list):
        raise_error(ERR_INVALID_REQUEST, "line_results must be an array")

    lines = [l for l in db.order_lines.values() if l["order_id"] == order["id"]]
    lines.sort(key=lambda l: (l["created_at"], l["id"]))

    # Interpret per-line results. A dict entry may identify its line by
    # line_id / order_line_id / id / menu_item_id; or the caller may submit
    # positional booleans in line order. An entry that reports a mismatch but
    # identifies no line of this order still makes the pass FAIL (one
    # mismatched line is counted) without flagging a specific line.
    mismatched_ids = set()
    unidentified_mismatches = 0
    positional_bools = [e for e in line_results if isinstance(e, bool)]
    dict_entries = [e for e in line_results if isinstance(e, dict)]
    if dict_entries:
        for entry in dict_entries:
            lid = (entry.get("line_id") or entry.get("order_line_id")
                   or entry.get("id") or entry.get("menu_item_id"))
            matched = entry.get("matched", entry.get("match", entry.get("passed", True)))
            result_val = entry.get("result")
            if isinstance(result_val, str):
                matched = result_val.upper() in ("MATCH", "MATCHED", "PASS")
            if not matched:
                target = None
                if lid is not None:
                    for line in lines:
                        if line["id"] == lid or line["menu_item_id"] == lid:
                            target = line
                            break
                if target is not None:
                    mismatched_ids.add(target["id"])
                else:
                    unidentified_mismatches += 1
    elif positional_bools and len(positional_bools) == len(lines):
        for line, ok in zip(lines, positional_bools):
            if not ok:
                mismatched_ids.add(line["id"])

    checked = len(lines)
    mismatched = unidentified_mismatches
    for line in lines:
        if line["id"] in mismatched_ids:
            line["accuracy_check"] = "MISMATCHED"
            mismatched += 1
            touch(line)
        else:
            line["accuracy_check"] = "MATCHED"
            touch(line)

    if mismatched == 0:
        result = "PASS"
        order["accuracy_status"] = "VERIFIED"
    else:
        result = "FAIL"
        order["accuracy_status"] = "MISMATCHED"
    touch(order)

    ver = new_resource()
    ver.update({
        "order_id": order["id"],
        "verified_by": user_id,
        "checked_components": checked,
        "mismatched_lines": mismatched,
        "result": result,
        "created_at_note": f"pass-{len([v for v in db.verifications.values() if v['order_id'] == order['id']]) + 1}",
    })
    db.verifications[ver["id"]] = ver
    return success_object(ver, 200)


@bp.post("/stores/<store_id>/orders/<order_id>/mark-ready")
def mark_ready(store_id, order_id):
    require_roles("LineWorker")
    store, order = _order_transition(store_id, order_id, ("IN_PRODUCTION",))
    lines = [l for l in db.order_lines.values() if l["order_id"] == order["id"]]
    has_pass = any(
        v["order_id"] == order["id"] and v["result"] == "PASS"
        for v in db.verifications.values()
    )
    all_matched = all(l["accuracy_check"] == "MATCHED" for l in lines) and lines
    if not (has_pass and all_matched):
        raise_error(ERR_ACCURACY_UNVERIFIED,
                    "mark-ready requires every OrderLine MATCHED and at least one PASS verification")
    order["fulfillment_status"] = "READY"
    touch(order)
    return success_object(_public_order(order), 200)


@bp.post("/stores/<store_id>/orders/<order_id>/pickup")
def pickup(store_id, order_id):
    require_roles("LineWorker")
    store, order = _order_transition(store_id, order_id, ("READY",))

    # Release interval load and window commitment
    w = db.production_windows.get(order.get("production_window_id"))
    if w is not None:
        if order["line"] == "DIGITAL":
            w["digital_committed"] = max(0, w["digital_committed"] - order["entree_count"])
            w["digital_completed"] += order["entree_count"]
        else:
            w["instore_committed"] = max(0, w["instore_committed"] - order["entree_count"])
        touch(w)

    # Post theoretical + actual food cost
    store["theoretical_food_cost_cents"] += order["theoretical_cost_cents"]
    actual_cents = 0
    for ing_id, grams in (order.get("_consumed_grams") or {}).items():
        ing = db.ingredients[ing_id]
        actual_cents += round_half_up(Decimal(str(grams)) * Decimal(str(ing["unit_cost_cents_per_gram"])))
    store["actual_food_cost_cents"] += actual_cents
    touch(store)
    update_food_cost_variance(store)

    order["fulfillment_status"] = "PICKED_UP"
    touch(order)

    sync_interval_loads(store)
    recompute_throttle(store)
    return success_object(_public_order(order), 200)


@bp.post("/stores/<store_id>/orders/<order_id>/cancel")
def cancel_order(store_id, order_id):
    require_roles("StoreManager")
    store, order = _order_transition(store_id, order_id, ("PLACED", "ACCEPTED"))

    # Release capacity
    w = db.production_windows.get(order.get("production_window_id"))
    if w is not None:
        if order["line"] == "DIGITAL":
            w["digital_committed"] = max(0, w["digital_committed"] - order["entree_count"])
        else:
            w["instore_committed"] = max(0, w["instore_committed"] - order["entree_count"])
        touch(w)

    # Restore consumed grams to the newest ACTIVE batch per ingredient
    for ing_id, grams in (order.get("_consumed_grams") or {}).items():
        ingredient = db.ingredients[ing_id]
        batches = [
            b for b in db.batches.values()
            if b["ingredient_id"] == ing_id and b["status"] == "ACTIVE"
        ]
        if batches:
            # newest ACTIVE batch: created_at DESC, tie-break latest cooked_at
            batches.sort(key=lambda b: (b["created_at"], parse_iso(b["cooked_at"])), reverse=True)
            batches[0]["grams_remaining"] += grams
            touch(batches[0])
        ingredient["on_hand_grams"] += grams
        touch(ingredient)

    order["fulfillment_status"] = "CANCELLED"
    order["payment_status"] = "VOIDED"
    touch(order)

    sync_interval_loads(store)
    recompute_throttle(store)
    for ing_id in (order.get("_consumed_grams") or {}):
        evaluate_shortage(db.ingredients[ing_id])
    return success_object(_public_order(order), 200)


# ---------------------------------------------------------------------------
# Verifications
# ---------------------------------------------------------------------------

@bp.get("/orders/<order_id>/verifications")
def list_verifications_for_order(order_id):
    require_roles(*ALL_READ_ROLES)
    order = get_order_or_404(order_id)
    limit, offset = parse_pagination(request.args)
    items = [v for v in db.verifications.values() if v["order_id"] == order["id"]]
    items, total = paginate(items, limit, offset)
    return success_list(items, total, limit, offset)


@bp.get("/verifications")
def list_verifications():
    require_roles(*ALL_READ_ROLES)
    limit, offset = parse_pagination(request.args)
    items = list(db.verifications.values())
    order_id = request.args.get("order_id")
    if order_id:
        items = [v for v in items if v["order_id"] == order_id]
    items, total = paginate(items, limit, offset)
    return success_list(items, total, limit, offset)


@bp.get("/verifications/<verification_id>")
def get_verification(verification_id):
    require_roles(*ALL_READ_ROLES)
    v = db.verifications.get(verification_id)
    if v is None:
        raise_error(ERR_NOT_FOUND, f"Verification {verification_id} not found")
    return success_object(v)
