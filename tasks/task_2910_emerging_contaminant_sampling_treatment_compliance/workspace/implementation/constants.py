"""Global constants and enumerations (PRD sections 2 and 3)."""

from decimal import Decimal

# ---------------------------------------------------------------- auth / roles
HEADER_USER_ID = "X-User-ID"
HEADER_USER_ROLE = "X-User-Role"

ROLES = (
    "UtilityAdmin",
    "SamplingTechnician",
    "LaboratoryManager",
    "ComplianceOfficer",
    "TreatmentEngineer",
    "FinanceOfficer",
    "StateRegulator",
)
ANY_ROLE = ROLES

# ---------------------------------------------------------------- pagination
PAGE_LIMIT_DEFAULT = 10
PAGE_LIMIT_MIN = 1
PAGE_LIMIT_MAX = 100
PAGE_OFFSET_DEFAULT = 0
PAGE_OFFSET_MIN = 0

# ---------------------------------------------------------------- clock
DEFAULT_CLOCK_ISO = "2026-08-01T00:00:00.000Z"

# ---------------------------------------------------------------- rate base
PERSONS_PER_ACCOUNT = Decimal("2.5")
KGAL_PER_ACCOUNT_PER_YEAR = 60
BASE_RATE_CENTS_PER_KGAL = 950
MONTHS_PER_YEAR = 12

# ---------------------------------------------------------------- compliance
LRAA_WINDOW_QUARTERS = 4
POSTURE_TRIGGER_RATIO = Decimal("0.5")
HAZARD_INDEX_MCL = Decimal("1.00")
HAZARD_TERM_CAP = Decimal("4.00")
ACUTE_MULTIPLIER = 4
ACUTE_MIN_POPULATION = 10000
FIELD_BLANK_LIMIT_NG_PER_L = Decimal("2.00")
SUSPENSION_INVALIDATION_STREAK = 3

HOLDING_TIME_HOURS_BY_METHOD = {
    "METHOD_533": Decimal("336"),
    "METHOD_537_1": Decimal("336"),
    "METHOD_1633": Decimal("720"),
}
METHODS = tuple(HOLDING_TIME_HOURS_BY_METHOD.keys())

TIER_DEADLINE_HOURS = {"TIER_1": 24, "TIER_2": 720, "TIER_3": 8760}
NOTIFICATION_TIERS = ("TIER_1", "TIER_2", "TIER_3")

MAX_NOTIFICATION_REVISIONS = 3
MANDATORY_CONTENT_ELEMENTS = (
    "VIOLATION_DESCRIPTION",
    "HEALTH_EFFECTS_LANGUAGE",
    "POPULATION_AT_RISK",
    "CORRECTIVE_ACTION",
    "UTILITY_CONTACT",
    "ALTERNATE_WATER_GUIDANCE",
)
DELIVERY_METHODS = (
    "BROADCAST_MEDIA",
    "POSTING",
    "MAIL",
    "HAND_DELIVERY",
    "ANNUAL_REPORT",
)
REQUIRED_DELIVERY_METHODS_BY_TIER = {
    "TIER_1": ("BROADCAST_MEDIA", "POSTING"),
    "TIER_2": ("MAIL", "POSTING"),
    "TIER_3": ("ANNUAL_REPORT",),
}

REDUCTION_MIN_QUARTERS_ANNUAL = 4
REDUCTION_MIN_QUARTERS_TRIENNIAL = 8

# ---------------------------------------------------------------- treatment
MIN_COMPLETED_PILOTS = 2
MIN_REMOVAL_PCT = Decimal("90.00")
TECHNOLOGY_WEIGHTS = {
    "removal": Decimal("0.35"),
    "lifecycle_cost": Decimal("0.25"),
    "residuals_burden": Decimal("0.20"),
    "footprint": Decimal("0.10"),
    "om_complexity": Decimal("0.10"),
}
LIFECYCLE_COST_DIVISOR_CENTS = Decimal("100000000")
PILOT_DECONTAMINATION_BUFFER_HOURS = 48
TECHNOLOGIES = ("GAC", "IX", "RO")

