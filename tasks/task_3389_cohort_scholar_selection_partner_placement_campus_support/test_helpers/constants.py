"""Domain thresholds and fixture constants, each traceable to PRD prose.

Logical clock (PRD §2.4), scoring weights/floor/cap and cutoffs (PRD §3.2),
quota bounds (PRD §3.1), cohort size bounds (PRD §3.3), seat ledger and fill
projection weight (PRD §3.4), offer TTL (PRD §2.4), program-fee invoice
constants (PRD §3.6), outcome-rate and renewal thresholds (PRD §3.9),
meeting buffer (PRD §3.8), pagination defaults (PRD §2.3).
"""

# --- Logical clock (PRD §2.4) ---
CLOCK_BOOT = "2026-09-01T00:00:00Z"

# Standard fixture window: opens exactly at clock boot so the default clock is
# inside the nomination window; closes 2026-11-30T23:59:59Z.
WINDOW_OPENS = "2026-09-01T00:00:00Z"
WINDOW_CLOSES = "2026-11-30T23:59:59Z"
WINDOW_ONE_SECOND_PAST_CLOSE = "2026-12-01T00:00:00Z"

DEFAULT_CYCLE = "2027"
DEFAULT_CITY_CODE = "ATL"
DEFAULT_CITY_NAME = "Atlanta"
DEFAULT_PARTNER_NAME = "West High"
DEFAULT_COLLEGE_NAME = "Elm College"
DEFAULT_MENTOR_NAME = "Prof Elm"

# --- Evaluation scoring (PRD §3.2) ---
W_LEADERSHIP = 4
W_TEAMWORK = 3
W_GROUP_PRESENCE = 3
DIMENSION_FLOOR = 40
FLOOR_CAP_SCORE = 499
REQUIRED_EVALUATIONS_PER_ROUND = 2
SCORE_MIN = 0
SCORE_MAX = 100

# --- Round advancement cutoffs, inclusive (PRD §3.2) ---
ROUND_1_CUTOFF = 600
ROUND_2_CUTOFF = 700
ROUND_3_CUTOFF = 800

# Standard passing scorecard: (90, 90, 90) -> weighted 900, clears all cutoffs.
PASSING_SCORE = 90
PASSING_WEIGHTED = 900
ASSESSOR_A = "assessor-a"
ASSESSOR_B = "assessor-b"

# --- Nomination quota bounds (PRD §3.1) ---
QUOTA_MIN = 1
QUOTA_MAX = 20

# --- Cohort size bounds on agreement create (PRD §3.3) ---
COHORT_SIZE_MIN = 3
COHORT_SIZE_MAX = 6
DEFAULT_COHORT_SIZE = 3
DEFAULT_TUITION_CENTS = 6123460

# --- Offers / seat ledger (PRD §2.4, §3.4, §3.5) ---
OFFER_TTL_DAYS = 14
PROVISIONAL_OFFER_WEIGHT_BPS = 7500

# --- Program-fee invoice (PRD §3.6) ---
FEE_BASE_CENTS = 250000
FEE_RATE_BPS = 125
# tuition 6123460 with 2 matriculated scholars pins 653086 (per-line rounding).
EXPECTED_INVOICE_TWO_SCHOLARS = 653086
PER_SCHOLAR_FEE_CENTS = 326543  # 250000 + round_half_up(6123460 * 125 / 10000)

# --- Outcome rates / standing / renewal (PRD §3.9) ---
PROBATION_RETENTION_FLOOR_BPS = 7000
RECOVERY_RETENTION_BPS = 8000
RENEWAL_MIN_RETENTION_BPS = 8000
RENEWAL_MIN_GRADUATION_BPS = 6000

# --- Pre-collegiate training (PRD §3.7) ---
TRAINING_MODULE_COUNT = 8

# --- Meetings (PRD §3.8) ---
MEETING_BUFFER_MINUTES = 15

# --- Pagination (PRD §2.3) ---
PAGE_LIMIT_DEFAULT = 10
PAGE_LIMIT_MIN = 1
PAGE_LIMIT_MAX = 100
PAGE_OFFSET_DEFAULT = 0

# Well-formed but never-existent identifier for 404 probes.
MISSING_UUID = "00000000-0000-0000-0000-000000000000"
