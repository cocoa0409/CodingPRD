"""Domain services: lookups, computed fields, cascades, shared checks."""
from datetime import timedelta
from decimal import Decimal

import calc
from core import ApiError, D, db, new_row, rhu, sort_created, touch


# ---------------------------------------------------------------------------
# Lookups (tier 4 existence; one generic ERR_NOT_FOUND per the scaffold)
# ---------------------------------------------------------------------------
def need(collection, row_id):
    row = collection.get(row_id)
    if row is None:
        raise ApiError("ERR_NOT_FOUND")
    return row


def need_category(row_id):
    return need(db.categories, row_id)


def need_supplier(row_id):
    return need(db.suppliers, row_id)


def need_product(row_id):
    return need(db.products, row_id)


def need_tender(row_id):
    return need(db.tenders, row_id)


def need_bid(row_id):
    return need(db.bids, row_id)


def need_panel(row_id):
    return need(db.panels, row_id)


def need_store(row_id):
    return need(db.stores, row_id)


def need_employee(row_id):
    return need(db.employees, row_id)


def need_finds_buy(row_id):
    return need(db.finds_buys, row_id)


def need_allocation(row_id):
    return need(db.allocations, row_id)


def need_shift(row_id):
    return need(db.register_shifts, row_id)


def need_labor_window(row_id):
    return need(db.labor_windows, row_id)


def need_claim(row_id):
    return need(db.claims, row_id)


# ---------------------------------------------------------------------------
# Relationship helpers
# ---------------------------------------------------------------------------
def products_of_category(category_id):
    return sort_created(
        [p for p in db.products.values() if p["category_id"] == category_id]
    )


def bids_of_tender(tender_id):
    return sort_created([b for b in db.bids.values() if b["tender_id"] == tender_id])


def panel_of_bid(bid_id):
    rows = [p for p in db.panels.values() if p["bid_id"] == bid_id]
    return sort_created(rows)[0] if rows else None


def allocations_of_buy(buy_id):
    return sort_created(
        [a for a in db.allocations.values() if a["finds_buy_id"] == buy_id]
    )


def allocations_of_store(store_id):
    return sort_created(
        [a for a in db.allocations.values() if a["store_id"] == store_id]
    )


def coin_events_of_store(store_id):
    return sort_created(
        [e for e in db.cart_coin_events.values() if e["store_id"] == store_id]
    )


# ---------------------------------------------------------------------------
# Categories: category_sku_count with the OPEN <-> LOCKED auto-transition
# ---------------------------------------------------------------------------
def recompute_category(category):
    count = sum(
        1
        for p in db.products.values()
        if p["category_id"] == category["id"]
        and p["kind"] == "CORE"
        and p["status"] == "ACTIVE"
    )
    new_status = "LOCKED" if count >= category["sku_cap"] else "OPEN"
    if count != category["active_sku_count"] or new_status != category["status"]:
        category["active_sku_count"] = count
        category["status"] = new_status
        touch(category)


# ---------------------------------------------------------------------------
# Cart coin ledger
# ---------------------------------------------------------------------------
def apply_coin_event(store, event_type, coin_count):
    if event_type == "INSERT":
        new_outstanding = store["coins_outstanding"] + coin_count
    elif event_type in ("RETURN", "CORRAL_COLLECT"):
        new_outstanding = store["coins_outstanding"] - coin_count
    else:  # AUDIT_ADJUST is signed
        new_outstanding = store["coins_outstanding"] + coin_count
    if new_outstanding < 0:
        raise ApiError("ERR_COIN_BALANCE_NEGATIVE")
    store["coins_outstanding"] = new_outstanding
    store["coin_liability_cents"] = new_outstanding * calc.COIN_VALUE_CENTS
    touch(store)


def coin_reconciliation(store):
    inserted = returned = collected = adjusted = 0
    for e in coin_events_of_store(store["id"]):
        if e["event_type"] == "INSERT":
            inserted += e["coin_count"]
        elif e["event_type"] == "RETURN":
            returned += e["coin_count"]
        elif e["event_type"] == "CORRAL_COLLECT":
            collected += e["coin_count"]
        else:
            adjusted += e["coin_count"]
    return {
        "coins_inserted": inserted,
        "coins_returned": returned,
        "coins_collected": collected,
        "coins_adjusted": adjusted,
        "coins_outstanding": store["coins_outstanding"],
        "coin_liability_cents": store["coin_liability_cents"],
    }


# ---------------------------------------------------------------------------
# Finds buys: allocations, sell cascade, sell-through
# ---------------------------------------------------------------------------
def recompute_buy_quantities(buy):
    allocs = allocations_of_buy(buy["id"])
    buy["allocated_quantity"] = sum(a["allocated_quantity"] for a in allocs)
    buy["remaining_quantity"] = buy["allocated_quantity"] - sum(
        a["sold_quantity"] for a in allocs
    )


def recompute_sell_through(store):
    """Percentage of allocated Finds quantity sold across the store's
    allocations that sit in terminal sell states (SOLD_OUT or CLOSED)."""
    terminal = [
        a
        for a in allocations_of_store(store["id"])
        if a["status"] in ("SOLD_OUT", "CLOSED")
    ]
    allocated = sum(a["allocated_quantity"] for a in terminal)
    if allocated <= 0:
        pct = Decimal("0")
    else:
        sold = sum(a["sold_quantity"] for a in terminal)
        pct = rhu(Decimal("100") * Decimal(sold) / Decimal(allocated), 2)
    if pct != store["finds_sell_through_pct"]:
        store["finds_sell_through_pct"] = pct
        touch(store)


