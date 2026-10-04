"""Shared business logic: derived fields, calculations, serializers.

Implements PRD §2 (global specs) and §3 (business logic) for the
Instant-Needs MFC API. All temporal reasoning reads the logical clock
(db.now()); all money is integer cents rounded half-up at pinned points.
"""

import re
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP

import db
import errors

# ---------------------------------------------------------------------------
# Constants (calculation table §1.3)
# ---------------------------------------------------------------------------
TOBACCO_TAX_RATE = Decimal("0.07")
LOYALTY_RATE = Decimal("0.03")
LOYALTY_CAP_CENTS = 500
WALLET_FLOOR_CENTS = 0
MIN_AGE_RESTRICTED = 21
TENURE_DISCOUNT_BPS = 500
TENURE_THRESHOLD_PERIODS = 12
NIGHT_LIFT_PCT = Decimal("0.40")
WEATHER_LIFT_PCT = Decimal("0.25")

PRODUCT_CLASSES = {"STANDARD", "AGE_RESTRICTED", "PERISHABLE"}
DAYS = ["MON", "TUE", "WED", "THU", "FRI", "SAT", "SUN"]
FEE_FIELDS = ["base_cents", "per_mile_cents", "included_miles",
              "peak_surcharge_cents", "min_fee_cents", "max_fee_cents"]


# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------
def round_half_up_cents(value):
    """Round a Decimal/float to integer cents, half-up."""
    return int(Decimal(str(value)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def round_half_up_int(value):
    return int(Decimal(str(value)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def is_int(v):
    return isinstance(v, int) and not isinstance(v, bool)


def is_num(v):
    return (isinstance(v, (int, float)) and not isinstance(v, bool))


def parse_dt(value):
    """Parse an ISO 8601 date/datetime (UTC assumed when naive); None if invalid."""
    if not isinstance(value, str):
        return None
    s = value.strip()
    try:
        if "T" in s or " " in s:
            dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
        else:
            dt = datetime.strptime(s, "%Y-%m-%d")
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        else:
            dt = dt.astimezone(timezone.utc)
        return dt
    except (ValueError, TypeError):
        return None


def years_between(dob, ref):
    """Whole years elapsed from dob to ref; birthday-on-ref-date counts."""
    age = ref.year - dob.year
    if (ref.month, ref.day) < (dob.month, dob.day):
        age -= 1
    return age


def is_peak(site, dt):
    """True iff dt (UTC) falls inside any of the site's peak windows."""
    windows = site.get("peak_windows") or []
    if not windows:
        return False
    dow = DAYS[dt.weekday()]
    mins = dt.hour * 60 + dt.minute
    for w in windows:
        if not isinstance(w, dict):
            continue
        if w.get("day_of_week") != dow:
            continue
        try:
            sh, sm = [int(x) for x in str(w.get("start")).split(":")]
            eh, em = [int(x) for x in str(w.get("end")).split(":")]
        except (ValueError, TypeError):
            continue
        start = sh * 60 + sm
        end = eh * 60 + em
        if start <= end:
            if start <= mins < end:
                return True
        else:  # overnight window
            if mins >= start or mins < end:
                return True
    return False


# ---------------------------------------------------------------------------
# Lookups and derived state
# ---------------------------------------------------------------------------
def get_site(site_id):
    s = db.sites.get(site_id)
    if s is None:
        raise errors.err_site_not_found()
    return s


def get_product(product_id):
    p = db.products.get(product_id)
    if p is None:
        raise errors.err_product_not_found()
    return p


def get_customer(customer_id):
    c = db.customers.get(customer_id)
    if c is None:
        raise errors.err_customer_not_found()
    return c


def get_order(order_id):
    o = db.orders.get(order_id)
    if o is None:
        raise errors.err_order_not_found()
    return o


def get_batch(batch_id):
    b = db.pick_batches.get(batch_id)
    if b is None:
        raise errors.err_pick_batch_not_found()
    return b


def get_picker(picker_id):
    p = db.pickers.get(picker_id)
    if p is None:
        raise errors.err_picker_not_found()
    return p


def get_driver(driver_id):
    d = db.drivers.get(driver_id)
    if d is None:
        raise errors.err_driver_not_found()
    return d


def get_bag(bag_id):
    b = db.delivery_bags.get(bag_id)
    if b is None:
        raise errors.err_delivery_bag_not_found()
    return b


def get_replenish(rid):
    r = db.replenish_orders.get(rid)
    if r is None:
        raise errors.err_replenish_order_not_found()
    return r


def get_membership(mid):
    m = db.memberships.get(mid)
    if m is None:
        raise errors.err_membership_not_found()
    return m


def get_balance(bid):
    b = db.balances.get(bid)
    if b is None:
        raise errors.err_invalid_request("balance not found")
    return b


def get_lot(lot_id):
    l = db.lots.get(lot_id)
    if l is None:
        raise errors.err_stock_lot_not_found()
    return l


def effective_status(site):
    """PRD §2.5: SUSPENDED if suspended; else OPENED_REPLENISH while any
    ReplenishOrder of the site is PLACED; else OPERATING."""
    if site["status"] == "SUSPENDED":
        return "SUSPENDED"
    for r in db.replenish_orders.values():
        if r["site_id"] == site["id"] and r["status"] == "PLACED":
            return "OPENED_REPLENISH"
    return "OPERATING"


def lot_status(lot):
    """PRD §3.2: EXPIRED if expires_at <= now; EXPIRING if within horizon; else FRESH."""
    site = db.sites.get(lot["site_id"])
    horizon_days = site.get("expiry_horizon_days", 0) if site else 0
    now = db.now()
    exp = lot["expires_at"]
    if exp <= now:
        return "EXPIRED"
    if exp <= now + timedelta(days=horizon_days):
        return "EXPIRING"
    return "FRESH"


def fresh_lot_cover(site_id, product_id):
    """Sum of remaining_qty across FRESH lots of (site, product)."""
    total = 0
    for lot in db.lots.values():
        if lot["site_id"] == site_id and lot["product_id"] == product_id:
            if lot_status(lot) == "FRESH":
                total += lot["remaining_qty"]
    return total


def find_balance(site_id, product_id):
    for b in db.balances.values():
        if b["site_id"] == site_id and b["product_id"] == product_id:
            return b
    return None


def membership_for(customer_id):
    for m in db.memberships.values():
        if m["customer_id"] == customer_id:
            return m
    return None


def driver_run_size(driver_id):
    """Bags the driver currently holds in ASSIGNED or OUT_FOR_DELIVERY."""
    n = 0
    for bag in db.delivery_bags.values():
        if bag.get("driver_id") == driver_id and bag["delivery_status"] in ("ASSIGNED", "OUT_FOR_DELIVERY"):
            n += 1
    return n


# ---------------------------------------------------------------------------
# Batch helpers
# ---------------------------------------------------------------------------
def batch_qtys(batch):
    """List of (order_id, total_qty) for appended orders, in append order."""
    return [(oid, sum(l["qty"] for l in db.orders[oid]["lines"]))
            for oid in batch["order_ids"] if oid in db.orders]


def batch_item_total(batch):
    return sum(q for _, q in batch_qtys(batch))


def maybe_close_batch(batch_id):
    """SEALED -> CLOSED once every appended order is terminal."""
    batch = db.pick_batches.get(batch_id)
    if batch is None or batch["status"] != "SEALED":
        return
    if not batch["order_ids"]:
        return
    for oid in batch["order_ids"]:
        o = db.orders.get(oid)
        if o is None or o["status"] not in ("DELIVERED", "CANCELLED"):
            return
    batch["status"] = "CLOSED"
    db.touch(batch)


# ---------------------------------------------------------------------------
# Serializers
# ---------------------------------------------------------------------------
def _base(r):
    return {
        "id": r["id"],
        "created_at": db.fmt_ts(r["created_at"]),
        "updated_at": db.fmt_ts(r["updated_at"]),
        "version": r["version"],
    }


def serialize_site(s):
    out = _base(s)
    out.update({
        "code": s["code"],
        "name": s["name"],
        "delivery_radius_miles": s["delivery_radius_miles"],
        "fee_schedule": s["fee_schedule"],
        "fee_waiver_threshold_cents": s["fee_waiver_threshold_cents"],
        "batch_max_lines": s["batch_max_lines"],
        "batch_max_items": s["batch_max_items"],
        "expiry_horizon_days": s["expiry_horizon_days"],
        "peak_windows": s.get("peak_windows") or [],
        "status": s["status"],
        "effective_status": effective_status(s),
    })
    return out


def serialize_product(p):
    out = _base(p)
    out.update({
        "sku": p["sku"],
        "name": p["name"],
        "price_cents": p["price_cents"],
        "product_class": p["product_class"],
        "restricted": p["product_class"] == "AGE_RESTRICTED",
        "perishable": p["product_class"] == "PERISHABLE",
        "status": p["status"],
    })
    return out


def serialize_balance(b):
    out = _base(b)
    out.update({
        "site_id": b["site_id"],
        "product_id": b["product_id"],
        "on_hand": b["on_hand"],
        "reserved": b["reserved"],
        "min_par_level": b["min_par_level"],
        "on_order": b["on_order"],
    })
    return out


def serialize_lot(l):
    out = _base(l)
    out.update({
        "site_id": l["site_id"],
        "product_id": l["product_id"],
        "lot_code": l["lot_code"],
        "received_qty": l["received_qty"],
        "remaining_qty": l["remaining_qty"],
        "expires_at": db.fmt_ts(l["expires_at"]),
        "status": lot_status(l),
    })
    return out


def serialize_customer(c):
    out = _base(c)
    out.update({
        "email": c["email"],
        "full_name": c["full_name"],
        "date_of_birth": db.fmt_ts(c["date_of_birth"]),
        "wallet_credit_cents": c["wallet_credit_cents"],
        "status": c["status"],
    })
    return out


def serialize_membership(m):
    out = _base(m)
    out.update({
        "customer_id": m["customer_id"],
        "tier": m["tier"],
        "status": m["status"],
        "monthly_fee_cents": m["monthly_fee_cents"],
        "current_period_start": db.fmt_ts(m["current_period_start"]),
        "current_period_end": db.fmt_ts(m["current_period_end"]),
        "periods_paid": m["periods_paid"],
        "period_orders_count": m["period_orders_count"],
        "period_credit_earned_cents": m["period_credit_earned_cents"],
        "auto_renew": m["auto_renew"],
        "tenure_discount_bps": m["tenure_discount_bps"],
    })
    return out


def serialize_replenish(r):
    out = _base(r)
    out.update({
        "site_id": r["site_id"],
        "reference": r["reference"],
        "lines": r["lines"],
        "expected_at": db.fmt_ts(r["expected_at"]),
        "status": r["status"],
        "idempotency_key": r["idempotency_key"],
    })
    return out


def serialize_order(o):
    out = _base(o)
    out.update({
        "customer_id": o["customer_id"],
        "site_id": o["site_id"],
        "lines": o["lines"],
        "delivery_distance_miles": o["delivery_distance_miles"],
        "contains_age_restricted": o["contains_age_restricted"],
        "subtotal_cents": o["subtotal_cents"],
        "tax_cents": o["tax_cents"],
        "delivery_fee_cents": o["delivery_fee_cents"],
        "loyalty_credit_applied_cents": o["loyalty_credit_applied_cents"],
        "total_cents": o["total_cents"],
        "pick_batch_id": o["pick_batch_id"],
        "status": o["status"],
    })
    return out


def serialize_batch(b):
    out = _base(b)
    out.update({
        "site_id": b["site_id"],
        "picker_id": b["picker_id"],
        "order_ids": list(b["order_ids"]),
        "total_items": batch_item_total(b),
        "sealed_at": db.fmt_ts(b["sealed_at"]) if b.get("sealed_at") else None,
        "sealed_by_id": b.get("sealed_by_id"),
        "status": b["status"],
    })
    return out


def serialize_picker(p):
    out = _base(p)
    out.update({
        "site_id": p["site_id"],
        "name": p["name"],
        "status": p["status"],
    })
    return out


def serialize_driver(d):
    out = _base(d)
    out.update({
        "site_id": d["site_id"],
        "name": d["name"],
        "max_run_orders": d["max_run_orders"],
        "status": d["status"],
    })
    return out


def serialize_bag(b):
    out = _base(b)
    out.update({
        "order_id": b["order_id"],
        "driver_id": b.get("driver_id"),
        "assigned_at": db.fmt_ts(b["assigned_at"]) if b.get("assigned_at") else None,
        "delivery_status": b["delivery_status"],
        "handoff_status": b["handoff_status"],
        "scanned_id_last4": b.get("scanned_id_last4"),
    })
    return out
