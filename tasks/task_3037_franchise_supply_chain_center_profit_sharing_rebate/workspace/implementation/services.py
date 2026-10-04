"""Business logic: calculations, derived fields, cascades, and automatic sweeps."""
from datetime import timedelta
from decimal import Decimal, ROUND_FLOOR, ROUND_HALF_UP

from db import db
from errors import ApiError, parse_ts, week_of

VALID_ROLES = {"SupplyChainAdmin", "StoreManager", "RouteCoordinator", "Any"}

YIELD_FACTORS = {
    "DOUGH": 0.85,
    "FOOD_INGREDIENT": 0.92,
    "PACKAGING": 1.00,
    "EQUIPMENT": 0.00,
    "SMALLWARES": 0.00,
}

GREEN_THRESHOLD = 0.05
YELLOW_THRESHOLD = 0.10
ELIGIBLE_RATE = 0.05
CONDITIONAL_RATE = 0.02
PROMOTION_BOOST = 1.5
POOL_RATE = 0.10
HOLDBACK_DAYS = 30
FULL_COMPLIANCE_THRESHOLD = 0.95
PROBATION_THRESHOLD = 0.80


# ---------------------------------------------------------------------------
# Generic helpers
# ---------------------------------------------------------------------------

def touch(rec):
    rec["version"] = rec.get("version", 1) + 1
    rec["updated_at"] = db.clock.now()


def new_record():
    now = db.clock.now()
    return {"created_at": now, "updated_at": now, "version": 1}


def round4(value: float):
    """Round half-up to 4 decimal places; returns a float for JSON output."""
    q = Decimal(str(value)).quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)
    return float(q)


def dec(value) -> Decimal:
    """Exact Decimal for a numeric input (avoids binary float error for rates)."""
    return value if isinstance(value, Decimal) else Decimal(str(value))


def floor_cents(value: Decimal) -> int:
    return int(value.to_integral_value(rounding=ROUND_FLOOR))


# ---------------------------------------------------------------------------
# Posture & tier derivation
# ---------------------------------------------------------------------------

def recompute_posture(center):
    if center["status"] == "SUSPENDED":
        center["posture"] = "SUSPENDED"
    elif any(p["center_id"] == center["id"] and p["status"] == "OVERBOOKED"
             for p in db.plans.values()):
        center["posture"] = "CONSTRAINED"
    elif any(pr["center_id"] == center["id"] and pr["status"] in ("CONFIRMED", "EXECUTING")
             for pr in db.promotions.values()):
        center["posture"] = "SURGE_MODE"
    else:
        center["posture"] = "ACTIVE"


def recompute_store_derived(store):
    """Re-evaluate compliance_tier and rebate_eligibility_status."""
    agreements = [a for a in db.agreements.values() if a["store_id"] == store["id"]]
    has_active = any(a["status"] == "ACTIVE" for a in agreements)
    has_breached = any(a["status"] == "BREACHED" for a in agreements)
    has_terminated = any(a["status"] == "TERMINATED" for a in agreements)

    if has_breached:
        store["compliance_tier"] = "NON_COMPLIANT"
    elif store["exclusive_purchase_pct"] >= FULL_COMPLIANCE_THRESHOLD:
        store["compliance_tier"] = "FULL_COMPLIANCE"
    elif store["exclusive_purchase_pct"] >= PROBATION_THRESHOLD:
        store["compliance_tier"] = "PROBATION"
    else:
        store["compliance_tier"] = "NON_COMPLIANT"

    if has_breached:
        store["rebate_eligibility_status"] = "CONDITIONAL"
    elif has_terminated and not has_active:
        store["rebate_eligibility_status"] = "INELIGIBLE"
    else:
        store["rebate_eligibility_status"] = "ELIGIBLE"


def plan_available(plan):
    return plan["baseline_units"] + plan["surge_units"] - plan["allocated_units"]


