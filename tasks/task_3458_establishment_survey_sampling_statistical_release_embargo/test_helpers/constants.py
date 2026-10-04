"""Domain thresholds — numeric constants pinned by PRD prose.

Every value here is stated in the PRD (program defaults, Neyman allocation
dispersion proxies, suppression thresholds, burden accounting, temporal
spacings, factor-set bounds, pagination, and the logical-clock startup
reading). Tests import these instead of hard-coding literals.
"""

# --- Logical clock -----------------------------------------------------------
# PRD: "At server startup the clock reads exactly 2026-09-01T00:00:00Z"
CLOCK_STARTUP_DEFAULT = "2026-09-01T00:00:00Z"

# --- SurveyProgram config (PRD 3.1) ------------------------------------------
# embargo_window_minutes defaults to 30, range 1..1440
DEFAULT_EMBARGO_WINDOW_MINUTES = 30
EMBARGO_WINDOW_MINUTES_MIN = 1
EMBARGO_WINDOW_MINUTES_MAX = 1440
# annual_burden_budget_minutes defaults to 120, never below 15
DEFAULT_ANNUAL_BURDEN_BUDGET_MINUTES = 120
MIN_ANNUAL_BURDEN_BUDGET_MINUTES = 15
# sample_budget must be at least 2
MIN_SAMPLE_BUDGET = 2

# --- Neyman stratum allocation (PRD 3.1) --------------------------------------
SIZE_DISPERSION_SMALL = 4
SIZE_DISPERSION_MEDIUM = 15
SIZE_DISPERSION_LARGE = 50
MIN_STRATUM_SAMPLE = 2

# --- Estimation / response rates (PRD 3.5) ------------------------------------
MIN_CELL_RESPONDENTS = 3
DOMINANCE_THRESHOLD = 0.60
MIN_WEIGHTED_RESPONSE_RATE = 0.600000
RATE_PRECISION_DECIMALS = 6

# --- Burden ledger and follow-up protocol (PRD 3.4) ---------------------------
BURDEN_MINUTES_PER_SUBMISSION = 15
CONTACT_MINUTES_MIN = 1
CONTACT_MINUTES_MAX = 480
FOLLOW_UP_SPACING_HOURS = 24
ESCALATION_MIN_CONTACTS = 2
ESCALATION_AGE_DAYS = 7

# --- Collection window (PRD 3.3) ----------------------------------------------
COLLECTION_OPEN_DAY = 1
COLLECTION_CLOSE_DAY = 20

# --- Release calendar (PRD 2.9) ------------------------------------------------
PREANNOUNCE_LEAD_DAYS = 3

# --- Seasonal factor sets (PRD 3.6) --------------------------------------------
SEASONAL_FACTOR_COUNT = 12
SEASONAL_FACTOR_MIN = 0.2
SEASONAL_FACTOR_MAX = 5.0
SEASONAL_FACTOR_MEAN_TARGET = 1.0
SEASONAL_FACTOR_MEAN_TOLERANCE = 0.0005

# --- Methodology reconstruction (PRD 3.8) ---------------------------------------
PPM_BASELINE = 1_000_000  # reconstruction_factor_ppm of 1,000,000 = no change

# --- Pagination (PRD 2.3) --------------------------------------------------------
PAGINATION_DEFAULT_LIMIT = 10
PAGINATION_MIN_LIMIT = 1
PAGINATION_MAX_LIMIT = 100
PAGINATION_DEFAULT_OFFSET = 0

# --- Common derived instants -----------------------------------------------------
def collection_open_instant(reference_month: str) -> str:
    """First day of the reference month at 00:00:00Z (YYYY-MM input)."""
    return f"{reference_month}-01T00:00:00Z"


def collection_close_passed_instant(reference_month: str) -> str:
    """First instant strictly after the collection close (20th 23:59:59Z)."""
    return f"{reference_month}-21T00:00:00Z"
