"""Domain thresholds and numeric constants stated by the PRD."""

# Spreads applied to a published national rate (PRD §3.1).
THRESHOLDS = {
    "NATIONAL_SPREAD_BPS": 75,            # cap_bps = published + 75
    "NON_MATURITY_SPREAD_BPS": 50,        # non_maturity_cap_bps = published + 50
    "MAX_BPS": 10000,                     # 10000 bps == 100 percent
    "DAY_COUNT_BASIS": 365,               # accrued interest / penalty day basis
    # Diligence composite weights (PRD §3.2) and floors (PRD §3.2).
    "AML_WEIGHT": 35,
    "FINANCIAL_WEIGHT": 30,
    "INSURANCE_WEIGHT": 20,
    "RECORDKEEPING_WEIGHT": 15,
    "APPROVED_SCORE_FLOOR": 70,
    "CONDITIONAL_SCORE_FLOOR": 60,
    "AML_SUBSCORE_FLOOR": 60,
    # Primary purpose tests (PRD §3.3).
    "TWENTY_FIVE_PERCENT_BPS": 2500,
    "ENABLING_TRANSACTIONS_BPS": 7500,
    "REPORTING_DUE_DATE_DAYS": 90,
    # Review-cycle round caps (PRD §2.8 rule 25).
    "MAX_RFI_ROUNDS": 2,
    "MAX_INFO_REQUEST_ROUNDS": 2,
    "MAX_AMENDMENT_ROUNDS": 2,
    # Balance-sheet capacity (PRD §3.4, §3.5).
    "RECIPROCAL_CAP_BPS": 2500,
    "MATURITY_WINDOW_CAP_BPS": 3500,
    "MATURITY_WINDOW_DAYS": 15,
    # Liquidity buffer sizing (PRD §3.7).
    "MATURING_SOON_HORIZON_DAYS": 90,
    "STAGE_1_MULTIPLIER_BPS": 2500,
    "STAGE_2_MULTIPLIER_BPS": 5000,
    "STAGE_3_MULTIPLIER_BPS": 10000,
    # Volume-tiered fee tier edges, in cents (PRD §3.2).
    "VOLUME_TIER_1_LIMIT_CENTS": 100_000_000,
    "VOLUME_TIER_2_LIMIT_CENTS": 500_000_000,
    "VOLUME_TIER_1_BPS": 15,
    "VOLUME_TIER_2_BPS": 10,
    "VOLUME_TIER_3_BPS": 7,
    # Call report accuracy tiers (PRD §3.9).
    "VARIANCE_MATERIAL_BPS": 25,
    # Tenor bucket inclusive upper edges, in days (PRD §3.4).
    "TENOR_EDGE_DAYS_1_30": 30,
    "TENOR_EDGE_DAYS_31_90": 90,
    "TENOR_EDGE_DAYS_91_180": 180,
    "TENOR_EDGE_DAYS_181_365": 365,
}

# The logical clock's value before any caller sets it (PRD §2.10).
DEFAULT_CLOCK_INSTANT = "2026-08-01T00:00:00Z"
DEFAULT_CLOCK_DATE = "2026-08-01"

TEST_DEFAULTS = {
    "CORE_DEPOSITS_CENTS": 40_000_000_000,
    "TOTAL_LIABILITIES_CENTS": 50_000_000_000,
    "TIER1_CAPITAL_CENTS": 5_000_000_000,
    "LIQUIDITY_BUFFER_CENTS": 1_000_000_000,
    "PRINCIPAL_CENTS": 2_000_000_000,
    "PUBLISHED_NATIONAL_RATE_BPS": 400,
    "OFFERED_RATE_BPS": 470,
    "BENCHMARK_EFFECTIVE_DATE": "2026-07-01",
    "AGREEMENT_EFFECTIVE_DATE": "2026-07-01",
    "ISSUE_DATE": "2026-08-01",
    "TENOR_DAYS": 60,
}
