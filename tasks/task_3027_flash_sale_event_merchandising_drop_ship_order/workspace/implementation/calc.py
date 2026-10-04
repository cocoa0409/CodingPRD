"""Calculation rules (SCAFFOLD §1.3 / PRD §3.4, §3.6, §3.7, §3.9).

Every rule here is written from the pinned evaluation orders stated in the
scaffold, cross-checked against the PRD prose.  All money is integer cents;
``round_half_up`` is applied only at the steps the rule names.
"""

from decimal import Decimal

from store import db, hours, days, rhu, rhu_int, touch, now, ordered

# --------------------------------------------------------------------------
# constants (SCAFFOLD §1.3)
# --------------------------------------------------------------------------
STRATEGIC_SPIFF_RATE = Decimal("0.03")
BUFFER_CREDIT_PER_UNIT_CENTS = 2500
MAX_PENALTY_RATE = Decimal("0.40")
MIN_CONTRIBUTION_RATE = Decimal("0.15")
OVERSELL_PENALTY_MULTIPLIER = Decimal("1.50")

DISPATCH_CUTOFF_HOUR_UTC = 17
TRANSPARENCY_EMBARGO_HOURS = 6

WINDOW_DAYS = 90

MAX_OVERSELL_PCT = Decimal("0.20")

DUE_DAYS_TOTAL = 14

GRACE_HOURS = 30

BUFFER_HOURS = 2

BUCKET_CAPACITY_UNITS = 100
BUCKET_HOURS = 6

ANNUAL_CAP_CENTS = 50000
CS_GOODWILL_BASE_CENTS = 500
GOODWILL_PCT_OF_LINE = Decimal("0.50")
LINE_GOODWILL_CEILING_CENTS = 20000

SELL_THROUGH_TAIL_THRESHOLD = Decimal("0.9000")

# line scopes -------------------------------------------------------------
BOUGHT_STATES = (
    "VENDOR_CONFIRMED",
    "PURCHASE_ORDER_ISSUED",
    "IN_TRANSIT_TO_CROSS_DOCK",
    "RECEIVED_AT_CROSS_DOCK",
    "SHIPPED",
    "SHORT_SHIPPED",
)
REALIZED_STATES = ("SHIPPED", "SHORT_SHIPPED")
CONSUMING_STATES = (
    "PENDING_VENDOR",
    "VENDOR_CONFIRMED",
    "PURCHASE_ORDER_ISSUED",
    "IN_TRANSIT_TO_CROSS_DOCK",
    "RECEIVED_AT_CROSS_DOCK",
    "SHIPPED",
    "SHORT_SHIPPED",
)
TERMINAL_LINE_STATES = ("SHIPPED", "SHORT_SHIPPED", "CANCELLED")


# --------------------------------------------------------------------------
# small helpers
# --------------------------------------------------------------------------

def all_confirmations():
    return list(db.confirmations.values())


def lines_of_order(order_id):
    return [c for c in db.confirmations.values() if c["customer_order_id"] == order_id]


def lines_of_listing(listing_id):
    return [c for c in db.confirmations.values() if c["listing_id"] == listing_id]


def listings_of_event(event_id):
    return [l for l in db.listings.values() if l["event_id"] == event_id]


def events_of_shop(shop_id):
    return [e for e in db.events.values() if e["shop_id"] == shop_id]


def orders_of_customer(customer_id):
    return [o for o in db.orders.values() if o["customer_id"] == customer_id]


def pos_of_event(event_id):
    return [p for p in db.purchase_orders.values() if p["event_id"] == event_id]


def pos_of_vendor(vendor_id):
    return [p for p in db.purchase_orders.values() if p["vendor_id"] == vendor_id]


def polines_of_po(po_id):
    return [l for l in db.polines.values() if l["purchase_order_id"] == po_id]


def shipments_of_po(po_id):
    return [s for s in db.shipments.values() if s["purchase_order_id"] == po_id]


