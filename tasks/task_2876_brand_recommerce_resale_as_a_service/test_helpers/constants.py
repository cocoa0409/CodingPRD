"""Domain thresholds and canonical fixture literals from the PRD."""

# ---------------------------------------------------------------- clock ----
DEFAULT_CLOCK = "2026-08-01T00:00:00Z"

# ------------------------------------------------------------- thresholds ---
THRESHOLDS = {
    # §2.5 basis points
    "BASIS_POINTS_FULL": 10000,
    # §3.2 intake
    "TRADE_IN_CREDIT_CAP_MINOR": 60000,
    "MAIL_IN_RECEIVE_WINDOW_DAYS": 21,
    "IN_STORE_RECEIVE_WINDOW_DAYS": 2,
    # §3.4 issuance
    "PLUS_LOYALTY_BONUS_PCT_BP": 500,
    # §3.5 refurbishment
    "LABOR_RATE_MINOR_PER_MINUTE": 145,
    "BAY_MULTIPLIER_CLEANING_BP": 10000,
    "BAY_MULTIPLIER_REPAIR_BP": 13500,
    "BAY_MULTIPLIER_REPACKAGING_BP": 9000,
    "SANITATION_BUFFER_MINUTES": 60,
    "VIABILITY_RATIO_WHEN_BASELINE_ZERO_BP": 10001,
    "REWORK_LIMIT": 2,
    # §3.6 listing and markdown
    "MARGIN_FLOOR_PCT_BP": 11500,
    "MAX_OVERLAPPING_CAMPAIGNS_PER_CHANNEL": 2,
    # §3.7 channel fee bands, upper-inclusive on gross price
    "FEE_BAND_LOW_MAX_MINOR": 20000,
    "FEE_BAND_LOW_BP": 900,
    "FEE_BAND_MID_MAX_MINOR": 60000,
    "FEE_BAND_MID_BP": 650,
    "FEE_BAND_HIGH_BP": 450,
    # §3.8 after-sale
    "BUYER_REMORSE_WINDOW_DAYS": 14,
    # §3.3 appeals
    "APPEAL_LIMIT": 1,
}

BAY_MULTIPLIER_BP = {
    "CLEANING": THRESHOLDS["BAY_MULTIPLIER_CLEANING_BP"],
    "REPAIR": THRESHOLDS["BAY_MULTIPLIER_REPAIR_BP"],
    "REPACKAGING": THRESHOLDS["BAY_MULTIPLIER_REPACKAGING_BP"],
}

# ------------------------------------------------- canonical fixture data ---
# Condition-tier policies used across the suite.
GRADE_POLICY_FOOTWEAR_A = {
    "product_category": "FOOTWEAR",
    "condition_grade": "A",
    "base_credit_pct_bp": 3500,
    "resale_price_pct_bp": 6500,
    "refurb_budget_cap_pct_bp": 2500,
    "restock_fee_pct_bp": 1200,
    "warranty_days": 30,
}

GRADE_POLICY_OUTERWEAR_B = {
    "product_category": "OUTERWEAR",
    "condition_grade": "B",
    "base_credit_pct_bp": 2000,
    "resale_price_pct_bp": 3900,
    "refurb_budget_cap_pct_bp": 3000,
    "restock_fee_pct_bp": 1200,
    "warranty_days": 30,
}

GRADE_POLICY_OUTERWEAR_C = {
    "product_category": "OUTERWEAR",
    "condition_grade": "C",
    "base_credit_pct_bp": 1200,
    "resale_price_pct_bp": 3000,
    "refurb_budget_cap_pct_bp": 2500,
    "restock_fee_pct_bp": 1200,
    "warranty_days": 30,
}

GRADE_POLICY_FOOTWEAR_B = {
    "product_category": "FOOTWEAR",
    "condition_grade": "B",
    "base_credit_pct_bp": 2400,
    "resale_price_pct_bp": 4800,
    "refurb_budget_cap_pct_bp": 2500,
    "restock_fee_pct_bp": 1200,
    "warranty_days": 30,
}

GRADE_POLICY_FOOTWEAR_SALVAGE = {
    "product_category": "FOOTWEAR",
    "condition_grade": "SALVAGE",
    "base_credit_pct_bp": 500,
    "resale_price_pct_bp": 0,
    "refurb_budget_cap_pct_bp": 1,
    "restock_fee_pct_bp": 1200,
    "warranty_days": 30,
}

CREDIT_POLICY_CORE = {
    "code": "CORE-2026",
    "expiry_days": 180,
    "mail_in_bonus_pct_bp": 1000,
    "max_redemption_pct_bp": 5000,
    "min_cash_remainder_minor": 500,
    "eligible_assortment": "BOTH",
}

CREDIT_POLICY_OPEN = {
    "code": "OPEN-2026",
    "expiry_days": 180,
    "mail_in_bonus_pct_bp": 1000,
    "max_redemption_pct_bp": 10000,
    "min_cash_remainder_minor": 500,
    "eligible_assortment": "BOTH",
}

CHANNEL_RESALE_MP = {
    "code": "RESALE-MP",
    "channel_type": "RESALE_MARKETPLACE",
    "allowed_assortment": "RESALE_ONLY",
    "max_resale_price_ratio_bp": 7000,
    "region_code": "US-CA",
}

STORE_ST_01 = {"code": "ST-01", "region_code": "US-CA"}
STORE_ST_02 = {"code": "ST-02", "region_code": "US-NY"}

BAY_REPAIR = {"code": "BAY-R1", "bay_type": "REPAIR"}
BAY_CLEANING = {"code": "BAY-C1", "bay_type": "CLEANING"}

# Refurbishment windows used by the bay-conflict scenarios.
WINDOW_09_11 = ("2026-08-01T09:00:00Z", "2026-08-01T11:00:00Z")
WINDOW_12_14 = ("2026-08-01T12:00:00Z", "2026-08-01T14:00:00Z")
WINDOW_13_15 = ("2026-08-01T13:00:00Z", "2026-08-01T15:00:00Z")

TEST_DEFAULTS = {
    "OUTERWEAR_MSRP_MINOR": 50000,
    "OUTERWEAR_MASS_GRAMS": 1400,
    "FOOTWEAR_MSRP_MINOR": 120000,
    "FOOTWEAR_MASS_GRAMS": 1300,
}
