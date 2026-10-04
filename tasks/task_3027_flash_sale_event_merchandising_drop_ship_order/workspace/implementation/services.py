"""Cross-cutting services: the credit ledger, balance reconciliation, the shop
and vendor cascades, and lookup helpers that preserve validation precedence.
"""

from errors import fail
from store import db, now, touch, days, hours, stamp
import calc


# --------------------------------------------------------------------------
# lookups — validations priority 4 (left to right, first failure wins)
# --------------------------------------------------------------------------

CHECKS = (
    ("vendors", "ERR_VENDOR_NOT_FOUND"),
    ("shops", "ERR_SHOP_NOT_FOUND"),
    ("events", "ERR_EVENT_NOT_FOUND"),
    ("listings", "ERR_LISTING_NOT_FOUND"),
    ("customers", "ERR_CUSTOMER_NOT_FOUND"),
    ("orders", "ERR_ORDER_NOT_FOUND"),
    ("confirmations", "ERR_CONFIRMATION_NOT_FOUND"),
    ("purchase_orders", "ERR_PURCHASE_ORDER_NOT_FOUND"),
    ("polines", "ERR_POLINE_NOT_FOUND"),
    ("shipments", "ERR_VENDOR_SHIPMENT_NOT_FOUND"),
    ("parcels", "ERR_PARCEL_NOT_FOUND"),
    ("returns", "ERR_RETURN_NOT_FOUND"),
)

ERROR_BY_COLLECTION = dict(CHECKS)


def get_or_404(collection, ident):
    entity = getattr(db, collection).get(ident)
    if entity is None:
        fail(ERROR_BY_COLLECTION[collection])
    return entity


def resolve_ordered(*pairs):
    """pairs of (collection, ident) validated left to right."""
    out = []
    for collection, ident in pairs:
        out.append(get_or_404(collection, ident))
    return out


def require_enum(value, allowed, field="field"):
    from errors import invalid_request
    if value not in allowed:
        invalid_request("Field %s carries an undeclared enum member." % field)
    return value


# --------------------------------------------------------------------------
# the append-only credit ledger (PRD §2.8)
# --------------------------------------------------------------------------

def ledger_issue(customer_id, source_kind, source_ref_id, amount_cents,
                 idempotency_key=None, label=None, settle=False):
    """Append a ledger row.  Returns (row, created)."""
    if idempotency_key is not None and idempotency_key in db.idem:
        return db.ledger[db.idem[idempotency_key]], False
    if amount_cents == 0:
        from errors import invalid_request
        invalid_request("A CreditLedger amount_cents may never be zero.")
    row = {
        "customer_id": customer_id,
        "source_kind": source_kind,
        "source_ref_id": source_ref_id,
        "amount_cents": amount_cents,
        "entry_status": "SETTLED" if settle else "ISSUED",
        "idempotency_key": idempotency_key,
        "label": label,
    }
    stamp(row)
    db.ledger[row["id"]] = row
    if idempotency_key is not None:
        db.idem[idempotency_key] = row["id"]
    customer = db.customers.get(customer_id)
    if customer is not None:
        reconcile_customer(customer)
    return row, True


def set_settled(row):
    """ISSUED -> SETTLED: the row's last and only change, no version bump."""
    if row["entry_status"] != "SETTLED":
        row["entry_status"] = "SETTLED"


def entries_for(customer_id):
    return [r for r in db.ledger.values() if r["customer_id"] == customer_id]


