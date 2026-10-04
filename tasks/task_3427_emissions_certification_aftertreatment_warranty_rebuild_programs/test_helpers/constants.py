"""Domain thresholds and program constants — every value verified against PRD.md.

PRD section each constant is pinned by is noted inline. The PRD is the contract:
where prose and any other source disagree, PRD prose wins.
"""

# --- Logical clock (PRD §2.4) -------------------------------------------------
# "the logical clock reads exactly 2026-09-01T00:00:00Z, and the clock never
# falls back to wall-clock time at any point afterward"
DEFAULT_CLOCK_UTC = "2026-09-01T00:00:00Z"

# --- Pagination (PRD §2.3) ----------------------------------------------------
DEFAULT_PAGE_LIMIT = 10
MIN_PAGE_LIMIT = 1
MAX_PAGE_LIMIT = 100
DEFAULT_PAGE_OFFSET = 0

# --- Certification testing (PRD §3.2) -----------------------------------------
# "for each of the three required test types FTP, RMC, and SET, at least one
# certification test run in ACCEPTED status"
REQUIRED_TEST_TYPES = ("FTP", "RMC", "SET")

# --- Numeric precision (PRD §2.6) ----------------------------------------------
# "rounded half-up to 4 decimal places" (emissions, ratios, rates, deviation)
EMISSIONS_RESULT_DECIMALS = 4
# "Dosing targets are rounded half-up to 2 decimal places"
DOSING_TARGET_DECIMALS = 2

# --- Extended emissions warranty coverage (PRD §3.7) ---------------------------
# "the smaller of 5 years and the standard's useful_life_years ... the smaller
# of 100,000 miles ... the smaller of 3,000 hours"
EXTENDED_WARRANTY_YEARS = 5
EXTENDED_WARRANTY_MILES = 100000
EXTENDED_WARRANTY_HOURS = 3000
# "one of the five emissions component classes — AFTERTREATMENT_SCR,
# AFTERTREATMENT_DPF, DOSING_SYSTEM, NOX_SENSOR, or EGR_SYSTEM"
EMISSIONS_COMPONENT_CLASSES = (
    "AFTERTREATMENT_SCR",
    "AFTERTREATMENT_DPF",
    "DOSING_SYSTEM",
    "NOX_SENSOR",
    "EGR_SYSTEM",
)

# --- Neglect scoring (PRD §3.7) -------------------------------------------------
MAINTENANCE_INTERVAL_MILES = 15000          # "the 15,000-mile maintenance interval"
NEGLECT_MISSED_INTERVAL_POINTS = 25         # "Each missed oil change contributes 25 points"
NEGLECT_BAD_DEF_POINTS = 15                 # "def_quality_ok set false contributes 15 points"
NEGLECT_CRITICAL_FAULT_POINTS = 20          # "at least one CRITICAL entry contributes 20 points"
NEGLECT_SCORE_CAP = 100                     # "The score is the sum, capped at 100"
NEGLECT_PARTIAL_MIN_SCORE = 30              # "at least 30 and below 60 ... APPROVE_PARTIAL"
NEGLECT_DENY_MIN_SCORE = 60                 # "a score of at least 60 ... DENY_NEGLECT"
# "the cap is half of claimed_amount_cents rounded half-up to whole cents"
PARTIAL_CUSTOMER_SHARE_CAP_PCT = 0.5
# "when that count reaches 3, the fleet transitions from ACTIVE to SUSPENDED"
FLEET_NEGLECT_SUSPENSION_THRESHOLD = 3
# "only while review_round is below 2"
MAX_REVIEW_ROUNDS = 2

# --- Reman / core credit (PRD §3.9) ---------------------------------------------
# "60 percent of the quoted_core_value_cents ... rounded half-up to whole cents"
CORE_PROVISIONAL_CREDIT_PCT = 0.6
# "the full value (1.0) for grade A, 0.75 for grade B, and 0.5 for grade C";
# REJECT is "defined as a 0.0 grade percentage"
CORE_GRADE_PCT = {"A": 1.0, "B": 0.75, "C": 0.5, "REJECT": 0.0}
# "the credit cap is the effective price multiplied by 0.4 (that is, 40 percent)"
MAX_CORE_CREDIT_PCT_OF_PRICE = 0.4
# "the multiplier is 1.0 for STANDARD (a surcharge of zero), 1.15 for PLUS,
# and 1.3 for PREMIUM"
SPEC_LEVEL_MULTIPLIER = {"STANDARD": 1.0, "PLUS": 1.15, "PREMIUM": 1.3}
# "When that count reaches 2, the center transitions from AUTHORIZED to SUSPENDED"
CORE_REVERSAL_SUSPENSION_THRESHOLD = 2

# --- In-use compliance (PRD §3.4) -----------------------------------------------
# "CONFORMING when that rounded ratio is at least 0.9 — a ratio of exactly
# 0.9000 conforms, because the threshold is inclusive"
CONFORMITY_RATIO_THRESHOLD = 0.9
# "The sample_size must be at least 5"
MIN_IN_USE_SAMPLE_SIZE = 5

# --- Campaign completion (PRD §3.8) ---------------------------------------------
# "an optional completion_threshold that defaults to 0.95 when omitted"
DEFAULT_COMPLETION_THRESHOLD = 0.95

# --- Telematics fault risk (PRD §3.5) -------------------------------------------
FAULT_WEIGHT_CRITICAL = 40      # "40 points when its severity is CRITICAL"
FAULT_WEIGHT_MAJOR = 20         # "20 when MAJOR"
FAULT_WEIGHT_MINOR = 5          # "5 when MINOR"
FAULT_RISK_DRIFT_DIVISOR = 10   # "divided by 10 and floored"
FAULT_RISK_DRIFT_CAP = 30       # "capped at 30 drift points"
DEF_ZERO_MILES_THRESHOLD = 500  # "exceeds 500 miles"
DEF_ZERO_PENALTY_POINTS = 25    # "a flat 25 penalty points"
FAULT_RISK_SCORE_CAP = 100      # "an integer capped at 100"
PREDICTIVE_SERVICE_THRESHOLD = 70  # "When the resulting score is at least 70"

# --- Service network (PRD §3.6) --------------------------------------------------
TECH_CERT_VALIDITY_DAYS = 730        # "certification_expires_at is set exactly 730 days later"
TOOL_CALIBRATION_VALIDITY_DAYS = 365  # "sets calibration_valid_until exactly 365 days later"

# --- Work orders (PRD §3.8) ------------------------------------------------------
# "for any work order occupying 3 or more bay days — must hold LEVEL_2 or
# LEVEL_3 certification"
WORK_ORDER_LEVEL2_MIN_BAY_DAYS = 3

# --- Dosing calibration (PRD §3.3) ------------------------------------------------
# "6.0 grams of DEF per kilowatt-hour, scaled by the family's
# displacement_liters against a 12.0-liter reference displacement"
DOSING_BASE_G_PER_KWH = 6.0
DOSING_REFERENCE_DISPLACEMENT_L = 12.0
# "no greater than 0.05 — a deviation of precisely 0.0500 calibrates"
DOSING_TOLERANCE_PCT = 0.05
# "the observed NOx average is no greater than 400 parts per million"
NOX_SENSOR_PPM_MAX = 400
