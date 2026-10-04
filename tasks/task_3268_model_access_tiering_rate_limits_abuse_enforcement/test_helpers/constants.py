"""Domain thresholds — numeric constants from the PRD's calculation rules."""

# Logical clock default at server startup.
CLOCK_DEFAULT_UTC = "2026-09-01T00:00:00Z"

# Tier progression thresholds (cumulative and conjunctive: spend AND count).
TIER_2_SPEND_CENTS = 5_000_000
TIER_2_COUNT = 5
TIER_3_SPEND_CENTS = 25_000_000
TIER_3_COUNT = 25
TIER_4_SPEND_CENTS = 100_000_000
TIER_4_COUNT = 100
MIN_QUALIFYING_PAYMENT_CENTS = 1000

# Per-tier base rate ceilings: (requests per minute, tokens per minute).
TIER_CAPS = {
    "TIER_1": {"rpm": 50, "tpm": 50_000},
    "TIER_2": {"rpm": 200, "tpm": 200_000},
    "TIER_3": {"rpm": 1000, "tpm": 1_000_000},
    "TIER_4": {"rpm": 4000, "tpm": 4_000_000},
}

# Rate-limit mechanics.
BURST_MULTIPLIER = 2
AVG_TOKENS_PER_REQUEST = 1000
THROTTLE_FACTOR = 0.25
QUEUE_TTL_SECONDS = 120
QUEUE_MAX_DEPTH = 100

# Billing.
BATCH_DISCOUNT_PCT = 0.5

# Safety gate pass thresholds (inclusive).
STANDARD_PASS_SCORE = 0.70
ELEVATED_PASS_SCORE = 0.70
FRONTIER_PASS_SCORE = 0.90

# Automated abuse escalation threshold (inclusive).
AUTO_ACTION_THRESHOLD = 0.95

# Deprecation / migration window.
MIGRATION_WINDOW_DAYS = 30
LOOKBACK_DAYS = 30
