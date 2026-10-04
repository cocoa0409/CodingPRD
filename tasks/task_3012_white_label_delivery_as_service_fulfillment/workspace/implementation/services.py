"""Business logic: calculations (PRD section 3), serializers, shared workflows.

All monetary math uses integer cents with round-half-up applied per component
before summing (component-then-sum order pinned by PRD section 2.7).
"""
import math
import uuid
from datetime import timedelta
from decimal import Decimal, ROUND_HALF_UP

from zoneinfo import ZoneInfo

import db
import errors
import middleware as mw

# ---------------------------------------------------------------------------
# Constants (PRD section 3)
# ---------------------------------------------------------------------------
LATE_GRACE_SECONDS = 600
LATE_FULL_SECONDS = 1800
LATE_PARTIAL_PCT = Decimal("0.25")
PLATFORM_DELAY_CAP_MULTIPLIER = Decimal("2.0")
BATCH_BASE_COST_CENTS = 400
BATCH_PER_ORDER_CENTS = 150
CREDIT_TRIGGER_ATTAINMENT = Decimal("0.97")
MAX_APPEALS = 1
QUOTE_VALIDITY_MINUTES = 15
# Fixed return-handling fee debited when the merchant chooses RETURN_TO_STORE
# (PRD section 3.7 names RETURN_FEE_CENTS as a fixed platform fee).
RETURN_FEE_CENTS = 500

TERMINAL_FULFILLMENT = {"DELIVERED", "RETURNED_TO_STORE", "DISPOSED", "CANCELLED"}


