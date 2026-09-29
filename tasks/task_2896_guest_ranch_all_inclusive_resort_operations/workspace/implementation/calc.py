"""The thirteen named ranch calculations (PRD 2.6, 3.x).

Every money figure is integer cents and every rounding step is ROUND_HALF_UP,
applied at exactly the points the PRD names and nowhere else.
"""

import datetime
from decimal import ROUND_CEILING, ROUND_HALF_UP, Decimal

# ---------------------------------------------------------------- rank ladder
RANKS = {
    "UNASSESSED": 0,
    "BEGINNER": 1,
    "NOVICE": 2,
    "INTERMEDIATE": 3,
    "ADVANCED": 4,
}
RANK_NAMES = dict((v, k) for k, v in RANKS.items())
RIDER_RANKS = ("BEGINNER", "NOVICE", "INTERMEDIATE", "ADVANCED")
ALL_RANKS = ("UNASSESSED", "BEGINNER", "NOVICE", "INTERMEDIATE", "ADVANCED")

# ------------------------------------------------------------------ constants
LOS_BAND_1_MAX_NIGHTS = 7
LOS_BAND_2_MAX_NIGHTS = 13
LOS_BAND_2_DISCOUNT_PCT = Decimal("0.05")
LOS_BAND_3_DISCOUNT_PCT = Decimal("0.08")

GRATUITY_PCT = Decimal("0.18")
HIGH_SPEND_THRESHOLD_CENTS = 1200000
HIGH_SPEND_CREDIT_BONUS_CENTS = 5000

BEGINNER_PER_GUIDE = 4
NOVICE_PER_GUIDE = 6
INTERMEDIATE_PER_GUIDE = 8
ADVANCED_PER_GUIDE = 10
PER_GUIDE = {
    "BEGINNER": BEGINNER_PER_GUIDE,
    "NOVICE": NOVICE_PER_GUIDE,
    "INTERMEDIATE": INTERMEDIATE_PER_GUIDE,
    "ADVANCED": ADVANCED_PER_GUIDE,
}
STEEP_TERRAIN_MIN_GUIDES = 2
FLAT_TERRAIN_MIN_GUIDES = 1
MINOR_PRESENT_MIN_GUIDES = 2
STEEP_TERRAINS = ("STEEP", "RIVER_CROSSING")

FULL_REFUND_DAYS = 90
HALF_REFUND_DAYS = 60
QUARTER_REFUND_DAYS = 30

CAPITAL_RESERVE_PCT = Decimal("0.25")

MOUNT_RECOVERY_MINUTES = 60
MAX_DAILY_MOUNT_HOURS = Decimal("4.0")
MAX_CONSECUTIVE_DUTY_DAYS = 5

WAIVER_VALID_DAYS = 365
ADULT_AGE_YEARS = 18
MINOR_RIDER_AGE_YEARS = 12
GUIDE_DAILY_HOURS_CEILING = Decimal("10.0")

MOUNTED_ACTIVITIES = ("TRAIL_RIDE", "ARENA_LESSON")
ACTIVITY_CERTIFICATION = {
    "TRAIL_RIDE": "EQUINE_HANDLER",
    "ARENA_LESSON": "EQUINE_HANDLER",
    "FLY_FISHING": "FLY_CASTING",
    "KIDS_PROGRAM": "CHILD_PROGRAM",
    "HIKE": "WILDERNESS_FIRST_AID",
}


# ----------------------------------------------------------------- primitives
def dec(value):
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def round_half_up(value, places=0):
    exp = Decimal(1).scaleb(-places)
    return dec(value).quantize(exp, rounding=ROUND_HALF_UP)


def cents(value):
    """Round half up to a whole cent and return a Python int."""
    return int(round_half_up(value, 0))


def hours(value, places=1):
    """Round half up to `places` decimals and return a float."""
    return float(round_half_up(value, places))


def ceil_int(value):
    return int(dec(value).to_integral_value(rounding=ROUND_CEILING))


def days_between(start, end):
    return (end - start).days


def age_years(birth_date, on_date):
    if birth_date is None or on_date is None:
        return 0
    years = on_date.year - birth_date.year
    if (on_date.month, on_date.day) < (birth_date.month, birth_date.day):
        years -= 1
    return years


# ----------------------------------------------------- 1. package_charge_total
def los_discount_pct(nights):
    if nights <= LOS_BAND_1_MAX_NIGHTS:
        return Decimal("0")
    if nights <= LOS_BAND_2_MAX_NIGHTS:
        return LOS_BAND_2_DISCOUNT_PCT
    return LOS_BAND_3_DISCOUNT_PCT


