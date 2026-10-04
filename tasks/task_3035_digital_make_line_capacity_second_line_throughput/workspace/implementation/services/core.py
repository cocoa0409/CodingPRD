"""Core domain helpers: entity creation, serialization, pagination,
logical-clock driven transitions, throttle evaluation, suppression cascade,
FIFO consumption, and food-cost accounting."""

import math
import uuid
from datetime import datetime, timezone, timedelta
from decimal import Decimal, ROUND_HALF_UP

from db import db, fresh_timestamp
from errors import raise_error, ERR_INVALID_REQUEST


# ---------------------------------------------------------------------------
# Generic helpers
# ---------------------------------------------------------------------------

def new_id():
    return str(uuid.uuid4())


def new_resource():
    ts = fresh_timestamp()
    return {
        "id": new_id(),
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
    }


def touch(resource):
    """Bump version and updated_at on a mutated resource."""
    resource["version"] += 1
    resource["updated_at"] = fresh_timestamp()


def round_half_up(value):
    """Round a Decimal/float to the nearest integer, half-up."""
    return int(Decimal(str(value)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def parse_iso(s):
    """Parse an ISO-8601 datetime string into an aware datetime (UTC)."""
    if not isinstance(s, str):
        raise_error(ERR_INVALID_REQUEST, "Expected ISO-8601 datetime string")
    v = s.strip()
    if v.endswith("Z"):
        v = v[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(v)
    except ValueError:
        raise_error(ERR_INVALID_REQUEST, f"Invalid ISO-8601 datetime: {s}")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def iso_str(dt):
    """Format an aware datetime as ISO-8601 UTC with Z suffix, seconds precision
    (or millisecond precision if microseconds are set)."""
    dt = dt.astimezone(timezone.utc)
    if dt.microsecond:
        return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_pagination(args):
    """Read limit/offset query params with defaults per PRD 2.3."""
    limit_raw = args.get("limit")
    offset_raw = args.get("offset")
    if limit_raw is None:
        limit = 10
    else:
        try:
            limit = int(limit_raw)
        except (TypeError, ValueError):
            raise_error(ERR_INVALID_REQUEST, "limit must be an integer")
    if offset_raw is None:
        offset = 0
    else:
        try:
            offset = int(offset_raw)
        except (TypeError, ValueError):
            raise_error(ERR_INVALID_REQUEST, "offset must be an integer")
    if limit < 1 or limit > 100:
        raise_error(ERR_INVALID_REQUEST, "limit must be between 1 and 100")
    if offset < 0:
        raise_error(ERR_INVALID_REQUEST, "offset must be >= 0")
    return limit, offset


def paginate(items, limit, offset):
    """Sort by created_at ASC (id tiebreak), then slice."""
    items = sorted(items, key=lambda r: (r.get("created_at", ""), r.get("id", "")))
    total = len(items)
    return items[offset:offset + limit], total


def require_fields(payload, fields):
    if not isinstance(payload, dict):
        raise_error(ERR_INVALID_REQUEST, "Request body must be a JSON object")
    for f in fields:
        if f not in payload or payload[f] is None:
            raise_error(ERR_INVALID_REQUEST, f"Missing required field: {f}")


def require_int(payload, field, minimum=None):
    v = payload.get(field)
    if isinstance(v, bool) or not isinstance(v, int):
        raise_error(ERR_INVALID_REQUEST, f"Field {field} must be an integer")
    if minimum is not None and v < minimum:
        raise_error(ERR_INVALID_REQUEST, f"Field {field} must be >= {minimum}")
    return v


def require_number(payload, field):
    v = payload.get(field)
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        raise_error(ERR_INVALID_REQUEST, f"Field {field} must be a number")
    return v


def require_string(payload, field):
    v = payload.get(field)
    if not isinstance(v, str) or not v:
        raise_error(ERR_INVALID_REQUEST, f"Field {field} must be a non-empty string")
    return v


# ---------------------------------------------------------------------------
# Store lookups
# ---------------------------------------------------------------------------

def get_store_or_404(store_id):
    from errors import ERR_STORE_NOT_FOUND
    store = db.stores.get(store_id)
    if store is None:
        raise_error(ERR_STORE_NOT_FOUND, f"Store {store_id} not found")
    return store


def get_order_or_404(order_id, store_id=None):
    from errors import ERR_ORDER_NOT_FOUND
    order = db.orders.get(order_id)
    if order is None or (store_id is not None and order["store_id"] != store_id):
        raise_error(ERR_ORDER_NOT_FOUND, f"Order {order_id} not found")
    return order


def get_menu_item_or_404(item_id, store_id=None):
    from errors import ERR_MENU_ITEM_NOT_FOUND
    item = db.menu_items.get(item_id)
    if item is None or (store_id is not None and item["store_id"] != store_id):
        raise_error(ERR_MENU_ITEM_NOT_FOUND, f"Menu item {item_id} not found")
    return item


def get_ingredient_or_404(ingredient_id):
    from errors import ERR_INGREDIENT_NOT_FOUND
    ing = db.ingredients.get(ingredient_id)
    if ing is None:
        raise_error(ERR_INGREDIENT_NOT_FOUND, f"Ingredient {ingredient_id} not found")
    return ing


def get_batch_or_404(batch_id):
    from errors import ERR_BATCH_NOT_FOUND
    batch = db.batches.get(batch_id)
    if batch is None:
        raise_error(ERR_BATCH_NOT_FOUND, f"Batch {batch_id} not found")
    return batch


def get_channel_or_404(channel_id):
    from errors import ERR_CHANNEL_NOT_FOUND
    ch = db.marketplace_channels.get(channel_id)
    if ch is None:
        raise_error(ERR_CHANNEL_NOT_FOUND, f"Marketplace channel {channel_id} not found")
    return ch


def get_deployment_or_404(deployment_id, store_id=None):
    from errors import ERR_DEPLOYMENT_NOT_FOUND
    dep = db.deployments.get(deployment_id)
    if dep is None or (store_id is not None and dep["store_id"] != store_id):
        raise_error(ERR_DEPLOYMENT_NOT_FOUND, f"Deployment {deployment_id} not found")
    return dep


def get_suppression_event_or_404(event_id, store_id=None):
    from errors import ERR_SUPPRESSION_EVENT_NOT_FOUND
    ev = db.suppression_events.get(event_id)
    if ev is None or (store_id is not None and ev["store_id"] != store_id):
        raise_error(ERR_SUPPRESSION_EVENT_NOT_FOUND, f"Suppression event {event_id} not found")
    return ev


# ---------------------------------------------------------------------------
# Throttle state (per PRD 2.9 / scaffold calc throttle_band)
# ---------------------------------------------------------------------------

def current_window(store):
    """Earliest OPEN ProductionWindow whose interval_end > now. None if none."""
    now = db.clock
    windows = [
        w for w in db.production_windows.values()
        if w["store_id"] == store["id"] and w["status"] == "OPEN"
        and parse_iso(w["interval_end"]) > now
    ]
    if not windows:
        return None
    windows.sort(key=lambda w: (parse_iso(w["interval_start"]), w["created_at"], w["id"]))
    return windows[0]


def recompute_throttle(store):
    """Recompute store.throttle_state from the current window's digital_committed."""
    w = current_window(store)
    if w is None:
        new_state = "OPEN"
    else:
        capacity = store["digital_line_capacity_per_interval"]
        threshold = math.ceil(store["overage_threshold_pct"] * capacity)
        load = w["digital_committed"]
        if load >= capacity:
            new_state = "CLOSED"
        elif load >= threshold:
            new_state = "THROTTLED"
        else:
            new_state = "OPEN"
    if store["throttle_state"] != new_state:
        store["throttle_state"] = new_state
        touch(store)


def sync_interval_loads(store):
    """Store interval load counters mirror the current window's committed load."""
    w = current_window(store)
    if w is None:
        digital = 0
        instore = 0
    else:
        digital = w["digital_committed"]
        instore = w["instore_committed"]
    if store["digital_interval_load"] != digital or store["instore_interval_load"] != instore:
        store["digital_interval_load"] = digital
        store["instore_interval_load"] = instore
        touch(store)


# ---------------------------------------------------------------------------
# Suppression cascade (per PRD 3.7 / scaffold calc suppression_cascade)
# ---------------------------------------------------------------------------

LOW_THRESHOLD = Decimal("0.5")
DEPLETED_THRESHOLD = Decimal("0.25")


def items_for_ingredient(ingredient_id):
    """All menu items with a RecipeComponent on this ingredient, ordered by
    item_code ASC (deterministic, never by id)."""
    item_ids = {
        rc["menu_item_id"] for rc in db.recipe_components.values()
        if rc["ingredient_id"] == ingredient_id
    }
    items = [db.menu_items[i] for i in item_ids]
    items.sort(key=lambda m: (m["item_code"], m["id"]))
    return items


def recompute_item_suppression(item):
    """Recompute an item's suppression_state from ACTIVE events covering it."""
    events = [
        e for e in db.suppression_events.values()
        if e["menu_item_id"] == item["id"] and e["status"] == "ACTIVE"
    ]
    if not events:
        new_state = "SELLABLE"
    else:
        scopes = {e["scope"] for e in events}
        if "ALL" in scopes:
            new_state = "SUPPRESSED_ALL"
        elif "MARKETPLACE" in scopes and "DIGITAL" in scopes:
            new_state = "SUPPRESSED_ALL"
        elif "MARKETPLACE" in scopes:
            new_state = "SUPPRESSED_MARKETPLACE"
        elif "DIGITAL" in scopes:
            new_state = "SUPPRESSED_DIGITAL"
        else:
            new_state = "SELLABLE"
    if item["suppression_state"] != new_state:
        item["suppression_state"] = new_state
        touch(item)


def evaluate_shortage(ingredient):
    """Derive shortage_state and fire suppression cascades on threshold crossings."""
    par = ingredient["par_level_grams"]
    on_hand = ingredient["on_hand_grams"]
    if on_hand >= float(LOW_THRESHOLD) * par:
        new_state = "STOCKED"
    elif on_hand >= float(DEPLETED_THRESHOLD) * par:
        new_state = "LOW"
    else:
        new_state = "DEPLETED"

    prior = ingredient["shortage_state"]
    if prior == new_state:
        return

    ingredient["shortage_state"] = new_state
    touch(ingredient)

    if new_state == "LOW":
        # Cascade MARKETPLACE-scope suppression for dependent items.
        for item in items_for_ingredient(ingredient["id"]):
            if item.get("is_digital_eligible", True):
                # Only create a SHORTAGE event if no ACTIVE shortage event already
                # covers this item for this ingredient.
                existing = [
                    e for e in db.suppression_events.values()
                    if e["menu_item_id"] == item["id"]
                    and e["ingredient_id"] == ingredient["id"]
                    and e["status"] == "ACTIVE"
                    and e["cause"] == "SHORTAGE"
                ]
                if not existing:
                    ev = new_resource()
                    ev.update({
                        "store_id": item["store_id"],
                        "menu_item_id": item["id"],
                        "ingredient_id": ingredient["id"],
                        "scope": "MARKETPLACE",
                        "cause": "SHORTAGE",
                        "status": "ACTIVE",
                    })
                    db.suppression_events[ev["id"]] = ev
            recompute_item_suppression(item)
    elif new_state == "DEPLETED":
        # Escalate ACTIVE SHORTAGE events for this ingredient to scope ALL;
        # when a straight drop to DEPLETED left no prior event, create one
        # directly at scope ALL so affected items become SUPPRESSED_ALL.
        for item in items_for_ingredient(ingredient["id"]):
            escalated = False
            for ev in db.suppression_events.values():
                if (ev["menu_item_id"] == item["id"]
                        and ev["ingredient_id"] == ingredient["id"]
                        and ev["status"] == "ACTIVE"
                        and ev["cause"] == "SHORTAGE"):
                    escalated = True
                    if ev["scope"] != "ALL":
                        ev["scope"] = "ALL"
                        touch(ev)
            if not escalated and item.get("is_digital_eligible", True):
                ev = new_resource()
                ev.update({
                    "store_id": item["store_id"],
                    "menu_item_id": item["id"],
                    "ingredient_id": ingredient["id"],
                    "scope": "ALL",
                    "cause": "SHORTAGE",
                    "status": "ACTIVE",
                })
                db.suppression_events[ev["id"]] = ev
            recompute_item_suppression(item)
    elif new_state == "STOCKED" and prior in ("LOW", "DEPLETED"):
        # Recovery: resolve ACTIVE SHORTAGE events for this ingredient.
        for ev in db.suppression_events.values():
            if (ev["ingredient_id"] == ingredient["id"]
                    and ev["status"] == "ACTIVE"
                    and ev["cause"] == "SHORTAGE"):
                ev["status"] = "RESOLVED"
                touch(ev)
        for item in items_for_ingredient(ingredient["id"]):
            recompute_item_suppression(item)


def update_food_cost_variance(store):
    actual = store["actual_food_cost_cents"]
    theoretical = store["theoretical_food_cost_cents"]
    denom = max(theoretical, 1)
    new_bps = round_half_up(Decimal(10000) * (Decimal(actual) - Decimal(theoretical)) / Decimal(denom))
    if store["food_cost_variance_bps"] != new_bps:
        store["food_cost_variance_bps"] = new_bps
        touch(store)


# ---------------------------------------------------------------------------
# Logical clock transitions (per PRD 2.4)
# ---------------------------------------------------------------------------

def _create_waste_event(store_id, batch, grams, reason):
    ingredient = db.ingredients[batch["ingredient_id"]]
    ev = new_resource()
    cost = round_half_up(Decimal(str(grams)) * Decimal(str(ingredient["unit_cost_cents_per_gram"])))
    ev.update({
        "store_id": store_id,
        "ingredient_batch_id": batch["id"],
        "grams": grams,
        "reason": reason,
        "cost_cents": cost,
    })
    db.waste_events[ev["id"]] = ev
    return ev


def fire_clock_transitions():
    """Fire automatic transitions driven by the logical clock:
    - IngredientBatch ACTIVE -> EXPIRED when discard_at <= now
    - Order READY -> EXPIRED when promised_at + 45min <= now
    - ProductionWindow OPEN -> CUTOFF when interval_start <= now
    """
    now = db.clock

    # Batches expiring
    for batch in list(db.batches.values()):
        if batch["status"] == "ACTIVE" and parse_iso(batch["discard_at"]) <= now:
            remaining = batch["grams_remaining"]
            if remaining > 0:
                ingredient = db.ingredients[batch["ingredient_id"]]
                store = db.stores.get(batch["store_id"])
                _create_waste_event(batch["store_id"], batch, remaining, "HOLD_TIME_EXPIRED")
                ingredient["on_hand_grams"] -= remaining
                touch(ingredient)
                if store is not None:
                    cost = round_half_up(Decimal(str(remaining)) * Decimal(str(ingredient["unit_cost_cents_per_gram"])))
                    store["actual_food_cost_cents"] += cost
                    touch(store)
                    update_food_cost_variance(store)
                batch["discarded_grams"] += remaining
                batch["grams_remaining"] = 0
                evaluate_shortage(ingredient)
            batch["status"] = "EXPIRED"
            touch(batch)

    # Ready orders expiring
    for order in list(db.orders.values()):
        if order["fulfillment_status"] == "READY":
            promised = parse_iso(order["promised_at"])
            if promised + timedelta(minutes=45) <= now:
                order["fulfillment_status"] = "EXPIRED"
                if order["payment_status"] == "CAPTURED":
                    order["payment_status"] = "REFUNDED"
                touch(order)
                store = db.stores.get(order["store_id"])
                if store is not None:
                    w = db.production_windows.get(order.get("production_window_id"))
                    if w is not None:
                        if order["line"] == "DIGITAL":
                            w["digital_committed"] = max(0, w["digital_committed"] - order["entree_count"])
                        else:
                            w["instore_committed"] = max(0, w["instore_committed"] - order["entree_count"])
                        touch(w)
                    sync_interval_loads(store)
                    recompute_throttle(store)

    # Windows cutting off
    for w in list(db.production_windows.values()):
        if w["status"] == "OPEN" and parse_iso(w["interval_start"]) <= now:
            w["status"] = "CUTOFF"
            touch(w)
            store = db.stores.get(w["store_id"])
            if store is not None:
                sync_interval_loads(store)
                recompute_throttle(store)

    # Windows settling when interval_end passed and all orders resolved
    for w in list(db.production_windows.values()):
        if w["status"] == "CUTOFF" and parse_iso(w["interval_end"]) <= now:
            live = [
                o for o in db.orders.values()
                if o.get("production_window_id") == w["id"]
                and o["fulfillment_status"] in ("PLACED", "ACCEPTED", "IN_PRODUCTION", "READY")
            ]
            if not live:
                w["status"] = "SETTLED"
                touch(w)


# ---------------------------------------------------------------------------
# FIFO consumption (per PRD 3.4 / scaffold calc fifo_consumption)
# ---------------------------------------------------------------------------

def line_required_grams(line):
    """Compute {ingredient_id: grams} required for an order line, honoring
    customizations: EXTRA doubles the component's standard grams; NONE zeros
    it; LIGHT halves it; SUB moves the grams to sub_ingredient_id."""
    item = db.menu_items[line["menu_item_id"]]
    components = [rc for rc in db.recipe_components.values() if rc["menu_item_id"] == item["id"]]
    customizations = line.get("customizations") or []
    cust_by_ing = {c["ingredient_id"]: c for c in customizations if isinstance(c, dict) and "ingredient_id" in c}

    required = {}
    for rc in components:
        ing_id = rc["ingredient_id"]
        grams = rc["standard_grams"] * line["quantity"]
        cust = cust_by_ing.get(ing_id)
        if cust:
            action = cust.get("action")
            if action == "EXTRA":
                grams = grams * 2
            elif action == "LIGHT":
                grams = grams // 2
            elif action == "NONE":
                grams = 0
            elif action == "SUB":
                sub_id = cust.get("sub_ingredient_id")
                grams = 0
                if sub_id:
                    required[sub_id] = required.get(sub_id, 0) + rc["standard_grams"] * line["quantity"]
        if grams:
            required[ing_id] = required.get(ing_id, 0) + grams
    return required


def available_grams(ingredient_id):
    return sum(
        b["grams_remaining"] for b in db.batches.values()
        if b["ingredient_id"] == ingredient_id and b["status"] == "ACTIVE"
    )


def consume_fifo(ingredient_id, grams):
    """Consume grams from ACTIVE batches in cooked_at ASC, created_at ASC order.
    Returns list of (batch, consumed) for compensation bookkeeping."""
    batches = [
        b for b in db.batches.values()
        if b["ingredient_id"] == ingredient_id and b["status"] == "ACTIVE"
        and b["grams_remaining"] > 0
    ]
    batches.sort(key=lambda b: (parse_iso(b["cooked_at"]), b["created_at"]))
    draws = []
    remaining = grams
    for b in batches:
        if remaining <= 0:
            break
        take = min(remaining, b["grams_remaining"])
        b["grams_remaining"] -= take
        touch(b)
        draws.append((b, take))
        remaining -= take
        if b["grams_remaining"] == 0:
            b["status"] = "DEPLETED"
            touch(b)
    return draws