def returns_of_confirmation(confirmation_id):
    return [r for r in db.returns.values() if r["confirmation_id"] == confirmation_id]


def has_refunded_return(confirmation):
    for r in returns_of_confirmation(confirmation["id"]):
        if r["return_status"] == "REFUNDED":
            return True
    return False


def event_of_listing(listing):
    return db.events.get(listing["event_id"])


def shop_of_event(event):
    return db.shops.get(event["shop_id"])


def vendor_of_shop(shop):
    return db.vendors.get(shop["vendor_id"])


def vendor_of_po(po):
    return db.vendors.get(po["vendor_id"])


# Buy states in which a line can still be confirmed or shipped against it.
LIVE_PO_STATES = ("DRAFT", "ISSUED", "PARTIALLY_FILLED")


def po_of_listing(listing_id):
    """The buy currently covering a listing, if any.

    A listing can be covered by more than one buy over its lifetime — a buy closed
    short and then reopened, or a fresh buy raised against the same listing — so
    the active buy (one still admitting confirmations and shipments) is preferred
    over a terminal one. Only genuine buys are considered; a CANCELLED buy has
    released its coverage entirely.
    """
    uncovered = []
    for line in db.polines.values():
        if line["listing_id"] != listing_id:
            continue
        po = db.purchase_orders.get(line["purchase_order_id"])
        if po is None or po["po_status"] == "CANCELLED":
            continue
        if po["po_status"] in LIVE_PO_STATES:
            return po, line
        uncovered.append((po, line))
    if uncovered:
        return uncovered[0]
    return None, None


# --------------------------------------------------------------------------
# cancellation window — calculations.cancellation_window
# --------------------------------------------------------------------------

def cancellation_window(order):
    """min over non-CANCELLED lines of min(confirmed_at + 30h, event.ends_at).

    Returns None when the order has no non-CANCELLED lines: the window is
    undefined, not zero-length (PRD §3.3).
    """
    edges = []
    for line in lines_of_order(order["id"]):
        if line["confirmation_status"] == "CANCELLED":
            continue
        confirmed_at = line.get("confirmed_at")
        if confirmed_at is None:
            continue
        listing = db.listings.get(line["listing_id"])
        event = event_of_listing(listing) if listing else None
        per_line = confirmed_at + hours(GRACE_HOURS)
        if event is not None and event["ends_at"] < per_line:
            per_line = event["ends_at"]
        edges.append(per_line)
    if not edges:
        return None
    return min(edges)


def refresh_cancellation_window(order):
    order["cancellation_window_ends_at"] = cancellation_window(order)


# --------------------------------------------------------------------------
# order money — calculations.order_refund_claim
# --------------------------------------------------------------------------

def refundable_lines(order, include_paid=False):
    """Lines that still participate in order_refund_claim.

    EXCLUDED: lines still in PENDING_AGGREGATION (not yet placed) and lines whose
    ReturnRequest has reached REFUNDED (their value is settled by the return) —
    the two exclusions PRD §3.6 names. ``include_paid`` additionally keeps lines
    whose claim has already been paid out, which is what the outstanding-refund
    guards (consolidate, seal, refund) read; the variant recompute must not, so
    that a named variant reports the basis figure rather than the residual.
    """
    out = []
    for line in lines_of_order(order["id"]):
        if line["confirmation_status"] == "PENDING_AGGREGATION":
            continue
        if not include_paid and line.get("refund_paid"):
            continue
        if has_refunded_return(line):
            continue
        out.append(line)
    return out


def line_refund(line, variant="net_of_allocation"):
    """Per-line refund contribution, pinned order oversell -> short-ship."""
    price = line.get("line_unit_price_cents") or 0
    quantity = line["quantity"]
    confirmed = line.get("confirmed_units")
    if confirmed is None:
        confirmed = 0
    missing = max(0, quantity - confirmed)
    oversell = line.get("oversold_units") or 0
    short = line.get("short_shipped_units") or 0

    if variant == "gross_line_writeoff" and short > 0:
        return quantity * price
    oversell_refund = oversell * price
    shortship_refund = short * price
    return min(oversell_refund + shortship_refund, missing * price)


