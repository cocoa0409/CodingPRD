"""Domain thresholds and pinned tables for the medical professional liability API.

Every number here is quoted from the PRD's business-logic sections; nothing is
invented locally.
"""

API_PREFIX = "/mpl"

# --- Logical clock (PRD 2.6) ------------------------------------------------
CLOCK_EPOCH = "2026-08-01T00:00:00Z"

# --- Pagination (PRD 2.3) --------------------------------------------------
DEFAULT_LIMIT = 10
MIN_LIMIT = 1
MAX_LIMIT = 100

# --- Risk classification (PRD 3.2) ----------------------------------------
RISK_WEIGHT_SPECIALTY = 0.40
RISK_WEIGHT_PROCEDURE = 0.35
RISK_WEIGHT_HISTORY = 0.25
RISK_HISTORY_CAP = 10.0
RISK_CLOSED_PAID_WEIGHT = 2.0
RISK_OPEN_CLAIM_WEIGHT = 1.0

RISK_BAND_R2_LOWER = 3.00
RISK_BAND_R3_LOWER = 5.00
RISK_BAND_R4_LOWER = 7.50

RISK_CLASS_FACTOR = {
    "R1": 0.85,
    "R2": 1.00,
    "R3": 1.30,
    "R4": 1.75,
}

# --- Risk-management credits (PRD 3.3) ------------------------------------
PROGRAM_CREDIT_PCT = {
    "CME_RISK_101": 0.03,
    "SIM_LAB": 0.05,
    "CHART_AUDIT": 0.04,
    "TEAMSTEPPS": 0.02,
    "EHR_SAFETY": 0.025,
}
MAX_STACKED_CREDIT_PCT = 0.10
CREDIT_LOOKBACK_DAYS = 730

# --- Peer review surcharges (PRD 3.3) -------------------------------------
PEER_REVIEW_SURCHARGE_PCT = {
    "NO_DEVIATION": 0.00,
    "DEVIATION_MINOR": 0.10,
    "DEVIATION_MAJOR": 0.25,
}
SURCHARGE_WINDOW_DAYS = 1095

# --- Term rating ladder (PRD 3.4) -----------------------------------------
STEP_FACTOR = {
    1: 0.35,
    2: 0.60,
    3: 0.80,
    4: 0.92,
    5: 1.00,
}
INCREASED_LIMITS_FACTOR = {
    1000000.00: 1.00,
    2000000.00: 1.45,
    3000000.00: 1.75,
    5000000.00: 2.10,
}
VENUE_SEVERITY_FACTOR = {
    "COOK_IL": 1.45,
    "MIAMI_DADE_FL": 1.60,
    "KINGS_NY": 1.35,
    "TRAVIS_TX": 1.05,
    "MARICOPA_AZ": 1.00,
}
ADMIN_FEE_TIER_MID_LOWER = 25000.00
ADMIN_FEE_TIER_HIGH_LOWER = 100000.00
ADMIN_FEE_LOW = 250.00
ADMIN_FEE_MID = 500.00
ADMIN_FEE_HIGH = 900.00
GUARANTY_FUND_RATE = 0.0125

# --- Tail endorsements (PRD 3.5) ------------------------------------------
TAIL_FACTOR = {
    "ERP_5YR": 1.55,
    "ERP_UNLIMITED": 2.00,
    "DEATH_DISABILITY_RETIREMENT": 0.00,
}
UNLIMITED_REPORTING_WINDOW_END = "9999-12-31"
DDR_MIN_YEARS_IN_PRACTICE = 5
DDR_MIN_STEP_YEAR = 5

# --- Claim severity bands (PRD 3.6) ---------------------------------------
SEVERITY_BAND_2_LOWER = 250000.00
SEVERITY_BAND_3_LOWER = 750000.00
SEVERITY_BAND_4_LOWER = 2000000.00
SEVERITY_BAND_FACTOR = {
    "BAND_1": 0.20,
    "BAND_2": 0.32,
    "BAND_3": 0.45,
    "BAND_4": 0.60,
}

# --- Reserving (PRD 3.7) --------------------------------------------------
FORMULA_EXPENSE_PCT = 0.28
EXPENSE_RESERVE_FLOOR = 15000.00

# --- Settlement / hammer (PRD 3.8) ----------------------------------------
HAMMER_EXPOSURE_MULTIPLIER = 1.60
INSURED_EXCESS_SHARE = 0.50

# --- Data bank reporting (PRD 3.9) ----------------------------------------
NPDB_DUE_DAYS = 30
CLAIM_CLOSE_RUNOFF_DAYS = 30

# --- Actuarial engine (PRD 3.1) -------------------------------------------
EXPENSE_LOADING_MULTIPLIER = 1.28
PERMISSIBLE_LOSS_RATIO = 0.6500
TREND_COMPLEMENT_PCT = 4.50
CREDIBILITY_FULL_CLAIM_COUNT = 30
CREDIBILITY_PARTIAL_CLAIM_COUNT = 10
CREDIBILITY_WEIGHT_FULL = 1.00
CREDIBILITY_WEIGHT_PARTIAL = 0.60
CREDIBILITY_WEIGHT_LOW = 0.30
ADEQUACY_DEFICIENT_UPPER = 0.9000
ADEQUACY_REDUNDANT_LOWER = 1.1000

# --- Enum member catalogues (PRD 3.x) -------------------------------------
SPECIALTY_CODES = [
    "NEUROSURGERY",
    "OBSTETRICS_GYNECOLOGY",
    "ORTHOPEDIC_SURGERY",
    "EMERGENCY_MEDICINE",
    "FAMILY_MEDICINE",
]
BASE_CLASS_CODES = [f"CLASS_{n}" for n in range(1, 9)]
VENUE_CODES = list(VENUE_SEVERITY_FACTOR.keys())
ALLEGATION_CATEGORIES = [
    "DIAGNOSIS_FAILURE",
    "SURGICAL_ERROR",
    "MEDICATION_ERROR",
    "OBSTETRIC_INJURY",
    "INFORMED_CONSENT",
]
PROGRAM_CODES = list(PROGRAM_CREDIT_PCT.keys())
PER_CLAIM_LIMITS = [1000000.00, 2000000.00, 3000000.00, 5000000.00]

# The canonical absent identifier used by the not-found probes.
ABSENT_UUID = "00000000-0000-4000-8000-000000000000"

# Opaque operator identifiers used throughout the suite. Seven of the eight
# roles carry an opaque X-User-ID that is never compared to an entity id.
OPERATOR_IDS = {
    "UnderwritingOfficer": "uw-1",
    "ClaimsAdjuster": "adj-1",
    "ClaimsAdjusterSecond": "adj-2",
    "ClaimsCommitteeApprover": "appr-1",
    "PeerReviewChair": "chair-1",
    "ActuarialAnalyst": "act-1",
    "ChiefActuary": "chief-1",
    "ComplianceOfficer": "comp-1",
}
