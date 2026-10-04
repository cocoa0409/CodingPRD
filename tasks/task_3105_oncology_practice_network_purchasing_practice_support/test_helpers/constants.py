"""Domain thresholds — numeric constants from the rebate, tier and shortage
calculations described in the PRD (§3.4, §3.5, §3.6, §3.7, §3.8, §3.9)."""

THRESHOLDS = {
    # Tier ladder boundary used by every fixture
    "TIER_3_MIN_PURCHASES_CENTS": 50_000_000,
    # Per-practice rebate cap
    "REBATE_CAP_PER_PRACTICE_CENTS": 2_500_000,
    # Write-off headroom menu
    "WRITE_OFF_W1_PCT": 0.10,
    "WRITE_OFF_W2_PCT": 0.25,
    # Management-services fairness floor
    "FAIRNESS_FLOOR_CENTS": 50_000,
    "TIER_RATE_ADJ_ADJUSTMENT": 0.75,
    # Agreement ceilings
    "MAX_DISCOUNT_PCT": 0.35,
    "MAX_REBATE_PCT": 0.10,
    "MAX_FEE_RATE": 0.15,
    # Management-term blackout
    "MANAGEMENT_BLACKOUT_DAYS": 30,
    # Epoch advance ceiling
    "MAX_EPOCH_ADVANCE": 12,
    # Compliance report grace window (network default)
    "COMPLIANCE_REPORT_GRACE_DAYS": 30,
    # Network default payment terms
    "PAYMENT_TERMS_DAYS": 60,
    # Admission / expiry boundary in the dual-variant stock count
    "EXPIRY_BOUNDARY_NOTE": "usable requires expires_at > administered_at (strict)",
}

TEST_DEFAULTS = {
    "CLOCK_START": "2026-09-01T00:00:00Z",
    "TIER_LADDER": [
        {"tier": "TIER_3", "min_trailing_12m_purchases_cents": 50_000_000},
        {"tier": "TIER_2", "min_trailing_12m_purchases_cents": 0},
    ],
    "DENIAL_RATIO_THRESHOLD_PCT": 0.20,
    "PATHWAY_STEERING_TARGET_PCT": 0.75,
    "UNIT_PRICE_CENTS": 1000,
}

# Rounded ratios are reported to four decimal places, rounded half up.
RATIO_DECIMAL_PLACES = 4