def total_line_refund(line):
    return line_refund(line, "net_of_allocation")


def order_refund_due(order, variant="net_of_allocation", include_paid=False):
    """Sum of per-line contributions; the cap is per line, never on the total."""
    return sum(line_refund(line, variant)
               for line in refundable_lines(order, include_paid=include_paid))


def recompute_order_refund(order, variant="net_of_allocation"):
    order["refund_due_cents"] = order_refund_due(order, variant)
    return order["refund_due_cents"]


def order_refund_with_writeoff(order, write_off=False):
    variant = "gross_line_writeoff" if write_off else "net_of_allocation"
    return order_refund_due(order, variant), variant


def recompute_line_refund(line):
    line["refund_due_cents"] = total_line_refund(line)
    return line["refund_due_cents"]


def recompute_all_line_refunds(order):
    for line in lines_of_order(order["id"]):
        recompute_line_refund(line)


def recompute_order_total(order):
    """Sum of line_unit_price_cents * quantity over non-refunded, non-cancelled lines."""
    total = 0
    for line in lines_of_order(order["id"]):
        if line["confirmation_status"] == "CANCELLED":
            continue
        if has_refunded_return(line):
            continue
        price = line.get("line_unit_price_cents") or 0
        total += price * line["quantity"]
    order["order_total_cents"] = total
    return total


def disclosed_ship_time(order):
    best = None
    for line in lines_of_order(order["id"]):
        listing = db.listings.get(line["listing_id"])
        event = event_of_listing(listing) if listing else None
        if event is None:
            continue
        value = event["ship_time_quote_days"]
        if best is None or value > best:
            best = value
    order["disclosed_ship_time_days"] = best
    return best


def ready_to_ship(order):
    lines = lines_of_order(order["id"])
    if not lines:
        return False
    for line in lines:
        if line["confirmation_status"] == "CANCELLED":
            continue
        if line["confirmation_status"] not in ("SHIPPED", "SHORT_SHIPPED"):
            return False
    return True


# --------------------------------------------------------------------------
# listing / event conserved quantities
# --------------------------------------------------------------------------

def computed_units_ordered(listing_id):
    total = 0
    for line in lines_of_listing(listing_id):
        if line["confirmation_status"] in CONSUMING_STATES:
            total += line["quantity"]
    return total


def reconcile_listing_units(listing):
    """Repair Listing.units_ordered on drift; True when a repair happened."""
    computed = computed_units_ordered(listing["id"])
    if listing["units_ordered"] != computed:
        listing["units_ordered"] = computed
        touch(listing)
        return True
    return False


def recompute_event_totals(event):
    units_ordered = 0
    oversell = 0
    for listing in listings_of_event(event["id"]):
        units_ordered += listing["units_ordered"]
        oversell += listing["oversell_units"]
    # PRD §3.9: "units_po_committed_total is the summed quantity_ordered across
    # the event's buys that are not CANCELLED". A DRAFT buy has not been placed
    # yet, which is why §3.1's LIVE-cancellation gate can still read exactly 0
    # for an event that already carries an unissued buy.
    po_committed = 0
    for po in pos_of_event(event["id"]):
        if po["po_status"] not in ("CANCELLED", "DRAFT"):
            po_committed += po["quantity_ordered"]
    event["units_ordered_total"] = units_ordered
    event["units_po_committed_total"] = po_committed
    event["oversell_units_total"] = max(0, oversell)
    return units_ordered, po_committed, over_ok(oversell)


def over_ok(value):
    return max(0, value)


