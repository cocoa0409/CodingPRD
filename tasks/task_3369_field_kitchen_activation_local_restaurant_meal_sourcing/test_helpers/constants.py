"""Domain thresholds and fixture defaults taken from the PRD's stated constants."""

# --- Logical clock -----------------------------------------------------------
DEFAULT_CLOCK_ISO = "2026-09-01T00:00:00Z"

# --- Assessment feeding priority --------------------------------------------
ACCESS_WEIGHT = {
    "OPEN": 10,
    "LIMITED": 25,
    "RESTRICTED": 40,
    "BLOCKED": 55,
}
WATER_MISSING_PENALTY = 20
POWER_MISSING_PENALTY = 15
PARTNER_BASE = 25
PARTNER_STEP = 5
DURABLE_INFRA_DIVISOR = 2
DURABLE_PARTNER_MULTIPLIER = 2
DURABLE_PARTNER_CAP = 40
PRIORITY_SCORE_CAP = 100

# --- Field kitchen food safety score ----------------------------------------
POWER_POINTS = {"GRID": 40, "GENERATOR": 30, "SOLAR": 20, "NONE": 0}
WATER_POINTS = {"PIPED": 35, "TRUCKED": 25, "WELL": 15, "NONE": 0}
REFRIGERATION_FULL_HOURS = 12
REFRIGERATION_PARTIAL_HOURS = 6
COLD_SCORE_FULL = 25
COLD_SCORE_PARTIAL = 15
MIN_VIABLE_CAPACITY_MEALS = 500
CAPACITY_PENALTY = 10
FOOD_SAFETY_CLEARANCE_MIN = 70

# --- Meal order cost buildup -------------------------------------------------
LOGISTICS_FEE_RATE = 0.03
TIER_BULK_MIN_CENTS = 2_000_000
TIER_STANDARD_MIN_CENTS = 800_000
TIER_RATE_BULK = 0.08
TIER_RATE_STANDARD = 0.05
TIER_RATE_SMALL = 0.00

# --- Meal order final settlement --------------------------------------------
QUALITY_MULTIPLIER_HIGH = 1.00
QUALITY_MULTIPLIER_MID = 0.95
QUALITY_MULTIPLIER_LOW = 0.85
QUALITY_MULTIPLIER_VOID = 0.00
QUALITY_SCORE_HIGH_MIN = 90
QUALITY_SCORE_MID_MIN = 75
QUALITY_SCORE_LOW_MIN = 60
QUALITY_SCORE_RELEASE_MIN = 80
QUALITY_REWORK_MAX = 2
QUALITY_HISTORY_WINDOW = 5
QUALITY_WEIGHT_MOST_RECENT = 5

# --- Partner kitchen lifecycle ----------------------------------------------
VETTING_SCORE_MIN = 60
COOLDOWN_HOURS = 8
KITCHEN_WINDOW_REJECTION_BUFFER_HOURS = 8

# --- Delivery runs -----------------------------------------------------------
KITCHEN_DAILY_RUN_CAP = 3

# --- Supplier standing -------------------------------------------------------
SUPPLIER_RELIABILITY_BASE = 50
DELIVERED_PURCHASE_CREDIT = 10
DISPUTED_PURCHASE_PENALTY = 25
SUPPLIER_SUSPENSION_MAX_SCORE = 40
PREFERRED_CASHFLOW_MIN_CENTS = 500_000
PREFERRED_RELIABILITY_MIN = 70

# --- Accountability report ---------------------------------------------------
LOCAL_SOURCING_TARGET_PCT = 30
PCT_SCALE = 100

# --- Fixture defaults --------------------------------------------------------
TEST_DEFAULTS = {
    "INCIDENT_NAME": "Central Valley Floods",
    "COUNTRY_CODE": "US",
    "DISASTER_TYPE": "FLOOD",
    "SEVERITY_LEVEL": 4,
    "TARGET_DAILY_MEALS": 12_000,
    "FUNDING_CEILING_CENTS": 5_000_000,
    "CURRENCY_CODE": "USD",
    "ASSESSED_AT": "2026-09-01T06:00:00Z",
    "POPULATION_AFFECTED": 40_000,
    "ESTIMATED_DAILY_MEAL_NEED": 9_000,
    "ACCESS_CONSTRAINT": "LIMITED",
    "WATER_AVAILABLE": False,
    "POWER_AVAILABLE": True,
    "PARTNER_KITCHENS_IDENTIFIED": 2,
    "SITE_NAME": "Riverside Depot",
    "LATITUDE": 36.75,
    "LONGITUDE": -119.77,
    "POWER_SOURCE": "GENERATOR",
    "WATER_SOURCE": "TRUCKED",
    "REFRIGERATION_HOURS": 12,
    "DAILY_CAPACITY_MEALS": 500,
    "BUSINESS_NAME": "Casa Rosa",
    "OWNER_NAME": "Rosa Delgado",
    "PER_MEAL_PRICE_CENTS": 1500,
    "PARTNER_DAILY_CAPACITY_MEALS": 1200,
    "MENU_NAME": "Arroz con Pollo",
    "ORDERED_MEALS": 1000,
    "SCHEDULED_START": "2026-09-01T08:00:00Z",
    "PRODUCTION_HOURS": 4,
    "PRODUCER_NAME": "Valle Verde Cooperative",
    "LOCALITY": "San Joaquin",
    "DRIVER_NAME": "Ana Ruiz",
    "DRIVER_PHONE": "+15550100",
    "PLANNED_DATE": "2026-09-01T07:00:00Z",
    "WINDOW_START": "2026-09-01T07:00:00Z",
    "WINDOW_END": "2026-09-01T19:00:00Z",
    "FUEL_COST_CENTS": 6000,
    "HANDLING_COST_CENTS": 4000,
    "DONOR_NAME": "Global Relief Fund",
}
