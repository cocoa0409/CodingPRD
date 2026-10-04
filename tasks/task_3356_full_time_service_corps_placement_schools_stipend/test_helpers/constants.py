"""Domain thresholds and canonical world literals.

Every numeric threshold named in the PRD's business rules lives here exactly
once, so tests cite the rule rather than re-deriving the number. The world
literals are the shared fixture values used to build a site / school / member
world: the service year, the annual stipend, the contracted team size and the
backfill deadline.
"""

# ── Logical clock ──────────────────────────────────────────────────────────
# The PRD fixes the logical clock's initial reading; tests that need a later
# date drive it explicitly.
BASE_CLOCK = "2026-09-01T00:00:00Z"

# ── Canonical world literals ───────────────────────────────────────────────
SERVICE_YEAR_START = "2026-09-01"
SERVICE_YEAR_END = "2027-06-15"
ANNUAL_STIPEND_CENTS = 1_300_000
SCHOOL_TEAM_SIZE = 3
SCHOOL_COST_SHARE_CENTS = 400_000
BACKFILL_DEADLINE = "2027-01-15"
BACKFILL_LIMIT = 2
MEMBER_DOB = "2003-05-20"  # age 23 at the service year start

# ── Stipend schedule (PRD §3.7) ────────────────────────────────────────────
STIPEND_PERIODS_PER_YEAR = 26
STIPEND_PERIOD_DAYS = 14

# ── Education award (PRD §3.7) ─────────────────────────────────────────────
FULL_TERM_HOURS = 120
MIN_PARTIAL_AWARD_HOURS = 24
EDUCATION_AWARD_FULL_CENTS = 739_500
PROJECTED_DAILY_HOURS = 8.0

# ── Funding posture bands (PRD §3.1) ───────────────────────────────────────
TIGHT_HEADROOM_CENTS = 500_000

# ── Hour ledger (PRD §3.6) ─────────────────────────────────────────────────
DAILY_HOUR_CAP = 12.0
HOUR_QUANTUM = 0.25
VERIFICATION_WINDOW_DAYS = 30
FUNDRAISING_CAP_FRACTION = 0.10

# ── Caseload (PRD §3.5) ────────────────────────────────────────────────────
CASELOAD_LIMIT = 12

# ── Evaluation reporting (PRD §3.8) ────────────────────────────────────────
REPORT_WINDOW_DAYS = 45
IMPROVEMENT_THRESHOLD_PCT = 5.0

THRESHOLDS = {
    "STIPEND_PERIODS_PER_YEAR": STIPEND_PERIODS_PER_YEAR,
    "STIPEND_PERIOD_DAYS": STIPEND_PERIOD_DAYS,
    "FULL_TERM_HOURS": FULL_TERM_HOURS,
    "MIN_PARTIAL_AWARD_HOURS": MIN_PARTIAL_AWARD_HOURS,
    "EDUCATION_AWARD_FULL_CENTS": EDUCATION_AWARD_FULL_CENTS,
    "PROJECTED_DAILY_HOURS": PROJECTED_DAILY_HOURS,
    "TIGHT_HEADROOM_CENTS": TIGHT_HEADROOM_CENTS,
    "DAILY_HOUR_CAP": DAILY_HOUR_CAP,
    "HOUR_QUANTUM": HOUR_QUANTUM,
    "VERIFICATION_WINDOW_DAYS": VERIFICATION_WINDOW_DAYS,
    "FUNDRAISING_CAP_FRACTION": FUNDRAISING_CAP_FRACTION,
    "CASELOAD_LIMIT": CASELOAD_LIMIT,
    "REPORT_WINDOW_DAYS": REPORT_WINDOW_DAYS,
    "IMPROVEMENT_THRESHOLD_PCT": IMPROVEMENT_THRESHOLD_PCT,
}

TEST_DEFAULTS = {
    "SERVICE_YEAR_START": SERVICE_YEAR_START,
    "SERVICE_YEAR_END": SERVICE_YEAR_END,
    "ANNUAL_STIPEND_CENTS": ANNUAL_STIPEND_CENTS,
    "SCHOOL_TEAM_SIZE": SCHOOL_TEAM_SIZE,
    "SCHOOL_COST_SHARE_CENTS": SCHOOL_COST_SHARE_CENTS,
    "BACKFILL_DEADLINE": BACKFILL_DEADLINE,
    "BACKFILL_LIMIT": BACKFILL_LIMIT,
    "MEMBER_DOB": MEMBER_DOB,
}

# A well-formed UUID that collides with nothing, for 404 probes.
NON_EXISTENT_ID = "8a3e1c0b-2f4d-4a91-9c8b-12e7b6a0f1d2"
