"""Domain thresholds and numeric constants from the PRD.

Fee constants come from PRD section 3.7; status thresholds from PRD
section 3.4; the calendar constants from PRD sections 3.2 and 3.9; and the
pinned logical-clock start from PRD section 2.4.
"""

# Pinned server default logical time (PRD section 2.4).
DEFAULT_CLOCK_ISO = "2026-09-01T00:00:00Z"

# Enrollment status credit bands (PRD section 3.4).
FT_UG_CREDITS = 12.0
HT_UG_CREDITS = 6.0
FT_GR_CREDITS = 9.0
HT_GR_CREDITS = 4.5
CENSUS_OFFSET_DAYS = 14
MAX_CREDIT_HOURS = 30.0

# Deferment grace window (PRD section 3.4).
WITHDRAWAL_GRACE_DAYS = 180

# Verification fee quote constants (PRD section 3.7).
DEGREE_BASE_FEE_CENTS = 2599
ENROLLMENT_BASE_FEE_CENTS = 1599
TRANSCRIPT_FEE_CENTS = 0
RUSH_SURCHARGE_BPS = 3333
PREFERRED_DISCOUNT_BPS = 2000
QUOTE_TTL_HOURS = 48
ARTIFACT_TTL_HOURS = 72
MAX_ACTIVE_TRANSCRIPTS = 2
VOLUME_TIER_THRESHOLD = 3

# Reporting calendar constants (PRD section 3.2).
GRACE_PERIOD_DAYS = 14
STANDING_LOOKBACK_PERIODS = 3

# Research cohort constants (PRD section 3.9).
K_ANONYMITY_MIN = 10
COMPLETION_LAG_DAYS = 730

# Convenience UUID for not-found probes (framework also exports one).
NON_EXISTENT_ID = "00000000-0000-0000-0000-000000000000"
