"""Domain thresholds and reference values drawn from the PRD's calculations."""

# The logical clock's value at process start.
CLOCK_START = "2026-08-01T00:00:00.000Z"

# Season rate-card defaults (PRD §2.5).
SEASON_DEFAULTS = {
    "print_cost_per_page_per_thousand_cents": 2600,
    "paper_cost_per_lb_cents": 92,
    "paper_oz_per_page_milli": 40,
    "usable_sq_in_per_page": 88,
    "default_postage_estimate_cents_per_piece": 55,
    "cogs_rate_bps": 5800,
    "prospect_base_response_bps": 110,
    "prospect_avg_order_value_cents": 11800,
    "min_inhome_gap_days": 21,
    "fatigue_window_days": 90,
    "fatigue_suppression_threshold": 100,
}

# Recency / frequency / monetary point scales (PRD §3.1).
RECENCY_POINTS = [(90, 40), (180, 30), (365, 18), (730, 8)]
FREQUENCY_POINTS = [(6, 30), (3, 22), (2, 14), (1, 6)]
MONETARY_POINTS = [(50000, 30), (25000, 22), (12000, 14), (5000, 6)]
RFM_SCORE_MULTIPLIER = 10

# rfm_score → segment_tier bands (PRD §3.1).
TIER_BANDS = [(800, "BEST"), (600, "CORE"), (400, "OCCASIONAL"), (200, "LAPSED")]

# Tier → default contact strategy (PRD §3.1).
TIER_DEFAULT_STRATEGY = {
    "BEST": "PREMIUM_FULL",
    "CORE": "STANDARD",
    "OCCASIONAL": "STANDARD",
    "LAPSED": "REACTIVATION",
    "DORMANT": "SUPPRESS_ONLY",
}

# Cooperative-model lift bands in basis points (PRD §3.2).
COOP_LIFT_BANDS = [(800, 4000), (600, 2000), (400, 0)]
COOP_LIFT_BELOW_400 = -3000

# Printer volume rebate bands in basis points (PRD §3.5 / §3.6).
PRINT_REBATE_BANDS = [(100000, 800), (40000, 500)]

# Postal presort tiers (PRD §3.7).
PRESORT_TIER_MINIMUM = 150
PRESORT_TIER_RATES = {
    "FIVE_DIGIT": 42,
    "THREE_DIGIT": 47,
    "AADC": 51,
    "MIXED_AADC": 58,
}
AUTOMATION_TIERS = ("FIVE_DIGIT", "THREE_DIGIT", "AADC")
WEIGHT_FREE_ALLOWANCE_OZ_MILLI = 4000
WEIGHT_SURCHARGE_CENTS_PER_OZ = 9
AUTOMATION_SHARE_QUALIFYING_BPS = 9000
AUTOMATION_DISCOUNT_CENTS_PER_PIECE = 2

# Contact fatigue weights and decay bands (PRD §3.8).
CHANNEL_WEIGHTS = {"MAIL": 40, "EMAIL": 12, "DIGITAL": 6}
DECAY_BANDS = [(14, 10000), (30, 7500), (60, 5000), (90, 2500)]

# Page placement position multipliers in basis points (PRD §3.4).
POSITION_MULTIPLIERS = {
    "FRONT_COVER": 18000,
    "HOT_SPOT": 14000,
    "BACK_COVER": 13000,
    "INSIDE": 10000,
}

# Test cell verdict thresholds (PRD §3.9).
TEST_CELL_MIN_SAMPLE = 1000
TEST_CELL_SIGNIFICANT_LIFT_BPS = 1500

# Pagination bounds (PRD §2.3).
PAGINATION = {"default_limit": 10, "min_limit": 1, "max_limit": 100, "min_offset": 0}

# Holdout share bound (PRD §3.5).
MAX_HOLDOUT_PCT_BPS = 5000

# Reference fixture values used across the suite. A 64-page book on the default
# rate card weighs 2560 thousandths of an ounce, offers 5632 square inches, and
# prices at 166 printing + 15 paper + 55 postage = 236 cents per book.
REFERENCE = {
    "page_count": 64,
    "weight_oz_milli": 2560,
    "square_inch_capacity": 5632,
    "printing_cents_per_book": 166,
    "paper_cents_per_book": 15,
    "estimated_cost_per_book_cents": 236,
    "plan_budget_cents": 20000000,
}
