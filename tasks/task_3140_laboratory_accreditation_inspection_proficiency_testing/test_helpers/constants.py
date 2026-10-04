"""Domain thresholds — numeric constants from the PRD."""

# PT grading thresholds (PRD §3.2)
ANALYTE_PASS_SCORE = 80
EVENT_PASS_SCORE = 80.0

# PT shipment timing (PRD §3.2)
SHIPMENT_DUE_DAYS = 10
COLLECTION_WINDOW_DAYS = 5

# Competency assessment thresholds (PRD §3.5)
COMPOSITE_PASS = 85.0
ELEMENT_MIN = 70
ELEMENT_COUNT = 6
COMPETENCY_VALIDITY_DAYS = 365

# Method validation approval thresholds (PRD §3.5)
CORRELATION_R2_MIN = 0.95
PRECISION_CV_MAX = 10.0

# Deficiency burden weights (PRD §3.6)
LEVEL_2_WEIGHT = 4
LEVEL_1_WEIGHT = 2
CRITICAL_SECTION_MULTIPLIER = 2

# Provisional decision band (PRD §3.6)
CONDITIONAL_MAX_BURDEN = 6

# Finding response deadlines (PRD §3.6)
LEVEL_1_RESPONSE_DAYS = 14
LEVEL_2_RESPONSE_BUSINESS_DAYS = 5

# Appeal rules (PRD §3.7)
APPEAL_WINDOW_DAYS = 30
APPEAL_LIMIT = 2

# Revocation cooling-off (PRD §3.7)
REVOKE_PROBATION_AGE_DAYS = 180

# Reciprocal-conflict lookback (PRD §3.4)
RECIPROCAL_CONFLICT_LOOKBACK_DAYS = 365

# Default logical clock value before any set call (PRD §2.4)
DEFAULT_CLOCK = "2026-09-01T00:00:00Z"
