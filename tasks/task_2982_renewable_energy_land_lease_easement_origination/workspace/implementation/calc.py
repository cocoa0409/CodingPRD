"""The seven pinned calculations of PRD section 3 / SCAFFOLD section 1.3.

Every rounding step below is placed exactly where the specification places it:
per-term rounding before summation for acreage, per-component rounding before
the greater-of comparison for rent, one rounding per ledger row for fees.
"""

from decimal import Decimal

from util import D, r2, rcents

# ---------------------------------------------------------------- screening
W_INTERCONNECT = Decimal("0.30")
W_RESOURCE = Decimal("0.25")
W_BUILDABILITY = Decimal("0.20")
W_TITLE = Decimal("0.25")
TITLE_GRADE_POINTS = {"A": 100, "B": 80, "C": 55, "D": 20}
GRADE_LADDER = ["A", "B", "C", "D"]
TIER_PRIORITY_MIN = Decimal("82.00")
TIER_STANDARD_MIN = Decimal("65.00")
TIER_DEFERRED_MIN = Decimal("45.00")
INTERCONNECT_PENALTY_PER_KM = Decimal("8")
RESOURCE_SCALE = Decimal("250")
SLOPE_PENALTY_PER_PCT = Decimal("4")

# ------------------------------------------------------------------ acreage
CONSENT_RELEASE_FRACTION = Decimal("0.80")
MIN_BUILDABLE_ACRES = Decimal("80.00")

# --------------------------------------------------------------- option fees
EXTENSION_STEP_UP_BPS = 1500
EXTENSION_TERM_DAYS = 180

# ---------------------------------------------------------------------- rent
ROYALTY_PRICE_CENTS_PER_MWH = Decimal("4200")
LEASE_TERM_YEARS = 35
INVOICE_NET_DAYS = 45

# ------------------------------------------------------------------ security
SECURITY_PER_ACRE_CENTS = Decimal("50000")
SECURITY_TIER_1_CENTS = 5000000
SECURITY_TIER_2_CENTS = 15000000
ADMIN_RATE_LOW_BPS = 600
ADMIN_RATE_MID_BPS = 450
ADMIN_RATE_HIGH_BPS = 300

# ------------------------------------------------------------------ crossing
CROSSING_RATE_CENTS_PER_M = {
    "COLLECTION_LINE": 1800,
    "INTERCONNECTION_ROUTE": 3400,
    "ACCESS_ROAD": 900,
}
LONG_OCCUPANCY_FREE_DAYS = 30
LONG_OCCUPANCY_BPS_PER_DAY = 50
LONG_OCCUPANCY_CAP_BPS = 2500

# ------------------------------------------------------------------- others
PROHIBITED_ZONING_CODES = ("RES1", "CONS1")
PARCEL_MAX_CONCURRENT_CREWS = 3
MAX_NEGOTIATION_ROUNDS = 3
MAX_WAIVED_BLOCKING_PER_PARCEL = 1
SLOPE_TIER_BREAKS = (Decimal("5.0"), Decimal("10.0"), Decimal("15.0"))
SLOPE_TIER_RATES = (Decimal("0.00"), Decimal("0.10"), Decimal("0.25"), Decimal("0.50"))


def _clamp(value, low, high):
    if value < low:
        return low
    if value > high:
        return high
    return value


# =============================================================== screening
def effective_grade(grade, blocking_open_count, screen_mode):
    """DESKTOP takes the desktop grade; FIELD_VERIFIED steps it down."""
    if screen_mode != "FIELD_VERIFIED":
        return grade
    index = GRADE_LADDER.index(grade) + int(blocking_open_count)
    if index > 3:
        index = 3
    return GRADE_LADDER[index]


def screening_score(interconnection_distance_km, resource_capacity_factor,
                    slope_pct, grade, blocking_open_count, screen_mode):
    interconnect_sub = _clamp(
        D(100) - INTERCONNECT_PENALTY_PER_KM * D(interconnection_distance_km),
        D(0), D(100),
    )
    resource_sub = r2(D(resource_capacity_factor) * RESOURCE_SCALE)
    buildability_sub = _clamp(
        D(100) - SLOPE_PENALTY_PER_PCT * D(slope_pct), D(0), D(100),
    )
    grade_used = effective_grade(grade, blocking_open_count, screen_mode)
    title_sub = D(TITLE_GRADE_POINTS[grade_used])
    score = r2(
        W_INTERCONNECT * interconnect_sub
        + W_RESOURCE * resource_sub
        + W_BUILDABILITY * buildability_sub
        + W_TITLE * title_sub
    )
    return score


def screening_tier(score):
    score = D(score)
    if score >= TIER_PRIORITY_MIN:
        return "PRIORITY"
    if score >= TIER_STANDARD_MIN:
        return "STANDARD"
    if score >= TIER_DEFERRED_MIN:
        return "DEFERRED"
    return "REJECTED"


