"""Domain thresholds and defaults for the contact-center contract API.

All values are pinned by the PRD: the base fee, the per-certification
monthly rate card, the baseline staffing, the auto-coach threshold, the
cure window, the critical reporting SLA, and the withholding tiers.
"""

# Logical clock
CLOCK_START = "2026-09-01T00:00:00Z"

# Money / fee constants (PRD Section 3.9)
BASE_FEE_CENTS = 50000
RATE_CARD_CENTS = 4000
BASELINE_STAFFING = 10

# Withholding tiers (PRD Section 3.10)
TIER1_BOUND = 0.05   # miss_ratio < 0.05 -> 0.10
TIER2_BOUND = 0.15   # [0.05, 0.15) -> 0.25; >= 0.15 -> 0.40
TIER1_RATE = 0.10
TIER2_RATE = 0.25
TIER3_RATE = 0.40

# Coaching cascade (PRD Section 3.5)
AUTO_COACH_THRESHOLD = 70
AUTO_COACH_DEDUP_DAYS = 7
AUTO_COACH_DUE_DAYS = 14

# Cure periods (PRD Section 3.11)
CURE_WINDOW_HOURS = 72

# Incident reporting SLA (PRD Section 3.8)
CRITICAL_REPORT_SLA_HOURS = 24

# Routing (PRD Section 3.3)
MAX_ROUTE_DEPTH = 2

# Common fixture values
DEFAULT_PROGRAM = "MEDICAID"
DEFAULT_LANGUAGE = "en"
DEFAULT_TZ = "UTC"
DEFAULT_PERIOD = "2026-09"
FAR_FUTURE_VALID_UNTIL = "2027-01-01T00:00:00Z"
NON_EXISTENT_ID = "00000000-0000-4000-8000-000000000000"
