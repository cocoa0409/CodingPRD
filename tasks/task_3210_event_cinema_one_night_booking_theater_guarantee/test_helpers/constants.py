"""Domain thresholds and numeric constants from the PRD's calculation rules."""

# --- Logical clock (PRD §2.8) ------------------------------------------------
DEFAULT_CLOCK = "2026-09-01T00:00:00Z"
CLOCK_STARTUP = "2026-09-01T00:00:00Z"

# --- Guarantee ceiling derivation (PRD §3.2) ---------------------------------
BASE_RATE_A_CENTS = 45000
BASE_RATE_B_CENTS = 35000
BASE_RATE_C_CENTS = 25000
VOLUME_TIER_1_MAX = 50
VOLUME_TIER_2_MAX = 150
VOLUME_TIER_3_MAX = 400
VOLUME_FACTOR_1 = 1.00
VOLUME_FACTOR_2 = 0.90
VOLUME_FACTOR_3 = 0.80
VOLUME_FACTOR_4 = 0.70
ADMISSION_MULTIPLE = 12

# --- Presale checkpoint (PRD §3.3) -------------------------------------------
CHECKPOINT_OFFSET_DAYS = 14

# --- Delivery lead verification (PRD §3.4) -----------------------------------
LEAD_HOURS_SATELLITE = 48
LEAD_HOURS_FILE = 24
LEAD_HOURS_BOTH = 48
LIVE_EVENT_SURCHARGE_HOURS = 12

# --- Make-good credit derivation (PRD §3.5) ----------------------------------
RATE_TIER_1_MIN_MINUTES = 90
RATE_TIER_2_MIN_MINUTES = 30
RATE_TIER_3_MIN_MINUTES = 5
RATE_TIER_1 = 1.00
RATE_TIER_2 = 0.60
RATE_TIER_3 = 0.25
RATE_TIER_4 = 0.00
CAP_FRACTION = 0.5

# --- Settlement split (PRD §3.6) ---------------------------------------------
ALLOCATION_ORDER_TERMS = ["NET_30", "NET_60"]
NET_OFF_TOP_TERMS = ["GROSS_ON_GROSS", "FOUR_WALL"]
GATE_RATIO_MAX_TIER = 1.5
GATE_RATIO_MID_TIER = 1.0
PAYMENT_RATE_TIER_1 = 1.00
PAYMENT_RATE_TIER_2 = 0.75
PAYMENT_RATE_TIER_3 = 0.50

# --- Encore price derivation (PRD §3.7) --------------------------------------
ABSOLUTE_DISCOUNT_CENTS = 500
RELATIVE_DISCOUNT = 0.55
ENCORE_ELIGIBILITY_RATIO_MIN = 0.5

# --- Pagination (PRD §2.3) ---------------------------------------------------
PAGINATION_DEFAULT_LIMIT = 10
PAGINATION_MIN_LIMIT = 1
PAGINATION_MAX_LIMIT = 100

# --- Common test defaults ----------------------------------------------------
TEST_DEFAULTS = {
    "GUARANTEE_CENTS": 1000000,
    "REVENUE_SHARE_PCT": 0.40,
    "TICKET_PRICE_CENTS": 1500,
    "SHOWTIME_DATE": "2026-12-01T00:00:00Z",
    "SHOWTIME_START_MINUTE": 1140,      # 19:00 UTC
    "SHOWTIME_END_MINUTE": 1260,        # 21:00 UTC
    "ON_SALE_AT": "2026-10-01T00:00:00Z",
    "RIGHTS_START": "2026-09-01T00:00:00Z",
    "RIGHTS_END": "2027-06-01T00:00:00Z",
}