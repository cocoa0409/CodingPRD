"""Domain constants for the Human Milk Bank Screening Pasteurization API.

Every value here is a literal the PRD declares. Nothing is inferred and nothing
is copied out of an implementation; the tests read these names so that a
threshold appears exactly once in the suite.
"""

# ---------------------------------------------------------------------------
# Routing
# ---------------------------------------------------------------------------
API_PREFIX = "/milk-bank"

DEFAULT_PAGE_LIMIT = 10
MIN_PAGE_LIMIT = 1
MAX_PAGE_LIMIT = 100

# ---------------------------------------------------------------------------
# Logical clock
# ---------------------------------------------------------------------------
CLOCK_STARTUP_INSTANT = "2026-08-01T00:00:00Z"

# The instants the suite drives the clock to. Chosen once so that every
# derived date in the expectations is stable.
CLOCK_INTAKE = "2026-08-05T08:00:00Z"          # donor screening / qualification day
CLOCK_INTAKE_DATE = "2026-08-05"
CLOCK_RUN = "2026-08-10T10:05:00Z"             # pasteurization / bottling day
CLOCK_RUN_DATE = "2026-08-10"

# ---------------------------------------------------------------------------
# Health-history risk arithmetic (PRD 3.1)
# ---------------------------------------------------------------------------
POINTS_PER_FLAGGED_MEDICATION = 8
POINTS_TRAVEL_RISK = 25
POINTS_TOBACCO_USE = 40

# alcohol_units_per_week -> points. Exactly 0 contributes nothing, 1-3 gives 5,
# 4-7 gives 15, 8 or more gives 45.
ALCOHOL_TIER_ZERO_POINTS = 0
ALCOHOL_TIER_LOW_POINTS = 5
ALCOHOL_TIER_MID_POINTS = 15
ALCOHOL_TIER_HIGH_POINTS = 45

POSTPARTUM_FREE_MONTHS = 12
POSTPARTUM_POINTS_PER_MONTH = 3
POSTPARTUM_TERM_CAP = 30

PENDING_SEROLOGY_PENALTY = 20
POINTS_PER_TEMPORARY_DEFERRAL = 15
DEFERRAL_DECAY_HALF_LIFE_DAYS = 180
RISK_SCORE_CAP = 100

TRIAGE_ACCEPTED_MAX = 60          # <= 60 -> ACCEPTED
TRIAGE_INFO_REQUESTED_MAX = 85    # > 60 and <= 85 -> INFO_REQUESTED, above -> AUTO_DEFERRED
QUALIFY_SURVEILLANCE_CEILING = 60

MEDICATION_FLAG_COUNT_MIN, MEDICATION_FLAG_COUNT_MAX = 0, 10
ALCOHOL_UNITS_MIN, ALCOHOL_UNITS_MAX = 0, 40
MONTHS_POSTPARTUM_MIN, MONTHS_POSTPARTUM_MAX = 0, 48

# ---------------------------------------------------------------------------
# Serology, approval, deferral (PRD 3.2, 3.3)
# ---------------------------------------------------------------------------
SEROLOGY_VALID_DAYS = 180
PHYSICIAN_APPROVAL_VALID_DAYS = 365
PHYSICIAN_NPI_DIGITS = 10

AUTO_HIGH_RISK_DEFERRAL_DAYS = 90
AUTO_HIGH_RISK_LOOKBACK_DAYS = 0
REACTIVE_SEROLOGY_DEFERRAL_DAYS = 0
REACTIVE_SEROLOGY_LOOKBACK_DAYS = 365
SYSTEM_USER_ID = "system"

DEFERRAL_DAYS_MIN, DEFERRAL_DAYS_MAX = 0, 3650
LOOKBACK_DAYS_MIN, LOOKBACK_DAYS_MAX = 0, 1095

# ---------------------------------------------------------------------------
# Cold chain reimbursement (PRD 3.4)
# ---------------------------------------------------------------------------
ZONE_BASE_CENTS = {"Z1": 1200, "Z2": 1850, "Z3": 2600}
DRY_ICE_MULTIPLIER = 1.15
PER_CONTAINER_HANDLING_CENTS = 275
PENALTY_RATE_PER_EXCURSION_MINUTE = 0.02
MAX_PENALTY_RATE = 0.60
QUARANTINE_CREDIT_FRACTION = 0.5

