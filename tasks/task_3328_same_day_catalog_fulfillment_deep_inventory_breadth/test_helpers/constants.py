"""Domain constants — thresholds, rates and fixture literals drawn from the PRD."""

import datetime as _dt

# --- Catalog / pricing constants -------------------------------------------------
SMALL_LINE_FEE_RATE = 0.03
CATALOG_DISCOUNT_FACTOR = 0.97
BASE_HANDLING_RATE = 0.10
SMALL_LINE_COUNT_THRESHOLD = 5
SMALL_LINE_COUNT_REDUCTION_CENTS = 250
ORDER_LEVEL_DISCOUNT_RATE = 0.37

# --- Freight constants ------------------------------------------------------------
ZONE_SURCHARGE_CENTS = 275
EARLY_COMMIT_MINUTES = 120
GROUND_SURCHARGE_RATE = 0.00
TWO_DAY_SURCHARGE_RATE = 0.30
OVERNIGHT_SURCHARGE_RATE = 0.60

# --- Damage / restock -------------------------------------------------------------
DAMAGE_VALUE_FACTOR = 0.60
DAMAGE_RATIO_TRIGGER_CENTS = 10000
RESTOCK_CAP_UNITS = 5
RESTOCK_RATIO_START = 0.80
RESTOCK_RATIO_STEP = 0.30

# --- Positioning / selection ------------------------------------------------------
POSITIONING_SKU_THRESHOLD = 2
SECONDS_PER_DAY = 86400
REGION_CROSS_PENALTY_SECONDS = 28800
RESTRICTED_RESERVE_RATIO = 0.90

# --- Pipe-length commitment -------------------------------------------------------
UNIT_MM_PER_FOOT = 304.8
WIP_STOCK_MM = 182880.0
FINISHED_STOCK_MM = 121920.0
WIP_STOCK_FEET = 600
FINISHED_STOCK_FEET = 400

# --- The logical clock ------------------------------------------------------------
CLOCK_START_UTC = "2026-09-01T00:00:00Z"
# 2026-09-14 is a Monday.
MONDAY_EARLY_UTC = "2026-09-14T08:00:00Z"      # BOS local 04:00, DAL local 03:00
MONDAY_EARLY_BEFORE_CUTOFF_UTC = "2026-09-14T09:00:00Z"  # BOS local 05:00
MONDAY_AFTER_CUTOFF_UTC = "2026-09-14T10:05:00Z"         # BOS local 06:05

# Days the logical clock is advanced to, for promise-date scenarios.
DAY_AFTER_CLOCK = "2026-09-15T10:05:00Z"
TWO_DAYS_AFTER_CLOCK = "2026-09-16T10:05:00Z"

# --- Reusable payload literals ----------------------------------------------------
TEST_DEFAULTS = {
    "CODE": "BOS",
    "REGION": "NORTHEAST",
    "LOCAL_ZONE": "America/New_York",
    "LOCAL_CUTOFF_TIME": "06:00:00",
    "UTC_OFFSET_MINUTES": -240,
    "INBOUND_CAPACITY_UNITS": 900,
    "TRANSIT_SECONDS": 86400,
    "ACCOUNT_NAME": "Riverside Machine",
    "DELIVERY_ZONE": "America/New_York",
    "HOME_REGION": "NORTHEAST",
    "SUPPLIER_NAME": "Long Tail Fasteners",
    "MIN_STOCK_COMMITMENT_UNITS": 50,
    "ATTRIBUTE_NAME": "Thread Pitch",
    "ATTRIBUTE_VALUE": "1.25 mm",
    "UNIT_OF_MEASURE": "mm",
    "UNIT_PRICE_CENTS": 1000,
    "UNIT_WEIGHT_KG": 0.10,
    "CURATION_BUNDLE_SIZE": 8,
    "ON_HAND_UNITS": 10,
    "DAILY_DEMAND_UNITS": 2,
    "INBOUND_DAILY_UNITS": 2,
    "SERVICE_LEVEL": "GROUND",
}

# Database phrase used freely by fixtures and tests.
EMPTY_DB = "the server starts each test against an empty database"


def dc_local_time(utc_iso: str, utc_offset_minutes: int) -> str:
    """Local wall-clock HH:MM:SS for a center at the given offset."""
    base = _dt.datetime.strptime(utc_iso, "%Y-%m-%dT%H:%M:%SZ")
    local = base + _dt.timedelta(minutes=utc_offset_minutes)
    return local.strftime("%H:%M:%S")


def boston_local_time(utc_iso: str = MONDAY_AFTER_CUTOFF_UTC) -> str:
    """Local wall-clock time of the BOS center (UTC-240)."""
    return dc_local_time(utc_iso, TEST_DEFAULTS["UTC_OFFSET_MINUTES"])