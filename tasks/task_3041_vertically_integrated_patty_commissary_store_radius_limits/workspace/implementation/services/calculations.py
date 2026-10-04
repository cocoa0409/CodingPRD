"""Business calculations (SCAFFOLD §1.3). All constants pinned here."""

import math
from datetime import datetime, timezone, timedelta
from decimal import Decimal, ROUND_HALF_UP

import db

# --- constants ---
EARTH_RADIUS_KM = 6371.0

PATTIES_PER_LB = 3
PATTY_CASE = 40
BUN_CASE = 48
PRODUCE_CASE = 12

COLD_CHAIN_MAX_C = 4.0

NORMAL_MAX_GAP_HOURS = 48
SURGE_MAX_GAP_HOURS = 24
HIGH_DEMAND_MAX_GAP_HOURS = 24
HIGH_DEMAND_PATTY_WEEK = 10000  # PRD names a threshold without a value; no store
                                # carries a demand-class field, so standard (48h)
                                # applies to every store in practice.

PROJECTION_HORIZON_DAYS = 14
NEAR_DAILY_WEEKDAYS = {0, 1, 2, 3, 4, 5}  # Mon..Sat; surge days 1-3 drop Sunday

MODIFIER_UNIT_CENTS = {
    "EXTRA_PATTY": 150,
    "ANIMAL_STYLE": 65,
    "PROTEIN_STYLE": 0,
    "WELL_DONE": 0,
}
MODIFIER_CODES = set(MODIFIER_UNIT_CENTS.keys())
WELL_DONE_DISCOUNT_PCT = Decimal("0.10")

SURGE_WINDOW_DAYS = 7
SURGE_BUCKET_SIZE = 10
SURGE_PACING_STEP_MIN = 5
MIN_PACING_MIN = 5
PACING_CAP_MIN = {1: 45, 2: 45, 3: 45, 4: 30, 5: 30, 6: 20, 7: 20}

WAGE_CENTS = {
    "LEVEL_1": 1750,
    "LEVEL_2": 1850,
    "LEVEL_3": 1975,
    "LEVEL_4": 2100,
    "LEVEL_5": 2250,
    "SHIFT_LEAD": 2500,
    "MANAGER": 3200,
}
LADDER_ORDER = ["LEVEL_1", "LEVEL_2", "LEVEL_3", "LEVEL_4", "LEVEL_5", "SHIFT_LEAD", "MANAGER"]
TENURE_MIN_DAYS = 180
SHIFT_MIN_ACTIVE = 2
MAX_PROMOTIONS = 6

COVERAGE_CRITICAL_PCT = 0.50
MIN_LEADS = 1


# --- geography ---

def haversine_km(lat1, lng1, lat2, lng2):
    """Raw great-circle distance in km (unrounded)."""
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlmb = math.radians(lng2 - lng1)
    a = math.sin(dphi / 2.0) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlmb / 2.0) ** 2
    c = 2.0 * math.atan2(math.sqrt(a), math.sqrt(1.0 - a))
    return EARTH_RADIUS_KM * c


def round_half_up_3(value):
    return float(Decimal(repr(value)).quantize(Decimal("0.001"), rounding=ROUND_HALF_UP))


def radius_ok(raw_distance, radius_limit_km):
    """Strict comparison against the RAW haversine value."""
    return raw_distance < radius_limit_km


# --- surge ---

def surge_day_index(store):
    """1-based day index into the surge window; None when not surging."""
    if store.get("opening_mode") != "OPENING_SURGE":
        return None
    start = store.get("surge_start_date")
    if start is None:
        return None
    start_day = start.date() if isinstance(start, datetime) else start
    clock_day = db.clock_now().date()
    return (clock_day - start_day).days + 1


def effective_max_gap_hours(store):
    """24h during surge days 1-3 (and for high-demand stores), else 48h."""
    idx = surge_day_index(store)
    if store.get("opening_mode") == "OPENING_SURGE" and idx is not None and 1 <= idx <= 3:
        return SURGE_MAX_GAP_HOURS
    # No demand-class field exists on Store; standard stores use 48h.
    return NORMAL_MAX_GAP_HOURS


# --- delivery-day gap projection (store approval) ---

def delivery_day_gap_projection(store, commissary):
    """14-day forward projection from the current logical-clock day.

    Returns True iff >= 2 delivery-capable days exist and the worst gap between
    consecutive capable days (in hours) is within the store's effective max gap.
    """
    mask = commissary["delivery_days_mask"]
    clock_day = db.clock_now().date()
    capable = []
    for i in range(PROJECTION_HORIZON_DAYS):
        d = clock_day + timedelta(days=i)
        wd = d.weekday()
        ok = bool(mask[wd])
        # Surge carve-out: days 1-3 of an OPEN store's surge are not capable on
        # Sundays (weekday 6); Mon..Sat remain capable.
        if ok and store.get("status") == "OPEN" and store.get("opening_mode") == "OPENING_SURGE":
            start = store.get("surge_start_date")
            start_day = start.date() if isinstance(start, datetime) else start
            surge_day = (d - start_day).days + 1
            if surge_day in (1, 2, 3) and wd not in NEAR_DAILY_WEEKDAYS:
                ok = False
        if ok:
            capable.append(d)
    if len(capable) < 2:
        return False
    worst_gap_hours = 0
    for a, b in zip(capable, capable[1:]):
        gap = (b - a).days * 24
        if gap > worst_gap_hours:
            worst_gap_hours = gap
    return worst_gap_hours <= effective_max_gap_hours(store)


