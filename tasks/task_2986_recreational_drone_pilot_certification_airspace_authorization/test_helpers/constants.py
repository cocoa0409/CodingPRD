"""Domain thresholds, bounds and fixed literals declared by the PRD."""

# ---------------------------------------------------------------------------
# Logical clock
# ---------------------------------------------------------------------------

# The clock's value at startup is exactly this instant, and it is monotonic and
# forward-only: any target at or before the present value is rejected.
CLOCK_STARTUP_UTC = "2026-08-01T00:00:00Z"

# ---------------------------------------------------------------------------
# Pagination
# ---------------------------------------------------------------------------

DEFAULT_LIMIT = 10
MIN_LIMIT = 1
MAX_LIMIT = 100
DEFAULT_OFFSET = 0

# ---------------------------------------------------------------------------
# Knowledge testing and certification
# ---------------------------------------------------------------------------

RECREATIONAL_PASS_MARK = 100
COMMERCIAL_PASS_MARK = 70
MIN_RAW_SCORE = 0
MAX_RAW_SCORE = 100

MAX_TEST_ATTEMPTS_PER_WINDOW = 3
TEST_ATTEMPT_WINDOW_DAYS = 365

CERTIFICATE_NUMBER_PREFIX = "CERT-"
CERTIFICATE_VALIDITY_MONTHS = 24

# ---------------------------------------------------------------------------
# Currency
# ---------------------------------------------------------------------------

RECENCY_WINDOW_DAYS = 90

# ---------------------------------------------------------------------------
# Airframes and remote identification
# ---------------------------------------------------------------------------

# remote_id_required is true exactly when takeoff_weight_g is strictly greater
# than this threshold; an airframe of exactly 250 grams is exempt.
REMOTE_ID_WEIGHT_THRESHOLD_G = 250
REMOTE_ID_EXEMPT_WEIGHT_G = 250
REMOTE_ID_REQUIRED_WEIGHT_G = 251

MIN_TAKEOFF_WEIGHT_G = 1
MAX_TAKEOFF_WEIGHT_G = 25000
MIN_AIRCRAFT_MAX_ALTITUDE_FT = 1
MAX_AIRCRAFT_MAX_ALTITUDE_FT = 5000

# ---------------------------------------------------------------------------
# Airspace zones and restrictions
# ---------------------------------------------------------------------------

MIN_CLASS_CEILING_FT = 100
MAX_CLASS_CEILING_FT = 2000
MIN_CONCURRENT_AUTHORIZATIONS = 1
MAX_CONCURRENT_AUTHORIZATIONS = 20
MIN_TFR_ALTITUDE_FT = 0
MAX_TFR_ALTITUDE_FT = 2000

# ---------------------------------------------------------------------------
# Authorization ceiling arithmetic
# ---------------------------------------------------------------------------

# The waiver cap when no usable waiver relief applies.
DEFAULT_WAIVER_CAP_FT = 400
# The category cap: 400 feet flat for a recreational operator; for a commercial
# operator 600 feet when the zone is structure-relief eligible and 400 when not.
RECREATIONAL_CATEGORY_CAP_FT = 400
COMMERCIAL_CATEGORY_CAP_FT = 400
COMMERCIAL_STRUCTURE_RELIEF_CAP_FT = 600

MIN_REQUESTED_CEILING_FT = 1
MAX_REQUESTED_CEILING_FT = 2000

# ---------------------------------------------------------------------------
# Waivers and safety cases
# ---------------------------------------------------------------------------

MAX_REVISION_ROUNDS = 2
MAX_APPROVABLE_SAIL = 5
MIN_SAIL_LEVEL = 1
MAX_SAIL_LEVEL = 6
WAIVER_VALIDITY_DAYS = 180

MIN_GROUND_RISK_CLASS = 1
MAX_GROUND_RISK_CLASS = 4

# ARC_A is 0, ARC_B is 1, ARC_C is 2, ARC_D is 3.
AIR_RISK_INDEX = {"ARC_A": 0, "ARC_B": 1, "ARC_C": 2, "ARC_D": 3}
# Beyond-visual-line-of-sight uplift of 1; 0 for OVER_PEOPLE and NIGHT.
BVLOS_SAIL_UPLIFT = 1

# ---------------------------------------------------------------------------
# Insurance
# ---------------------------------------------------------------------------

MIN_COMMERCIAL_COVERAGE_CENTS = 1000000

# ---------------------------------------------------------------------------
# Flights
# ---------------------------------------------------------------------------

TURNAROUND_BUFFER_MINUTES = 30
MIN_PLANNED_ALTITUDE_FT = 1
MAX_PLANNED_ALTITUDE_FT = 2000
# The effective ceiling of a flight that cites no authorization.
DEFAULT_EFFECTIVE_CEILING_FT = 400

MIN_LATITUDE = -90.0
MAX_LATITUDE = 90.0
MIN_LONGITUDE = -180.0
MAX_LONGITUDE = 180.0

# ---------------------------------------------------------------------------
# Accident reserve and settlement
# ---------------------------------------------------------------------------

PROVISIONAL_DAMAGE_MULTIPLIER = "1.25"
INJURY_RESERVE_CENTS = {"NONE": 0, "MINOR": 250000, "SERIOUS": 1500000}

COINSURANCE_RATE = "0.85"
SURCHARGE_TIER_1_MAX_CENTS = 500000
SURCHARGE_TIER_2_MAX_CENTS = 2000000
SURCHARGE_TIER_2_RATE = "0.02"
SURCHARGE_TIER_3_RATE = "0.05"

MAX_REMEDIATION_ROUNDS = 2

# ---------------------------------------------------------------------------
# Risk score and enforcement
# ---------------------------------------------------------------------------

RISK_WEIGHT_INCIDENT = 25
RISK_WEIGHT_EXCEEDANCE = 15
RISK_WEIGHT_OPEN_ACCIDENT = 30
RISK_WEIGHT_LAPSED = 10
RISK_CREDIT_CLEAN_FLIGHT = 5
MIN_RISK_SCORE = 0
MAX_RISK_SCORE = 100

# Suspension fires when the recomputed risk_score reaches 70; the comparison is
# inclusive, so exactly 70 suspends.
RISK_SUSPENSION_THRESHOLD = 70
AUTOMATIC_SUSPENSION_REASON = "RISK_THRESHOLD_REACHED"

# ---------------------------------------------------------------------------
# Blocking findings, sorted ascending by code as the check record reports them
# ---------------------------------------------------------------------------

BLOCKING_FINDING_CODES_SORTED = [
    "AIRCRAFT_NOT_REGISTERED",
    "AUTHORIZATION_NOT_APPROVED",
    "CURRENCY_LAPSED",
    "REMOTE_ID_INVALID",
    "TFR_TOTAL_BAN",
    "TFR_UNACKNOWLEDGED",
    "WAIVER_MISSING",
]
