"""Domain constants - every literal transcribed from PRD.md sections 2 and 3.

Nothing in this module is invented.  Tier floors, discount percentages,
handling fees, priority weights, tier multipliers, labor/trip/SLA rates,
response windows, PM quotas, parts coverage, monthly values, the
early-termination rate, the credit line, transit days, the engineer daily
capacity, the PM spacing rule, the renewal windows, the trailing-spend
window and the logical clock's startup instant each appear verbatim in the
PRD passage the block below cites.
"""

from decimal import Decimal, ROUND_HALF_UP

# --- Routing ---------------------------------------------------------------
API_PREFIX = "/lab"

# --- Logical clock (PRD section 2.4) ---------------------------------------
# Startup default reads exactly 2026-09-01T00:00:00Z and never falls back
# to wall-clock; the clock moves only through the clock-setting endpoint.
CLOCK_START_UTC = "2026-09-01T00:00:00Z"
# Standard fixture coverage window: clock start through clock start + 12
# months, the span every renewal recipe extends by another 12 months.
DEFAULT_WINDOW_START = "2026-09-01T00:00:00Z"
DEFAULT_WINDOW_END = "2027-09-01T00:00:00Z"
RENEWAL_EXTENSION_MONTHS = 12

# --- Pagination (PRD section 2.3) ------------------------------------------
PAGE_LIMIT_DEFAULT = 10
PAGE_LIMIT_MIN = 1
PAGE_LIMIT_MAX = 100
PAGE_OFFSET_DEFAULT = 0

# --- Enterprise agreement volume tiers (PRD section 3.2) --------------------
TRAILING_WINDOW_DAYS = 365
SILVER_FLOOR_CENTS = 10000000
GOLD_FLOOR_CENTS = 50000000
PLATINUM_FLOOR_CENTS = 200000000
EA_EXPIRING_WINDOW_DAYS = 60
EA_DISCOUNT_PCT = {"BASE": 0, "SILVER": 5, "GOLD": 10, "PLATINUM": 15}

# --- Order pricing and shipping (PRD section 3.6) ----------------------------
SHIPPING_CLASS_PRECEDENCE = ["CONTROLLED", "HAZARDOUS", "COLD_CHAIN", "STANDARD"]
HANDLING_FEE_CENTS = {
    "STANDARD": 0,
    "COLD_CHAIN": 4500,
    "HAZARDOUS": 7500,
    "CONTROLLED": 9500,
}
TRANSIT_DAYS = {"STANDARD": 3, "COLD_CHAIN": 1, "HAZARDOUS": 5, "CONTROLLED": 4}

# --- Surge allocation scoring (PRD section 3.7) ------------------------------
PRIORITY_WEIGHT = {"CRITICAL": 100, "PRIORITY": 50, "STANDARD": 10}
TIER_MULTIPLIER = {"PLATINUM": 2.0, "GOLD": 1.5, "SILVER": 1.2, "BASE": 1.0}

# --- Pull-through projection (PRD section 3.3) -------------------------------
FORWARD_WEIGHT = 0.5

# --- Service contract entitlement tiers (PRD section 3.4) --------------------
RESPONSE_HOURS = {"BRONZE": 72, "SILVER": 48, "GOLD": 24, "PLATINUM": 8}
PM_VISITS_PER_YEAR = {"BRONZE": 1, "SILVER": 2, "GOLD": 4, "PLATINUM": 12}
PARTS_COVERAGE_PCT = {"BRONZE": 0, "SILVER": 50, "GOLD": 90, "PLATINUM": 100}
LOANER_ELIGIBLE_TIERS = ("GOLD", "PLATINUM")
MONTHLY_VALUE_CENTS = {
    "BRONZE": 50000,
    "SILVER": 120000,
    "GOLD": 300000,
    "PLATINUM": 800000,
}
EARLY_TERMINATION_RATE = 0.5
CONTRACT_RENEWAL_WINDOW_DAYS = 30

# --- Service billing and field operations (PRD section 3.5) ------------------
LABOR_RATE_CENTS_PER_HOUR = 18500
TRIP_CHARGE_CENTS = 45000
SLA_CREDIT_PCT = 10
DEFAULT_RESPONSE_HOURS = 72
ENGINEER_DAILY_CAPACITY = 4
PM_MIN_GAP_DAYS = 30

# --- Credit exposure (PRD section 2.8) ---------------------------------------
CREDIT_LIMIT_CENTS = 2000000

# --- Roles (PRD section 2.1, spelled exactly) --------------------------------
ROLE_PLATFORM_ADMIN = "PlatformAdmin"
ROLE_ACCOUNT_MANAGER = "AccountManager"
ROLE_LAB_PROCUREMENT = "LabProcurement"
ROLE_SERVICE_DISPATCHER = "ServiceDispatcher"
ROLE_FIELD_ENGINEER = "FieldEngineer"
ROLE_SUPPLY_OPS = "SupplyOps"


def round_half_up(value):
    """Round a Decimal-compatible value to the nearest integer, half up."""
    return int(Decimal(str(value)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