# --- cooler cases ---

def cooler_cases_required(patty_count, bun_count, produce_units):
    return (
        math.ceil(patty_count / PATTY_CASE)
        + math.ceil(bun_count / BUN_CASE)
        + math.ceil(produce_units / PRODUCE_CASE)
    )


# --- delivery gap at load ---

def previous_delivered_batch(store_id, delivery_date):
    """Latest DELIVERED batch for the store with delivered_at < delivery_date.
    Tie on delivered_at: latest created_at wins (ids never consulted)."""
    candidates = []
    for b in db.batches.values():
        if b["store_id"] != store_id or b["status"] != "DELIVERED":
            continue
        da = b.get("delivered_at")
        if da is None or da >= delivery_date:
            continue
        candidates.append(b)
    if not candidates:
        return None
    candidates.sort(key=lambda b: (b["delivered_at"], b["created_at"]))
    return candidates[-1]


def gap_hours(prev_delivered_at, delivery_date):
    delta = delivery_date - prev_delivered_at
    return round(delta.total_seconds() / 3600.0, 2)


# --- modifier proration ---

def line_modifier_cents(qty, modifier_codes):
    """Per-line modifier charge, rounded half-up to whole cents.

    EXTRA_PATTY scales with the line's unit count (qty * (1 + #EXTRA_PATTY));
    other priced modifiers are charged flat per line. WELL_DONE takes 10% off
    the line's pre-discount amount.
    """
    extra_patties = sum(1 for c in modifier_codes if c == "EXTRA_PATTY")
    units = qty * (1 + extra_patties)
    pre_discount = Decimal(0)
    for c in modifier_codes:
        if c == "EXTRA_PATTY":
            pre_discount += Decimal(MODIFIER_UNIT_CENTS[c]) * Decimal(units)
        else:
            pre_discount += Decimal(MODIFIER_UNIT_CENTS[c])
    if "WELL_DONE" in modifier_codes:
        pre_discount = pre_discount * (Decimal(1) - WELL_DONE_DISCOUNT_PCT)
    return int(pre_discount.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


# --- surge pacing ---

def surge_pacing(store):
    """Returns (opening_mode_now, pacing_minutes or None, queue_position).

    Queue depth is measured in units: the sum of line quantities over the
    store's PLACED orders. If the surge window has elapsed, opening_mode
    auto-reverts to NORMAL and no pacing applies.
    """
    open_units = sum(
        line["qty"]
        for o in db.orders.values()
        if o["store_id"] == store["id"] and o["status"] == "PLACED"
        for line in o["lines"]
    )
    queue_position = open_units + 1
    if store.get("opening_mode") != "OPENING_SURGE":
        return "NORMAL", None, queue_position
    idx = surge_day_index(store)
    if idx is None or idx > SURGE_WINDOW_DAYS:
        # Auto-revert: window elapsed.
        return "NORMAL", None, queue_position
    intensity = open_units // SURGE_BUCKET_SIZE
    raw = intensity * SURGE_PACING_STEP_MIN
    cap = PACING_CAP_MIN[idx]
    effective = max(MIN_PACING_MIN, min(raw, cap))
    return "OPENING_SURGE", effective, queue_position


# --- wage ladder ---

def wage_for_level(level):
    return WAGE_CENTS[level]


# --- staffing posture ---

def staffing_posture(store_id, extra_covering_shifts=0):
    """Coverage-first pinned evaluation order.

    The no-manager rule applies only once the store has an assigned manager
    (manager_associate_id non-null): a store still bootstrapping its crew is
    not CRITICAL merely for lacking a manager-level crew member.
    """
    clock = db.clock_now()
    store = db.stores.get(store_id)
    active_crew = [
        a for a in db.associates.values()
        if a["home_store_id"] == store_id and a.get("active", True)
    ]
    sched_today = extra_covering_shifts + sum(
        1 for s in db.shifts.values()
        if s["store_id"] == store_id
        and s["status"] == "SCHEDULED"
        and s["shift_start"] <= clock < s["shift_end"]
    )
    coverage_ratio = sched_today / max(len(active_crew), 1)
    if coverage_ratio < COVERAGE_CRITICAL_PCT:
        return "CRITICAL"
    has_assigned_manager = store is not None and store.get("manager_associate_id") is not None
    if has_assigned_manager and sum(1 for a in active_crew if a["current_level"] == "MANAGER") == 0:
        return "CRITICAL"
    if sum(1 for a in active_crew if a["current_level"] in ("SHIFT_LEAD", "MANAGER")) < MIN_LEADS:
        return "STRAINED"
    return "STEADY"


# --- supplier freshness ---

def days_since_last_passed_audit(supplier):
    """Calendar days from the most recent RECORDED PASS audit's completed_at to the
    logical clock; 0 if never passed."""
    passes = [
        a for a in db.audits.values()
        if a["supplier_id"] == supplier["id"]
        and a["status"] == "RECORDED"
        and a.get("result") == "PASS"
        and a.get("completed_at") is not None
    ]
    if not passes:
        return 0
    latest = max(passes, key=lambda a: a["completed_at"])
    return (db.clock_now().date() - latest["completed_at"].date()).days


def supplier_audit_fresh(supplier):
    """Freshness is independent of status: days <= audit_frequency_days (inclusive)."""
    return days_since_last_passed_audit(supplier) <= supplier["audit_frequency_days"]
