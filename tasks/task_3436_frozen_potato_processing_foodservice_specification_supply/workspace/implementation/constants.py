"""Domain constants for the Frozen Potato Processing API.

All values are read from SCAFFOLD.yaml calculations/roles tables and PRD prose.
Numeric constants that participate in Decimal arithmetic are stored as strings
so they convert to exact Decimals without float noise.
"""

# --- RBAC (PRD section 2.1) ---
ROLES = [
    "PlatformAdmin",
    "GrowerRelationsManager",
    "Grower",
    "StorageOperator",
    "QualityAssuranceLead",
    "ProductionPlanner",
    "AccountManager",
    "ChainCustomer",
    "LogisticsCoordinator",
]
ROLE_SET = set(ROLES)

# --- Enums ---
REGIONS = {"COLUMBIA_BASIN", "SNAKE_RIVER_VALLEY", "RED_RIVER_VALLEY", "MAINE_AROOSTOOK"}
VARIETIES = {"RUSSET_BURBANK", "RANGER_RUSSET", "UMATILLA_RUSSET", "CLEARWATER_RUSSET"}
CUT_FAMILIES = {"STRAIGHT", "CRINKLE", "WEDGE", "SHOESTRING"}
COATING_TYPES = {"NONE", "CLEAR", "SEASONED", "BATTER"}
PRIORITY_TIERS = {"TIER_1_STRATEGIC", "TIER_2_PREFERRED", "TIER_3_STANDARD"}
TIER_ORDER = {"TIER_1_STRATEGIC": 0, "TIER_2_PREFERRED": 1, "TIER_3_STANDARD": 2}
ROUTE_TYPES = {"DIRECT_CHAIN", "DISTRIBUTOR"}
RESPONSE_MODES = {"PRO_RATA", "PRIORITY_WATERFALL"}
DISPOSITIONS = {"CONDEMNED_WASTE", "CATTLE_FEED", "STARCH_RECOVERY"}
RUN_REJECT_DISPOSITIONS = {"CONDEMNED_WASTE", "CATTLE_FEED"}
CREDIT_STATUSES = {"GOOD_STANDING", "ON_HOLD"}

# --- lot_quality_grade thresholds ---
REJECT_DEFECT_PCT = "8.0"
DEFECT_A_MAX = "3.0"
DEFECT_B_MAX = "5.0"
GRAVITY_A_MIN = "1.080"
GRAVITY_B_MIN = "1.070"
GRAVITY_C_MIN = "1.060"
SUGAR_A_MAX = "2.0"
SUGAR_B_MAX = "3.0"
SUGAR_C_MAX = "4.0"

# --- payment multipliers ---
GRADE_MULT = {"A": "1.08", "B": "1.03", "C": "0.88", "REJECT": "0.00"}

# --- storage_loss_pct ---
DAILY_LOSS_PCT = "0.02"
POSTURE_FACTOR = {"NORMAL": "1.0", "WATCH": "1.5", "QUARANTINED": "3.0"}
MAX_LOSS_PCT = "15.0"
DOWNGRADE_LOSS_PCT = "10.0"

# --- facility_posture thresholds (inclusive) ---
QUARANTINE_DISEASE_PCT = "6.0"
QUARANTINE_SPROUT = "4.0"
WATCH_DISEASE_PCT = "3.0"
WATCH_SPROUT = "2.0"
MAX_RECENT_READINGS = 10

# --- run_actual_cases ---
YIELD_CASES_PER_CWT = {
    "STRAIGHT": "0.62",
    "CRINKLE": "0.58",
    "WEDGE": "0.66",
    "SHOESTRING": "0.55",
}
REWORK_RETENTION = "0.96"  # 1 - REWORK_LOSS_PCT(0.04)

# --- weekly_capacity_reservation ---
PLANT_WEEK_CAPACITY_CASES = 100000

# --- shipment_invoice_and_credit ---
EXCURSION_LIMIT_MINUTES = 30
EXCURSION_DISCOUNT_MULT = "0.90"
SALVAGE_CREDIT_MULT = "0.85"

# --- fill_rate_pct ---
FILL_RATE_FLOOR_PCT = "85.0"

# --- line_schedule_conflict ---
CHANGEOVER_MINUTES = 60

# --- byproduct tariff ---
BYPRODUCT_TARIFF = {"CATTLE_FEED": 900, "STARCH_RECOVERY": 1400, "CONDEMNED_WASTE": 0}

# --- misc thresholds ---
PANEL_SCORE_MIN = "7.0"
COLOR_TOLERANCE = "0.5"
FULFILL_THRESHOLD = "0.98"

# --- logical clock default (PRD section 2.5) ---
DEFAULT_CLOCK_ISO = "2026-09-01T00:00:00Z"
