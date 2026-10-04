"""All PRD-pinned constants, each defined exactly once with its PRD literal value."""
from decimal import Decimal

# --- Roles (PRD section 2.1) ---
ROLES = [
    "PlatformAdmin",
    "IntakeCoordinator",
    "AccreditedRepresentative",
    "BenefitsOfficer",
    "ClinicalPartner",
    "CareerCounselor",
    "EventCoordinator",
    "OutcomeAnalyst",
    "ProgramMember",
]

# --- Enum sets ---
MEMBER_TYPES = ["VETERAN", "FAMILY_SUPPORT"]
BRANCHES = ["ARMY", "NAVY", "AIR_FORCE", "MARINES", "COAST_GUARD", "SPACE_FORCE"]
SERVICE_ERAS = ["POST_911", "PRE_911_GULF", "VIETNAM_ERA", "PEACETIME"]
INJURY_CONNECTIONS = ["SERVICE_CONNECTED", "NON_SERVICE_CONNECTED"]
SERVICE_CATEGORIES = ["MENTAL_HEALTH", "PHYSICAL_HEALTH", "CAREER", "INDEPENDENCE", "BENEFITS"]
TRACK_CODES = ["MENTAL_HEALTH", "PHYSICAL_HEALTH", "CAREER", "INDEPENDENCE"]
CLAIM_TYPES = ["DISABILITY_COMPENSATION", "HEALTHCARE_ACCESS"]
SPECIALTIES = ["PTSD", "TBI", "SUBSTANCE_USE", "DEPRESSION"]
ACCOMMODATIONS = ["WHEELCHAIR", "ASL_INTERPRETER", "SERVICE_ANIMAL", "SENSORY_FRIENDLY"]
RATING_STEPS = [0, 10, 20, 30, 40, 50, 60, 70, 80, 90, 100]

# --- Acuity scoring (calculations.acuity_scoring) ---
ACUITY_WEIGHTS_VETERAN = {
    "PSYCH": Decimal("0.4"), "PHYS": Decimal("0.3"),
    "VOC": Decimal("0.2"), "SOC": Decimal("0.1"),
}
ACUITY_WEIGHTS_FAMILY_SUPPORT = {
    "PSYCH": Decimal("0.5"), "PHYS": Decimal("0.1"),
    "VOC": Decimal("0.2"), "SOC": Decimal("0.2"),
}
ACUITY_TIER_ENHANCED_MIN = 40
ACUITY_TIER_INTENSIVE_MIN = 70

# --- Compensation (calculations.compensation_monthly) ---
RATING_BASE_CENTS = {
    0: 0, 10: 17500, 20: 34600, 30: 52400, 40: 75500, 50: 105700,
    60: 134000, 70: 166100, 80: 193200, 90: 217200, 100: 373700,
}
DEPENDENT_RATING_FLOOR_PCT = 30
DEPENDENT_ALLOWANCE_ONE_CENTS = 16000
DEPENDENT_ALLOWANCE_TWO_CENTS = 31000
DEPENDENT_ALLOWANCE_EXTRA_CENTS = 9000
COLA_RATE = Decimal("0.025")

# --- Travel (calculations.travel_award) ---
PER_REGISTRATION_TRAVEL_CAP_CENTS = 50000

# --- Donor reporting (calculations.program_effect_reporting) ---
BASELINE_IMPUTE_SCORE = 50

# --- Survey windows (calculations.survey_window_schedule) ---
BASELINE_WINDOW_DAYS = 14
EXIT_WINDOW_DAYS = 30
FOLLOWUP_90_OFFSET_DAYS = 90
FOLLOWUP_GRACE_DAYS = 7

# --- Claims / appeals ---
APPEAL_WINDOW_DAYS = 90
CLAIM_CLOSE_GRACE_DAYS = 7

# --- Referral recovery buffer (calculations.treatment_window_overlap) ---
RECOVERY_BUFFER_DAYS = 7

# --- Logical clock startup default (PRD section 2.5) ---
CLOCK_START = (2026, 9, 1, 0, 0, 0)
