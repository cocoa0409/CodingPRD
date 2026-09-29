"""Pure arithmetic: rounding, interval algebra and the declared calculations."""

import math
from datetime import timedelta
from decimal import Decimal, getcontext
from fractions import Fraction

getcontext().prec = 60

ZERO = Decimal(0)

# ---- constants -------------------------------------------------------------
W_SEVERITY = 40
W_ENERGY = 30
W_LDA = 20
W_AGE = 10
ENERGY_NORMALIZER_KWH = Decimal(5000)
AGE_NORMALIZER_DAYS = Decimal(30)
MAX_REVISION_ROUNDS = 3

W_CATEGORY = 30
W_TYPE = 30
W_LENGTH = 20
W_EXPOSURE = 20
LENGTH_NORMALIZER_MM = Decimal(3000)
AREA_NORMALIZER_CM2 = Decimal(3000)
BAND_CRITICAL_MIN = Decimal(80)
BAND_HIGH_MIN = Decimal(60)
BAND_MEDIUM_MIN = Decimal(40)

CRANE_SHIFT_HOURS = Decimal(10)
TIER_1_MIN_CENTS = 5000000
TIER_2_MIN_CENTS = 15000000
TIER_1_CREDIT_PCT = 3
TIER_2_CREDIT_PCT = 6
CRANE_CANCELLATION_PCT = 40
CRANE_BUFFER_HOURS = 48
UPTOWER_LABOR_RATE_CENTS_PER_HOUR = 950000

PRE_SERVICE_WINDOW_HOURS = Decimal(200)
RESET_WINDOW_HOURS = 24
MAX_ACTIVE_CURTAILMENTS = 2

FAULT_SEVERITY_WEIGHT = {
    "LOCKOUT": Decimal("0.90"),
    "RESETTABLE": Decimal("0.60"),
    "ADVISORY": Decimal("0.20"),
}
DAMAGE_TYPE_FACTOR = {
    "LEADING_EDGE_EROSION": Decimal("0.30"),
    "CRACK_TRANSVERSE": Decimal("1.00"),
    "LIGHTNING_STRIKE": Decimal("0.70"),
    "DELAMINATION": Decimal("0.85"),
}
REPAIR_DUE_DAYS = {"CRITICAL": 14, "HIGH": 45, "MEDIUM": 120, "LOW": 365}


# ---- rounding --------------------------------------------------------------
def _round_half_up_ratio(num, den):
    """Nearest integer to num/den, ties away from zero. Exact."""
    if den < 0:
        num, den = -num, -den
    sign = -1 if num < 0 else 1
    n = -num if num < 0 else num
    q, r = divmod(n, den)
    if 2 * r >= den:
        q += 1
    return sign * q


def rhu(value, places=0):
    """Round half up to `places` decimals, returning a Decimal."""
    fr = value if isinstance(value, Fraction) else Fraction(value)
    scaled = fr * (10 ** places)
    i = _round_half_up_ratio(scaled.numerator, scaled.denominator)
    return Decimal(i).scaleb(-places)


def rhu_cents(value):
    """Round half up to a whole cent, returning a Python int."""
    fr = value if isinstance(value, Fraction) else Fraction(value)
    return _round_half_up_ratio(fr.numerator, fr.denominator)


def dfloor(value):
    fr = value if isinstance(value, Fraction) else Fraction(value)
    return fr.numerator // fr.denominator


