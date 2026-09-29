"""Domain constants for the electric-motor manufacturing API.

Every table here is transcribed from the product requirements document.
One spelling per symbol, used by every other module in this package.
"""

# ── Roles (PRD 2.1) ───────────────────────────────────────────────────────────

ROLE_DESIGN_ENGINEER = "DesignEngineer"
ROLE_DESIGN_REVIEWER = "DesignReviewer"
ROLE_PRODUCTION_PLANNER = "ProductionPlanner"
ROLE_BUILD_TECHNICIAN = "BuildTechnician"
ROLE_TEST_ENGINEER = "TestEngineer"
ROLE_QUALITY_CERTIFIER = "QualityCertifier"
ROLE_COMPLIANCE_OFFICER = "ComplianceOfficer"
ROLE_DISTRIBUTOR = "Distributor"
ROLE_PLANT_ADMIN = "PlantAdmin"

ALL_ROLES = [
    ROLE_DESIGN_ENGINEER,
    ROLE_DESIGN_REVIEWER,
    ROLE_PRODUCTION_PLANNER,
    ROLE_BUILD_TECHNICIAN,
    ROLE_TEST_ENGINEER,
    ROLE_QUALITY_CERTIFIER,
    ROLE_COMPLIANCE_OFFICER,
    ROLE_DISTRIBUTOR,
    ROLE_PLANT_ADMIN,
]

# ── Logical clock (PRD 2.5) ───────────────────────────────────────────────────

DEFAULT_CLOCK_UTC = "2026-08-01T00:00:00Z"
DEFAULT_CLOCK_DATE = "2026-08-01"

# ── Pagination (PRD 2.3) ──────────────────────────────────────────────────────

DEFAULT_LIMIT = 10
MAX_LIMIT = 100

# ── Enumerations ──────────────────────────────────────────────────────────────

JURISDICTIONS = ["EU", "US", "CN"]
EFFICIENCY_CLASSES = ["IE2", "IE3", "IE4", "IE5"]
CLASS_BELOW_IE2 = "BELOW_IE2"
CLASS_RANK = {"BELOW_IE2": 0, "IE2": 1, "IE3": 2, "IE4": 3, "IE5": 4}

POLES_VALUES = [2, 4, 6, 8]
VOLTAGE_VALUES = [230, 400, 460, 690]
LAMINATION_GRADES = ["M400_50A", "M330_35A", "M270_35A", "M235_35A"]
WINDING_TYPES = ["CONCENTRIC", "LAP"]
INSULATION_CLASSES = ["B", "F", "H"]
ROTOR_CONSTRUCTIONS = ["DIE_CAST_ALUMINUM", "FABRICATED_COPPER"]
SHAFT_TOLERANCE_CLASSES = ["k6", "m6", "j6"]
LUBRICATION_SPECS = ["GREASE_LIFETIME", "GREASE_REGREASABLE", "OIL_MIST"]
DUTY_TYPES = ["S1", "S2", "S3"]
ENCLOSURES = ["IP55", "IP65", "IP66"]
MOUNTINGS = ["B3", "B5", "B35", "V1"]

DESIGN_STATUSES = ["DRAFT", "IN_REVIEW", "RELEASED", "REVISION_OPEN", "OBSOLETE"]
ORDER_STATUSES = ["DRAFT", "CONFIRMED", "IN_PRODUCTION", "FULFILLED", "CANCELLED"]
BUILD_STATUSES = [
    "RELEASED",
    "SUBASSEMBLIES_DONE",
    "ASSEMBLED",
    "TESTED",
    "SHIPPED",
    "CANCELLED",
]
CERTIFICATION_STATUSES = ["PENDING", "CERTIFIED", "SUSPENDED"]
STATOR_STATUSES = [
    "WOUND",
    "IMPREGNATED",
    "SURGE_TESTED",
    "ACCEPTED",
    "REJECTED",
    "SCRAPPED",
]
ROTOR_STATUSES = [
    "PLANNED",
    "CAST_POURED",
    "BARS_BRAZED",
    "MACHINED",
    "ACCEPTED",
    "REJECTED",
    "SCRAPPED",
]
ASSEMBLY_STATUSES = ["BUILT", "SCRAPPED"]
PERFORMANCE_TEST_STATUSES = ["SCHEDULED", "COMPLETED", "SUPERSEDED"]
NAMEPLATE_STATUSES = ["ISSUED", "REVOKED"]
CLAIM_STATUSES = [
    "SUBMITTED",
    "UNDER_ANALYSIS",
    "DEFECT_CONFIRMED",
    "MISUSE_DETERMINED",
    "CLOSED",
]

