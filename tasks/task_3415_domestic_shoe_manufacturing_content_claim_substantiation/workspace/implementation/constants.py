"""Named constants pinned by PRD.md / SCAFFOLD.yaml.

Every threshold, fee, tier, weight, and enum referenced by the business rules
is defined here exactly once; no module may inline a magic value.
"""
from decimal import Decimal

# --- RBAC (PRD section 2.1) ---
ROLES = [
    "PlatformAdmin",
    "SourcingManager",
    "ProductionPlanner",
    "ComplianceOfficer",
    "TrainingCoordinator",
    "FactoryManager",
    "CustomProgramCustomer",
]
ALL_ROLES = tuple(ROLES)

# --- logical clock (PRD section 2.4) ---
DEFAULT_CLOCK_RAW = "2026-09-01T00:00:00Z"

# --- enums ---
LOCATION_TYPES = ["DOMESTIC", "OVERSEAS"]
PRODUCTION_POLICIES = ["DOMESTIC_ONLY", "IMPORT_ONLY", "DUAL_SOURCE"]
COMPONENT_TYPES = [
    "UPPER", "MIDSOLE", "OUTSOLE", "INSOLE", "LACES",
    "EYELETS", "ADHESIVE", "THREAD", "OTHER",
]
SOURCING_REQUIREMENTS = ["DOMESTIC_REQUIRED", "DOMESTIC_PREFERRED", "IMPORT_ALLOWED"]
RUN_TYPES = ["STOCK", "CUSTOM_BATCH", "GOVERNMENT"]
REPORT_VARIANTS = ["PROVISIONAL", "CERTIFIED"]
CLAIM_TYPES = [
    "MADE_IN_USA",
    "MADE_IN_USA_OF_IMPORTED_MATERIALS",
    "ASSEMBLED_IN_USA",
    "IMPORTED",
]
DOC_TYPES = [
    "SUPPLIER_ORIGIN_CERT",
    "ASSEMBLY_LABOR_RECORD",
    "COST_BREAKDOWN",
    "CUSTOMS_ENTRY",
]
SHIFT_DIRECTIONS = ["TO_DOMESTIC", "TO_IMPORT"]
OPERATIONS = ["STITCHING", "LASTING", "ASSEMBLY"]

# Run states that block model discontinuation / week reconciliation.
OPEN_RUN_STATES = ("PLANNED", "MATERIAL_RESERVED", "IN_PRODUCTION", "QUALITY_HOLD")
# Run states whose planned_units count against the week's consumed pool.
CONSUMED_RUN_STATES = ("MATERIAL_RESERVED", "IN_PRODUCTION", "QUALITY_HOLD", "COMPLETED")
# Run states that hold a production line window.
LINE_HOLDING_STATES = ("MATERIAL_RESERVED", "IN_PRODUCTION", "QUALITY_HOLD")

# --- workforce (skill_coverage_score / start-resume headcount) ---
REQUIRED_WORKERS_PER_RUN = {"STITCHING": 2, "LASTING": 1, "ASSEMBLY": 1}
OP_WEIGHTS = {
    "STITCHING": Decimal("0.5"),
    "LASTING": Decimal("0.3"),
    "ASSEMBLY": Decimal("0.2"),
}
PIPELINE_CREDIT = Decimal("0.5")
TRAINING_PASS_SCORE = 80

# --- run_unit_cost tiers ---
TIER_1_MAX_UNITS = 10
TIER_2_MAX_UNITS = 25
TIER_3_MAX_UNITS = 50
TIER_1_PCT = Decimal("0.25")
TIER_2_PCT = Decimal("0.15")
TIER_3_PCT = Decimal("0.08")
CUSTOM_BATCH_EXTRA_PCT = Decimal("0.05")
GOVERNMENT_PCT = Decimal("0.0")

# --- custom_order_price ---
CUSTOM_FALLBACK_MARKUP = Decimal("1.15")
MONOGRAM_FEE_CENTS = 500
COLORWAY_FEE_CENTS = 250
DISCOUNT_TIER_1_MIN_CENTS = 20000
DISCOUNT_TIER_1_PCT = Decimal("0.10")
DISCOUNT_TIER_2_MIN_CENTS = 12000
DISCOUNT_TIER_2_PCT = Decimal("0.05")
MAX_CUSTOM_ORDER_UNITS = 12

# --- capacity_waterfall ---
BUCKET_ORDER = ["GOVERNMENT", "CUSTOM_BATCH", "STOCK"]

# --- claim_threshold_check (inclusive >= thresholds) ---
MADE_IN_USA_MIN_PCT = Decimal("95.00")
MADE_IN_USA_OF_IMPORTED_MIN_PCT = Decimal("70.00")
ASSEMBLED_IN_USA_MIN_PCT = Decimal("20.00")
BERRY_REQUIRED_PCT = Decimal("100.00")

# --- pagination defaults (scaffold response_envelope) ---
PAGINATION_DEFAULT_LIMIT = 10
PAGINATION_MIN_LIMIT = 1
PAGINATION_MAX_LIMIT = 100
PAGINATION_DEFAULT_OFFSET = 0