# ---------------------------------------------------------------- residuals
LEACHATE_HAZARDOUS_NG_PER_L = Decimal("500.0")
LEACHATE_SPECIAL_NG_PER_L = Decimal("50.0")
DISPOSAL_METHODS = ("LANDFILL", "REACTIVATION", "INCINERATION_1100C", "DEEP_WELL")
DISPOSAL_RATE_CENTS_PER_KG = {
    "LANDFILL": Decimal("12"),
    "REACTIVATION": Decimal("95"),
    "INCINERATION_1100C": Decimal("340"),
    "DEEP_WELL": Decimal("210"),
}
PERMITTED_DISPOSAL_BY_CLASSIFICATION = {
    "NON_HAZARDOUS_SOLID": ("LANDFILL", "REACTIVATION", "INCINERATION_1100C", "DEEP_WELL"),
    "SPECIAL_WASTE": ("REACTIVATION", "INCINERATION_1100C", "DEEP_WELL"),
    "HAZARDOUS": ("INCINERATION_1100C", "DEEP_WELL"),
}
MEDIA_TYPES = ("GAC_CARBON", "IX_RESIN", "RO_MEMBRANE", "RO_CONCENTRATE")
MEDIA_TYPE_BY_TECHNOLOGY = {
    "GAC": ("GAC_CARBON",),
    "IX": ("IX_RESIN",),
    "RO": ("RO_MEMBRANE", "RO_CONCENTRATE"),
}
FULL_SCALE_DISPOSAL_BY_TECHNOLOGY = {
    "GAC": "REACTIVATION",
    "IX": "INCINERATION_1100C",
    "RO": "DEEP_WELL",
}
CONCENTRATE_PERMIT_BY_TECHNOLOGY = {"GAC": False, "IX": False, "RO": True}
DEFAULT_RESIDUALS_BUDGET_CENTS = 250000

# ---------------------------------------------------------------- finance
ANNUITY_FACTOR_20Y_2PCT = Decimal("0.0611567181")
OM_RESERVE_PCT = Decimal("25.00")
FUNDING_PROGRAMS = ("SRF_LOAN", "EC_GRANT", "BIL_SUPPLEMENTAL")
RATE_DESIGNS = ("UNIFORM", "VOLUMETRIC")
CONSTRUCTION_SEQUENCE = ("PLANNED", "BIDDING", "CONSTRUCTION", "IN_SERVICE")

# ---------------------------------------------------------------- misc enums
SOURCE_TYPES = ("GROUNDWATER", "SURFACE_WATER", "PURCHASED")
SAMPLE_PROTOCOLS = ("LOW_FLOW_GRAB", "COMPOSITE")
MONITORING_STATUSES = (
    "INITIAL",
    "QUARTERLY",
    "REDUCTION_PENDING",
    "ANNUAL",
    "TRIENNIAL",
    "SUSPENDED",
)
COMPLIANCE_POSTURES = ("COMPLIANT", "TRIGGERED", "VIOLATION_PENDING")
TREATMENT_STATUSES = ("NONE", "PILOT", "INSTALLED")
INVALIDATION_REASONS = (
    "CHAIN_OF_CUSTODY_BROKEN",
    "FIELD_BLANK_CONTAMINATED",
    "HOLDING_TIME_EXCEEDED",
    "QC_FAILURE",
    "OPERATOR_ERROR",
)
REJECT_REASON_CODES = ("QC_FAILURE", "TRANSCRIPTION_ERROR", "METHOD_DEVIATION")
VOID_REASON_CODES = ("DUPLICATE_ENTRY", "MASS_CORRECTION", "CLASSIFICATION_ERROR")
INVESTIGATION_BASES = (
    "UPSTREAM_DISCHARGER",
    "AFFF_TRAINING_SITE",
    "LANDFILL_LEACHATE",
    "MANUFACTURING_SITE",
)
