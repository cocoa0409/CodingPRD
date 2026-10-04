"""Domain thresholds and shared test values.

All monetary amounts are integer cents; surges and shares are integer basis
points, where ten thousand basis points equal one times the base.
"""

# --- Named thresholds ---

# Four tenths of one hundred percent of the house, expressed in basis points.
MARKET_RUSH_SHARE_CAP_BP = 4000

# Demand surge contributions and their cap.
SURGE_CAP_BP = 5000
SURGE_A_BP = 2500
SURGE_B_BP = 1500
SURGE_C_BP = 1000
SURGE_A_MIN_ACTIVE_ORDERS = 12
SURGE_B_MIN_RELEASED_OFF = 0.90
SURGE_C_MIN_FILL = 0.80
SURGE_BASE_BP = 10000

# Group concession on an order line.
GROUP_MIN_QUANTITY = 4
GROUP_DISCOUNT_BP = 1000

# Refund processing fee and the half-value ratio.
REFUND_PROCESSING_FEE_CENTS = 200
HALF_VALUE_NUMERATOR = 1
HALF_VALUE_DENOMINATOR = 2

# Exchange fee band and cap.
EXCHANGE_FEE_CAP_CENTS = 500
FREE_EXCHANGE_HOURS_BEFORE_START = 24
DOUBLED_FEE_HOURS_BEFORE_START = 2
DOUBLE_FEE_MULTIPLIER = 2

# Queue admission quota.
QUOTA_NUMERATOR = 1
QUOTA_DENOMINATOR = 2
QUOTA_FLOOR_MIN_CAP = 2
ADMISSION_WINDOW_MINUTES = 20

# Draw waitlist depth and the patron cost model.
WAITLIST_MULTIPLIER = 2
COST_FORFEIT = 1
COST_PURCHASE = 0.25
VIOLATION_CEILING = 2

# Reconciliation tolerance and the default handoff model.
VARIANCE_TOLERANCE_COUNT = 0
DEFAULT_HANDOFF_MODEL = "MOBILE_PUSH"

# --- Logical clock and shared instants ---

CLOCK_START = "2026-09-01T00:00:00Z"
BASE_CLOCK = "2026-09-12T09:00:00Z"
BASE_CLOCK_DAY = "2026-09-12"
PREV_CLOCK = "2026-09-11T09:00:00Z"
PREV_CLOCK_DAY = "2026-09-11"
PERFORMANCE_START = "2026-10-05T19:00:00Z"

# --- Shared test values ---

TEST_DEFAULTS = {
    "REFUND_WINDOW_HOURS": 720,
    "EXCHANGE_FEE_CENTS": 300,
    "MARKET_CODE": "NYC",
    "CITY": "New York",
    "PRODUCTION_TITLE": "Test Play",
    "PRODUCER_ORG": "Test Partners",
    "VENUE_NAME": "Test Theatre",
    "FACE_VALUE_CENTS": 10_000,
    "TOTAL_SEAT_CAPACITY": 30,
    "DAILY_QUANTITY": 6,
    "DISCOUNT_PCT": 0.5,
    "RELEASE_TIME_LOCAL": "09:00",
    "PER_ORDER_LIMIT": 2,
    "CLAIM_WINDOW_MINUTES": 30,
}

# --- Literal expected values pinned by the design index ---

# per_seat_price, round_per_step: face 19990, discount 0.05, surge 1500 bp.
PER_SEAT_PRICE_ROUND_PER_STEP_UNIT_CENTS = 21840
PER_SEAT_PRICE_ROUND_ONCE_UNIT_CENTS = 21839

# purchase_line_subtotal, discount_after_quantity: unit 8385 against quantity 4.
SUBTOTAL_UNIT_CENTS = 8385
SUBTOTAL_GROUP_DISCOUNTED_CENTS = 30186
SUBTOTAL_DISCOUNT_BEFORE_QUANTITY_CENTS = 30188

# rush_daily_release_cap with a 7 seat house.
MARKET_CAP_SEVEN_SEAT_HOUSE = 2

# demand_surge_bp boundary: a five seat epoch prices its four-seat order with a
# fill fraction of exactly 0.80 (no surge), and its follow-up single seat at 1.00.
SURGE_BOUNDARY_UNIT_AT_080_CENTS = 18991
SURGE_BOUNDARY_UNIT_AT_100_CENTS = 20890

# refund_amount, per_purchase: the four-ticket subtotal 61171 is returned whole
# while the window is open; the per-ticket variant reaches 61172.
REFUND_PER_PURCHASE_AMOUNT_CENTS = 61171
REFUND_PER_TICKET_AMOUNT_CENTS = 61172
REFUND_HALF_VALUE_WHOLE_SUBTOTAL_CENTS = 4193
REFUND_HALF_VALUE_PER_TICKET_CENTS = 4196

# exchange_cost split for a recalled 10000 on a target priced at the same rate.
EXCHANGE_QUOTE_FEE_CENTS = 500
EXCHANGE_QUOTE_VALUE_RETURNED_CENTS = 9500
EXCHANGE_APPLIED_REFUNDED_CENTS = 1000

# A stable, syntactically valid but unminted identifier.
NON_EXISTENT_PERFORMANCE_ID = "00000000-0000-4000-8000-000000000000"