def reconcile_event(event):
    """event_filled_units_reconciliation: repair + report drift."""
    drift = False
    for listing in listings_of_event(event["id"]):
        if reconcile_listing_units(listing):
            drift = True
    before = (event["units_ordered_total"], event["units_po_committed_total"],
              event["oversell_units_total"])
    recompute_event_totals(event)
    after = (event["units_ordered_total"], event["units_po_committed_total"],
             event["oversell_units_total"])
    if before != after:
        drift = True
    return drift


# --------------------------------------------------------------------------
# oversell watermark — calculations.oversell_allocation
# --------------------------------------------------------------------------

def candidate_lines(listing):
    return [
        c for c in lines_of_listing(listing["id"])
        if c["confirmation_status"] in ("PENDING_VENDOR", "VENDOR_CONFIRMED")
    ]


def order_candidates(lines, variant):
    """Order candidates per the active variant's declared sort key."""
    if variant == "cancel_newest_first":
        return sorted(
            lines,
            key=lambda l: (_rev(l.get("confirmed_at")),
                           l.get("line_unit_price_cents") or 0,
                           _rev(l.get("created_at"))),
        )
    # fifo_by_confirmed_at (the producer default)
    return sorted(
        lines,
        key=lambda l: (l.get("confirmed_at") or l.get("created_at"),
                       -(l.get("line_unit_price_cents") or 0),
                       l.get("created_at")),
    )


def _rev(value):
    """Descending key for an instant that tolerates None."""
    return (1, 0.0) if value is None else (0, -value.timestamp())


def oversell_split(listing, variant="fifo_by_confirmed_at"):
    """Return {line_id: oversold_units} for one listing.

    The variant's declared sort key orders the candidates by who KEEPS their
    units (``fifo_by_confirmed_at`` ⇒ the earliest-confirmed buyer keeps them;
    ``cancel_newest_first`` ⇒ the newest does), so the walk that consumes the
    excess runs that ordering from the tail backwards, each candidate absorbing
    ``min(remaining, quantity)`` until the excess is exhausted.

    This is the one reading under which both of the scaffold's worked examples
    hold: the fifo illustration (A confirmed 10:00, B confirmed 11:00, both
    quantity 3, allocation 4 ⇒ A=0, B=2) and the provisional illustration
    (same pair under ``cancel_newest_first`` ⇒ A=2, B=0). Applying the walk
    front-first instead would invert each of them.
    """
    allocation = listing["allocation_units"]
    if allocation <= 0:
        return {line["id"]: 0 for line in candidate_lines(listing)}
    excess = listing["units_ordered"] - allocation
    candidates = candidate_lines(listing)
    splits = {line["id"]: 0 for line in candidates}
    if excess <= 0:
        return splits
    remaining = excess
    for line in reversed(order_candidates(candidates, variant)):
        take = min(remaining, line["quantity"])
        splits[line["id"]] = take
        remaining -= take
        if remaining == 0:
            break
    return splits


def apply_oversell_watermark(listing, variant="fifo_by_confirmed_at"):
    """Persist the watermark: per-line oversold_units + the listing watermark."""
    allocation = listing["allocation_units"]
    splits = oversell_split(listing, variant)
    for line in lines_of_listing(listing["id"]):
        if line["id"] in splits:
            line["oversold_units"] = splits[line["id"]]
        elif line["confirmation_status"] not in ("PENDING_VENDOR", "VENDOR_CONFIRMED"):
            # post-buy states are never oversell territory
            if line["confirmation_status"] not in CONSUMING_STATES:
                line["oversold_units"] = 0
    excess = max(0, listing["units_ordered"] - allocation) if allocation > 0 else 0
    listing["oversell_units"] = excess
    for line in lines_of_listing(listing["id"]):
        recompute_line_refund(line)
    return splits


def oversell_units_total(listing):
    if listing["allocation_units"] <= 0:
        return 0
    return max(0, listing["units_ordered"] - listing["allocation_units"])