REJECT_TEMP_CELSIUS = 4.0            # peak temperature strictly above -> REJECTED
REJECT_EXCURSION_MINUTES = 120       # excursion strictly above -> REJECTED
QUARANTINE_TEMP_CELSIUS = -8.0       # peak temperature strictly above -> QUARANTINED
QUARANTINE_EXCURSION_MINUTES = 30    # excursion strictly above -> QUARANTINED

CONTAINER_COUNT_MIN, CONTAINER_COUNT_MAX = 1, 8
DECLARED_VOLUME_MIN, DECLARED_VOLUME_MAX = 50, 9600
CONTAINER_LABEL_MIN_LEN, CONTAINER_LABEL_MAX_LEN = 1, 16
DONATION_VOLUME_MIN, DONATION_VOLUME_MAX = 50, 1200
KCAL_PER_OZ_MIN, KCAL_PER_OZ_MAX = 14.0, 26.0

# ---------------------------------------------------------------------------
# Pooling (PRD 3.5)
# ---------------------------------------------------------------------------
POOL_DONOR_CAP = 5
POOL_MIN_DISTINCT_DONORS = 3
POOL_KCAL_MIN, POOL_KCAL_MAX = 19.00, 21.00
POOL_VOLUME_MIN, POOL_VOLUME_MAX = 1500, 6000
RAW_MILK_MAX_AGE_DAYS = 365
ALLOCATED_VOLUME_MIN, ALLOCATED_VOLUME_MAX = 50, 1200

# ---------------------------------------------------------------------------
# Pasteurization run (PRD 3.6)
# ---------------------------------------------------------------------------
CLEANING_BUFFER_MINUTES = 15
CYCLE_MINUTES_MIN, CYCLE_MINUTES_MAX = 30, 120
OFFSET_SECONDS_MIN, OFFSET_SECONDS_MAX = 0, 14400
CELSIUS_MIN, CELSIUS_MAX = 0.0, 90.0
HOLD_BAND_LOW_CELSIUS, HOLD_BAND_HIGH_CELSIUS = 62.5, 65.0
THERMAL_PASS_HOLD_SECONDS = 1800
MAX_MONITORING_GAP_SECONDS = 600
MIN_READINGS_TO_COMPLETE = 2
CULTURE_FAIL_CFU_PER_ML = 10
NO_GROWTH_ORGANISM = "NONE"

# ---------------------------------------------------------------------------
# Bottling and shelf life (PRD 3.7)
# ---------------------------------------------------------------------------
BOTTLE_COUNT_MIN, BOTTLE_COUNT_MAX = 1, 200
BOTTLE_VOLUME_MIN, BOTTLE_VOLUME_MAX = 20, 250
PASTEURIZATION_SHELF_DAYS = 180
RAW_AGE_SHELF_DAYS = 365
RECEIPT_SHELF_DAYS = 240

# ---------------------------------------------------------------------------
# Subsidy, prescriptions, pricing (PRD 3.8, 3.9, 3.10)
# ---------------------------------------------------------------------------
COVERAGE_PCT_MIN, COVERAGE_PCT_MAX = 0.00, 1.00
ANNUAL_CAP_CENTS_MIN, ANNUAL_CAP_CENTS_MAX = 1, 100000000
PATIENT_REFERENCE_MIN_LEN, PATIENT_REFERENCE_MAX_LEN = 1, 40
PRESCRIBED_ML_MIN, PRESCRIBED_ML_MAX = 50, 12000
DISPENSE_VOLUME_MIN, DISPENSE_VOLUME_MAX = 20, 12000

BILLABLE_UNIT_ML = 100
CENTS_PER_BILLABLE_UNIT = 480
OUTPATIENT_HANDLING_CENTS = 350
TIER_DISCOUNT_NONE = 0.00
TIER_DISCOUNT_MID = 0.05
TIER_DISCOUNT_HIGH = 0.12
TIER_BREAK_LOW_ML = 2000     # prior volume strictly below -> 0.00
TIER_BREAK_HIGH_ML = 5000    # prior volume strictly below -> 0.05, otherwise 0.12

NICU_RESERVE_ML = 3000
ALLOCATION_LOT_CAP_PER_PRESCRIPTION = 3

PRIORITY_TIER_NICU_CRITICAL = 1
PRIORITY_TIER_NICU_STANDARD = 2
PRIORITY_TIER_OUTPATIENT = 3
