"""Domain thresholds, rates and pinned literals from the PRD.

Every figure here is stated in the PRD's narrative sections: the screening
thresholds and weight bands, the posture boundaries, the certificate day
counts, the billing credits, the item validity windows and the fixed
examination charge.
"""

# ── Grooming screening ───────────────────────────────────────────────────────
PET_RISK_CAP = 100
BREED_RISK_SOFT_CEILING = 25
SCORE_CAP = 160
WEIGHT_BAND_LARGE_KG = 40.0
WEIGHT_BAND_LARGE_POINTS = 10
WEIGHT_BAND_MEDIUM_KG = 25.0
WEIGHT_BAND_MEDIUM_POINTS = 5
CONDITION_POINTS = {
    "CARDIAC": 30,
    "EPILEPSY": 25,
    "DIABETES": 20,
    "ORTHOPEDIC": 15,
    "SKIN_INFECTION": 10,
}
# Circumferential conditions total (the set used by the boundary/screening tests).
ALL_CONDITIONS_POINTS = 30 + 25 + 20 + 15 + 10  # 100

HIGH_RISK_THRESHOLD = 70
SENSITIVE_THRESHOLD = 40

# ── Hospital posture ladder ──────────────────────────────────────────────────
SURGE_FREEZE_PCT = 0.90
RESTRICT_FREEZE_PCT = 0.80
HYSTERESIS_RELEASE_PCT = 0.70

# ── Temporal guards ──────────────────────────────────────────────────────────
SCREENING_VALIDITY_DAYS = 30
PET_BUFFER_MINUTES = 15
NO_SHOW_GRACE_MINUTES = 30
PHARMACY_HOLD_HOURS = 72

# ── Rabies certificates ──────────────────────────────────────────────────────
STATE_DEFAULT_DAYS = {"CA": 1095, "TX": 365, "NY": 365, "FL": 1095}
BOOSTER_CAP_DAYS = 365
REPORTING_STATES = ("CA", "TX", "NY")

# ── Encounters, prescriptions and pharmacy ───────────────────────────────────
EXAM_CHARGE_CENTS = 8500
ITEM_VALIDITY_DAYS = {"MEDICATION": 30, "DIET": 90, "TREATMENT": 60}

# ── Packages and billing ─────────────────────────────────────────────────────
DEFAULT_MONTHLY_FEE_CENTS = {"ESSENTIAL": 3999, "PLUS": 6999, "UNLIMITED": 11999}
TIER_HARD_CAP = {"ESSENTIAL": 4, "PLUS": 8, "UNLIMITED": 12}
TIER_INCLUSIONS = {
    "ESSENTIAL": {"grooming": 1, "vet": 0, "vaccine": 1},
    "PLUS": {"grooming": 2, "vet": 1, "vaccine": 1},
    "UNLIMITED": {"grooming": 6, "vet": 2, "vaccine": 2},
}
GROOMING_VISIT_CREDIT_CENTS = 2500
VET_VISIT_CREDIT_CENTS = 4000
VACCINE_VISIT_CREDIT_CENTS = 1500
OVERAGE_CREDIT_CENTS = 500
BILLING_CYCLE_COUNTS = (1, 3, 6, 12)

# ── Cross-sell credit ────────────────────────────────────────────────────────
CROSS_SELL_CREDIT_RATE = 0.10

# ── Incident risk points ─────────────────────────────────────────────────────
SEVERITY_RISK_POINTS = {"MINOR": 10, "MODERATE": 25, "SEVERE": 40}

# ── Logical clock ────────────────────────────────────────────────────────────
CLOCK_DEFAULT = "2026-09-01T00:00:00Z"
# A Monday inside a CA clinic window, and instants used by several workflows.
CLOCK_MONDAY_SEP_21 = "2026-09-21T09:00:00Z"
CLOCK_MONDAY_JUN_01 = "2026-06-01T00:00:00Z"

# ── Pagination (PRD §2.3) ────────────────────────────────────────────────────
PAGINATION_DEFAULT_LIMIT = 10
PAGINATION_MIN_LIMIT = 1
PAGINATION_MAX_LIMIT = 100

# ── Test defaults ────────────────────────────────────────────────────────────
TEST_DEFAULTS = {
    "CITY": "Sacramento",
    "STATE_CODE": "CA",
    "SERVICE_BAY_COUNT": 2,
    "HOSPITAL_CAPACITY": 4,
    "TAX_RATE": 0.07,
    "WEIGHT_KG": 12.0,
}