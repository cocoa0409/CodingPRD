"""Booth posture, the three conserved aggregates, and the cascade discipline.

Every aggregate here is a FULL recomputation from its source rows, never an
incremental delta, so a forward action and its compensating reversal land the
aggregate back on exactly the figure it held before (PRD §2.11).
"""
import db
from services import calc

store = db.store


# ------------------------------------------------------------ small lookups
def booths_of_exhibitor(exhibitor_id):
    return [b for b in store.booths.values() if b["exhibitor_id"] == exhibitor_id]


def booths_of_show(show_id):
    return [b for b in store.booths.values() if b["show_id"] == show_id]


def booths_of_exhibitor_and_show(exhibitor_id, show_id):
    return [b for b in store.booths.values()
            if b["exhibitor_id"] == exhibitor_id and b["show_id"] == show_id]


def orders_of_booth(booth_id):
    return [o for o in store.service_orders.values() if o["booth_id"] == booth_id]


def calls_of_booth(booth_id):
    return [c for c in store.labor_calls.values() if c["booth_id"] == booth_id]


def calls_of_show(show_id):
    booth_ids = {b["id"] for b in booths_of_show(show_id)}
    return [c for c in store.labor_calls.values() if c["booth_id"] in booth_ids]


def licenses_of_show(show_id):
    booth_ids = {b["id"] for b in booths_of_show(show_id)}
    return [lic for lic in store.licenses.values() if lic["booth_id"] in booth_ids]


def show_of_booth(booth):
    return store.shows.get(booth["show_id"])


# --------------------------------------------------------------- booth posture
def compute_posture(booth):
    """Clauses in fixed order; the first match fixes posture and reason."""
    exhibitor = store.exhibitors.get(booth["exhibitor_id"])
    show = store.shows.get(booth["show_id"])
    if exhibitor is not None and exhibitor["status"] == "SUSPENDED":
        return "FROZEN", "EXHIBITOR_SUSPENDED"
    if exhibitor is not None and \
            int(exhibitor["account_balance_cents"]) > int(exhibitor["credit_limit_cents"]):
        return "FROZEN", "CREDIT_LIMIT_BREACHED"
    if show is not None and show["status"] == "CLOSED":
        return "FROZEN", "SHOW_CLOSED"
    if show is not None and show["status"] == "CANCELLED":
        return "FROZEN", "SHOW_CANCELLED"
    if any(c["status"] == "NO_SHOW" for c in calls_of_booth(booth["id"])):
        return "RESTRICTED", "LABOR_NO_SHOW"
    for shipment in store.shipments.values():
        if shipment.get("hold_flag") and shipment["exhibitor_id"] == booth["exhibitor_id"] \
                and shipment["show_id"] == booth["show_id"]:
            return "RESTRICTED", "FREIGHT_HOLD"
    for change_order in store.change_orders.values():
        if change_order["booth_id"] == booth["id"] and change_order["status"] == "APPROVED":
            return "RESTRICTED", "CHANGE_ORDER_APPROVED"
    return "OPEN", None


def refresh_booth(booth):
    """Recompute posture; a change is a mutation and drives the order cascade."""
    posture, reason = compute_posture(booth)
    if posture == booth["posture"] and reason == booth["posture_reason"]:
        return booth
    was_frozen = booth["posture"] == "FROZEN"
    booth["posture"] = posture
    booth["posture_reason"] = reason
    db.touch(booth)
    if posture == "FROZEN" and not was_frozen:
        _freeze_orders(booth)
    elif was_frozen and posture != "FROZEN":
        _release_orders(booth)
    return booth


def refresh_booths(booths):
    for booth in list(booths):
        refresh_booth(booth)


def refresh_exhibitor_booths(exhibitor_id):
    refresh_booths(booths_of_exhibitor(exhibitor_id))


def refresh_show_booths(show_id):
    refresh_booths(booths_of_show(show_id))


def refresh_exhibitor_show_booths(exhibitor_id, show_id):
    refresh_booths(booths_of_exhibitor_and_show(exhibitor_id, show_id))


def _freeze_orders(booth):
    """A booth that has just become FROZEN holds its PENDING service orders."""
    show = show_of_booth(booth)
    touched_show = False
    for order in orders_of_booth(booth["id"]):
        if order["fulfillment_status"] != "PENDING":
            continue
        order["fulfillment_status"] = "HELD"
        db.touch(order)
        for call in store.labor_calls.values():
            if call.get("service_order_id") == order["id"] and call["status"] == "REQUESTED":
                call["status"] = "CANCELLED"
                db.touch(call)
                touched_show = True
    if touched_show and show is not None:
        recompute_show_aggregates(show)


def _release_orders(booth):
    """Leaving FROZEN restores the fulfillment dimension only."""
    for order in orders_of_booth(booth["id"]):
        if order["fulfillment_status"] == "HELD":
            order["fulfillment_status"] = "PENDING"
            db.touch(order)


# ------------------------------------------------------- conserved aggregates
def recompute_balance(exhibitor):
    """Issued and partially settled invoices, less payments, less settled claims."""
    total = 0
    settled = 0
    for invoice in store.invoices.values():
        if invoice["exhibitor_id"] != exhibitor["id"]:
            continue
        if invoice["status"] in ("ISSUED", "PARTIALLY_SETTLED"):
            total += int(invoice["total_cents"])
            settled += int(invoice["settled_cents"])
    claims = 0
    for claim in store.claims.values():
        if claim["exhibitor_id"] == exhibitor["id"] and claim["status"] == "SETTLED":
            claims += int(claim.get("settlement_cents") or 0)
    balance = total - settled - claims
    if balance != int(exhibitor["account_balance_cents"]):
        exhibitor["account_balance_cents"] = balance
        db.touch(exhibitor)
    return balance


def recompute_warehouse_cwt(warehouse):
    """Per-crate CEIL then sum, over warehouse-bearing crate statuses only."""
    total = 0
    for crate in store.crates.values():
        if crate.get("warehouse_id") == warehouse["id"] and \
                crate["status"] in ("AT_ADVANCE_WAREHOUSE", "RETURNED_TO_WAREHOUSE"):
            total += calc.cwt_of(crate["weight_lbs"])
    if total != int(warehouse["committed_cwt"]):
        warehouse["committed_cwt"] = total
        db.touch(warehouse)
    return total


def recompute_show_aggregates(show):
    """Committed crew-hours and the cancelled-call count, both full recomputes."""
    hours = calc.dec(0)
    cancelled = 0
    for call in calls_of_show(show["id"]):
        if call["status"] in ("DISPATCHED", "ON_SITE"):
            hours += calc.dec(call["crew_size"]) * calc.dec(call["scheduled_hours"])
        if call["status"] == "CANCELLED":
            cancelled += 1
    hours = calc.hours_2dp(hours)
    changed = False
    if hours != calc.dec(show["committed_labor_hours"]):
        show["committed_labor_hours"] = hours
        changed = True
    if cancelled != int(show["cancelled_labor_call_count"]):
        show["cancelled_labor_call_count"] = cancelled
        changed = True
    if changed:
        db.touch(show)
    return show


def warehouse_of_crate(crate):
    warehouse_id = crate.get("warehouse_id")
    if warehouse_id is None:
        return None
    return store.warehouses.get(warehouse_id)
