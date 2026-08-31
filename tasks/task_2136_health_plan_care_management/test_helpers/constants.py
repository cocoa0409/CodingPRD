"""Domain thresholds and defaults drawn from the PRD's narrative rules."""

# ─── Logical clock (PRD §2.5) ─────────────────────────────────────────────
CLOCK_STARTUP_INSTANT = "2026-08-01T00:00:00Z"
CLOCK_STARTUP_INSTANT_MS = "2026-08-01T00:00:00.000Z"

# ─── Risk stratification (PRD §3.2) ───────────────────────────────────────
RETROSPECTIVE_WINDOW_DAYS = 180
FORWARD_WINDOW_DAYS = 90
RECENCY_FULL_DAYS = 90
RECENCY_DECAYED_FACTOR = 0.5
EVENT_BASE_POINTS = {
    "INPATIENT_ADMISSION": 20,
    "ED_VISIT": 8,
    "OBSERVATION_STAY": 5,
    "SCHEDULED_ADMISSION": 20,
}
CHRONIC_POINTS_PER_CONDITION = 6
SDOH_POINTS_PER_NEED = 4
SDOH_POINT_CAP = 12
SCORE_CAP = 100
TIER_BANDS = {"HIGH": 85, "RISING": 60, "MODERATE": 35}

# ─── Caseload arithmetic (PRD §3.3) ───────────────────────────────────────
TIER_POINTS = {"LOW": 1, "MODERATE": 2, "RISING": 4, "HIGH": 7}
CADENCE_MULTIPLIER = {"STANDARD": 1.0, "INTENSIVE": 1.5, "TOC_INTENSIVE": 2.0}

# ─── Outreach cadence (PRD §3.6) ──────────────────────────────────────────
CADENCE_INTERVAL_DAYS = {"STANDARD": 30, "INTENSIVE": 14, "TOC_INTENSIVE": 7}
ENGAGEMENT_WINDOW_DAYS = 90
ENGAGEMENT_ENGAGED_THRESHOLD = 60
DISENGAGED_FAILURE_THRESHOLD = 3
ESCALATION_FAILURE_THRESHOLD = 2
ESCALATION_MIN_DAYS = 3
RELAXATION_BONUS_DAYS = 7
RELAXATION_MAX_DAYS = 45
TOC_CLAMP_DAYS = 2
DOCUMENTATION_BUFFER_MINUTES = 15

# ─── Outcome measurement (PRD §3.9) ───────────────────────────────────────
PRE_POST_BASELINE_MONTHS = 12
PRE_POST_TREND_FACTOR = 1.03
COHORT_RISK_FACTOR = {"LOW": 0.6, "MODERATE": 1.0, "RISING": 1.4, "HIGH": 2.1}

# ─── Test defaults ────────────────────────────────────────────────────────
TEST_DEFAULTS = {
    "STATE_CODE": "CA",
    "CAPACITY_POINTS": 20.0,
    "HOURLY_COST_CENTS": 9000,
    "COHORT_BENCHMARK_PMPM_CENTS": 100000,
    "STAFF_MINUTE_BUDGET": 100000,
    "CARE_PLAN_REVIEW_INTERVAL_DAYS": 90,
    "TOC_OUTREACH_HOURS": 48,
    "REFERRAL_LOOP_DAYS": 30,
    "CONCURRENT_SLOT_CAPACITY": 5,
}

# A syntactically valid UUID that never resolves to a stored record.
UNKNOWN_UUID = "8a3e1c0b-2f4d-4a91-9c8b-12e7b6a0f1d2"