def check_plan_overbook(plan):
    """Flip plan between OPEN and OVERBOOKED; re-evaluate center posture."""
    center = db.centers[plan["center_id"]]
    if plan["status"] == "OPEN" and plan["allocated_units"] > plan["baseline_units"] + plan["surge_units"]:
        plan["status"] = "OVERBOOKED"
        touch(plan)
        center["posture"] = "CONSTRAINED"
    elif plan["status"] == "OVERBOOKED" and plan["allocated_units"] <= plan["baseline_units"] + plan["surge_units"]:
        plan["status"] = "OPEN"
        touch(plan)
        recompute_posture(center)


def allocate_units(plan, qty):
    if plan["status"] == "LOCKED":
        raise ApiError("ERR_CAPACITY_PLAN_LOCKED", "Capacity plan is LOCKED; modifications blocked", 409)
    plan["allocated_units"] += qty
    plan["available_units"] = plan_available(plan)
    touch(plan)
    check_plan_overbook(plan)


def deallocate_units(plan, qty):
    if plan["status"] == "LOCKED":
        return
    plan["allocated_units"] = max(0, plan["allocated_units"] - qty)
    plan["available_units"] = plan_available(plan)
    touch(plan)
    check_plan_overbook(plan)


# ---------------------------------------------------------------------------
# Pricing & order totals
# ---------------------------------------------------------------------------

def store_price_tier(quantity):
    if quantity >= 100:
        return "VOLUME_DISCOUNT"
    return "STANDARD"


def price_line(product, quantity):
    """Return unit_price_cents per the tiered cost-plus rule."""
    now = db.clock.now()
    center_id = product["center_id"]
    candidates = []
    for pb in db.price_books.values():
        if pb["center_id"] != center_id or pb["product_id"] != product["id"]:
            continue
        if pb["status"] != "ACTIVE":
            continue
        if pb["min_quantity"] > quantity:
            continue
        if not (pb["effective_from"] <= now < pb["effective_until"]):
            continue
        candidates.append(pb)
    if candidates:
        best = max(candidates, key=lambda p: p["min_quantity"])
        markup = best["markup_pct"]
    else:
        tier = store_price_tier(quantity)
        markup = {"STANDARD": 0.15, "VOLUME_DISCOUNT": 0.12, "PREMIUM": 0.20}[tier]
    return floor_cents(dec(product["base_cost_cents_per_unit"]) * (Decimal(1) + dec(markup)))


def compute_delivery_fee(order):
    """Route delivery surcharge. Waived entirely when an active promotion applies."""
    promo_id = order.get("promotion_id")
    if promo_id:
        promo = db.promotions.get(promo_id)
        if promo and promo["status"] in ("CONFIRMED", "EXECUTING"):
            return 0
    return 0


def compute_po_totals(order):
    lines = [l for l in db.lines.values()
             if l["order_id"] == order["id"] and l["status"] in ("PENDING", "CONFIRMED", "SHIPPED", "DELIVERED")]
    subtotal = sum(l["extended_price_cents"] for l in lines)
    base_sum = sum(db.products[l["product_id"]]["base_cost_cents_per_unit"] * l["quantity"] for l in lines)
    order["subtotal_cents"] = subtotal
    order["markup_cents"] = subtotal - base_sum
    order["delivery_fee_cents"] = compute_delivery_fee(order)
    order["total_cents"] = subtotal + order["markup_cents"] + order["delivery_fee_cents"]


def order_units(order):
    return sum(l["quantity"] for l in db.lines.values()
               if l["order_id"] == order["id"] and l["status"] in ("PENDING", "CONFIRMED", "SHIPPED", "DELIVERED"))


# ---------------------------------------------------------------------------
# Rebate ledger
# ---------------------------------------------------------------------------

def running_balance(store_id):
    bal = 0
    entries = sorted(
        (e for e in db.ledgers.values() if e["store_id"] == store_id and e["status"] != "VOIDED"),
        key=lambda e: (e["created_at"], e["id"]),
    )
    for e in entries:
        bal += e["amount_cents"]
    return bal


