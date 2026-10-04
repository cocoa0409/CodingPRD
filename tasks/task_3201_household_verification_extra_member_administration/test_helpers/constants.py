"""Domain thresholds — numeric constants from the PRD's pricing, entitlement,
confidence, and challenge rules."""

# Default logical clock value before any administrative clock call.
DEFAULT_CLOCK = "2026-09-01T00:00:00Z"

# Regional base slot fees (integer cents).
REGION_BASE_FEE_CENTS = {"NA": 799, "LATAM": 299, "EMEA": 499, "APAC": 349}

# Plan-tier fee multiplier applied to the base fee (BASIC cannot buy slots).
TIER_FEE_MULTIPLIER = {"STANDARD": 1.0, "PREMIUM": 0.75}

# Per-slot surcharge: (slot_index - 1) * SURCHARGE.
SLOT_INDEX_SURCHARGE_CENTS = 200

# Billing cycle length in days (drives proration and the credit per-day rate).
CYCLE_DAYS = 30

# Revocations at most this many cycle-days after purchase get a full credit.
FULL_CREDIT_WINDOW_DAYS = 7

# Household-match confidence weights.
WEIGHT_NETWORK = 40
WEIGHT_GEO = 30
WEIGHT_RECENCY_FRESH = 30
WEIGHT_RECENCY_STALE = 10
STRICT_CAP_NO_NETWORK = 50
TRUST_THRESHOLD = 70

# Plan-tier entitlements.
PLAN_MAX_STREAMS = {"BASIC": 1, "STANDARD": 2, "PREMIUM": 4}
PLAN_MAX_RESOLUTION = {"BASIC": "SD", "STANDARD": "HD", "PREMIUM": "UHD"}
PLAN_MONTHLY_DOWNLOADS = {"BASIC": 5, "STANDARD": 25, "PREMIUM": 100}
PLAN_MAX_EXTRA_SLOTS = {"BASIC": 0, "STANDARD": 1, "PREMIUM": 2}

# Verification challenge timing.
CHALLENGE_TTL_SECONDS = {"EMAIL": 900, "SMS": 900, "VOICE_CALL": 1800}
CHALLENGE_MAX_ATTEMPTS = {"EMAIL": 3, "SMS": 3, "VOICE_CALL": 5}
CHALLENGE_REISSUE_COOLDOWN_SECONDS = 300
# Reserved code guaranteed to be a wrong submission.
WRONG_CODE = "000000"

# Travel pass durations in days.
TRAVEL_PASS_DAYS = {"TEMPORARY_14D": 14, "TEMPORARY_30D": 30}

# Profile transfer validity window (days).
TRANSFER_TTL_DAYS = 7

# Download lazy-expiry age (days).
DOWNLOAD_EXPIRY_DAYS = 30
