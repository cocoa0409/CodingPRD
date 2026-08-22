"""Pinned domain constants (PRD 2.7, 3.3-3.9; SCAFFOLD 1.3).

Every literal below is quoted verbatim from the PRD narrative or the scaffold's
`calculations[].constants` block. Nothing here is inferred.
"""
from decimal import Decimal

# ---- roles (PRD 2.1) -------------------------------------------------------
ROLE_PLANT_ADMIN = "PlantAdmin"
ROLE_PRODUCTION_SUPERVISOR = "ProductionSupervisor"
ROLE_QC_TECHNICIAN = "QCTechnician"
ROLE_QUALITY_ENGINEER = "QualityEngineer"
ROLE_YARD_FOREMAN = "YardForeman"
ROLE_PERMIT_COORDINATOR = "PermitCoordinator"
ROLE_PROJECT_OWNER = "ProjectOwner"

ALL_ROLES = [
    ROLE_PLANT_ADMIN,
    ROLE_PRODUCTION_SUPERVISOR,
    ROLE_QC_TECHNICIAN,
    ROLE_QUALITY_ENGINEER,
    ROLE_YARD_FOREMAN,
    ROLE_PERMIT_COORDINATOR,
    ROLE_PROJECT_OWNER,
]

# ---- pagination (PRD 2.3) --------------------------------------------------
LIMIT_DEFAULT = 10
LIMIT_MIN = 1
LIMIT_MAX = 100
OFFSET_DEFAULT = 0
OFFSET_MIN = 0

# ---- logical clock (PRD 2.4) ----------------------------------------------
CLOCK_DEFAULT_ISO = "2026-08-01T00:00:00Z"

# ---- enums -----------------------------------------------------------------
STRENGTH_CLASSES = ["C40", "C50", "C60", "C70"]
BED_TYPES = ["LONG_LINE_PRESTRESS", "SELF_STRESSING_FORM", "FLAT_BED_RC"]
BED_STATUSES = ["AVAILABLE", "OCCUPIED", "DOWN"]
YARD_SLOT_STATUSES = ["EMPTY", "PARTIAL", "FULL", "BLOCKED"]
CYLINDER_PURPOSES = ["RELEASE", "ACCEPTANCE_28DAY", "INFORMATION"]
DEFECT_TYPES = ["SPALL", "HONEYCOMB", "CRACK", "DIMENSIONAL", "FINISH"]
SEVERITIES = ["MINOR", "MAJOR", "STRUCTURAL"]
DISPOSITIONS = ["PATCH_MINOR", "STRUCTURAL_REPAIR", "USE_AS_IS", "REJECT_RECAST"]
RELEASE_REASONS = ["LOAD", "SCRAP", "RESTACK"]
REINSPECT_RESULTS = ["PASS", "FAIL"]

MIX_STATUSES = ["DRAFT", "QUALIFIED", "SUSPENDED", "RETIRED"]
BED_RUN_STATUSES = [
    "SCHEDULED", "BLOCKED", "TENSIONED", "CURING",
    "RELEASE_READY", "RELEASED", "STRIPPED",
]
CURING_STATUSES = ["SCHEDULED", "RUNNING", "COMPLETED"]
CYLINDER_SET_STATUSES = ["CAST", "TESTING", "RELEASE_MET", "RELEASE_NOT_MET"]
PRODUCTION_STATUSES = [
    "PLANNED", "SCHEDULED", "CAST", "STRIPPED", "YARDED",
    "LOADED", "SHIPPED", "ERECTED", "SCRAPPED",
]
QC_STATUSES = ["PENDING", "HOLD", "CLEARED", "NONCONFORMING", "REPAIRED", "REJECTED"]
QC_HOLD_REASONS = ["AWAITING_RELEASE_STRENGTH", "MIX_SUSPENDED", "OPEN_NCR"]
PLACEMENT_STATUSES = ["ACTIVE", "RELEASED"]
PERMIT_STATUSES = ["APPLIED", "ISSUED", "ACTIVE", "CONSUMED", "EXPIRED"]
SHIPMENT_STATUSES = ["BUILDING", "DISPATCHED", "DELIVERED"]
DISPOSITION_STATUSES = [
    "OPEN", "DISPOSITIONED", "REPAIR_IN_PROGRESS", "REINSPECTION",
    "CLOSED_ACCEPTED", "REJECTED_RECAST", "SUPERSEDED",
]

# ---- cylinder_break_strength_psi ------------------------------------------
PI = Decimal("3.14159265358979")
AREA_BY_DIAMETER = {
    Decimal("4.00"): Decimal("12.566370614359172"),
    Decimal("6.00"): Decimal("28.274333882308138"),
}
CYLINDER_DIAMETERS = [Decimal("4.00"), Decimal("6.00")]

# ---- cylinder_set_qualified_strength --------------------------------------
OUTLIER_TOLERANCE_PCT = Decimal("10.0")

# ---- curing_energy_accounting ---------------------------------------------
AMBIENT_F = Decimal("60.0")
COOLDOWN_RATE_F_PER_HR = Decimal("20.0")
THERM_PER_BHP_HOUR = Decimal("0.335")
ENERGY_VARIANCE_TOLERANCE_PCT = Decimal("15.0")

# ---- strand_jacking_force --------------------------------------------------
STRAND_AREA_IN2 = {
    Decimal("0.500"): Decimal("0.153"),
    Decimal("0.600"): Decimal("0.217"),
}
STRAND_DIAMETERS = [Decimal("0.500"), Decimal("0.600")]
F_PU_KSI = Decimal("270.0")
JACK_FRACTION = Decimal("0.75")
SEATING_LOSS_PCT = {
    "LONG_LINE_PRESTRESS": Decimal("2.5"),
    "SELF_STRESSING_FORM": Decimal("4.5"),
    "FLAT_BED_RC": Decimal("0.0"),
}
STRENGTH_CLASS_TEMP_ADJ_PCT = {
    "C40": Decimal("0.0"),
    "C50": Decimal("0.0"),
    "C60": Decimal("1.5"),
    "C70": Decimal("1.5"),
}
MIN_JACK_KIPS_PER_STRAND = Decimal("32.0")
STRAND_MODULUS_KSI = Decimal("28500.0")
ELONGATION_TOLERANCE_PCT = Decimal("5.0")

# ---- bed_run_cost_allocation ----------------------------------------------
STRAND_COST_CENTS_PER_KIP = Decimal("145")
BED_TYPE_SETUP_CENTS = {
    "LONG_LINE_PRESTRESS": 180000,
    "SELF_STRESSING_FORM": 240000,
    "FLAT_BED_RC": 90000,
}
OVERHEAD_TIER_1_CENTS = 500000
OVERHEAD_TIER_2_CENTS = 1000000

# ---- shipment_load_metrics / shipment_permit_fee --------------------------
TRACTOR_TARE_LB = Decimal("32000")
LEGAL_WIDTH_FT = Decimal("8.50")
LEGAL_HEIGHT_FT = Decimal("13.50")
LEGAL_LENGTH_FT = Decimal("53.00")
LEGAL_GROSS_WEIGHT_LB = Decimal("80000")
WIDTH_RATE_DOLLARS_PER_FT = Decimal("12.75")
HEIGHT_RATE_DOLLARS_PER_FT = Decimal("21.40")
LENGTH_RATE_DOLLARS_PER_FT = Decimal("3.66")
PERMIT_BASE_CENTS = 8500
ESCORT_CENTS_EACH = 27500

# ---- repair loop -----------------------------------------------------------
MAX_REINSPECTION_FAILS = 2
