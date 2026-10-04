"""Domain thresholds and test defaults for the Medicare broker compliance API.

Every constant below is named in the PRD's calculation prose (Section 3.4-3.10)
and the Section 2.7 posture rules.
"""

# ─── Posture and complaint thresholds ────────────────────────
POSTURE_FREEZE_STRIKES = 5
POSTURE_FREEZE_LOSS_RATIO = 0.20
POSTURE_RESTRICT_THRESHOLD = 0.05
POSTURE_STRIKE_WINDOW_DAYS = 365

# ─── Scope and recording windows ─────────────────────────────
DEFAULT_SOA_MAX_AGE_DAYS = 30
DEFAULT_SOA_RETENTION_DAYS = 3650
DEFAULT_RECORDING_RETENTION_DAYS = 2555
DEFAULT_RAPID_DISENROLLMENT_DAY_LIMIT = 90
DEFAULT_MAX_LIVE_CALLS_PER_AGENT = 1
DEFAULT_MAX_OPEN_COACHING_PER_AGENT = 2

# ─── Carrier windows ─────────────────────────────────────────
DEFAULT_ACK_EXPECTED_WITHIN_DAYS = 5
DEFAULT_EFFECTUATION_EXPECTED_WITHIN_DAYS = 30

# ─── Chargeback day bands ────────────────────────────────────
DAY_BANDS = [
    {"name": "DAY_0_30", "min_day": 0, "max_day": 30, "base_pct": 1.00},
    {"name": "DAY_31_60", "min_day": 31, "max_day": 60, "base_pct": 0.75},
    {"name": "DAY_61_90", "min_day": 61, "max_day": 90, "base_pct": 0.50},
]
ESCALATION_TIER_THRESHOLD = 4
HARD_ESCALATION_TIER_THRESHOLD = 7
ESCALATION_COMPLAINT_WINDOW_DAYS = 30

# ─── Risk-score weights ──────────────────────────────────────
RISK_WINDOW_DAYS = 365
SESSION_RECORDING_PENALTY = 3.0
SESSION_DISCLAIMER_PENALTY = 7.0
SESSION_SCOPE_PENALTY = 2.0
RAPID_DISENROLLMENT_PENALTY = 10.0
COMPLAINT_SEVERITY_POINTS = {"LOW": 8.0, "MEDIUM": 16.0, "HIGH": 24.0}
COACHING_ASSIGNMENT_POINTS = 5.0
OVERDUE_DAY_POINTS = 3.0

# ─── Plan comparison scoring ─────────────────────────────────
WEIGHT_PLAN_TYPE = 10
WEIGHT_STAR = 12
WEIGHT_PHARMACY = 8
WEIGHT_PROVIDER = 15
WEIGHT_COST = 1.0
COST_DIVISOR_CENTS = 100
DAYS_SUPPLY_RATIO_MULTIPLIER = 1.05
DAYS_PER_FILL = 30

# ─── Commission projection ───────────────────────────────────
FORWARD_WINDOW_DAYS = 365
METHOD_FEE_MULTIPLIER = 1.06
LAPSE_GAP_DAYS = 0

# ─── Coaching ────────────────────────────────────────────────
COACHING_DUE_DAYS = 14
SHOPPER_SCORE_FLOOR = 70

# ─── Ledger ──────────────────────────────────────────────────
RENEWAL_ADJUSTMENT_MONTHS = 1

# ─── Named instants used by the shared anchor setup ──────────
CLOCK_START = "2026-10-01T00:00:00Z"
CLOCK_START_0900 = "2026-10-01T09:00:00Z"
CLOCK_BEFORE_AEP = "2026-09-01T00:00:00Z"

THRESHOLDS = {
    "POSTURE_FREEZE_STRIKES": POSTURE_FREEZE_STRIKES,
    "POSTURE_FREEZE_LOSS_RATIO": POSTURE_FREEZE_LOSS_RATIO,
    "POSTURE_RESTRICT_THRESHOLD": POSTURE_RESTRICT_THRESHOLD,
    "ESCALATION_TIER_THRESHOLD": ESCALATION_TIER_THRESHOLD,
    "HARD_ESCALATION_TIER_THRESHOLD": HARD_ESCALATION_TIER_THRESHOLD,
    "SHOPPER_SCORE_FLOOR": SHOPPER_SCORE_FLOOR,
    "COACHING_DUE_DAYS": COACHING_DUE_DAYS,
}

TEST_DEFAULTS = {
    "MONTHLY_PREMIUM_CENTS": 1500,
    "ANNUAL_DRUG_DEDUCTIBLE_CENTS": 20000,
    "STAR_RATING": 4.5,
    "INITIAL_COMMISSION_RATE_PCT": 0.20,
    "RENEWAL_COMMISSION_RATE_PCT": 0.10,
    "CHARGEBACK_CLAWBACK_PCT": 0.25,
    "AEP_DAILY_SUBMISSION_CAPACITY": 3,
    "PLAN_TYPE": "MAPD",
    "STATE_CODE": "TX",
    "COUNTY_CODE": "TX-201",
}

__all__ = [name for name in dir() if not name.startswith("_")]