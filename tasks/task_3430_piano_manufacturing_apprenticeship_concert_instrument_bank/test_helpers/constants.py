"""Domain thresholds and rates — every value appears verbatim in PRD.md.

Each group is tagged with the PRD section it traces to. No value here comes
from anywhere but the PRD text.
"""

# --- Logical clock (PRD section 2.4) ---
CLOCK_START_ISO = "2026-09-01T00:00:00Z"  # startup value of the logical clock
SECONDS_PER_DAY = 86400  # a day count is whole 86,400-second days, rounded down

# --- Pagination (PRD section 2.3) ---
PAGE_LIMIT_DEFAULT = 10
PAGE_LIMIT_MIN = 1
PAGE_LIMIT_MAX = 100
PAGE_OFFSET_DEFAULT = 0

# --- Drying and seasoning gates (PRD sections 3.1, 3.2) ---
MOISTURE_READY_PCT = 8.0  # exactly 8.0 passes
MIN_DRYING_DAYS = 240  # exactly 240 passes
SEASONING_MIN_DAYS = 365  # exactly 365 passes

# --- Advance payload numeric bound (PRD sections 2.8, 3.2) ---
HOURS_APPLIED_MAX = 500  # hours_applied must be > 0 and at most 500

# --- WIP valuation (PRD section 3.2) ---
MATERIAL_COST_CENTS = {
    "MODEL_D": 4_200_000,
    "MODEL_B": 3_600_000,
    "MODEL_O": 3_100_000,
    "ART_CASE": 9_000_000,
}
STAGE_RATE_CENTS = {
    "RIM_BENDING": 14_500,
    "SEASONING_CHECK": 9_500,
    "ACTION_REGULATION": 21_000,
    "VOICING": 24_000,
}
PLANNED_HOURS = {
    "RIM_BENT": 120,
    "SEASONING": 40,
    "ACTION_REGULATION": 40,
    "VOICING": 200,
    "COMPLETED": 160,
}

# --- Apprenticeship crediting (PRD section 3.3) ---
HOURS_REQUIRED = {"RIM_BENDING": 600, "SEASONING_CHECK": 300}  # equality passes
MATCHED_SUPERVISION_RATIO = 1.0
MISMATCHED_SUPERVISION_RATIO = 0.5
FAIL_RETAIN_RATIO = 0.75  # applied per entry, rounded down to whole hours

# --- Loan fee (PRD section 3.6) ---
WEEKLY_RATE_CENTS = {
    "MODEL_D": 85_000,
    "MODEL_B": 72_000,
    "MODEL_O": 64_000,
    "ART_CASE": 150_000,
}
TIER_FACTOR = {"STANDARD": 1.0, "PRIVILEGED": 0.8}
MIN_FEE_CENTS = 55_000  # clamp raises anything below this
MAX_FEE_CENTS = 2_000_000  # clamp caps anything above this
DAYS_PER_WEEK = 7  # tour weeks = whole-day length divided by 7, rounded up
TECH_BUFFER_DAYS = 1  # one buffer day added on both sides of every existing tour

# --- Artist review period (PRD section 3.5) ---
REVIEW_PERIOD_DAYS = 365

# --- Restoration authenticity (PRD section 3.7) ---
AUTHENTICITY_MIN_PCT = 70.0  # exactly 70.0 passes; 69.9 fails
