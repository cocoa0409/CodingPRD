"""Calculation rules (SCAFFOLD §1.3 / PRD §2.6, §3).

All score and monetary math runs on Decimal; rounding is round-half-up at the
precision each rule pins. Allocation arithmetic runs in whole cases.
"""

import math
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_FLOOR, ROUND_HALF_UP

# --- equity_index_score (§3.2) ---
DIST_WEIGHT = Decimal("0.5")
FRESH_WEIGHT = Decimal("0.3")
SHARE_WEIGHT = Decimal("0.2")

# --- allocation_waterfall_assignment (§3.5) ---
TIER_MULT_GOLD = Decimal("1.2")
TIER_MULT_SILVER = Decimal("1.0")
TIER_MULT_BRONZE = Decimal("0.8")
TIER_MULT = {
    "GOLD": TIER_MULT_GOLD,
    "SILVER": TIER_MULT_SILVER,
    "BRONZE": TIER_MULT_BRONZE,
}

# --- performance_composite_score (§3.8) ---
CORRECTIVE_FLOOR = Decimal("70.00")
COMPOSITE_WEIGHTS = {
    "STANDARD": (Decimal("0.40"), Decimal("0.30"), Decimal("0.30")),
    "SHARE_TILTED": (Decimal("0.25"), Decimal("0.25"), Decimal("0.50")),
}

# --- keg_freshness_index (§3.6) ---
STALE_AGE_DAYS = 90
CRITICAL_AGE_DAYS = 120
MIN_AUDIT_GAP_SECONDS = 604800  # 7 days between accepted audits on one account

# --- pos_ytd_chargeable caps, integer cents (§3.7) ---
CAP_TX_CENTS = 30000
CAP_CA_CENTS = 25000
CAP_DEFAULT_CENTS = 20000

# --- successor_qualification_score (§3.3) ---
QUALIFY_THRESHOLD = Decimal("70.00")
FIN_WEIGHT = Decimal("0.5")
WH_WEIGHT = Decimal("0.3")
MKT_WEIGHT = Decimal("0.2")

# --- book_concentration_rule (§3.1) ---
COMPETING_MIN_COUNT = 4
CONCENTRATION_LIMIT = Decimal("0.50")
COMPETING_TYPES = frozenset({"CRAFT", "IMPORT"})

QUARTER_START_MONTH = {"Q1": 1, "Q2": 4, "Q3": 7, "Q4": 10}


def dec(x):
    return Decimal(str(x))


def round2(x):
    return dec(x).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def round1(x):
    return dec(x).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP)


def equity_index(distribution, freshness, share):
    """0.5*d + 0.3*f + 0.2*s, rounded half-up to 2 decimals."""
    return round2(DIST_WEIGHT * dec(distribution)
                  + FRESH_WEIGHT * dec(freshness)
                  + SHARE_WEIGHT * dec(share))


def qualification_score(financial, warehouse, market):
    """0.5*fin + 0.3*warehouse + 0.2*market, rounded half-up to 2 decimals."""
    return round2(FIN_WEIGHT * dec(financial)
                  + WH_WEIGHT * dec(warehouse)
                  + MKT_WEIGHT * dec(market))


def composite_score(distribution, freshness, share, profile):
    """Pinned order: round each input to 1dp half-up, weight, then round2."""
    wd, wf, ws = COMPOSITE_WEIGHTS[profile]
    blended = (wd * round1(distribution)
               + wf * round1(freshness)
               + ws * round1(share))
    return round2(blended)


def book_concentration_breached(supplier_book):
    """Reject when >= 4 competing (CRAFT/IMPORT) entries and the competing
    ratio is strictly greater than 0.50 (exactly one half is allowed)."""
    total = len(supplier_book)
    competing = sum(1 for e in supplier_book
                    if e.get("supplier_type") in COMPETING_TYPES)
    return (competing >= COMPETING_MIN_COUNT
            and (total == 0 or dec(competing) / dec(total) > CONCENTRATION_LIMIT))


def pos_cap_cents(state_code):
    if state_code == "TX":
        return CAP_TX_CENTS
    if state_code == "CA":
        return CAP_CA_CENTS
    return CAP_DEFAULT_CENTS


def whole_days(earlier, later):
    """Complete 86400-second days between two datetimes, partial day discarded."""
    return math.floor((later - earlier).total_seconds() / 86400)


def quarter_window(year, quarter):
    """[quarter_start, quarter_end] inclusive instants for a calendar quarter."""
    month = QUARTER_START_MONTH[quarter]
    start = datetime(year, month, 1, tzinfo=timezone.utc)
    if month == 10:
        next_start = datetime(year + 1, 1, 1, tzinfo=timezone.utc)
    else:
        next_start = datetime(year, month + 3, 1, tzinfo=timezone.utc)
    return start, next_start - timedelta(milliseconds=1)


def waterfall_assignments(requests, total_qty, min_guarantee, cap_pct):
    """Two-phase iterative waterfall (§3.5).

    `requests` are dicts carrying requested_qty_cases, created_at and _tier.
    Returns a list of assigned integer case quantities in request order.
    """
    n = len(requests)
    cap = int((dec(cap_pct) * dec(total_qty)).to_integral_value(rounding=ROUND_FLOOR))
    assigned = [min(r["requested_qty_cases"], min_guarantee, cap) for r in requests]
    pool = total_qty - sum(assigned)
    while pool > 0:
        capacity = [min(r["requested_qty_cases"], cap) - assigned[i]
                    for i, r in enumerate(requests)]
        active = [i for i in range(n) if capacity[i] > 0]
        if not active:
            break
        # Weights are fixed for the duration of the pass.
        weights = {i: dec(capacity[i]) * TIER_MULT[requests[i]["_tier"]]
                   for i in active}
        weight_sum = sum(weights.values())
        granted = {}
        for i in active:
            share = (dec(pool) * weights[i] / weight_sum).to_integral_value(
                rounding=ROUND_FLOOR)
            granted[i] = min(int(share), capacity[i])
        for i in active:
            assigned[i] += granted[i]
        remainder = pool - sum(granted.values())
        if remainder > 0:
            order = sorted(active,
                           key=lambda i: (-weights[i], requests[i]["created_at"], i))
            while remainder > 0:
                progressed = False
                for i in order:
                    if remainder == 0:
                        break
                    if min(requests[i]["requested_qty_cases"], cap) - assigned[i] > 0:
                        assigned[i] += 1
                        remainder -= 1
                        progressed = True
                if not progressed:
                    break
        pool = total_qty - sum(assigned)
    return assigned