# --------------------------------------------------------------------------
# fill-rate ramp — calculations.fill_rate_shipment_gate
# --------------------------------------------------------------------------

def effective_floor(po, at=None):
    """round_half_up(floor * min(1, elapsed_days / 14), 4)."""
    at = at or now()
    floor = po.get("fill_rate_floor_pct")
    if floor is None:
        return None
    if po.get("issued_at") is None:
        return rhu(floor, 4)
    elapsed = (at - po["issued_at"]).total_seconds() / 86400.0
    fraction = min(Decimal(1), Decimal(str(elapsed / DUE_DAYS_TOTAL)))
    if fraction < 0:
        fraction = Decimal(0)
    return rhu(Decimal(str(floor)) * fraction, 4)


def projected_rate(po, extra_units=0):
    ordered = po.get("quantity_ordered") or 0
    if ordered <= 0:
        return Decimal("0")
    shipped = (po.get("quantity_shipped") or 0) + extra_units
    return rhu(Decimal(shipped) / Decimal(ordered), 4)


def shipment_admitted(po, extra_units):
    """Inclusive comparison against the ramped effective floor."""
    floor = effective_floor(po)
    if floor is None:
        return True
    return projected_rate(po, extra_units) >= floor


# --------------------------------------------------------------------------
# vendor rolling fill rate — calculations.vendor_rolling_fill_rate
# --------------------------------------------------------------------------

def rolling_scope(vendor_id, window_days=WINDOW_DAYS, at=None):
    at = at or now()
    window_start = at - days(window_days)
    scope = []
    for po in pos_of_vendor(vendor_id):
        if po["po_status"] not in ("FILLED", "CLOSED_SHORT"):
            continue
        if po.get("issued_at") is None:
            continue
        closed_at = po.get("closed_at")
        if closed_at is None or not (closed_at > window_start):
            continue
        if (po.get("quantity_ordered") or 0) == 0:
            continue
        scope.append(po)
    return scope


def rolling_fill_rate(vendor_id, window_days=WINDOW_DAYS, at=None):
    scope = rolling_scope(vendor_id, window_days, at)
    units_ordered = sum(po["quantity_ordered"] for po in scope)
    units_shipped = sum(po["quantity_shipped"] for po in scope)
    if units_ordered <= 0:
        unit_weighted = None
    else:
        unit_weighted = rhu(Decimal(units_shipped) / Decimal(units_ordered), 4)
    closed = len(scope)
    if closed <= 0:
        count_weighted = None
    else:
        filled = len([po for po in scope if po["po_status"] == "FILLED"])
        count_weighted = rhu(Decimal(filled) / Decimal(closed), 4)
    return unit_weighted, count_weighted, units_ordered, units_shipped


def standing_from_rate(rate):
    """The tier a ratio produces (PRD §3.9)."""
    if rate is None:
        return None
    if rate >= Decimal("0.9700"):
        return "EXCELLENT"
    if rate >= Decimal("0.9000"):
        return "GOOD"
    if rate >= Decimal("0.7500"):
        return "PROBATION"
    return "SUSPENDED"


def any_late_close_short(vendor_id, window_days=WINDOW_DAYS, at=None):
    for po in rolling_scope(vendor_id, window_days, at):
        if po["po_status"] != "CLOSED_SHORT":
            continue
        closed_at = po.get("closed_at")
        due_at = po.get("due_at")
        if closed_at is not None and due_at is not None and closed_at > due_at:
            return True
    return False


def next_standing(current, rate, late_short=False):
    """Apply the tier ladder, honouring the cyclic SUSPENDED/PROBATION rules."""
    if rate is None:
        return current, current
    tier = standing_from_rate(rate)
    if current == "SUSPENDED":
        # only a ratio at or above 0.7500 recovers, and only as far as PROBATION
        if rate >= Decimal("0.7500"):
            return "PROBATION", "PROBATION"
        return "SUSPENDED", "SUSPENDED"
    if tier == "PROBATION" or late_short:
        return "PROBATION", "PROBATION"
    return tier, tier


