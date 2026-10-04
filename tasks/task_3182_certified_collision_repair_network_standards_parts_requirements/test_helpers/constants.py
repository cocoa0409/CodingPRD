"""Domain thresholds — numeric constants from PRD calculation sections."""

# Compliance score category weights (PRD: "weights 30 for EQUIPMENT, 30 for
# STRUCTURAL, 15 for TOOLING, and 25 for TRAINING")
CATEGORY_WEIGHTS = {
    "EQUIPMENT": 30,
    "STRUCTURAL": 30,
    "TOOLING": 15,
    "TRAINING": 25,
}

# Finding severity weights (PRD: "1 per MINOR, 5 per MAJOR, 25 per CRITICAL")
SEVERITY_WEIGHTS = {
    "MINOR": 1,
    "MAJOR": 5,
    "CRITICAL": 25,
}

# Corrective-action deadlines in days (PRD: "a MAJOR finding is due 30 days
# after issuance, a CRITICAL finding 10 days, and a MINOR finding 60 days")
CORRECTIVE_ACTION_DAYS = {
    "MINOR": 60,
    "MAJOR": 30,
    "CRITICAL": 10,
}

# Grade boundaries (PRD: "0 effective points is grade A; from 1 up to and
# including 5 is B; from 6 up to and including 24 is C; 25 or more is F")
GRADE_B_MAX = 5
GRADE_C_MAX = 24
ESCALATION_PENALTY_EACH = 3
ESCALATION_THRESHOLD_CENTS = 500000

# Warranty reserve accrual tiers (PRD section on reserve accrual)
TIER1_CAP_CENTS = 100000
TIER1_RATE = 0.03
TIER2_CAP_CENTS = 500000
TIER2_RATE = 0.02
TIER3_RATE = 0.01
ADAS_MULTIPLIER = 1.5
REWORK_PENALTY_CENTS = 500

# Misc domain constants
ADAS_MODEL_YEAR_THRESHOLD = 2018
LOCATOR_RADIUS_MILES = 25
LOAD_CAP = 20
REFERRAL_TTL_HOURS = 72
DELIVERY_GRACE_HOURS = 24
WARRANTY_MONTHS = 12
MAX_REWORK = 3
DECERTIFY_GRACE_DAYS = 90

TEST_DEFAULTS = {
    "VIN": "1HGCV1F34LA000001",
    "ESTIMATE_CENTS": 10000,
    "WINDOW_START": "2026-09-01T00:00:00Z",
    "WINDOW_END": "2027-08-31T23:59:59Z",
    "CLOCK_DEFAULT": "2026-09-01T00:00:00Z",
}