def reconcile_customer(customer):
    """calculations.customer_refund_balance_reconciliation.

    refund_balance = sum(amount) over ISSUED|SETTLED refund-source rows
                     - sum(amount) over SETTLED, negative refund-source rows
    store_credit   = sum(amount) over RETURN_GOODWILL | MANUAL_ADJUSTMENT rows
    """
    refund_total = 0
    credit_total = 0
    for row in entries_for(customer["id"]):
        kind = row["source_kind"]
        amount = row["amount_cents"]
        if kind in ("OVERSELL", "SHORT_SHIP", "CANCELLATION"):
            if row["entry_status"] in ("ISSUED", "SETTLED"):
                refund_total += amount
            if row["entry_status"] == "SETTLED" and amount < 0:
                refund_total -= amount
        elif kind == "MANUAL_ADJUSTMENT" and row.get("label") == "PAYOUT":
            # A cash payout draws down the owed refund balance; POST
            # /customers/{id}/payouts states that as its own side effect, so the
            # ledger row it writes is what moves refund_balance_cents.
            refund_total += amount
        elif kind in ("RETURN_GOODWILL", "MANUAL_ADJUSTMENT"):
            credit_total += amount
    refund_total = max(0, refund_total)
    credit_total = max(0, credit_total)
    drift = False
    if customer["refund_balance_cents"] != refund_total:
        customer["refund_balance_cents"] = refund_total
        drift = True
    if customer["store_credit_balance_cents"] != credit_total:
        customer["store_credit_balance_cents"] = credit_total
        drift = True
    if drift:
        touch(customer)
    return drift


def customer_balance_drift(customer):
    """Reconcile and report whether a repair was needed, without mutating twice."""
    before = (customer["refund_balance_cents"], customer["store_credit_balance_cents"])
    reconcile_customer(customer)
    after = (customer["refund_balance_cents"], customer["store_credit_balance_cents"])
    return before != after


# --------------------------------------------------------------------------
# shop state machine
# --------------------------------------------------------------------------

def shop_has_committed_event(shop_id, exclude_event_id=None):
    """A SCHEDULED or LIVE event other than the excluded one."""
    for event in calc.events_of_shop(shop_id):
        if event["id"] == exclude_event_id:
            continue
        if event["event_status"] in ("SCHEDULED", "LIVE"):
            return True
    return False


def shop_has_live_event(shop_id):
    for event in calc.events_of_shop(shop_id):
        if event["event_status"] == "LIVE":
            return True
    return False


def refresh_shop(shop, exclude_event_id=None):
    """Bubble the shop's status from its events and its vendor's standing."""
    vendor = db.vendors.get(shop["vendor_id"])
    open_like = vendor is not None and vendor["standing"] in ("EXCELLENT", "GOOD")
    if vendor is not None and vendor["standing"] in ("PROBATION", "SUSPENDED"):
        if shop["shop_status"] in ("OPEN", "SCHEDULED", "DRAFT"):
            shop["shop_status"] = "SUSPENDED"
            touch(shop)
    elif not open_like:
        pass
    else:
        if shop["shop_status"] == "SUSPENDED":
            shop["shop_status"] = "OPEN" if shop_has_live_event(shop["id"]) else "SCHEDULED"
            touch(shop)
        elif shop["shop_status"] == "DRAFT":
            if shop_has_committed_event(shop["id"], exclude_event_id):
                shop["shop_status"] = "SCHEDULED"
                touch(shop)
        elif shop["shop_status"] in ("SCHEDULED", "OPEN"):
            if shop_has_live_event(shop["id"]):
                if shop["shop_status"] != "OPEN":
                    shop["shop_status"] = "OPEN"
                    touch(shop)
            elif not shop_has_committed_event(shop["id"], exclude_event_id):
                shop["shop_status"] = "CLOSED"
                shop["curated_sku_count"] = 0
                touch(shop)
    recompute_curated(shop)
    return shop


def recompute_curated(shop):
    count = 0
    for event in calc.events_of_shop(shop["id"]):
        if event["event_status"] not in ("SCHEDULED", "LIVE"):
            continue
        for listing in calc.listings_of_event(event["id"]):
            if listing["listing_status"] == "ACTIVE":
                count += 1
    if shop["curated_sku_count"] != count:
        shop["curated_sku_count"] = count
        touch(shop)
    return count


def suspend_shops_of_vendor(vendor_id):
    for shop in [s for s in db.shops.values() if s["vendor_id"] == vendor_id]:
        if shop["shop_status"] in ("OPEN", "SCHEDULED", "DRAFT"):
            shop["shop_status"] = "SUSPENDED"
            touch(shop)


