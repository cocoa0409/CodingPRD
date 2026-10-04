"""Domain thresholds and literal constants named by the PRD's calculations.

Every value here is quoted from the PRD prose so that tests can express
boundary arithmetic (``THRESHOLD - 1``, ``THRESHOLD``, ``THRESHOLD + 1``)
without re-deriving magic numbers.  Money is always an integer number of cents.
"""

# ─── Logical clock (PRD §2.5) ─────────────────────────

#: The logical clock reads exactly this on server startup and never falls back
#: to the host's system time.
CLOCK_START_ISO = "2026-09-01T00:00:00Z"
CLOCK_START_DATE = "2026-09-01"

# ─── Pagination (PRD §2.3) ────────────────────────────

DEFAULT_PAGE_LIMIT = 10
MIN_PAGE_LIMIT = 1
MAX_PAGE_LIMIT = 100
DEFAULT_PAGE_OFFSET = 0

# ─── Order price quote (PRD §3.1) ─────────────────────

LINE_SURCHARGE_CENTS = 25000
LABOR_RATE_CENTS_PER_BUILD_HOUR = 45000
CHANGE_FEE_PER_ENDORSEMENT_CENTS = 15000
FEE_CAP_PCT_OF_UNROUNDED = 8

#: The forecast basis applies while the order is still DRAFT and the current
#: date is more than this many days past ``order_date``.
FORECAST_LOCK_HORIZON_DAYS = 120
#: Forecast uplift applied to WHEELSET / CASTING unit costs once the lock
#: horizon has lapsed: cost * 110 / 100, rounded up to a whole cent.
WHEELSET_CASTING_LAPSE_UPLIFT_PCT = 110
#: Forecast uplift applied to COATING unit costs when the supplier lead time
#: exceeds the threshold: cost * 104 / 100, rounded up to a whole cent.
COATING_LONG_LEAD_UPLIFT_PCT = 104
COATING_LONG_LEAD_THRESHOLD_DAYS = 60

# ─── Lead-time feasibility gate (PRD §3.1) ────────────

#: Only these component classes gate the order-to-delivery horizon.
GATED_COMPONENT_CLASSES = ("WHEELSET", "CASTING")

# ─── Capital allocation (PRD §3.4) ────────────────────

RETAINED_CAR_EQUITY_BPS = 700
EQUITY_BPS_CEILING = 900
BPS_DIVISOR = 10000

# ─── Per-diem accrual (PRD §3.6) ──────────────────────

UTILIZATION_CREDIT_PCT = 12
MILES_PER_UTILIZATION_POINT = 100
#: The restated basis clips each interval to the window from this many days
#: before the current clock date up to (not including) the current clock date.
RESTATEMENT_WINDOW_DAYS = 365

# ─── Mileage true-up (PRD §3.7) ───────────────────────

MILEAGE_OVERAGE_RATE_CENTS = 12
DAYS_PER_ALLOWANCE_BLOCK = 30

# ─── Maintenance burden allocation (PRD §3.7) ─────────

CONDITION_PARTS_CENTS = {"A": 0, "B": 200000, "C": 400000, "D": 600000}
LESSEE_PARTS_SHARE_PCT = 1
LESSEE_PARTS_SHARE_PCT_CEILING = 5

# ─── Retrofit economics (PRD §3.8) ────────────────────

RETROFIT_ALLOWANCE_CENTS = 2500000
RETROFIT_SHOP_DAY_RATE_CENTS = 185000

# ─── Sale gain / loss and fleet depreciation (PRD §3.9) ───

DAILY_DEPRECIATION_CENTS = 2500

# ─── Placement buffering (PRD §3.6) ───────────────────

#: A one-day buffer is required between placements of the same car, so a new
#: ``start_date`` must be at least this many days after a prior ``end_date``.
PLACEMENT_BUFFER_DAYS = 2

# ─── Factory / fixture defaults ───────────────────────

TEST_DEFAULTS = {
    # Catalogue
    "CAR_TYPE_MODEL_CODE": "BOX-100",
    "CAR_TYPE_CAR_CLASS": "BOXCAR",
    "CAR_TYPE_BUILD_HOURS": 10,
    "CAR_TYPE_LIFE_YEARS": 25,
    "CAR_TYPE_LINE_FAMILY": "LINE-A",
    "COMPONENT_WHEELSET_PART_NUMBER": "WS-200",
    "COMPONENT_CASTING_PART_NUMBER": "CS-200",
    "COMPONENT_COATING_PART_NUMBER": "CT-200",
    "COMPONENT_WHEELSET_UNIT_COST_CENTS": 200000,
    "COMPONENT_CASTING_UNIT_COST_CENTS": 50000,
    "COMPONENT_COATING_UNIT_COST_CENTS": 25000,
    "COMPONENT_LEAD_TIME_DAYS": 10,
    "COMPONENT_ON_HAND_QTY": 1000,
    "BOM_WHEELSET_QTY_PER_CAR": 4,
    "BOM_CASTING_QTY_PER_CAR": 2,
    "BOM_COATING_QTY_PER_CAR": 1,
    # Commercial
    "LESSEE_LEGAL_NAME": "Acme Rail Leasing",
    "LESSEE_CREDIT_TIER": "A",
    "LESSEE_UTILIZATION_THRESHOLD_PCT": 80,
    "LESSEE_CREDIT_CEILING_CENTS": 500_000_000,
    "CONTRACT_PER_DIEM_RATE_CENTS": 20000,
    "CONTRACT_LEASE_TYPE": "FULL_SERVICE",
    "CONTRACT_LIABILITY_BEARER": "LESSOR",
    "CONTRACT_TERM_START_DATE": "2026-09-01",
    "CONTRACT_TERM_END_DATE": "2028-09-01",
    "CONTRACT_FLEET_CAR_CAP": 100,
    # Backlog
    "ORDER_QUANTITY": 1,
    "ORDER_DISPOSITION": "RETAINED",
    "ORDER_PRIORITY_RANK": 1,
    "ORDER_ORDER_DATE": "2026-09-01",
    "ORDER_REQUIRED_DELIVERY_DATE": "2026-12-01",
    # Placement
    "ASSIGNMENT_START_DATE": "2026-09-10",
    "ASSIGNMENT_END_DATE": "2026-10-10",
    "ASSIGNMENT_MILEAGE_ALLOWANCE": 1000,
    # Retrofit
    "PROGRAM_MANDATE_CODE": "MAND-2026-01",
    "PROGRAM_COMPLIANCE_DEADLINE_DATE": "2027-06-30",
    "PROGRAM_REQUIRED_SHOP_DAYS_PER_CAR": 10,
    "WORK_ORDER_SHOP_LINE": "SHOP-L1",
    # Sale
    "SALE_BUYER_NAME": "Secondary Market Buyer",
    "SALE_WRITEBACK_LIABILITY_CENTS": 0,
}