def package_charge_total(tier, party_members, nights, is_buyout, buyout_premium_pct):
    """Per-member-line rounding, then summation; then the buyout premium."""
    los = los_discount_pct(nights)
    adult_rate = dec(tier["adult_nightly_rate_cents"])
    child_rate = round_half_up(adult_rate * (Decimal(1) - dec(tier["child_discount_pct"])), 0)
    subtotal = 0
    for member in party_members:
        nightly = adult_rate if member["member_type"] == "ADULT" else child_rate
        line = round_half_up(nightly * dec(nights) * (Decimal(1) - los), 0)
        subtotal += int(line)
    premium = 0
    if is_buyout:
        premium = cents(dec(subtotal) * dec(buyout_premium_pct))
    return subtotal, premium, subtotal + premium


def deposit_required_cents(package_total, deposit_pct):
    return cents(dec(package_total) * dec(deposit_pct))


# --------------------------------------------------- 2. folio_settlement_amount
def activity_credit_cap(tier, realized_subtotal_cents):
    cap = int(tier["included_activity_credit_cents"])
    if realized_subtotal_cents >= HIGH_SPEND_THRESHOLD_CENTS:
        cap += HIGH_SPEND_CREDIT_BONUS_CENTS
    return cap


def gratuity_cents(realized_subtotal_cents):
    return cents(dec(realized_subtotal_cents) * GRATUITY_PCT)


# ----------------------------------------------- 4. guide_staffing_requirement
def guide_staffing_requirement(rank_counts, minor_rider_count, terrain_grade, confirmed_rider_count):
    if confirmed_rider_count == 0:
        return 0
    total = Decimal(0)
    for rank, per_guide in PER_GUIDE.items():
        total += Decimal(rank_counts.get(rank, 0)) / Decimal(per_guide)
    ability_mix = ceil_int(total)
    terrain = (
        STEEP_TERRAIN_MIN_GUIDES
        if terrain_grade in STEEP_TERRAINS
        else FLAT_TERRAIN_MIN_GUIDES
    )
    minors = MINOR_PRESENT_MIN_GUIDES if minor_rider_count >= 1 else 0
    return max(ability_mix, terrain, minors)


# ----------------------------------------------- 5. cancellation_refund_split
def cancellation_refund_pct(days_out):
    if days_out >= FULL_REFUND_DAYS:
        return Decimal("1.00")
    if days_out >= HALF_REFUND_DAYS:
        return Decimal("0.50")
    if days_out >= QUARTER_REFUND_DAYS:
        return Decimal("0.25")
    return Decimal("0.00")


def cancellation_refund_split(deposit_paid_cents, days_out):
    pct = cancellation_refund_pct(days_out)
    refunded = cents(dec(deposit_paid_cents) * pct)
    forfeited = int(deposit_paid_cents) - refunded
    return float(pct), refunded, forfeited


# -------------------------------------------------------- 6. retention_bonus
def staff_days_worked(hired_on, contract_days, clock_date):
    raw = days_between(hired_on, clock_date)
    if raw < 0:
        raw = 0
    if raw > contract_days:
        raw = contract_days
    return raw


def pro_rated_bonus(retention_bonus_cents, days_worked, contract_days):
    if contract_days <= 0:
        return 0
    return cents(dec(retention_bonus_cents) * dec(days_worked) / dec(contract_days))


def settled_bonus(retention_bonus_cents, days_worked, contract_days, completed):
    if completed:
        return int(retention_bonus_cents)
    if days_worked * 2 < contract_days:
        return 0
    return pro_rated_bonus(retention_bonus_cents, days_worked, contract_days)


# ------------------------------------------------- 7. season_financial_rollup
def capital_reserve(net_surplus_cents):
    base = net_surplus_cents if net_surplus_cents > 0 else 0
    return cents(dec(base) * CAPITAL_RESERVE_PCT)


# ------------------------------------------------------- 13. duty-day run
def next_duty_run(last_duty_date, consecutive_duty_days, duty_date):
    if last_duty_date is None:
        return 1
    if last_duty_date == duty_date - datetime.timedelta(days=1):
        return int(consecutive_duty_days) + 1
    if last_duty_date == duty_date:
        return int(consecutive_duty_days)
    return 1


# ------------------------------------------------- interval helpers (slots)
def intervals_overlap(a_start, a_end, b_start, b_end):
    """Half-open [start, end) overlap."""
    return a_start < b_end and b_start < a_end


def dates_overlap(a_start, a_end, b_start, b_end):
    """Half-open [arrival, departure) overlap on calendar dates."""
    return a_start < b_end and b_start < a_end


def mount_buffer_conflict(cand_start, cand_end, other_start, other_end):
    """Strict recovery buffer on both sides; a gap of exactly 60 minutes is allowed."""
    buf = datetime.timedelta(minutes=MOUNT_RECOVERY_MINUTES)
    return cand_start < other_end + buf and other_start < cand_end + buf