def reopen_shops_of_vendor(vendor_id):
    for shop in [s for s in db.shops.values() if s["vendor_id"] == vendor_id]:
        if shop["shop_status"] == "SUSPENDED":
            shop["shop_status"] = "OPEN" if shop_has_live_event(shop["id"]) else "SCHEDULED"
            touch(shop)
            recompute_curated(shop)


# --------------------------------------------------------------------------
# event cascades
# --------------------------------------------------------------------------

def orders_touched_by(lines):
    ids = []
    for line in lines:
        if line["customer_order_id"] not in ids:
            ids.append(line["customer_order_id"])
    return [db.orders[i] for i in ids if i in db.orders]


def cancel_line(line, reason):
    if line["confirmation_status"] == "CANCELLED":
        return False
    line["confirmation_status"] = "CANCELLED"
    line["cancellation_reason"] = reason
    # A line cancelled only after it had been priced keeps its frozen price:
    # PRD §3.9's realized scope reads "CANCELLED but carrying a non-null
    # line_unit_price_cents — that is, a line cancelled only after it had been
    # priced", so the price is what distinguishes a priced cancellation from an
    # unplaced one that never held an allocation.
    listing = db.listings.get(line["listing_id"])
    if listing is not None:
        listing["units_ordered"] = max(0, listing["units_ordered"] - line["quantity"])
        touch(listing)
    calc.recompute_line_refund(line)
    touch(line)
    return True


def release_po_if_uncovered(po):
    """A buy whose every POLine reverted to OPEN resets to CANCELLED."""
    if po is None or po["po_status"] == "CANCELLED":
        return False
    lines = calc.polines_of_po(po["id"])
    if not lines:
        return False
    for line in lines:
        if line["poline_status"] != "OPEN" or line["quantity_ordered"] > 0:
            return False
    po["po_status"] = "CANCELLED"
    po["closed_at"] = now()
    po["quantity_ordered"] = 0
    touch(po)
    return True


def revert_buy_commitment(po):
    """Cancelling a buy: covered PURCHASE_ORDER_ISSUED lines -> VENDOR_CONFIRMED."""
    for line in calc.polines_of_po(po["id"]):
        line["poline_status"] = "OPEN"
        line["quantity_ordered"] = 0
        line["quantity_confirmed"] = 0
        line["quantity_shipped"] = 0
        touch(line)
    for confirmation in calc.all_confirmations():
        if confirmation["confirmation_status"] != "PURCHASE_ORDER_ISSUED":
            continue
        listing = db.listings.get(confirmation["listing_id"])
        if listing is None or listing["event_id"] != po["event_id"]:
            continue
        confirmation["confirmation_status"] = "VENDOR_CONFIRMED"
        touch(confirmation)
    recompute_cancellation_waived_for_event(po["event_id"])


def recompute_cancellation_waived_for_event(event_id):
    listing_ids = {l["id"] for l in calc.listings_of_event(event_id)}
    orders = set()
    for line in calc.all_confirmations():
        if line["listing_id"] in listing_ids:
            orders.add(line["customer_order_id"])
    for order_id in orders:
        order = db.orders.get(order_id)
        if order is None:
            continue
        waived = False
        for line in calc.lines_of_order(order_id):
            if line["confirmation_status"] in (
                "PURCHASE_ORDER_ISSUED", "IN_TRANSIT_TO_CROSS_DOCK",
                "RECEIVED_AT_CROSS_DOCK", "SHIPPED", "SHORT_SHIPPED",
            ):
                waived = True
                break
        if order["order_status"] == "DELIVERED":
            waived = True
        order["cancellation_waived"] = waived


def derive_order_status(order):
    """Re-derive the fulfillment posture from the line set."""
    lines = calc.lines_of_order(order["id"])
    if not lines:
        return order["order_status"]
    statuses = [l["confirmation_status"] for l in lines]
    if all(s == "CANCELLED" for s in statuses):
        order["order_status"] = "CANCELLED"
        return order["order_status"]
    if any(s in ("SHORT_SHIPPED",) for s in statuses) and not all(
        s in ("SHIPPED", "SHORT_SHIPPED", "CANCELLED") for s in statuses
    ):
        if order["order_status"] in ("AWAITING_VENDOR", "PARTIALLY_FILLED"):
            order["order_status"] = "PARTIALLY_FILLED"
        return order["order_status"]
    if statuses and all(s in ("SHIPPED", "SHORT_SHIPPED", "CANCELLED") for s in statuses):
        if order["order_status"] in ("AWAITING_VENDOR", "PARTIALLY_FILLED"):
            order["order_status"] = "READY_FOR_CONSOLIDATION"
        return order["order_status"]
    return order["order_status"]


