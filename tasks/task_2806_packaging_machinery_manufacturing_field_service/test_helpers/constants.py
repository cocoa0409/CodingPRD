"""Domain thresholds and numeric constants taken from the PRD's calculations."""

# --- Logical clock (PRD §2.5) -------------------------------------------
CLOCK_START_UTC = "2026-08-01T00:00:00Z"
CLOCK_START_DATE = "2026-08-01"

# --- Order roll-up (PRD §3.3) ------------------------------------------
DISCOUNT_TIER_FLOORS_CENTS = {"T3": 150_000_000, "T2": 75_000_000, "T1": 25_000_000}
COMMISSIONING_FEE_PCT = {"NONE": 6.00, "T1": 5.00, "T2": 4.00, "T3": 3.00}

# --- Product trials (PRD §3.2) -----------------------------------------
TRIAL_STANDARD_FLOOR_PCT = 90.00
TRIAL_HEAVY_DUTY_FLOOR_PCT = 75.00
TRIAL_RETEST_CEILING = 2

# --- Acceptance testing (PRD §3.5) -------------------------------------
FAT_MIN_CONTAINERS = 500
SAT_MIN_CONTAINERS = 200
REWORK_DAYS_PER_FAILURE = 7
FAT_FAILURE_ABANDON_COUNT = 3
PRODUCT_ADJUSTED_REFERENCE_FLOOR_CPM = 1

# --- Format kits (PRD §3.7) --------------------------------------------
KIT_LEAD_TIME_CAP_DAYS = 180
KIT_PARTS_PER_ASSEMBLY_DAY = 4
KIT_FAMILY_CHANGE_ALLOWANCE_DAYS = 10
KIT_SAME_FAMILY_ALLOWANCE_DAYS = 3
KIT_OUT_OF_RANGE_ALLOWANCE_DAYS = 15
KIT_MINIMUM_LEAD_DAYS = 5
KIT_MARKUP_PCT = 17.50
KIT_ENGINEERING_FEE_CENTS = 120_000

# --- Spare-parts stocking (PRD §3.7) ----------------------------------
STOCKING_DAYS_PER_YEAR = 365
STOCKING_REVIEW_PERIOD_DAYS = 30
OBSOLESCENCE_MULTIPLIER = {
    "ACTIVE": 1.00,
    "NOTICE_ISSUED": 1.50,
    "LAST_TIME_BUY": 3.00,
    "OBSOLETE": 0.00,
}
LEAD_TIME_DEMAND_SAFETY_FACTOR = {"A": 0.50, "B": 0.25, "C": 0.10}
SERVICE_LEVEL_FACTOR = {"A": 1.60, "B": 1.30, "C": 1.05}

# --- Service contracts and goodwill (PRD §3.8, §3.9) -------------------
RESTRICT_THRESHOLD_CENTS = 50_000
TIER_GOODWILL_SHARE_PCT = {"BRONZE": 50.00, "SILVER": 75.00, "GOLD": 100.00}

# --- Warranty claims (PRD §3.9) ----------------------------------------
MACHINE_DEFECT_FLOOR_PCT = 80.00
PRODUCT_VARIATION_CEILING_PCT = 20.00
VARIATION_TOLERANCE_PCT = 5.00

# --- Test scenario defaults --------------------------------------------
TEST_DEFAULTS = {
    "CUSTOMER_LEGAL_NAME": "Northwind Beverages",
    "REGION_CODE": "NA",
    "PRODUCT_VARIATION_PCT": 4.00,
    "MODEL_CODE": "FL-600",
    "MACHINE_FAMILY": "FILLER",
    "NAMEPLATE_RATE_CPM": 600,
    "GUARANTEE_EFFICIENCY_PCT": 90.00,
    "BASE_PRICE_CENTS": 68_000_000,
    "MIN_CONTAINER_DIAMETER_MM": 60,
    "MAX_CONTAINER_DIAMETER_MM": 110,
    "LINE_CODE": "LINE-A",
    "CHANGEOVER_BUFFER_DAYS": 5,
    "CAPACITY_DAYS_PER_QUARTER": 120,
    "ENGINEER_NAME": "Dana Reyes",
    "PRODUCT_NAME": "Sparkling Cider",
    "CONTAINER_FAMILY": "PET_ROUND",
    "CONTAINER_DIAMETER_MM": 82,
    "EQUIPMENT_PRICE_CENTS": 70_000_000,
    "CHANGE_PARTS_PRICE_CENTS": 3_000_000,
    "SLOT_START_DATE": "2026-08-06",
    "REQUESTED_SLOT_DAYS": 20,
    "FAT_SCHEDULED_ON": "2026-08-26",
    "SAT_SCHEDULED_ON": "2026-08-27",
    "SERIAL_NUMBER": "SN-2806-001",
    "CONTRACT_START_DATE": "2026-08-01",
    "CONTRACT_END_DATE": "2027-07-31",
}