def dceil(value):
    fr = value if isinstance(value, Fraction) else Fraction(value)
    return -((-fr.numerator) // fr.denominator)


def dmin(a, b):
    return a if a <= b else b


# ---- interval algebra ------------------------------------------------------
def micros_between(start, end):
    delta = end - start
    return delta.days * 86400 * 1000000 + delta.seconds * 1000000 + delta.microseconds


def hours_between(start, end):
    """Elapsed hours as a Decimal."""
    micros = micros_between(start, end)
    return Decimal(micros) / Decimal(3600 * 1000000)


def overlap_hours(a_start, a_end, b_start, b_end):
    """Hours common to two half-open intervals; zero when disjoint."""
    if a_start is None or a_end is None or b_start is None or b_end is None:
        return ZERO
    lo = a_start if a_start > b_start else b_start
    hi = a_end if a_end < b_end else b_end
    if hi <= lo:
        return ZERO
    return hours_between(lo, hi)


def overlaps(a_start, a_end, b_start, b_end):
    """Half-open overlap: adjacency does not overlap."""
    return a_start < b_end and a_end > b_start


def utc_dates(start, end):
    """Every UTC calendar date whose 00:00Z instant lies in [start, end).

    For a midnight-aligned span this is exactly the number of whole days in it.
    """
    out = []
    day = timedelta(days=1)
    cur = start.replace(hour=0, minute=0, second=0, microsecond=0)
    if cur < start:
        cur = cur + day
    while cur < end:
        out.append(cur)
        cur = cur + day
    return out


def date_contained(day_start, w_start, w_end):
    """Is [D 00:00Z, D+1 00:00Z) contained in [w_start, w_end)?"""
    return w_start <= day_start and (day_start + timedelta(days=1)) <= w_end


def whole_days_elapsed(start, end):
    return micros_between(start, end) // (86400 * 1000000)


# ---- blade damage severity -------------------------------------------------
def blade_severity(damage_category, damage_type, damage_length_mm, exposed_area_cm2):
    category_factor = Decimal(damage_category) / Decimal(5)
    type_factor = DAMAGE_TYPE_FACTOR[damage_type]
    length_factor = dmin(Decimal(1), Decimal(damage_length_mm) / LENGTH_NORMALIZER_MM)
    exposure_factor = dmin(Decimal(1), Decimal(exposed_area_cm2) / AREA_NORMALIZER_CM2)
    # The rounding order is pinned: each weighted term is rounded FIRST, the
    # rounded terms are summed, and the sum is rounded again.
    term_category = rhu(Decimal(W_CATEGORY) * category_factor, 2)
    term_type = rhu(Decimal(W_TYPE) * type_factor, 2)
    term_length = rhu(Decimal(W_LENGTH) * length_factor, 2)
    term_exposure = rhu(Decimal(W_EXPOSURE) * exposure_factor, 2)
    score = rhu(term_category + term_type + term_length + term_exposure, 2)
    if score >= BAND_CRITICAL_MIN:
        band = "CRITICAL"
    elif score >= BAND_HIGH_MIN:
        band = "HIGH"
    elif score >= BAND_MEDIUM_MIN:
        band = "MEDIUM"
    else:
        band = "LOW"
    return score, band, REPAIR_DUE_DAYS[band]


# ---- work order priority score --------------------------------------------
def priority_score(severity_weight, estimated_hours, expected_kwh_per_hour,
                   at_risk, days_open):
    projected = Decimal(estimated_hours) * Decimal(expected_kwh_per_hour)
    energy_factor = dmin(Decimal(1), projected / ENERGY_NORMALIZER_KWH)
    lda_factor = Decimal(1) if at_risk else Decimal(0)
    age_factor = dmin(Decimal(1), Decimal(days_open) / AGE_NORMALIZER_DAYS)
    # The four weighted terms are summed at FULL precision and the sum is
    # rounded exactly once.
    total = (
        Decimal(W_SEVERITY) * Decimal(severity_weight)
        + Decimal(W_ENERGY) * energy_factor
        + Decimal(W_LDA) * lda_factor
        + Decimal(W_AGE) * age_factor
    )
    return rhu(total, 2)


# ---- crane pricing ---------------------------------------------------------
def volume_credit_pct(subtotal_cents):
    if subtotal_cents < TIER_1_MIN_CENTS:
        return 0
    if subtotal_cents < TIER_2_MIN_CENTS:
        return TIER_1_CREDIT_PCT
    return TIER_2_CREDIT_PCT


def crane_lift_days(total_lift_hours):
    return dceil(Fraction(Decimal(total_lift_hours)) / Fraction(CRANE_SHIFT_HOURS))


def waterfall(total_cents, members):
    """Allocate total_cents across members, remainder to the earliest one.

    `members` is an ordered (created_at ASC) list of (key, lift_hours).
    Returns a dict key -> allocated cents.
    """
    shares = {}
    if not members:
        return shares
    total_lift = sum((Decimal(m[1]) for m in members), Decimal(0))
    count = len(members)
    for key, lift in members:
        if total_lift == 0:
            share = dfloor(Fraction(total_cents, count))
        else:
            share = dfloor(
                Fraction(total_cents) * Fraction(Decimal(lift)) / Fraction(total_lift)
            )
        shares[key] = share
    remainder = total_cents - sum(shares.values())
    shares[members[0][0]] = shares[members[0][0]] + remainder
    return shares


# ---- service due -----------------------------------------------------------
def service_figures(last_service_hours, interval_hours, tolerance_hours, operating_hours):
    due = Decimal(last_service_hours) + Decimal(interval_hours)
    flag = Decimal(operating_hours) >= due
    breached = Decimal(operating_hours) > due + Decimal(tolerance_hours)
    return due, flag, breached


# ---- availability ----------------------------------------------------------
def availability_pcts(counted_downtime_hours, period_hours, turbine_count,
                      actual_sum, potential_sum):
    denominator = Decimal(period_hours) * Decimal(turbine_count)
    time_based = rhu(
        Fraction(Decimal(100))
        * (Fraction(1) - Fraction(Decimal(counted_downtime_hours)) / Fraction(denominator)),
        4,
    )
    if Decimal(potential_sum) == 0:
        energy_based = Decimal("100.0000")
    else:
        energy_based = rhu(
            Fraction(Decimal(100))
            * Fraction(Decimal(actual_sum))
            / Fraction(Decimal(potential_sum)),
            4,
        )
    return time_based, energy_based


def shortfall_pct(guaranteed_pct, basis_pct):
    diff = Decimal(guaranteed_pct) - Decimal(basis_pct)
    if diff < 0:
        diff = Decimal(0)
    return rhu(diff, 4)