FLOORS = {
    "EXCELLENT": 0.9000,
    "GOOD": 0.8500,
    "PROBATION": 0.9500,
    "SUSPENDED": 1.0000,
}


# --------------------------------------------------------------------------
# event net contribution — calculations.event_net_contribution
# --------------------------------------------------------------------------

def contribution_scope(event, realized=False):
    lines = []
    ids = {l["id"] for l in listings_of_event(event["id"])}
    for line in all_confirmations():
        if line["listing_id"] not in ids:
            continue
        status = line["confirmation_status"]
        if status in REALIZED_STATES:
            lines.append(line)
        elif status == "CANCELLED" and line.get("line_unit_price_cents") is not None:
            lines.append(line)
        else:
            if status in BOUGHT_STATES or status == "PENDING_VENDOR":
                lines.append(line)
    return lines


def event_net_contribution(event):
    """Eight pinned steps; the variant depends on event_status."""
    realized = event["event_status"] == "CLOSED"
    lines = contribution_scope(event, realized=realized)

    price_by_listing = {}
    for listing in listings_of_event(event["id"]):
        price_by_listing[listing["id"]] = listing

    units_sold = sum(line.get("confirmed_units") or 0 for line in lines)
    units_allocated = sum(l["allocation_units"] for l in listings_of_event(event["id"]))
    gross_revenue = sum(
        (line.get("line_unit_price_cents") or 0) * (line.get("confirmed_units") or 0)
        for line in lines
    )
    vendor_cost = 0
    for line in lines:
        listing = price_by_listing.get(line["listing_id"])
        if listing is None:
            continue
        vendor_cost += listing["vendor_unit_cost_cents"] * (line.get("confirmed_units") or 0)
    oversell_base = sum(
        (line.get("oversold_units") or 0) * (line.get("line_unit_price_cents") or 0)
        for line in lines
    )
    oversell_penalty = rhu_int(Decimal(oversell_base) * OVERSELL_PENALTY_MULTIPLIER)

    vendors = set()
    for listing in listings_of_event(event["id"]):
        shop = db.shops.get(listing and event["shop_id"])
        if shop:
            vendors.add(shop["vendor_id"])
    spiff_rate = Decimal("0")
    for vid in vendors:
        vendor = db.vendors.get(vid)
        if vendor is not None and vendor["vendor_tier"] == "STRATEGIC":
            spiff_rate = STRATEGIC_SPIFF_RATE
            break

    # step 1-2
    vendor_payable = rhu_int(Decimal(vendor_cost) * (Decimal(1) - spiff_rate))
    # step 3-4
    sell_through = Decimal(units_sold) / Decimal(max(units_allocated, 1))
    buffer_credit = rhu_int(sell_through * Decimal(BUFFER_CREDIT_PER_UNIT_CENTS))
    # step 5
    penalty = min(oversell_penalty, rhu_int(Decimal(gross_revenue) * MAX_PENALTY_RATE))
    # step 6
    provisional = gross_revenue - vendor_payable - penalty + buffer_credit
    if not realized and sell_through >= SELL_THROUGH_TAIL_THRESHOLD:
        tail = rhu_int(
            Decimal(units_allocated - units_sold) * sell_through
            * Decimal(BUFFER_CREDIT_PER_UNIT_CENTS)
        )
        provisional += tail
    # step 7
    floor = rhu_int(Decimal(gross_revenue) * MIN_CONTRIBUTION_RATE)
    # step 8
    return max(provisional, floor)


def refresh_event_contribution(event):
    if event["event_status"] in ("LIVE", "CLOSED"):
        event["net_contribution_cents"] = event_net_contribution(event)
        event["net_contribution_variant"] = (
            "REALIZED_ON_CLOSURE" if event["event_status"] == "CLOSED"
            else "PROJECTED_WHILE_LIVE"
        )
    return event.get("net_contribution_cents")


