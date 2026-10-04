"""Domain thresholds and fixed test defaults for the scoring platform."""

# ─── Tiered marginal pricing ──────────────────────────
TIER_1_RATE_CENTS = 18
TIER_2_RATE_CENTS = 14
TIER_3_RATE_CENTS = 9
TIER_1_UPPER_BOUND = 10000
TIER_2_UPPER_BOUND = 50000
FIXED_OVERAGE_FEE_CENTS = 250
VOLUME_TIER_BOUNDARIES = [0, 10000, 50000]
VOLUME_TIER_RATES_CENTS = [18, 14, 9]

# ─── Reason-code catalogue ────────────────────────────
BUBBLE_UP_FLOOR = 0.05

# ─── Cross-bureau discrepancy scan ────────────────────
DISCREPANCY_POINTS = 15

# ─── Disparate impact ─────────────────────────────────
PPM_SCALE = 1000000
THRESHOLD_PPM = 800000

# ─── Window mixture ratio ─────────────────────────────
MIXTURE_SCALE = 1000000
MILLI = 1000

# ─── Discovery slots ──────────────────────────────────
DISCOVERY_EXPIRY_LOGICAL_HOURS = 720

# ─── Defaults ─────────────────────────────────────────
DEFAULT_SCORE_FLOOR = 300
DEFAULT_SCORE_CEILING = 850
DEFAULT_LOGICAL_CLOCK = "2026-09-01T00:00:00Z"

THRESHOLDS = {
    "TIER_1_RATE_CENTS": TIER_1_RATE_CENTS,
    "TIER_2_RATE_CENTS": TIER_2_RATE_CENTS,
    "TIER_3_RATE_CENTS": TIER_3_RATE_CENTS,
    "TIER_1_UPPER_BOUND": TIER_1_UPPER_BOUND,
    "TIER_2_UPPER_BOUND": TIER_2_UPPER_BOUND,
    "FIXED_OVERAGE_FEE_CENTS": FIXED_OVERAGE_FEE_CENTS,
    "BUBBLE_UP_FLOOR": BUBBLE_UP_FLOOR,
    "DISCREPANCY_POINTS": DISCREPANCY_POINTS,
    "THRESHOLD_PPM": THRESHOLD_PPM,
    "DEFAULT_SCORE_FLOOR": DEFAULT_SCORE_FLOOR,
    "DEFAULT_SCORE_CEILING": DEFAULT_SCORE_CEILING,
}

# The CREDIT-DUAL-V1 AUTO odds-to-score geometry used throughout the fixtures.
CREDIT_DUAL_AUTO = {
    "industry": "AUTO",
    "ref_score": 700,
    "base_odds": 18.0,
    "double_odds_points": 35,
    "segment_width": 60,
    "segment_offsets": [0, 10, -6],
    "rounding_penalty_pct": 0.02,
    "aggregate_weight_pct": 0.42,
    "elongation_points": 700,
    "cutoff_baseline": 700,
}

# The PRIME-SHIFT-V2 AUTO geometry — a wider odds-to-score relationship.
PRIME_SHIFT_AUTO = {
    "industry": "AUTO",
    "ref_score": 680,
    "base_odds": 20.0,
    "double_odds_points": 40,
    "segment_width": 60,
    "segment_offsets": [0, 6, -4],
    "rounding_penalty_pct": 0.02,
    "aggregate_weight_pct": 0.42,
    "elongation_points": 680,
    "cutoff_baseline": 660,
}

CREDIT_DUAL_LABEL = "CREDIT-DUAL-V1"
PRIME_SHIFT_LABEL = "PRIME-SHIFT-V2"