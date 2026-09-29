"""Domain thresholds and canonical test data for the placement API (PRD §2, §3)."""

# --------------------------------------------------------------------------
# Numeric constants named by the PRD calculations
# --------------------------------------------------------------------------
THRESHOLDS = {
    # PRD §3.1 — contract certainty window
    "CONTRACT_CERTAINTY_DAYS": 30,
    # PRD §3.2 — sign-off gate
    "SIGNOFF_MIN_SCORE": 70.00,
    "COMPLETENESS_QUALITY_WEIGHT": 40,
    "COMPLETENESS_HISTORY_WEIGHT": 25,
    "COMPLETENESS_LOSS_WEIGHT": 25,
    "COMPLETENESS_REPORT_WEIGHT": 10,
    "COMPLETENESS_HISTORY_CAP_YEARS": 5,
    # PRD §3.3 — reinstatement loading and the volume tier ladder
    "REINSTATEMENT_LOAD_PCT_PER_UNIT": 5,
    # Tier ceilings are provisional-premium amounts in minor units (PRD §3.3).
    "VOLUME_TIER_1_FLOOR_MINOR": 5_000_000,
    "VOLUME_TIER_2_FLOOR_MINOR": 25_000_000,
    "VOLUME_TIER_3_FLOOR_MINOR": 100_000_000,
    "VOLUME_TIER_0_DISCOUNT_PCT": 0.0,
    "VOLUME_TIER_1_DISCOUNT_PCT": 2.5,
    "VOLUME_TIER_2_DISCOUNT_PCT": 5.0,
    "VOLUME_TIER_3_DISCOUNT_PCT": 7.5,
    # PRD §3.5 — capacity aggregation window
    "CAPACITY_WINDOW_DAYS": 30,
    # PRD §3.6 — sign-down allocation step
    "SIGNDOWN_STEP_PCT": 0.0001,
    "FULL_PLACEMENT_PCT": 100.0000,
    # PRD §3.9 — advocacy and settlement
    "ARBITRATION_COST_PCT": 1.5,
    "COMMISSION_SLIDE_PIVOT_LOSS_RATIO_PCT": 60.0,
    "COMMISSION_SLIDE_FACTOR": 0.5,
    "COMMISSION_SLIDE_FLOOR_PCT": 20.0,
    "COMMISSION_SLIDE_CEILING_PCT": 35.0,
    "MARKET_CONDITION_RISK_WEIGHT": 0.6,
    "MARKET_CONDITION_EFFICIENCY_WEIGHT": 0.4,
}

# --------------------------------------------------------------------------
# Pagination (PRD §2.3)
# --------------------------------------------------------------------------
PAGINATION = {
    "DEFAULT_LIMIT": 10,
    "MIN_LIMIT": 1,
    "MAX_LIMIT": 100,
    "DEFAULT_OFFSET": 0,
}

# --------------------------------------------------------------------------
# Logical clock instants (PRD §2.4)
# --------------------------------------------------------------------------
CLOCK = {
    # Startup default before the clock is ever set.
    "STARTUP_DEFAULT": "2026-08-01T00:00:00.000Z",
    # The instant nearly every placement chain parks the clock on.
    "PLACEMENT_START": "2026-01-01T00:00:00.000Z",
    "INCEPTION": "2026-01-01T00:00:00.000Z",
    "EXPIRY": "2027-01-01T00:00:00.000Z",
    "CERTAINTY_DEADLINE": "2026-01-31T00:00:00.000Z",
    "RESPONSE_DEADLINE": "2026-02-01T00:00:00.000Z",
    "QUOTE_EXPIRY": "2026-02-15T00:00:00.000Z",
}

# --------------------------------------------------------------------------
# Canonical entity inputs reused across the suite
# --------------------------------------------------------------------------
TEST_DEFAULTS = {
    "CEDENT_NAME": "Northwind Mutual",
    "DOMICILE_CODE": "USNYC",
    "FINANCIAL_RATING": "A",
    "PROGRAM_NAME": "Northwind Property 2026",
    "LINE_OF_BUSINESS": "PROPERTY",
    "UNDERWRITING_YEAR": 2026,
    "ESTIMATED_PREMIUM_INCOME_MINOR": 2_000_000_000,
    "BROKERAGE_PCT": 2.5000,
    "CURRENCY_CODE": "USD",
    "PACKAGE_LABEL": "NW-PROP-2026-EDP",
    "CAT_MODEL_VERSION": "RMS-23.1",
    "REINSURER_CAPACITY_MINOR": 1_000_000_000,
    "REINSURER_MAX_LINE_PCT": 100.0000,
}

# The catastrophe layer used by most placement chains: subject premium base
# 1,250,000,000 at 8.0000% with one reinstatement prices at a provisional
# 105,000,000, which selects the 7.5000% tier, so the frozen gross premium is
# 97,125,000 minor units (PRD §3.3).
CANONICAL_CAT_LAYER = {
    "layer_label": "PROP CAT 1B xs 2B",
    "layer_type": "CATASTROPHE",
    "attachment_minor": 2_000_000_000,
    "limit_minor": 1_000_000_000,
    "base_rate_pct": 8.0000,
    "subject_premium_base_minor": 1_250_000_000,
    "expected_loss_cost_minor": 60_000_000,
    "reinstatements_total": 1,
    "reinstatement_premium_pct": 100.0000,
    "sublimit_minor": 0,
}
CANONICAL_CAT_LAYER_GROSS_PREMIUM_MINOR = 97_125_000

# The quota-share layer used by the ceding-commission chains: subject premium
# base 2,000,000,000 at 40.0000% prices at a provisional 800,000,000, tier
# 7.5000%, so the frozen gross premium is 740,000,000 minor units (PRD §3.3).
CANONICAL_QUOTA_SHARE_LAYER = {
    "layer_label": "PROP QS 40%",
    "layer_type": "QUOTA_SHARE",
    "attachment_minor": 0,
    "limit_minor": 2_000_000_000,
    "cession_pct": 40.0000,
    "base_rate_pct": 40.0000,
    "subject_premium_base_minor": 2_000_000_000,
    "expected_loss_cost_minor": 500_000_000,
    "ceding_commission_pct": 30.0000,
}
CANONICAL_QUOTA_SHARE_GROSS_PREMIUM_MINOR = 740_000_000

# The excess-of-loss layer used by the brokerage-rounding chain: subject premium
# base 200,000,000 at 5.0000% prices at 10,000,000, tier 2.5000%, so the frozen
# gross premium is 9,750,000 minor units (PRD §3.3).
CANONICAL_XOL_LAYER = {
    "layer_label": "PROP XOL 200M xs 800M",
    "layer_type": "EXCESS_OF_LOSS",
    "attachment_minor": 800_000_000,
    "limit_minor": 200_000_000,
    "base_rate_pct": 5.0000,
    "subject_premium_base_minor": 200_000_000,
    "expected_loss_cost_minor": 20_000_000,
    "sublimit_minor": 0,
}
CANONICAL_XOL_GROSS_PREMIUM_MINOR = 9_750_000

# A well-formed UUID that is never the id of any row.
UNUSED_UUID = "11111111-1111-4111-8111-111111111111"
UNUSED_UUID_ALT = "22222222-2222-4222-8222-222222222222"