def create_ledger_entry(pool_id, store_id, entry_type, amount, source_order_id=None, settlement_date=None):
    import uuid
    rec = new_record()
    rec.update({
        "id": str(uuid.uuid4()),
        "pool_id": pool_id,
        "store_id": store_id,
        "entry_type": entry_type,
        "amount_cents": amount,
        "running_balance_cents": running_balance(store_id) + amount,
        "source_order_id": source_order_id,
        "settlement_date": settlement_date,
        "status": "PENDING",
    })
    db.ledgers[rec["id"]] = rec
    return rec


def quarter_of(dt):
    m = dt.month
    q = (m - 1) // 3 + 1
    return f"{dt.year}-Q{q}"


def maybe_auto_close_pool(pool):
    settlements = [e for e in db.ledgers.values()
                   if e["pool_id"] == pool["id"] and e["entry_type"] == "SETTLEMENT"]
    if settlements and all(e["status"] in ("SETTLED", "VOIDED") for e in settlements):
        pool["status"] = "CLOSED"
        touch(pool)
        center = db.centers.get(pool["center_id"])
        if center is not None:
            center["rebate_pool_balance_cents"] = 0
            center["rebate_pool_locked_cents"] = 0
            touch(center)


# ---------------------------------------------------------------------------
# Settlement fan-out (PO DELIVERED -> SETTLED)
# ---------------------------------------------------------------------------

def settle_order(order):
    """Cascade: DELIVERED -> SETTLED with variance, balance, and rebate effects."""
    if order["status"] == "SETTLED":
        return
    store = db.stores[order["store_id"]]
    center = db.centers[order["center_id"]]

    lines = [l for l in db.lines.values() if l["order_id"] == order["id"]]

    # Theoretical usage across DELIVERED lines (floor per line).
    theo = 0
    for l in lines:
        if l["status"] != "DELIVERED":
            continue
        product = db.products[l["product_id"]]
        factor = YIELD_FACTORS.get(product["category"], 0.0)
        l["theoretical_usage_cents"] = floor_cents(
            dec(l["quantity"]) * dec(product["base_cost_cents_per_unit"]) * dec(factor))
        theo += l["theoretical_usage_cents"]
    order["theoretical_usage_cents"] = theo

    actual = order.get("actual_usage_cents", 0)
    order["actual_usage_cents"] = actual
    if theo == 0:
        order["food_cost_variance_pct"] = None
        severity = "GREEN"
    else:
        variance = actual - theo
        pct = round4(variance / theo)
        order["food_cost_variance_pct"] = pct
        severity = "GREEN" if pct <= GREEN_THRESHOLD else ("YELLOW" if pct <= YELLOW_THRESHOLD else "RED")

    # Compliance gate for rebate accrual.
    eligible_status = store["rebate_eligibility_status"]
    agreements = [a for a in db.agreements.values()
                  if a["store_id"] == store["id"] and a["status"] == "ACTIVE"]
    if eligible_status != "INELIGIBLE" and not agreements:
        raise ApiError("ERR_COMPLIANCE_REQUIRED",
                       "Store lacks ACTIVE compliance agreement for rebate accrual", 409)

    # Rebate accrual.
    accrual = 0
    if eligible_status == "CONDITIONAL":
        rate = CONDITIONAL_RATE
    elif eligible_status == "ELIGIBLE":
        rate = ELIGIBLE_RATE
    else:
        rate = 0.0
    if rate > 0:
        promo = db.promotions.get(order.get("promotion_id") or "")
        if promo and promo["status"] == "EXECUTING":
            rate = rate * PROMOTION_BOOST
        accrual = floor_cents(dec(order["total_cents"]) * dec(rate) * dec(store["exclusive_purchase_pct"]))
    if accrual > 0:
        pool = next((p for p in db.pools.values()
                     if p["center_id"] == center["id"] and p["quarter"] == quarter_of(db.clock.now())
                     and p["status"] == "OPEN"), None)
        if pool is not None:
            create_ledger_entry(pool["id"], store["id"], "ACCRUAL", accrual, source_order_id=order["id"])
            pool["pool_total_cents"] += accrual
            touch(pool)
            center["rebate_pool_balance_cents"] += accrual

    # Store balance.
    store["outstanding_balance_cents"] += order["total_cents"]

    # Weekly FoodCostVariance update.
    week = week_of(order["week_start_date"])
    variance_rec = next((v for v in db.variances.values()
                         if v["store_id"] == store["id"] and week_of(v["week_start_date"]) == week),
                        None)
    if variance_rec is not None and variance_rec["status"] == "PENDING":
        variance_rec["theoretical_cents"] += theo
        variance_rec["actual_cents"] += actual
        variance_rec["variance_cents"] = variance_rec["actual_cents"] - variance_rec["theoretical_cents"]
        if variance_rec["theoretical_cents"] == 0:
            variance_rec["variance_pct"] = None
            variance_rec["severity"] = "GREEN"
        else:
            vpct = round4(variance_rec["variance_cents"] / variance_rec["theoretical_cents"])
            variance_rec["variance_pct"] = vpct
            variance_rec["severity"] = ("GREEN" if vpct <= GREEN_THRESHOLD
                                        else "YELLOW" if vpct <= YELLOW_THRESHOLD else "RED")
            if variance_rec["severity"] == "RED":
                variance_rec["status"] = "FLAGGED"
        touch(variance_rec)

    order["status"] = "SETTLED"
    touch(order)
    touch(store)
    touch(center)

    # Automatic store suspension when over credit limit.
    if store["outstanding_balance_cents"] > store["credit_limit_cents"] and store["status"] == "ACTIVE":
        suspend_store_cascade(store)