def refresh_order_derived(order):
    calc.recompute_all_line_refunds(order)
    calc.recompute_order_refund(order)
    calc.refresh_cancellation_window(order)
    order["ready_to_ship"] = calc.ready_to_ship(order)
    return order


# --------------------------------------------------------------------------
# checkpoint helpers
# --------------------------------------------------------------------------

def lapse_return_escalations():
    """AI1_DENIED whose 72-hour escalation window lapsed -> DENIED."""
    lapsed = 0
    for request in list(db.returns.values()):
        if request["return_status"] != "AI1_DENIED":
            continue
        decided_at = request.get("ai_decided_at")
        if decided_at is None:
            decided_at = request.get("decided_at")
        if decided_at is None:
            decided_at = request.get("updated_at") or request.get("created_at")
        if now() >= decided_at + hours(72):
            request["return_status"] = "DENIED"
            request["decided_at"] = decided_at + hours(72)
            touch(request)
            lapsed += 1
    return lapsed


def restrict_over_cancellers():
    """3+ CANCELLATION ledger rows in the trailing 30 days -> RESTRICTED."""
    cutoff = now() - days(30)
    for customer in list(db.customers.values()):
        if customer["account_status"] != "ACTIVE":
            continue
        recent = 0
        for row in entries_for(customer["id"]):
            if row["source_kind"] != "CANCELLATION":
                continue
            if row["created_at"] > cutoff:
                recent += 1
        if recent >= 3:
            customer["account_status"] = "RESTRICTED"
            touch(customer)


def evaluate_vendor_standing(vendor, at=None):
    """Re-score one vendor.  Returns (old_standing, new_standing).

    Pinned order: window filter first, ratio second, tier written third.
    """
    at = at or now()
    unit_rate, _count_rate, _u_ord, _u_ship = calc.rolling_fill_rate(vendor["id"], at=at)
    late_short = calc.any_late_close_short(vendor["id"], at=at)
    old = vendor["standing"]
    new, _tier = calc.next_standing(old, unit_rate, late_short)
    if unit_rate is None and not late_short:
        return old, old
    if new != old:
        vendor["standing"] = new
    vendor["fill_rate_floor_pct"] = calc.FLOORS[new]
    vendor["standing_evaluated_at"] = at
    touch(vendor)
    # downward cascades are immediate
    if new in ("PROBATION", "SUSPENDED"):
        suspend_shops_of_vendor(vendor["id"])
    elif new in ("EXCELLENT", "GOOD"):
        reopen_shops_of_vendor(vendor["id"])
    return old, new


def rescore_vendors_in_scope():
    changed = []
    for vendor in list(db.vendors.values()):
        if calc.rolling_scope(vendor["id"]) or calc.any_late_close_short(vendor["id"]):
            old, new = evaluate_vendor_standing(vendor)
            if old != new:
                changed.append((vendor["id"], old, new))
    return changed


# --------------------------------------------------------------------------
# misc
# --------------------------------------------------------------------------

def escalate_count(return_id):
    return db.escalations.get(return_id, 0)


def record_escalation(return_id):
    db.escalations[return_id] = db.escalations.get(return_id, 0) + 1
    return db.escalations[return_id]


def all_order_line_ids(order_id):
    return [l["id"] for l in calc.lines_of_order(order_id)]


def shipment_ids_for_lines(lines):
    ids = set()
    for line in lines:
        listing = db.listings.get(line["listing_id"])
        if listing is None:
            continue
        po, poline = calc.po_of_listing(listing["id"])
        if po is None:
            continue
        for shipment in calc.shipments_of_po(po["id"]):
            if shipment["shipment_status"] == "RECEIVED":
                ids.add(shipment["id"])
    return ids