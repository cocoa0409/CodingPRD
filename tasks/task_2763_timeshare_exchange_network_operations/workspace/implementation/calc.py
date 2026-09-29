"""The eight calculation specifications (SCAFFOLD 1.3 / PRD 3.3, 3.4, 3.5, 3.6, 3.7, 3.8).

Every rounding rule here is normative and deliberately NOT shared: the week
valuation rounds half up at exactly two points, the getaway price rounds half
up exactly once at the very end, the power budget and deposit-first credit
truncate, and the cancellation haircut rounds up.
"""

from decimal import Decimal, ROUND_HALF_UP, ROUND_CEILING

# --- deposit_trading_power -------------------------------------------------
UNIT_SIZE_BASE = {"STUDIO": 30, "ONE_BR": 45, "TWO_BR": 60, "THREE_BR": 80}
SEASON_MULT = {
    "PLATINUM": Decimal("1.50"),
    "GOLD": Decimal("1.25"),
    "SILVER": Decimal("1.00"),
    "BRONZE": Decimal("0.70"),
}
QUALITY_BONUS = {"GOLD_CROWN": 6, "SILVER_CROWN": 3, "STANDARD": 0, "HOSPITALITY": -4}
DEMAND_STEP = Decimal("0.10")
DEMAND_PIVOT = 3
LEAD_FACTOR_BANDS = [
    (270, Decimal("1.20")),
    (180, Decimal("1.10")),
    (90, Decimal("1.00")),
    (None, Decimal("0.85")),
]
POWER_FLOOR = 1

# --- request_power_budget -------------------------------------------------
REQUEST_FIRST_POWER_SURCHARGE_PCT = 10

# --- exchange_charge ------------------------------------------------------
SHORTFALL_CENTS_PER_POWER = 350
DEPOSIT_FIRST_CREDIT_BANDS = [(9999, 0), (19999, 5), (None, 10)]
PROCESSING_FEE_BANDS = [(14999, 1200), (29999, 2000), (None, 2900)]

# --- request_priority_score ----------------------------------------------
TIER_WEIGHT = {"BASIC": 0, "PLUS": 20, "ELITE": 40}
DEPOSIT_FIRST_BONUS = 15
TENURE_POINTS_PER_YEAR = 1
TENURE_POINTS_CAP = 10
DECLINE_PENALTY_PER_DECLINE = 5
DUES_ARREARS_PENALTY = 25
SCORE_FLOOR = 0

# --- resort_quality_score -------------------------------------------------
CLEANLINESS_WEIGHT = Decimal("0.40")
SERVICE_WEIGHT = Decimal("0.35")
AMENITIES_WEIGHT = Decimal("0.25")
REVIEW_WINDOW_SIZE = 8
MIN_REVIEWS_FOR_SCORE = 2
RATING_BANDS = [
    (Decimal("8.50"), "GOLD_CROWN"),
    (Decimal("7.00"), "SILVER_CROWN"),
    (Decimal("5.00"), "STANDARD"),
    (None, "HOSPITALITY"),
]
RATING_LADDER = ["GOLD_CROWN", "SILVER_CROWN", "STANDARD", "HOSPITALITY"]
COMPLAINT_STRIKE_THRESHOLD = 2
MAX_DOWNGRADE_NOTCHES = 3

# --- cancellation_settlement ---------------------------------------------
FULL_RESTORE_MIN_DAYS = 30
PRORATED_HAIRCUT_PCT = 25
LATE_CANCEL_SURCHARGE_CENTS = 7500

# --- getaway_list_price ---------------------------------------------------
GETAWAY_BASE_CENTS_PER_POWER = 900
DEMAND_PREMIUM_PCT_PER_STEP = 5
URGENCY_BANDS = [(120, 0), (60, 10), (30, 20), (None, 35)]
GETAWAY_FLOOR_CENTS = 29900
GETAWAY_CEILING_CENTS = 249900


def round_half_up(value, places=0):
    exponent = Decimal(1).scaleb(-places)
    return Decimal(value).quantize(exponent, rounding=ROUND_HALF_UP)


def truncate_div(numerator, denominator):
    """Integer division truncating toward zero."""
    quotient = abs(numerator) // abs(denominator)
    if (numerator < 0) != (denominator < 0):
        return -quotient
    return quotient


def lead_factor(lead_time_days):
    for threshold, factor in LEAD_FACTOR_BANDS:
        if threshold is None or threshold <= lead_time_days:
            return factor
    return LEAD_FACTOR_BANDS[-1][1]


def demand_multiplier(demand_index):
    return Decimal("1.00") + DEMAND_STEP * (Decimal(demand_index) - Decimal(DEMAND_PIVOT))


def trading_power(unit_size, band_code, demand_index, quality_rating, lead_time_days):
    """calculations.deposit_trading_power -- two roundings, in this exact order."""
    base = Decimal(UNIT_SIZE_BASE[unit_size])
    season_mult = SEASON_MULT[band_code]
    demand_mult = demand_multiplier(demand_index)
    bonus = QUALITY_BONUS[quality_rating]
    factor = lead_factor(lead_time_days)
    step_1 = round_half_up(base * season_mult * demand_mult, 0)
    step_2 = step_1 + Decimal(bonus)
    step_3 = round_half_up(step_2 * factor, 0)
    return max(POWER_FLOOR, int(step_3))