# --------------------------------------------------------------------------
# parcel dispatch ETA — calculations.cross_dock_dispatch_eta
# --------------------------------------------------------------------------

def dispatch_eta(parcel, sealed_at):
    lines = [db.confirmations.get(i) for i in parcel["contained_line_ids"]]
    lines = [l for l in lines if l is not None]
    lines = [l for l in lines if l["confirmation_status"] not in ("SHORT_SHIPPED", "CANCELLED")]
    if not lines:
        return None
    edges = []
    for line in lines:
        listing = db.listings.get(line["listing_id"])
        event = event_of_listing(listing) if listing else None
        if event is not None:
            edges.append((event["ship_time_quote_days"], event))
    if not edges:
        return None
    slowest_days = max(day for day, _ in edges)
    slowest_event = None
    for day, event in edges:
        if day == slowest_days:
            if slowest_event is None or event["ends_at"] > slowest_event["ends_at"]:
                slowest_event = event

    raw_eta = sealed_at + hours(slowest_days * 24)
    if sealed_at.hour >= DISPATCH_CUTOFF_HOUR_UTC:
        raw_eta = raw_eta + hours(24)
    embargo_eta = slowest_event["ends_at"] + hours(TRANSPARENCY_EMBARGO_HOURS)
    return max(raw_eta, embargo_eta)


# --------------------------------------------------------------------------
# dock buckets — calculations.cross_dock_bucket_capacity
# --------------------------------------------------------------------------

def bucket_index(instant):
    """6-hour buckets aligned to 00:00Z, inclusive on the left."""
    seconds = instant.hour * 3600 + instant.minute * 60 + instant.second
    return (instant.toordinal(), seconds // (BUCKET_HOURS * 3600))


def bucket_occupied(instant, exclude_id=None):
    target = bucket_index(instant)
    total = 0
    for shipment in db.shipments.values():
        if shipment["shipment_status"] != "RECEIVED":
            continue
        if shipment["id"] == exclude_id:
            continue
        arrived = shipment.get("arrived_at")
        if arrived is None:
            continue
        if bucket_index(arrived) == target:
            total += shipment["quantity_shipped"]
    return total


# --------------------------------------------------------------------------
# goodwill — calculations.goodwill_credit_cap
# --------------------------------------------------------------------------

def goodwill_credit(line, customer):
    price = line.get("line_unit_price_cents") or 0
    confirmed = line.get("confirmed_units") or 0
    base = min(price * confirmed, LINE_GOODWILL_CEILING_CENTS)
    raw = rhu_int(Decimal(base) * GOODWILL_PCT_OF_LINE) + CS_GOODWILL_BASE_CENTS
    headroom = ANNUAL_CAP_CENTS - (customer["lifetime_credit_issued_cents"] or 0)
    if headroom <= 0:
        return None, headroom
    return max(0, min(raw, headroom)), headroom


# --------------------------------------------------------------------------
# brand window overlap — calculations.shop_brand_window_overlap
# --------------------------------------------------------------------------

def brand_window_blocker(event, shop_id):
    """Return the blocking event, or None when the schedule is admitted."""
    buffer = hours(BUFFER_HOURS)
    start = event["starts_at"] - buffer
    end = event["ends_at"] + buffer
    blockers = []
    for other in events_of_shop(shop_id):
        if other["id"] == event["id"]:
            continue
        if other["event_status"] not in ("SCHEDULED", "LIVE"):
            continue
        o_start = other["starts_at"] - buffer
        o_end = other["ends_at"] + buffer
        if start <= o_end and o_start <= end:
            blockers.append(other)
    if not blockers:
        return None
    blockers.sort(key=lambda e: (e["starts_at"], e["created_at"]))
    return blockers[0]