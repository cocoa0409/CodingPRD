"""Domain thresholds and shared test defaults.

Every figure here is a business constant the PRD states in prose.
"""

# ─── Money and rate thresholds ───────────────────────────────────────────────
THRESHOLDS = {
    # Settlement split
    "TIER_BONUS_HIGH": 0.02,
    "TIER_BONUS_MID": 0.01,
    "TIER_BONUS_LOW": 0.00,
    "TIER_BONUS_HIGH_THRESHOLD_CENTS": 20_000_000,
    "TIER_BONUS_MID_THRESHOLD_CENTS": 10_000_000,
    "SPLIT_PCT_CAP": 0.75,
    # Waste tiers
    "WASTE_TIER_HIGH_THRESHOLD_CENTS": 500_000,
    "WASTE_TIER_MEDIUM_THRESHOLD_CENTS": 100_000,
    "WASTE_TIER_HIGH_ADDER": 0.05,
    "WASTE_TIER_MEDIUM_ADDER": 0.02,
    "WASTE_TIER_LOW_ADDER": 0.00,
    "WASTE_SHARE_PCT_CAP": 0.60,
    # Risk bands
    "RISK_BAND_A_MIN_CENTS": 15_000_000,
    "RISK_BAND_B_MIN_CENTS": 5_000_000,
    # Draw ceiling
    "DRAW_LIMIT_CENTS": 5_000_000,
    # Renewal eligibility
    "ELIGIBILITY_OPEN_MIN": 60,
    "PROVISIONAL_HIGH": 75,
    "PROVISIONAL_MID": 55,
    "RENEWAL_NET_WORTH_HIGH_CENTS": 15_000_000,
    "RENEWAL_NET_WORTH_MID_CENTS": 10_000_000,
    "RENEWAL_NET_WORTH_BASE_CENTS": 7_500_000,
    # Temporal windows
    "AUDIT_CADENCE_DAYS": 31,
    "WINDOW_HANDLING_BUFFER_MINUTES": 30,
    "WINDOW_LOCK_LEAD_HOURS": 24,
    "SETTLEMENT_FINALIZE_COOLOFF_DAYS": 7,
    "SETTLEMENT_DISPUTE_WINDOW_DAYS": 14,
}

# ─── Shared test defaults ────────────────────────────────────────────────────
DEFAULTS = {
    "STATED_NET_WORTH_CENTS": 30_000_000,
    "MINIMUM_NET_WORTH_CENTS": 10_000_000,
    "SPLIT_PCT": 0.50,
    "WASTE_SHARE_PCT": 0.50,
    "SHRINK_RESPONSIBILITY_PCT": 0.50,
    "REBATE_PASS_PCT": 1.0,
    "TERM_START": "2025-01-01T00:00:00Z",
    "TERM_END": "2030-01-01T00:00:00Z",
    "RENEWAL_WINDOW_DAYS": 90,
    "STATE_CODE": "TX",
    "STORE_FORMAT": "URBAN",
    "OPENED_ON": "2022-01-01T00:00:00Z",
    "TRAILING_AVG_GROSS_PROFIT_CENTS": 1_000_000,
    "COMMISSARY_CODE": "COMM-TX-1",
    "DAY_OF_WEEK": "TUE",
}

# Compressed totals used where a fixture needs a deterministic, easily-summed book.
WEEK_PERIOD_START = "2026-09-01T00:00:00Z"
WEEK_PERIOD_END = "2026-09-08T00:00:00Z"

__all__ = ["THRESHOLDS", "DEFAULTS", "WEEK_PERIOD_START", "WEEK_PERIOD_END"]