def suspend_store_cascade(store):
    store["status"] = "SUSPENDED"
    touch(store)
    for o in db.orders.values():
        if o["store_id"] == store["id"] and o["status"] in ("DRAFT", "SUBMITTED"):
            o["status"] = "CANCELLED"
            touch(o)
            for l in db.lines.values():
                if l["order_id"] == o["id"] and l["status"] == "PENDING":
                    l["status"] = "CANCELLED"
                    touch(l)


# ---------------------------------------------------------------------------
# Route completion cascade
# ---------------------------------------------------------------------------

def maybe_complete_route(route):
    if route["status"] != "DISPATCHED":
        return
    stops = [s for s in db.stops.values() if s["route_id"] == route["id"]]
    if stops and all(s["status"] in ("COMPLETED", "SKIPPED", "FAILED") for s in stops):
        route["status"] = "COMPLETED"
        touch(route)
        for o in db.orders.values():
            if o.get("route_id") == route["id"] and o["status"] == "DELIVERED":
                settle_order(o)


# ---------------------------------------------------------------------------
# Compliance reporting
# ---------------------------------------------------------------------------

def recompute_exclusive_pct(store):
    now = db.clock.now()
    window_start = week_of(now) - timedelta(weeks=3)
    center_purchases = sum(
        o["total_cents"] for o in db.orders.values()
        if o["store_id"] == store["id"] and o["status"] == "SETTLED"
        and window_start <= week_of(o["week_start_date"]) <= week_of(now)
    )
    external = sum(
        r["external_purchases_cents"] for r in db.compliance_reports.values()
        if r["store_id"] == store["id"] and window_start <= week_of(r["week_start_date"]) <= week_of(now)
    )
    total = center_purchases + external
    store["exclusive_purchase_pct"] = 0.0 if total <= 0 else round4(center_purchases / total)
    recompute_store_derived(store)


# ---------------------------------------------------------------------------
# Automatic sweeps (run_ops + clock set)
# ---------------------------------------------------------------------------