def recompute_sell_through_for_buy(buy):
    for a in allocations_of_buy(buy["id"]):
        recompute_sell_through(db.stores[a["store_id"]])


def sell_from_allocation(allocation, quantity):
    """Record a sale; cascades allocation -> buy -> stores. Tier-7 (window) and
    tier-9 (remaining) checks are the caller's job."""
    allocation["sold_quantity"] += quantity
    allocation["remaining_quantity"] -= quantity
    touch(allocation)
    buy = db.finds_buys[allocation["finds_buy_id"]]
    if allocation["remaining_quantity"] == 0:
        allocation["status"] = "SOLD_OUT"
        touch(allocation)
    recompute_buy_quantities(buy)
    if buy["remaining_quantity"] == 0 and buy["status"] == "ON_SALE":
        buy["status"] = "SOLD_OUT"
        touch(buy)
        recompute_sell_through_for_buy(buy)


def plan_allocations(buy):
    """Delete any existing draft plan and run the waterfall from scratch."""
    for a in allocations_of_buy(buy["id"]):
        del db.allocations[a["id"]]
    stores = sort_created(
        [s for s in db.stores.values() if s["status"] == "ACTIVE"]
    )
    for store, units in calc.waterfall(buy["total_quantity"], stores):
        row = new_row(
            "FindsAllocation",
            finds_buy_id=buy["id"],
            store_id=store["id"],
            allocated_quantity=units,
            sold_quantity=0,
            remaining_quantity=units,
            sale_start_date=None,
            sale_end_date=None,
            clearance_markdown_pct=None,
            clearance_value_cents=None,
            status="RESERVED",
        )
        db.allocations[row["id"]] = row
    recompute_buy_quantities(buy)
    if buy["status"] == "PLANNED":
        buy["status"] = "ALLOCATED"
    touch(buy)


# ---------------------------------------------------------------------------
# Tender evaluation / award
# ---------------------------------------------------------------------------
def evaluate_tender(tender):
    """CLOSED -> EVALUATING: score every bid, lock every panel."""
    for bid in bids_of_tender(tender["id"]):
        panel = panel_of_bid(bid["id"])
        if panel is None or panel["status"] != "SCORED":
            raise ApiError("ERR_PANEL_INCOMPLETE")
    for bid in bids_of_tender(tender["id"]):
        panel = panel_of_bid(bid["id"])
        supplier = db.suppliers[bid["supplier_id"]]
        status, score = calc.award_score(tender, bid, panel, supplier)
        bid["award_score"] = score
        bid["status"] = status
        touch(bid)
    for bid in bids_of_tender(tender["id"]):
        panel = panel_of_bid(bid["id"])
        panel["status"] = "LOCKED"
        touch(panel)
    tender["status"] = "EVALUATING"
    touch(tender)


def award_tender(tender, primary_bid, secondary_bid):
    """EVALUATING -> AWARDED with the full cascade."""
    product = db.products[tender["product_id"]]
    for bid in bids_of_tender(tender["id"]):
        if bid["id"] == primary_bid["id"]:
            bid["status"] = "AWARDED_PRIMARY"
        elif bid["id"] == secondary_bid["id"]:
            bid["status"] = "AWARDED_SECONDARY"
        else:
            bid["status"] = "NOT_SELECTED"
        touch(bid)
    tender["winning_primary_bid_id"] = primary_bid["id"]
    tender["winning_secondary_bid_id"] = secondary_bid["id"]
    tender["status"] = "AWARDED"
    touch(tender)
    # Product activation cascade
    product["primary_supplier_id"] = primary_bid["supplier_id"]
    product["secondary_supplier_id"] = secondary_bid["supplier_id"]
    product["status"] = "ACTIVE"
    touch(product)
    recompute_category(db.categories[product["category_id"]])
    # Quality history: winners +2, disqualified -5, clamped to [0, 100]
    for bid in bids_of_tender(tender["id"]):
        supplier = db.suppliers[bid["supplier_id"]]
        delta = None
        if bid["status"] in ("AWARDED_PRIMARY", "AWARDED_SECONDARY"):
            delta = Decimal("2")
        elif bid["status"] == "DISQUALIFIED":
            delta = Decimal("-5")
        if delta is not None:
            new_score = D(supplier["quality_score"]) + delta
            new_score = max(Decimal("0"), min(Decimal("100"), new_score))
            if new_score != D(supplier["quality_score"]):
                supplier["quality_score"] = new_score
                touch(supplier)


def retender(tender):
    """EVALUATING -> OPEN: bids revert to SUBMITTED, panels revert to SCORED."""
    for bid in bids_of_tender(tender["id"]):
        bid["status"] = "SUBMITTED"
        bid["award_score"] = None
        touch(bid)
    for bid in bids_of_tender(tender["id"]):
        panel = panel_of_bid(bid["id"])
        if panel is not None and panel["status"] == "LOCKED":
            panel["status"] = "SCORED"
            touch(panel)
    tender["status"] = "OPEN"
    touch(tender)
