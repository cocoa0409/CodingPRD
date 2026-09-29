"""Domain constants for the Interlibrary Loan & Resource Sharing API test suite.

Every value here is a literal fixed by the PRD. Money is always integer cents.
"""

# --- Logical clock -----------------------------------------------------------
# "Its value at startup is exactly `2026-08-01T00:00:00Z`"
CLOCK_START_ISO = "2026-08-01T00:00:00Z"
CLOCK_START_INSTANT = "2026-08-01T00:00:00.000Z"

# --- Pagination --------------------------------------------------------------
DEFAULT_LIMIT = 10
DEFAULT_OFFSET = 0
MIN_LIMIT = 1
MAX_LIMIT = 100

# --- Patron defaults ---------------------------------------------------------
DEFAULT_MAX_OPEN_REQUESTS = 5
DEFAULT_MAX_CONCURRENT_LOANS = 3
DEFAULT_UNPAID_BALANCE_CAP_CENTS = 5000

# --- Standing score ----------------------------------------------------------
STANDING_WEIGHT_LOST = 25
STANDING_WEIGHT_DAMAGED = 12
STANDING_WEIGHT_LATE_RETURN = 6
STANDING_WEIGHT_UNCLAIMED = 8
STANDING_UNPAID_CENTS_PER_POINT = 1000
STANDING_BLOCK_THRESHOLD = 40
STANDING_FINAL_OVERDUE_IN_CUSTODY_POINTS = 6
STANDING_FINAL_ON_TIME_RETURN_POINTS = -4
STANDING_SCORE_MIN = 0
STANDING_SCORE_MAX = 100

# --- Copyright ---------------------------------------------------------------
CONTU_FREE_FILL_ALLOWANCE = 5
COPYRIGHT_RECENCY_WINDOW_YEARS = 5
ROYALTY_FLOOR_CENTS = 1500
ROYALTY_BASE_CENTS = 800
ROYALTY_PER_PAGE_CENTS = 65

# --- Rota / sourcing ---------------------------------------------------------
DEFAULT_MAX_ATTEMPTS = 3
DEFAULT_AUTO_ESCALATE_POD = False
DEFAULT_OFFER_RESPONSE_HOURS = 48
LATE_DAY_PENALTY_CENTS = 250
IMBALANCE_PENALTY_CENTS = 1500
DEFAULT_BALANCE_TOLERANCE_ITEMS = 3
DEFAULT_CAPPED_WAIVER_CENTS = 0

# --- Pricing -----------------------------------------------------------------
RUSH_SURCHARGE_CENTS = 1200
RUSH_DAYS_AVAILABLE_THRESHOLD = 3
SUBSIDY_CAP_CENTS = 4000
SUBSIDY_TIER_1_MAX_GROSS = 2000  # <= 2000 -> 0.80
SUBSIDY_TIER_2_MAX_GROSS = 6000  # 2001..6000 -> 0.60
SUBSIDY_TIER_3_MAX_GROSS = 12000  # 6001..12000 -> 0.40
SUBSIDY_RATE_TIER_1 = 0.80
SUBSIDY_RATE_TIER_2 = 0.60
SUBSIDY_RATE_TIER_3 = 0.40
SUBSIDY_RATE_TIER_4 = 0.25

# --- Loans -------------------------------------------------------------------
PICKUP_SHELF_DAYS = 7
RENEWAL_EXTENSION_DAYS = 14
MAX_TOTAL_LOAN_DAYS = 84
DEFAULT_REPLACEMENT_COST_CENTS = 7500
LENDER_PROCESSING_FEE_CENTS = 2500
DEFAULT_RECALL_GRACE_DAYS = 7

# --- Overdue fine ------------------------------------------------------------
OVERDUE_FINE_PER_DAY_CENTS = 150
OVERDUE_GRACE_DAYS = 2
OVERDUE_FINE_CAP_CENTS = 6000
RECALL_BREACHED_FINE_MULTIPLIER = 3

# --- Electronic delivery -----------------------------------------------------
DELIVERY_WINDOW_DAYS = 30
DELIVERY_MAX_DOWNLOADS = 3

# --- Transit / sweep ---------------------------------------------------------
TRANSIT_WRITE_OFF_DAYS = 14

# --- Invoicing ---------------------------------------------------------------
CONSORTIUM_SURCHARGE_RATE = 0.075

# --- Ops-run summary counters ------------------------------------------------
OPS_RUN_COUNTER_FIELDS = (
    "agreements_expired",
    "offers_expired",
    "recalls_breached",
    "pickups_abandoned",
    "deliveries_expired",
    "shipments_lost",
    "requests_escalated",
    "requests_unfilled",
    "patrons_blocked",
)

# --- Common resource properties ---------------------------------------------
COMMON_FIELDS = ("id", "created_at", "updated_at", "version")
NOTIFICATION_FIELDS = ("id", "created_at")