ORDER_TYPES = ["STOCK_REPLENISH", "MADE_TO_ORDER", "ENGINEERED_SPECIAL"]
DISTRIBUTOR_TIERS = ["PLATINUM", "GOLD", "SILVER"]
RESOURCE_STATUSES = ["AVAILABLE", "MAINTENANCE"]
INSULATION_SYSTEMS = [
    "CLASS_B_POLYESTER",
    "CLASS_F_POLYESTERIMIDE",
    "CLASS_H_POLYAMIDEIMIDE",
]
INSULATION_SYSTEM_TO_CLASS = {
    "CLASS_B_POLYESTER": "B",
    "CLASS_F_POLYESTERIMIDE": "F",
    "CLASS_H_POLYAMIDEIMIDE": "H",
}
VARNISH_PROCESSES = ["DIP_BAKE", "VPI", "TRICKLE"]
CAGE_METHODS = ["DIE_CAST", "BRAZED_BAR"]
BALANCE_GRADES = ["G1_0", "G2_5", "G6_3"]
BEARING_INSTALL_METHODS = ["INDUCTION_HEAT", "PRESS", "OIL_BATH"]
TEST_METHODS = ["IEC_60034_2_1_SUMMATION", "IEEE_112_B_DYNAMOMETER"]
FAILURE_MODES = [
    "BEARING_FAILURE",
    "WINDING_SHORT",
    "ROTOR_BAR_CRACK",
    "SHAFT_FRACTURE",
    "INSULATION_BREAKDOWN",
]
ANALYSIS_BASES = ["FIELD_DATA", "TEARDOWN"]
REVIEW_DECISIONS = ["APPROVE", "REQUEST_CHANGES", "OBSOLETE"]
DISPOSITIONS = ["ACCEPTED", "REJECTED"]

# ── Predicted loss model (PRD 3.2) ────────────────────────────────────────────

BASE_LOSS_FRACTION_BY_POLES = {2: 0.070, 4: 0.060, 6: 0.075, 8: 0.090}
CORE_SHARE = 0.30
COPPER_SHARE = 0.35
ROTOR_SHARE = 0.20
FRICTION_SHARE = 0.10
STRAY_SHARE = 0.05
LAMINATION_FACTOR = {
    "M400_50A": 1.30,
    "M330_35A": 1.12,
    "M270_35A": 1.00,
    "M235_35A": 0.92,
}
WINDING_FACTOR = {"CONCENTRIC": 1.06, "LAP": 1.00}
ROTOR_FACTOR = {"DIE_CAST_ALUMINUM": 1.15, "FABRICATED_COPPER": 0.88}
REFERENCE_STACK_LENGTH_MM = 180
REFERENCE_COPPER_KG = 12.0
TOLERANCE_COEFFICIENT = 0.15

# Class floors in percent, keyed class -> poles (PRD 3.2)
CLASS_FLOORS = {
    "IE2": {2: 89.60, 4: 90.40, 6: 89.80, 8: 88.60},
    "IE3": {2: 91.40, 4: 92.10, 6: 91.60, 8: 90.50},
    "IE4": {2: 93.00, 4: 93.60, 6: 93.10, 8: 92.20},
    "IE5": {2: 94.30, 4: 94.80, 6: 94.40, 8: 93.60},
}

REVIEW_ROUND_LIMIT = 3

# ── Lead time (PRD 3.4) ───────────────────────────────────────────────────────

ORDER_TYPE_BASE_DAYS = {
    "STOCK_REPLENISH": 5,
    "MADE_TO_ORDER": 28,
    "ENGINEERED_SPECIAL": 56,
}
SPECIAL_REQUIREMENT_ADDERS = [
    ("non_standard_mounting", 7),
    ("hazardous_environment", 14),
    ("non_standard_duty", 5),
    ("marine_certification", 21),
]
STOCK_SHORTFALL_PENALTY_DAYS = 11
JURISDICTION_ADDER_DAYS = {"EU": 3, "US": 5, "CN": 9}
TIER_REDUCTION_DAYS = {"PLATINUM": 4, "GOLD": 2, "SILVER": 0}
LEAD_TIME_FLOOR_DAYS = 3

# ── Work order cost (PRD 3.5) ─────────────────────────────────────────────────

