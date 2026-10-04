"""Domain thresholds and test defaults drawn from the PRD's numeric rules."""

# ─── Week lattice anchors (PRD §2.4) ──────────────────
CLOCK_DEFAULT = "2026-09-01T00:00:00Z"
WEEK_ONE_START = "2026-09-07T00:00:00Z"

# ─── Roster fee weights (PRD §3.2) ────────────────────
THRESHOLDS = {
    # Payability weights
    "ELIGIBLE_WEIGHT": 1.00,
    "INELIGIBLE_WEIGHT": 0.50,
    # LEGACY roster base multiplier
    "LEGACY_ROSTER_MULTIPLIER": 0.75,
    # Attrition-risk score terms (PRD §3.2)
    "PER_MISSED_WEEK": 12,
    "PER_FAILED_OUTREACH": 15,
    "LOW_ADHERENCE_PENALTY": 40,
    "LOW_ADHERENCE_THRESHOLD": 0.35,
    "STALE_ENGAGEMENT_PENALTY": 20,
    "STALE_ENGAGEMENT_START_WEEK": 4,
    "STALE_ENGAGEMENT_THRESHOLD": 0.50,
    "SCORE_CEILING": 100,
    # Spine red-flag escalation (PRD §3.2)
    "RED_FLAG_ESCALATION_THRESHOLD": 0.30,
    # Engagement milestone (PRD §3.7)
    "WEEKS_PER_MONTH": 4,
    # Appointment geometry / capacity (PRD §3.4)
    "APPOINTMENT_START_TO_START_BUFFER_MINUTES": 60,
    "MINUTES_PER_CAPACITY_SLOT": 60,
    "MIN_DURATION_MINUTES": 15,
    "MAX_DURATION_MINUTES": 120,
    # Dropout window (PRD §3.9)
    "DROPOUT_WINDOW_WEEKS": 4,
    "DROPOUT_CONSECUTIVE_MISSED": 3,
    "DROPOUT_FAILED_OUTREACH": 2,
    # Outreach cadence window (PRD §3.4)
    "OUTREACH_FIRST_WEEK": 1,
    "OUTREACH_LAST_WEEK": 4,
    # Review reconciliation ladder (PRD §3.5)
    "REVIEW_LAPSE_DAYS": 7,
    "NO_ENGAGEMENT_STALE_DAYS": 14,
    # Pagination (PRD §2.3)
    "PAGINATION_DEFAULT_LIMIT": 10,
    "PAGINATION_MIN_LIMIT": 1,
    "PAGINATION_MAX_LIMIT": 100,
    "PAGINATION_DEFAULT_OFFSET": 0,
}

TEST_DEFAULTS = {
    # Care-track defaults
    "MIN_ADHERENCE_RATE": 0.70,
    "ACUTE_BASE_FEE_CENTS": 9000,
    "CHRONIC_BASE_FEE_CENTS": 12000,
    "SEVERITY_WEIGHTS": {"LOW": 0.2, "HIGH": 0.5},
    # Client contract defaults
    "SAVINGS_SHARE_RATE": 0.30,
    "EXPECTED_MONTHLY_ENGAGEMENT_RATE": 0.60,
    # Clinician defaults
    "WEEKLY_CAPACITY_SLOTS": 20,
    "PHYSICIAN_WEEKLY_CAPACITY_SLOTS": 12,
    # Roster defaults
    "FILE_PERIOD": "2026-09",
    "ROSTER_FORMAT": "STANDARD",
    # Session defaults
    "PLANNED_REPS": 12,
    "PLANNED_MINUTES": 18,
    "PAIN_SCORE_AFTER": 6.5,
}

# Appointment anchor day used throughout the appointment scenarios.
APPOINTMENT_DAY = "2026-09-08T00:00:00Z"