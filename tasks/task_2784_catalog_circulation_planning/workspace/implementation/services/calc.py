"""Pure calculation kernels.

Every reduction to an integer is named explicitly, exactly where the
specification places it: `rhu_div` for round-half-up, `floor_div` for floor.
No float and no banker's rounding appears anywhere in this module.
"""

from util import floor_div, rhu_div

# ---------------------------------------------------------------------------
# 3.1  Recency / frequency / monetary scoring
# ---------------------------------------------------------------------------

TIER_STRATEGY_DEFAULT = {
    "BEST": "PREMIUM_FULL",
    "CORE": "STANDARD",
    "OCCASIONAL": "STANDARD",
    "LAPSED": "REACTIVATION",
    "DORMANT": "SUPPRESS_ONLY",
}


def rfm_score(recency_days, orders_12mo, ltv_cents):
    if recency_days <= 90:
        recency_points = 40
    elif recency_days <= 180:
        recency_points = 30
    elif recency_days <= 365:
        recency_points = 18
    elif recency_days <= 730:
        recency_points = 8
    else:
        recency_points = 0

    if orders_12mo >= 6:
        frequency_points = 30
    elif orders_12mo >= 3:
        frequency_points = 22
    elif orders_12mo >= 2:
        frequency_points = 14
    elif orders_12mo >= 1:
        frequency_points = 6
    else:
        frequency_points = 0

    if ltv_cents >= 50000:
        monetary_points = 30
    elif ltv_cents >= 25000:
        monetary_points = 22
    elif ltv_cents >= 12000:
        monetary_points = 14
    elif ltv_cents >= 5000:
        monetary_points = 6
    else:
        monetary_points = 0

    return (recency_points + frequency_points + monetary_points) * 10


def segment_tier(score):
    if score >= 800:
        return "BEST"
    if score >= 600:
        return "CORE"
    if score >= 400:
        return "OCCASIONAL"
    if score >= 200:
        return "LAPSED"
    return "DORMANT"


# ---------------------------------------------------------------------------
# 3.2  Cooperative-model lift and rental pricing
# ---------------------------------------------------------------------------


def coop_lift_bps(coop_model_score):
    if coop_model_score >= 800:
        return 4000
    if coop_model_score >= 600:
        return 2000
    if coop_model_score >= 400:
        return 0
    return -3000


def expected_response_rate_bps(prospect_base_response_bps, coop_model_score):
    return rhu_div(
        prospect_base_response_bps * (10000 + coop_lift_bps(coop_model_score)), 10000
    )


def unit_cost_cents_per_name(cost_per_thousand_cents):
    return rhu_div(cost_per_thousand_cents, 1000)


# ---------------------------------------------------------------------------
# 3.5 / 3.6  Drop cost per book
# ---------------------------------------------------------------------------


def print_rebate_bps(quantity):
    if quantity >= 100000:
        return 800
    if quantity >= 40000:
        return 500
    return 0


def printing_cents_per_book(page_count, print_cost_per_page_per_thousand_cents, rebate_bps):
    # page_count * cpm / 1000 * (10000 - rebate) / 10000, rounded half up once.
    return rhu_div(
        page_count * print_cost_per_page_per_thousand_cents * (10000 - rebate_bps),
        1000 * 10000,
    )


def paper_cents_per_book(page_count, paper_oz_per_page_milli, paper_cost_per_lb_cents):
    # page_count * milli-oz / 1000 (oz) / 16 (lb) * cents-per-lb, rounded half up once.
    return rhu_div(page_count * paper_oz_per_page_milli * paper_cost_per_lb_cents, 1000 * 16)


def weight_oz_milli(page_count, paper_oz_per_page_milli):
    return page_count * paper_oz_per_page_milli


def square_inch_capacity(page_count, usable_sq_in_per_page):
    return page_count * usable_sq_in_per_page


# ---------------------------------------------------------------------------
# 3.4  Page placements
# ---------------------------------------------------------------------------

POSITION_MULTIPLIER_BPS = {
    "FRONT_COVER": 18000,
    "HOT_SPOT": 14000,
    "BACK_COVER": 13000,
    "INSIDE": 10000,
}


def forecast_space_demand_cents(square_inches, demand_per_sq_inch_cents, multiplier_bps):
    return rhu_div(square_inches * demand_per_sq_inch_cents * multiplier_bps, 10000)


def space_productivity_cents_per_sq_in(forecast_cents, square_inches):
    # Deliberate re-division of the already-rounded forecast.
    return rhu_div(forecast_cents, square_inches)


# ---------------------------------------------------------------------------
# 3.7  Postal presort
# ---------------------------------------------------------------------------

TIER_MINIMUM_PIECES = {
    "FIVE_DIGIT": 150,
    "THREE_DIGIT": 150,
    "AADC": 150,
    "MIXED_AADC": 0,
}

TIER_RATE_CENTS_PER_PIECE = {
    "FIVE_DIGIT": 42,
    "THREE_DIGIT": 47,
    "AADC": 51,
    "MIXED_AADC": 58,
}

AUTOMATION_TIERS = ("FIVE_DIGIT", "THREE_DIGIT", "AADC")

WEIGHT_FREE_ALLOWANCE_MILLI = 4000


def effective_tier(declared_tier, piece_count):
    if piece_count >= TIER_MINIMUM_PIECES[declared_tier]:
        return declared_tier
    return "MIXED_AADC"


def weight_surcharge_cents_per_piece(drop_weight_oz_milli):
    excess = drop_weight_oz_milli - WEIGHT_FREE_ALLOWANCE_MILLI
    if excess < 0:
        excess = 0
    return rhu_div(excess * 9, 1000)


def automation_share_bps(automation_pieces, planned_quantity):
    return floor_div(automation_pieces * 10000, planned_quantity)


# ---------------------------------------------------------------------------
# 3.5  Forecast demand and per-line profitability
# ---------------------------------------------------------------------------


def forecast_orders(quantity, effective_response_bps):
    return floor_div(quantity * effective_response_bps, 10000)


def gross_margin_cents(forecast_demand_cents, cogs_rate_bps):
    return rhu_div(forecast_demand_cents * (10000 - cogs_rate_bps), 10000)


def holdout_quantity(allocated_quantity, holdout_pct_bps):
    return floor_div(allocated_quantity * holdout_pct_bps, 10000)


def budget_cap(remaining_budget_cents, unit_cost_cents):
    if unit_cost_cents <= 0:
        # A zero-cost book consumes no budget, so the budget imposes no cap.
        return None
    return floor_div(remaining_budget_cents, unit_cost_cents)


# ---------------------------------------------------------------------------
# 3.8  Contact fatigue
# ---------------------------------------------------------------------------

CHANNEL_WEIGHT = {"MAIL": 40, "EMAIL": 12, "DIGITAL": 6}


def decay_factor_bps(days_ago):
    if days_ago <= 14:
        return 10000
    if days_ago <= 30:
        return 7500
    if days_ago <= 60:
        return 5000
    if days_ago <= 90:
        return 2500
    return 0


def weighted_points(channel, days_ago):
    return rhu_div(CHANNEL_WEIGHT[channel] * decay_factor_bps(days_ago), 10000)


# ---------------------------------------------------------------------------
# 3.9  Test cell lift
# ---------------------------------------------------------------------------

MIN_SIGNIFICANT_SAMPLE = 1000
SIGNIFICANT_LIFT_BPS = 1500


def response_rate_bps(responders, quantity):
    return rhu_div(responders * 10000, quantity)


def lift_bps(rate, control_rate):
    return rhu_div((rate - control_rate) * 10000, control_rate)
