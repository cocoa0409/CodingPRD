"""Domain thresholds and numeric constants stated by the PRD's calculations."""

# ─── Logical clock (PRD §2.5) ─────────────────────────────────────────────
CLOCK_STARTUP_INSTANT = "2026-08-01T00:00:00Z"

# ─── Rollover due-date projection (PRD §3.6) ──────────────────────────────
SECONDS_PER_WEEK = 604800
RATIO_FLOOR = 0.0
RATIO_CEILING = 1.0

# ─── Grade percentages (PRD §3.8) ─────────────────────────────────────────
PERCENT_SCALE = 100
ZERO_DENOMINATOR_RESULT = 0.00

# ─── Sandbox storage chargeback (PRD §3.3) ────────────────────────────────
FREE_TIER_MB = 100.00
RATE_PER_MB_USD = 0.0150
SANDBOX_MULTIPLIER = 1.00
DEV_MULTIPLIER = 0.50
SANDBOX_STORAGE_QUOTA_MB = 500.00
MAX_SANDBOX_SHELLS_PER_PERSON = 3
SANDBOX_GRACE_DAYS = 60

# ─── Seat capacity / waitlist (PRD §3.4) ──────────────────────────────────
OVERFLOW_RATIO_NORMAL = 0.00
OVERFLOW_RATIO_ELEVATED = 0.10
OVERFLOW_RATIO_CONTINUITY_MODE = 0.20
DEFAULT_BASE_SEAT_CAP = 25
MIN_BASE_SEAT_CAP = 1
MAX_BASE_SEAT_CAP = 2000

# ─── Tool risk score (PRD §3.7) ───────────────────────────────────────────
PII_TIER_POINTS = 10
VPAT_WEIGHT = 0.30
EXPOSURE_PER_PLACEMENT = 3
EXPOSURE_CAP = 15
SCORE_FLOOR = 0.00
SCORE_CEILING = 100.00
RISK_CONDITIONAL_THRESHOLD = 40.00
RISK_REJECT_THRESHOLD = 70.00
SCOPE_POINTS = {
    "NONE": 0,
    "ROSTER_ONLY": 10,
    "ROSTER_AND_GRADES": 25,
    "FULL_PROFILE": 40,
}
CONFORMANCE_POINTS = {"NONE": 20, "A": 10, "AA": 0, "AAA": -5}

# ─── Term rollover completion (PRD §3.2) ──────────────────────────────────
ROLLOVER_READINESS_PCT = 100.00
EMPTY_SET_RESULT = 100.00

# ─── Passback points ledger (PRD §3.8) ────────────────────────────────────
INITIAL_BUCKET_VALUE = 0.00

# ─── Retention schedule (PRD §3.1) ────────────────────────────────────────
RETENTION_DAYS_STANDARD = 365
RETENTION_DAYS_EXTENDED = 1825
ACCESS_END_TIME_OF_DAY = "23:59:59"
DEFAULT_ACCESS_GRACE_DAYS = 30
MAX_ACCESS_GRACE_DAYS = 365
DEFAULT_ADD_DROP_OFFSET_DAYS = 14
DEFAULT_FINALS_WINDOW_LEAD_DAYS = 7

# ─── Continuity windows (PRD §3.9) ────────────────────────────────────────
SECONDS_PER_DAY = 86400
CONTINUITY_CONCURRENCY_CAP = 2

# ─── Pagination (PRD §2.3) ────────────────────────────────────────────────
DEFAULT_LIMIT = 10
MIN_LIMIT = 1
MAX_LIMIT = 100
DEFAULT_OFFSET = 0

# ─── Sync batch (PRD §3.4) ────────────────────────────────────────────────
MIN_BATCH_OPERATIONS = 1
MAX_BATCH_OPERATIONS = 200

# ─── Convenient calendar literals reused by the design fixtures ───────────
# A 100-day source term and a 109-day target term: the pair the PRD works
# through when it contrasts the two date_shift_mode variants.
SOURCE_TERM_START = "2026-01-12T00:00:00Z"
SOURCE_TERM_END = "2026-04-22T00:00:00Z"
TARGET_TERM_START = "2026-08-24T00:00:00Z"
TARGET_TERM_END = "2026-12-11T00:00:00Z"
