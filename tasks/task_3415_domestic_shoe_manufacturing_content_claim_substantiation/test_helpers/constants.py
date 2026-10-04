"""Domain thresholds — numeric constants named in the PRD's calculations."""

# Logical clock (PRD: logical clock default and monotonicity).
CLOCK_START_ISO = "2026-09-01T00:00:00Z"
CLOCK_START_PREFIX = "2026-09-01T00:00:00"

# ISO week buckets used across fixtures.
WEEK_36 = "2026-W36"
WEEK_37 = "2026-W37"
WEEK_38 = "2026-W38"
WEEK_39 = "2026-W39"
WEEK_40 = "2026-W40"

# Standard half-open line window for runs.
RUN_START_DAY = "2026-09-07"
RUN_END_DAY = "2026-09-11"

# Workforce requirements per run (PRD workforce section) and coverage weights.
REQUIRED_WORKERS_PER_RUN = {"STITCHING": 2, "LASTING": 1, "ASSEMBLY": 1}
OP_WEIGHTS = {"STITCHING": 0.5, "LASTING": 0.3, "ASSEMBLY": 0.2}
PIPELINE_CREDIT = 0.5
TRAINING_PASS_SCORE = 80

# Certified unit cost small-batch surcharge tiers (PRD run completion).
TIER_1_MAX_UNITS = 10    # below 10 -> 25%
TIER_2_MAX_UNITS = 25    # [10, 25)   -> 15%
TIER_3_MAX_UNITS = 50    # [25, 50)   -> 8%; 50+ -> 0%
TIER_1_PCT = 0.25
TIER_2_PCT = 0.15
TIER_3_PCT = 0.08
CUSTOM_BATCH_EXTRA_PCT = 0.05
GOVERNMENT_PCT = 0.0

# Custom order pricing (PRD custom program section).
CUSTOM_FALLBACK_MARKUP = 1.15
MONOGRAM_FEE_CENTS = 500
COLORWAY_FEE_CENTS = 250
DISCOUNT_TIER_1_MIN_CENTS = 20000
DISCOUNT_TIER_1_PCT = 0.10
DISCOUNT_TIER_2_MIN_CENTS = 12000
DISCOUNT_TIER_2_PCT = 0.05
MAX_CUSTOM_ORDER_UNITS = 12

# Claim content thresholds (PRD claims section; inclusive >=).
MADE_IN_USA_MIN_PCT = 95.0
MADE_IN_USA_OF_IMPORTED_MIN_PCT = 70.0
ASSEMBLED_IN_USA_MIN_PCT = 20.0
BERRY_REQUIRED_PCT = 100.0

# Standard evidence validity window used by claim fixtures.
DOC_VALID_FROM = "2026-08-01"
DOC_VALID_UNTIL = "2027-08-31"