COPPER_RATE_CENTS_PER_KG = 1150
LAMINATION_RATE_CENTS_PER_MM = {
    "M400_50A": 420,
    "M330_35A": 510,
    "M270_35A": 640,
    "M235_35A": 780,
}
ROTOR_PROCESS_COST_CENTS = {"DIE_CAST_ALUMINUM": 18000, "FABRICATED_COPPER": 47500}
LABOUR_CENTS_PER_UNIT = 26000
OVERHEAD_BAND_ENGINEERED_MIN_CENTS = 4000000
OVERHEAD_BAND_COMPLEX_MIN_CENTS = 1500000
OVERHEAD_RATE = {"STANDARD": 0.22, "COMPLEX": 0.31, "ENGINEERED": 0.44}
REWORK_SURCHARGE_CENTS = 62500

# ── Surge envelope (PRD 3.6) ──────────────────────────────────────────────────

SURGE_BASE_V = 1000
INSULATION_CLASS_FACTOR = {"B": 1.00, "F": 1.15, "H": 1.30}
VARNISH_PROCESS_FACTOR = {"DIP_BAKE": 1.00, "TRICKLE": 1.05, "VPI": 1.20}
CYCLE_BONUS_PER_EXTRA_CYCLE = 0.04
CYCLE_BONUS_CAP = 0.12
SLOT_FILL_MIN_PCT = 78.00
SLOT_FILL_MAX_PCT = 86.00

# ── Rotor cage / air gap / balance (PRD 3.7) ──────────────────────────────────

CAGE_PROPERTIES = {
    "DIE_CAST_ALUMINUM": {
        "cage_conductivity_ratio": 0.62,
        "slip_penalty_pct": 1.8,
        "rotor_process_cost_cents": 18000,
    },
    "FABRICATED_COPPER": {
        "cage_conductivity_ratio": 1.00,
        "slip_penalty_pct": 0.6,
        "rotor_process_cost_cents": 47500,
    },
}
CONSTRUCTION_TO_CAGE_METHOD = {
    "DIE_CAST_ALUMINUM": "DIE_CAST",
    "FABRICATED_COPPER": "BRAZED_BAR",
}
ISO_BALANCE_CONSTANT = 9549
BALANCE_GRADE_VELOCITY = {"G1_0": 1.0, "G2_5": 2.5, "G6_3": 6.3}
SYNCHRONOUS_RPM_BY_POLES = {2: 3000, 4: 1500, 6: 1000, 8: 750}

# ── Assembly metrology (PRD 3.8) ──────────────────────────────────────────────

SHAFT_FIT_BAND_UM = {"k6": (2, 18), "m6": (7, 25), "j6": (-5, 11)}
GREASE_FILL_BAND_PCT = {
    "GREASE_LIFETIME": (30.0, 40.0),
    "GREASE_REGREASABLE": (40.0, 60.0),
    "OIL_MIST": (0.0, 0.0),
}

# ── Efficiency verification (PRD 3.8) ─────────────────────────────────────────

STATOR_TEMP_CORRECTION_PER_C = 0.0035
STATOR_TEMP_REFERENCE_C = 25.0
STRAY_LOAD_FRACTION = 0.005

# ── Warranty adjudication (PRD 3.10) ──────────────────────────────────────────

OVERLOAD_REFERENCE_PCT = 100.0
OVERLOAD_SPAN = 40.0
THERMAL_REFERENCE_C = 40.0
THERMAL_SPAN = 25.0
VOLTAGE_REFERENCE_PCT = 1.0
VOLTAGE_SPAN = 3.0
STARTS_REFERENCE_BY_DUTY = {"S1": 6, "S2": 12, "S3": 30}

FIELD_DATA_WEIGHTS = {
    "overload": 0.34,
    "thermal": 0.26,
    "voltage": 0.22,
    "starts": 0.18,
}
TEARDOWN_WEIGHTS = {
    "overload": 0.20,
    "thermal": 0.18,
    "voltage": 0.14,
    "starts": 0.10,
    "evidence": 0.38,
}
MISUSE_THRESHOLD = 0.50

PRO_RATA_WINDOW_MONTHS = 60
CREDIT_CEILING_FRACTION = 0.85
PARTS_CAP_FRACTION = 0.60
LABOUR_CAP_CENTS = 45000
FREIGHT_CAP_CENTS = 18000
DISPUTE_ROUND_LIMIT = 2