def power_budget(awarded_power, deposit_first_bonus_pct, funding_mode):
    """calculations.request_power_budget -- floor in both branches."""
    if funding_mode == "DEPOSIT_FIRST":
        return truncate_div(awarded_power * (100 + deposit_first_bonus_pct), 100)
    return truncate_div(awarded_power * 100, 100 + REQUEST_FIRST_POWER_SURCHARGE_PCT)


def _band_value(bands, subtotal):
    for ceiling, value in bands:
        if ceiling is None or ceiling >= subtotal:
            return value
    return bands[-1][1]


def exchange_charge(required_power_estimate, budget, base_exchange_fee_cents,
                    priority_surcharge_cents, funding_mode):
    """calculations.exchange_charge -- both bands keyed on the pre-credit subtotal."""
    power_gap = max(0, required_power_estimate - budget)
    shortfall_cents = power_gap * SHORTFALL_CENTS_PER_POWER
    subtotal_cents = base_exchange_fee_cents + shortfall_cents + priority_surcharge_cents
    credit_pct = _band_value(DEPOSIT_FIRST_CREDIT_BANDS, subtotal_cents)
    if funding_mode == "DEPOSIT_FIRST":
        credit_cents = truncate_div(subtotal_cents * credit_pct, 100)
    else:
        credit_cents = 0
    processing_fee_cents = _band_value(PROCESSING_FEE_BANDS, subtotal_cents)
    return {
        "power_gap": power_gap,
        "shortfall_cents": shortfall_cents,
        "subtotal_cents": subtotal_cents,
        "credit_pct": credit_pct,
        "credit_cents": credit_cents,
        "processing_fee_cents": processing_fee_cents,
        "quoted_charge_cents": subtotal_cents - credit_cents + processing_fee_cents,
    }


def priority_score(tier_code, funding_mode, member_created_date, as_of_date,
                   decline_count, dues_paid_through, window_start_date):
    """calculations.request_priority_score."""
    tier_points = TIER_WEIGHT[tier_code]
    mode_points = DEPOSIT_FIRST_BONUS if funding_mode == "DEPOSIT_FIRST" else 0
    days = (as_of_date - member_created_date).days
    tenure_years = truncate_div(days, 365)
    tenure_points = min(TENURE_POINTS_CAP, TENURE_POINTS_PER_YEAR * tenure_years)
    decline_penalty = DECLINE_PENALTY_PER_DECLINE * decline_count
    if dues_paid_through is None or dues_paid_through < window_start_date:
        arrears_penalty = DUES_ARREARS_PENALTY
    else:
        arrears_penalty = 0
    return max(SCORE_FLOOR,
               tier_points + mode_points + tenure_points - decline_penalty - arrears_penalty)


def composite_score(cleanliness_score, service_score, amenities_score):
    raw = (CLEANLINESS_WEIGHT * Decimal(cleanliness_score)
           + SERVICE_WEIGHT * Decimal(service_score)
           + AMENITIES_WEIGHT * Decimal(amenities_score))
    return round_half_up(raw, 2)


def mean_composite(composites):
    total = sum((Decimal(str(value)) for value in composites), Decimal("0"))
    return round_half_up(total / Decimal(len(composites)), 2)


def score_band(quality_score):
    for minimum, rating in RATING_BANDS:
        if minimum is None or minimum <= quality_score:
            return rating
    return RATING_BANDS[-1][1]


def shift_ladder(rating, downgrade_notches):
    index = RATING_LADDER.index(rating)
    return RATING_LADDER[min(len(RATING_LADDER) - 1, index + downgrade_notches)]


def cancellation_settlement(days_out, power_debited, deposit_awarded_power,
                            tier_cancellation_fee_cents):
    """calculations.cancellation_settlement -- inclusive on the full-restore side."""
    if days_out >= FULL_RESTORE_MIN_DAYS:
        return {
            "restoration_variant": "FULL_RESTORE",
            "restored_power": power_debited,
            "haircut_power": 0,
            "cancellation_fee_cents": tier_cancellation_fee_cents,
        }
    haircut = Decimal(deposit_awarded_power * PRORATED_HAIRCUT_PCT) / Decimal(100)
    haircut_power = int(haircut.to_integral_value(rounding=ROUND_CEILING))
    return {
        "restoration_variant": "PRORATED_RESTORE",
        "restored_power": power_debited,
        "haircut_power": haircut_power,
        "cancellation_fee_cents": tier_cancellation_fee_cents + LATE_CANCEL_SURCHARGE_CENTS,
    }


def getaway_list_price(settlement_power, demand_index, days_to_check_in):
    """calculations.getaway_list_price -- one rounding at the end, then floor, then ceiling."""
    raw_cents = Decimal(settlement_power * GETAWAY_BASE_CENTS_PER_POWER)
    demand_premium = DEMAND_PREMIUM_PCT_PER_STEP * (demand_index - DEMAND_PIVOT)
    adjusted_cents = raw_cents * Decimal(100 + demand_premium) / Decimal(100)
    urgency_discount_pct = 35
    for threshold, discount in URGENCY_BANDS:
        if threshold is None or threshold <= days_to_check_in:
            urgency_discount_pct = discount
            break
    discounted_cents = adjusted_cents * Decimal(100 - urgency_discount_pct) / Decimal(100)
    rounded = int(round_half_up(discounted_cents, 0))
    list_price_cents = min(GETAWAY_CEILING_CENTS, max(GETAWAY_FLOOR_CENTS, rounded))
    return {
        "list_price_cents": list_price_cents,
        "urgency_discount_pct": urgency_discount_pct,
    }