# ================================================================= acreage
def slope_rate(slope_pct):
    slope = D(slope_pct)
    if slope <= SLOPE_TIER_BREAKS[0]:
        return SLOPE_TIER_RATES[0]
    if slope <= SLOPE_TIER_BREAKS[1]:
        return SLOPE_TIER_RATES[1]
    if slope <= SLOPE_TIER_BREAKS[2]:
        return SLOPE_TIER_RATES[2]
    return SLOPE_TIER_RATES[3]


def slope_excluded(gross_acres, slope_pct):
    return r2(D(gross_acres) * slope_rate(slope_pct))


def rule_term(gross_acres, encumbrance_rate_per_acre):
    """One setback rule's contribution, rounded BEFORE summation."""
    return r2(D(gross_acres) * D(encumbrance_rate_per_acre))


def consent_term(gross_acres, encumbrance_rate_per_acre):
    """One granted consent's release term, rounded BEFORE summation."""
    return r2(D(gross_acres) * D(encumbrance_rate_per_acre)
              * CONSENT_RELEASE_FRACTION)


def floor_acres(value):
    rounded = r2(value)
    return rounded if rounded > D("0.00") else D("0.00")


# ============================================================= option fees
def initial_option_fee_cents(option_fee_per_acre_cents, gross_acres):
    return rcents(D(option_fee_per_acre_cents) * D(gross_acres))


def extension_fee_cents(extension_fee_per_acre_cents, gross_acres, index):
    step_up = D(1) + D(EXTENSION_STEP_UP_BPS) / D(10000)
    return rcents(
        D(extension_fee_per_acre_cents) * D(gross_acres)
        * (step_up ** (int(index) - 1))
    )


# ==================================================================== rent
def escalation_factor(escalator_pct_bps, escalator_mode, period_year):
    elapsed = int(period_year) - 1
    rate = D(escalator_pct_bps) / D(10000)
    if escalator_mode == "COMPOUND":
        return (D(1) + rate) ** elapsed
    return D(1) + rate * D(elapsed)


def per_acre_component_cents(base_rent_per_acre_cents, acre_basis,
                             escalator_pct_bps, escalator_mode, period_year):
    base_cents = rcents(D(base_rent_per_acre_cents) * D(acre_basis))
    factor = escalation_factor(escalator_pct_bps, escalator_mode, period_year)
    return rcents(D(base_cents) * factor)


def royalty_component_cents(production_mwh, royalty_rate_bps):
    return rcents(D(production_mwh) * ROYALTY_PRICE_CENTS_PER_MWH
                  * D(royalty_rate_bps) / D(10000))


def gross_rent_cents(rent_structure_type, per_acre_cents, royalty_cents):
    if rent_structure_type == "ROYALTY_HYBRID":
        return max(int(per_acre_cents), int(royalty_cents))
    return int(per_acre_cents)


def rent_amounts(option, acre_basis, period_year, production_mwh, variant):
    """Returns (acre_basis, per_acre_cents, royalty_cents, gross_cents)."""
    per_acre = per_acre_component_cents(
        option["base_rent_per_acre_cents"], acre_basis,
        option["escalator_pct_bps"], option["escalator_mode"], period_year,
    )
    if variant == "PROVISIONAL":
        royalty = 0
    else:
        royalty = royalty_component_cents(production_mwh,
                                          option["royalty_rate_bps"])
    gross = gross_rent_cents(option["rent_structure_type"], per_acre, royalty)
    return per_acre, royalty, gross


# ================================================================ security
def decommissioning_security(acre_basis):
    gross = rcents(SECURITY_PER_ACRE_CENTS * D(acre_basis))
    if gross < SECURITY_TIER_1_CENTS:
        admin_rate = ADMIN_RATE_LOW_BPS
    elif gross < SECURITY_TIER_2_CENTS:
        admin_rate = ADMIN_RATE_MID_BPS
    else:
        admin_rate = ADMIN_RATE_HIGH_BPS
    loading = rcents(D(gross) * D(admin_rate) / D(10000))
    return gross, admin_rate, loading, gross + loading


# ================================================================ crossing
def duration_days(start, end):
    """Whole days, rounded up: any part-day counts as a full day."""
    delta = end - start
    micros = (delta.days * 86400 + delta.seconds) * 1000000 + delta.microseconds
    if micros <= 0:
        return 0
    return -(-micros // 86400000000)


def crossing_surcharge_bps(days):
    if days <= LONG_OCCUPANCY_FREE_DAYS:
        return 0
    return min(LONG_OCCUPANCY_CAP_BPS,
               LONG_OCCUPANCY_BPS_PER_DAY * (int(days) - LONG_OCCUPANCY_FREE_DAYS))


def crossing_compensation(crossing_kind, occupied_m, days):
    base_cents = int(occupied_m) * CROSSING_RATE_CENTS_PER_M[crossing_kind]
    surcharge_bps = crossing_surcharge_bps(days)
    surcharge = rcents(D(base_cents) * D(surcharge_bps) / D(10000))
    return surcharge_bps, base_cents + surcharge
