"""Calculation rules (scaffold table 1.3 / PRD section 3) with pinned rounding.

All money is whole-cent integers; scores/payback are 2-decimal round-half-up.
Pinned orders honored: install quote rounds each component before summing;
payback rounds weekly->monthly units to an integer FIRST.
"""
from datetime import timedelta
from decimal import Decimal, ROUND_HALF_UP

from state import DB, now

# --- constants ---------------------------------------------------------------
FOOTPRINT_REFERENCE_SQFT = 32
WEIGHTS = {
    "DEMOGRAPHIC_LED": {"d": Decimal("0.45"), "v": Decimal("0.25"),
                        "f": Decimal("0.20"), "c": Decimal("0.10")},
    "VELOCITY_LED": {"d": Decimal("0.20"), "v": Decimal("0.55"),
                     "f": Decimal("0.15"), "c": Decimal("0.10")},
}
SCORE_ELIGIBILITY_MIN = Decimal("60.0")
CHILLER_UNIT_CENTS = {"STANDARD": 325000, "COMPACT": 218000}
CHILLER_CAPACITY = {"STANDARD": 240, "COMPACT": 120}
CHILLER_FOOTPRINT = {"STANDARD": 8, "COMPACT": 5}
INSTALL_FEE_CENTS = 45000
RATE_PER_SQFT_CENTS = 1250
RATE_PER_MILE_CENTS = 925
UNIT_MARGIN_CENTS = 180
WEEKS_PER_MONTH_NUM = 13
WEEKS_PER_MONTH_DEN = 3
PAYBACK_MAX_MONTHS = Decimal("36.0")
SHELF_LIFE_DAYS = 45
SAFETY_STOCK_FACTOR = Decimal("1.25")
CHILLER_TEMP_MIN_C = 0.0
CHILLER_TEMP_MAX_C = 4.0
EXCURSION_SEVERE_MINUTES = 120
BASE_MANUFACTURING_CAPACITY_UNITS = 200
VELOCITY_FLOOR_UNITS_PER_WEEK = 40
UNDERPERFORMING_STREAK_REMOVAL_MIN = 2
MAX_TRANSIT_HOURS = 48
EVALUATION_STALENESS_DAYS = 90
REMOVAL_LEAD_DAYS = 7
TRIAL_MIN_GAP_DAYS = 14


def D(x):
    return x if isinstance(x, Decimal) else Decimal(str(x))


def rhu(x, places=0):
    """round-half-up to `places` decimal places, via Decimal."""
    q = Decimal(1).scaleb(-places)
    return D(x).quantize(q, rounding=ROUND_HALF_UP)


# --- site selection ----------------------------------------------------------
def footprint_score(allocated_sqft):
    """min(100, round_half_up(100 * allocated_sqft / 32)) -- whole-number score."""
    v = rhu(D(100) * D(allocated_sqft) / D(FOOTPRINT_REFERENCE_SQFT), 0)
    if v > 100:
        v = Decimal(100)
    return int(v)


def composite_score(variant, demographic, velocity, footprint, competitor):
    w = WEIGHTS[variant]
    s = (w["d"] * D(demographic) + w["v"] * D(velocity)
         + w["f"] * D(footprint) - w["c"] * D(competitor))
    return rhu(s, 2)


# --- installation quote (per-component round-then-sum, pinned) ---------------
def install_quote(model, allocated_sqft, distance_miles):
    unit = CHILLER_UNIT_CENTS[model]
    sqft_cost = rhu(D(allocated_sqft) * RATE_PER_SQFT_CENTS, 0)
    mile_cost = rhu(D(distance_miles) * RATE_PER_MILE_CENTS, 0)
    return int(unit + INSTALL_FEE_CENTS + sqft_cost + mile_cost)


# --- payback (round monthly units to integer FIRST, pinned) ------------------
def payback_months(weekly_units, total_cost_cents):
    monthly_units = int(rhu(D(weekly_units) * WEEKS_PER_MONTH_NUM / WEEKS_PER_MONTH_DEN, 0))
    if monthly_units == 0:
        return None
    monthly_margin = monthly_units * UNIT_MARGIN_CENTS
    return rhu(D(total_cost_cents) / D(monthly_margin), 2)


# --- delivery frequency plan --------------------------------------------------
def delivery_tier(velocity):
    v = D(velocity)
    for floor, per_week in ((300, 5), (150, 3), (60, 2), (25, 1)):
        if v >= floor:
            return per_week
    return 0


def safety_stock_units(velocity, capacity_units):
    raw = rhu(D(velocity) * SHELF_LIFE_DAYS / 7 * SAFETY_STOCK_FACTOR, 0)
    return int(min(D(capacity_units), raw))


# --- excursion severity accumulator -------------------------------------------
def excursion_minutes_24h(chiller):
    """Sum of excursion duration_minutes with recorded_at in [now-24h, now]
    (inclusive both ends) and recorded_at strictly after last_repair_at."""
    hi = now()
    lo = hi - timedelta(hours=24)
    last = chiller.get("last_repair_at")
    total = 0
    for r in DB["readings"].get(chiller["id"], []):
        if not r["is_excursion"]:
            continue
        ra = r["recorded_at"]
        if ra < lo or ra > hi:
            continue
        if last is not None and ra <= last:
            continue
        total += r["duration_minutes"]
    return total


# --- manufacturing capacity ledger (pinned top-down order) --------------------
def commissioned_capacity():
    return sum(p["capacity_delta_units"] for p in DB["projects"].values()
               if p["status"] == "COMMISSIONED")


def total_capacity_units():
    return BASE_MANUFACTURING_CAPACITY_UNITS + commissioned_capacity()


def registered_units():
    return len(DB["chillers"])


def headroom():
    return total_capacity_units() - registered_units()