def run_automatic_sweeps(center):
    """Fire all time-dependent automatic transitions for a center."""
    now = db.clock.now()

    # Promotions: CONFIRMED -> EXECUTING -> CLOSED
    for promo in [p for p in db.promotions.values() if p["center_id"] == center["id"]]:
        if promo["status"] == "CONFIRMED" and now >= promo["start_date"]:
            promo["status"] = "EXECUTING"
            touch(promo)
        if promo["status"] == "EXECUTING" and now >= promo["end_date"]:
            promo["status"] = "CLOSED"
            touch(promo)
            center["surge_capacity_multiplier"] = 1.0
            recompute_posture(center)
            for plan in db.plans.values():
                if plan["center_id"] == center["id"] and week_of(plan["week_start_date"]) > week_of(now):
                    if plan["surge_units"]:
                        plan["surge_units"] = 0
                        plan["available_units"] = plan_available(plan)
                        touch(plan)

    # Agreements: cure deadline passed -> TERMINATED
    store_ids = {s["id"] for s in db.stores.values() if s["center_id"] == center["id"]}
    for ag in db.agreements.values():
        if ag["store_id"] in store_ids and ag["status"] == "BREACHED":
            if ag.get("cure_deadline") and now >= ag["cure_deadline"]:
                ag["status"] = "TERMINATED"
                touch(ag)
                store = db.stores[ag["store_id"]]
                store["rebate_eligibility_status"] = "INELIGIBLE"
                store["compliance_tier"] = "NON_COMPLIANT"
                touch(store)

    # Ledger entries: POSTED -> SETTLED when settlement_date reached (no disputes modelled)
    for entry in sorted(
            (e for e in db.ledgers.values()
             if e["status"] == "POSTED" and e.get("settlement_date") and now >= e["settlement_date"]),
            key=lambda e: (e["store_id"], e["settlement_date"], e["created_at"])):
        entry["status"] = "SETTLED"
        touch(entry)
        if entry["amount_cents"] > 0:
            store = db.stores.get(entry["store_id"])
            if store is not None:
                store["outstanding_balance_cents"] -= entry["amount_cents"]
                touch(store)
        pool = db.pools.get(entry["pool_id"])
        if pool is not None:
            maybe_auto_close_pool(pool)


def run_ops_checkpoint(center):
    """The weekly ops checkpoint: five sweeps in one pass."""
    center["ops_run_index"] += 1

    # 1. Stale order expiry.
    for o in db.orders.values():
        if o["center_id"] != center["id"]:
            continue
        age = center["ops_run_index"] - o.get("created_ops_index", 0)
        if o["status"] == "DRAFT" and age >= 2:
            o["status"] = "CANCELLED"
            touch(o)
            for l in db.lines.values():
                if l["order_id"] == o["id"] and l["status"] == "PENDING":
                    l["status"] = "CANCELLED"
                    touch(l)
        elif o["status"] == "SUBMITTED" and age >= 1:
            o["status"] = "REJECTED"
            touch(o)

    # 2. Compliance evaluation.
    for store in db.stores.values():
        if store["center_id"] != center["id"]:
            continue
        recompute_exclusive_pct(store)
        for ag in db.agreements.values():
            if ag["store_id"] != store["id"] or ag["status"] != "ACTIVE":
                continue
            threshold = ag.get("exclusive_purchase_threshold")
            if threshold is not None and store["exclusive_purchase_pct"] < threshold:
                ag["consecutive_breach_weeks"] = ag.get("consecutive_breach_weeks", 0) + 1
                if ag["consecutive_breach_weeks"] >= 2:
                    ag["status"] = "BREACHED"
                    ag["breach_count"] += 1
                    ag["cure_deadline"] = now_plus(days=7)
                    touch(ag)
                    store["rebate_eligibility_status"] = "CONDITIONAL"
                    store["compliance_tier"] = "PROBATION"
                    touch(store)
            else:
                ag["consecutive_breach_weeks"] = 0

    # 3. Capacity reconciliation: LOCKED plans -> RECONCILED.
    for plan in db.plans.values():
        if plan["center_id"] == center["id"] and plan["status"] == "LOCKED":
            plan["status"] = "RECONCILED"
            touch(plan)

    # 4. Food-cost variance finalization.
    for v in db.variances.values():
        store = db.stores.get(v["store_id"])
        if store is not None and store["center_id"] == center["id"] and v["status"] == "PENDING":
            v["status"] = "FINALIZED"
            touch(v)

    # 5. Time-dependent automatic transitions (promotions, agreements, ledger).
    run_automatic_sweeps(center)

    touch(center)


def now_plus(days=0):
    return db.clock.now() + timedelta(days=days)