def round_half_up(dec):
    return int(dec.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def dec(v):
    return Decimal(str(v))


# ---------------------------------------------------------------------------
# Serializers (common fields per PRD section 2.4)
# ---------------------------------------------------------------------------
def new_common():
    ts = mw.iso(db.now())
    return {"id": uuid.uuid4().hex, "created_at": ts, "updated_at": ts, "version": 1}


def touch(e):
    e["updated_at"] = mw.iso(db.now())
    e["version"] += 1


def merchant_view(m):
    return dict(m)


def store_view(s):
    return dict(s)


def policy_view(p):
    v = dict(p)
    v["effective_from"] = mw.iso(p["effective_from"])
    v["effective_until"] = mw.iso(p["effective_until"])
    return v


def override_view(o):
    return dict(o)


def quote_view(q):
    v = dict(q)
    v["pickup_ready_at"] = mw.iso(q["pickup_ready_at"])
    v["valid_until"] = mw.iso(q["valid_until"])
    return v


def order_view(o):
    v = dict(o)
    v["promised_at"] = mw.iso(o["promised_at"]) if o.get("promised_at") else None
    v["delivered_at"] = mw.iso(o["delivered_at"]) if o.get("delivered_at") else None
    return v


def courier_view(c):
    return dict(c)


def batch_view(b):
    v = dict(b)
    v["dispatch_window_start"] = mw.iso(b["dispatch_window_start"])
    v["dispatch_window_end"] = mw.iso(b["dispatch_window_end"])
    return v


def disposition_view(d):
    return dict(d)


def claim_view(c):
    return dict(c)


def report_view(r):
    v = dict(r)
    v["period_start"] = mw.iso(r["period_start"])
    v["period_end"] = mw.iso(r["period_end"])
    return v


def credit_view(c):
    return dict(c)


def tracking_view(t):
    return dict(t)


# ---------------------------------------------------------------------------
# Lookup helpers (path/body FK existence -> 404)
# ---------------------------------------------------------------------------
def get_merchant(mid):
    m = db.merchants.get(mid)
    if m is None:
        raise errors.not_found("merchant")
    return m


def get_store(sid):
    s = db.stores.get(sid)
    if s is None:
        raise errors.not_found("store")
    return s


def get_policy(pid):
    p = db.policies.get(pid)
    if p is None:
        raise errors.not_found("policy")
    return p


def get_quote(qid):
    q = db.quotes.get(qid)
    if q is None:
        raise errors.not_found("quote")
    return q


def get_order(oid):
    o = db.orders.get(oid)
    if o is None:
        raise errors.not_found("order")
    return o


def get_courier(cid):
    c = db.couriers.get(cid)
    if c is None:
        raise errors.not_found("courier")
    return c


def get_batch(bid):
    b = db.batches.get(bid)
    if b is None:
        raise errors.not_found("batch")
    return b


def get_disposition(did):
    d = db.dispositions.get(did)
    if d is None:
        raise errors.not_found("disposition")
    return d


def get_claim(cid):
    c = db.claims.get(cid)
    if c is None:
        raise errors.not_found("claim")
    return c


def get_report(rid):
    r = db.reports.get(rid)
    if r is None:
        raise errors.not_found("report")
    return r


def get_credit(cid):
    c = db.credits.get(cid)
    if c is None:
        raise errors.not_found("credit")
    return c


# ---------------------------------------------------------------------------
# Tracking events
# ---------------------------------------------------------------------------
def emit_event(order_id, event_type, note="", visibility="MERCHANT_VISIBLE"):
    e = {
        "id": uuid.uuid4().hex,
        "created_at": mw.iso(db.now()),
        "delivery_order_id": order_id,
        "event_type": event_type,
        "note": note,
        "visibility": visibility,
        "occurred_at": mw.iso(db.now()),
    }
    db.tracking_events[e["id"]] = e
    return e


# ---------------------------------------------------------------------------
# Distance / serviceability (PRD section 3.2)
# ---------------------------------------------------------------------------
def delivery_distance(store, dropoff_lat, dropoff_lng):
    mean_lat_rad = math.radians((store["lat"] + dropoff_lat) / 2)
    d = 111320 * abs(dropoff_lat - store["lat"]) \
        + 111320 * abs(dropoff_lng - store["lng"]) * math.cos(mean_lat_rad)
    return round_half_up(dec(d))


def serviceability(store, dropoff_lat, dropoff_lng, address_text):
    """Returns (serviceable, distance_m, matched_override_effect)."""
    d = delivery_distance(store, dropoff_lat, dropoff_lng)
    matching = [
        o for o in db.overrides.values()
        if o["store_id"] == store["id"]
        and o["address_pattern"].lower() in address_text.lower()
    ]
    if matching:
        # winner: longest address_pattern, tie-break earliest created_at
        longest = max(len(o["address_pattern"]) for o in matching)
        candidates = [o for o in matching if len(o["address_pattern"]) == longest]
        winner = min(candidates, key=lambda o: o["created_at"])
        effect = winner["effect"]
        if effect == "DENY":
            return False, d, effect
        return (d <= store["delivery_radius_m"]), d, effect
    return (d <= store["delivery_radius_m"]), d, None


# ---------------------------------------------------------------------------
# Delivery fee (PRD section 3.4) — quoted and final variants
# ---------------------------------------------------------------------------
def band_fee_for(policy, d):
    """Returns band fee in cents; raises ERR_OUTSIDE_DELIVERY_RADIUS beyond last band."""
    prev_max = 0
    for i, band in enumerate(policy["distance_bands"]):
        if d <= band["max_m"]:
            if i == 0:
                return band["base_cents"]
            excess = d - prev_max
            increments = -(-excess // 100)  # ceil division
            return band["base_cents"] + increments * band["per_100m_cents"]
        prev_max = band["max_m"]
    raise errors.ApiError("ERR_OUTSIDE_DELIVERY_RADIUS", 409,
                          "Distance exceeds the last pricing band's max_m")


def value_surcharge_for(policy, order_value_cents):
    best = 0
    best_min = None
    for tier in policy["value_tiers"]:
        if order_value_cents >= tier["min_order_value_cents"]:
            if best_min is None or tier["min_order_value_cents"] > best_min:
                best_min = tier["min_order_value_cents"]
                best = tier["surcharge_cents"]
    return best


def is_peak(policy, store, pickup_ready_at):
    local = pickup_ready_at.astimezone(ZoneInfo(store["timezone"]))
    hhmm = local.strftime("%H:%M")
    for w in policy["peak_windows"]:
        if w["start_local_hhmm"] <= hhmm < w["end_local_hhmm"]:
            return True
    return False


def fee_components(policy, store, d, order_value_cents, pickup_ready_at, surge_multiplier):
    band_fee = band_fee_for(policy, d)
    value_surcharge = value_surcharge_for(policy, order_value_cents)
    if is_peak(policy, store, pickup_ready_at):
        peak_uplift = round_half_up(dec(band_fee + value_surcharge) * dec(policy["peak_uplift_pct"]))
    else:
        peak_uplift = 0
    base_total = band_fee + value_surcharge + peak_uplift
    surge_component = round_half_up(dec(base_total) * (dec(surge_multiplier) - 1))
    total = base_total + surge_component
    return {
        "band_fee_cents": band_fee,
        "value_surcharge_cents": value_surcharge,
        "peak_uplift_cents": peak_uplift,
        "surge_component_cents": surge_component,
        "base_total": base_total,
        "total": total,
    }


def merchant_invoice(base_total, quoted_surge, final_surge, passthrough_pct):
    delta = round_half_up(dec(passthrough_pct) * (final_surge - quoted_surge))
    invoice = base_total + quoted_surge + delta
    if invoice < base_total:
        invoice = base_total
    return invoice


# ---------------------------------------------------------------------------
# Late delivery credit (PRD section 3.7)
# ---------------------------------------------------------------------------
def late_credit(order, event_time):
    lateness = (event_time - order["promised_at"]).total_seconds()
    if lateness <= LATE_GRACE_SECONDS:
        return 0
    if lateness <= LATE_FULL_SECONDS:
        return round_half_up(dec(order["merchant_invoice_cents"]) * LATE_PARTIAL_PCT)
    return order["merchant_invoice_cents"]


# ---------------------------------------------------------------------------
# Batch helpers
# ---------------------------------------------------------------------------
def batch_fee_allocation(batch, orders):
    courier_cost = batch["courier_cost_cents"]
    total_invoice = sum(o["merchant_invoice_cents"] for o in orders)
    allocs = []
    for o in orders:
        raw = dec(courier_cost) * dec(o["merchant_invoice_cents"]) / dec(total_invoice)
        allocs.append(int(raw))  # floor per order
    remainder = courier_cost - sum(allocs)
    if remainder:
        # granted to the order with earliest created_at
        idx = min(range(len(orders)), key=lambda i: orders[i]["created_at"])
        allocs[idx] += remainder
    return allocs


def maybe_complete_batch(order):
    bid = order.get("batch_id")
    if not bid:
        return
    b = db.batches.get(bid)
    if b is None or b["status"] != "DISPATCHED":
        return
    if all(db.orders[oid]["fulfillment_status"] in TERMINAL_FULFILLMENT for oid in b["order_ids"]):
        b["status"] = "COMPLETED"
        touch(b)


# ---------------------------------------------------------------------------
# Merchant suspension cascade (PRD section 3.1)
# ---------------------------------------------------------------------------
def suspend_merchant_cascade(merchant):
    merchant["status"] = "SUSPENDED"
    touch(merchant)
    for o in db.orders.values():
        if o["merchant_id"] != merchant["id"]:
            continue
        if o["fulfillment_status"] in ("QUOTED", "ACCEPTED", "READY_FOR_PICKUP"):
            was_authorized = o["billing_status"] == "AUTHORIZED"
            o["fulfillment_status"] = "CANCELLED"
            o["billing_status"] = "VOIDED"
            touch(o)
            if was_authorized:
                merchant["billing_balance_cents"] += o["quoted_fee_cents"]
                merchant["updated_at"] = mw.iso(db.now())


# ---------------------------------------------------------------------------
# Delivery-order settlement shared by complete-delivery / report-undeliverable
# ---------------------------------------------------------------------------
def settle_order_billing(order):
    """AUTHORIZED -> SETTLED and invoice reconciliation against the hold.

    The merchant's billing_balance_cents is adjusted by
    (merchant_invoice_cents - quoted_fee_cents); a negative delta refunds
    the merchant (PRD section 3.7).
    """
    merchant = db.merchants[order["merchant_id"]]
    order["billing_status"] = "SETTLED"
    merchant["billing_balance_cents"] -= (order["merchant_invoice_cents"] - order["quoted_fee_cents"])
    merchant["updated_at"] = mw.iso(db.now())
