"""PRD-pinned constants for the Mine Safety Inspection API.

Every numeric threshold, rate, window, enum set, and role name below is taken
verbatim from PRD.md / SCAFFOLD.yaml. Referencing modules must never restate
these literals.
"""
from decimal import Decimal

# --- Roles (PRD section 2.1) ---
ROLE_MSHA_ADMIN = "MSHAAdmin"
ROLE_DISTRICT_MANAGER = "DistrictManager"
ROLE_INSPECTOR = "Inspector"
ROLE_OPERATOR_REP = "OperatorRep"
ROLE_COMMISSION_JUDGE = "CommissionJudge"
ROLE_PUBLIC_READER = "PublicReader"

ALL_ROLES = frozenset({
    ROLE_MSHA_ADMIN,
    ROLE_DISTRICT_MANAGER,
    ROLE_INSPECTOR,
    ROLE_OPERATOR_REP,
    ROLE_COMMISSION_JUDGE,
    ROLE_PUBLIC_READER,
})
# Every business-surface GET admits exactly these five roles (PRD section 4).
BUSINESS_READ_ROLES = (
    ROLE_MSHA_ADMIN,
    ROLE_DISTRICT_MANAGER,
    ROLE_INSPECTOR,
    ROLE_OPERATOR_REP,
    ROLE_COMMISSION_JUDGE,
)

# --- Logical clock (PRD section 2.4) ---
CLOCK_START_ISO = "2026-09-01T00:00:00Z"

# --- Statutory cycle geometry (PRD section 2.6) ---
UNDERGROUND_CYCLE_DAYS = 90
SURFACE_CYCLE_DAYS = 180

# --- Penalty point tables (PRD section 3.4) ---
NEGLIGENCE_POINTS = {
    "NONE": 0,
    "LOW": 10,
    "MODERATE": 25,
    "HIGH": 40,
    "RECKLESS_DISREGARD": 50,
}
LIKELIHOOD_POINTS = {
    "UNLIKELY": 5,
    "REASONABLY_LIKELY": 15,
    "HIGHLY_LIKELY": 25,
}
SEVERITY_POINTS = {
    "NO_INJURY": 0,
    "MINOR": 10,
    "SERIOUS": 20,
    "FATAL_POTENTIAL": 30,
}
SS_SURCHARGE = 15
HISTORY_WINDOW_DAYS = 730
# (minimum count, points) evaluated top-down: 0..5 -> 0; 6..15 -> 5; 16..30 -> 10; >=31 -> 20
HISTORY_BANDS = ((31, 20), (16, 10), (6, 5), (0, 0))
# (minimum annual tonnage, points): <50000 -> 0; 50000..499999 -> 5;
# 500000..4999999 -> 10; >=5000000 -> 15
SIZE_BANDS = ((5_000_000, 15), (500_000, 10), (50_000, 5), (0, 0))

# --- Dollar pipeline (PRD section 3.4); order pinned: tiers -> repeat -> discount -> floor ---
TIER1_POINT_CAP = 20
TIER2_POINT_CAP = 40
TIER3_POINT_CAP = 40
TIER1_CENTS = 11250
TIER2_CENTS = 22500
TIER3_CENTS = 37500
TIER4_CENTS = 52500
REPEAT_MULTIPLIER = Decimal("1.15")
GOOD_FAITH_RATE = Decimal("0.10")
FLOOR_ORDER_CENTS = 150000
FLOOR_CITATION_SS_CENTS = 120000
FLOOR_CITATION_CENTS = 60000

# --- Abatement base days by gravity severity (PRD section 3.4) ---
ABATEMENT_BASE_DAYS = {
    "NO_INJURY": 30,
    "MINOR": 15,
    "SERIOUS": 5,
    "FATAL_POTENTIAL": 1,
}

# --- Contest window (PRD sections 2.8 / 3.6) ---
CONTEST_WINDOW_DAYS = 30

# --- Mine plans (PRD section 3.7) ---
PLAN_REVISION_DAYS = 180
REQUIRED_PLAN_TYPES = {
    "UNDERGROUND": ("VENTILATION", "ROOF_CONTROL", "EMERGENCY_RESPONSE"),
    "SURFACE": ("EMERGENCY_RESPONSE",),
}
UNDERGROUND_ONLY_PLAN_TYPES = frozenset({"VENTILATION", "ROOF_CONTROL"})

# --- Accident late-report thresholds (PRD section 3.7); strict greater-than ---
FATAL_LIMIT_SECONDS = 900
OTHER_LIMIT_SECONDS = 7200
LATE_REPORT_STANDARD_CODE = "50.10 LATE REPORT"

# --- Pattern of violations (PRD section 3.7) ---
POV_WINDOW_DAYS = 365
SS_WEIGHT = 2
NEGLIGENCE_BONUS = 1
IDO_WEIGHT = 5
POV_THRESHOLD = 8
POV_BONUS_NEGLIGENCE = frozenset({"HIGH", "RECKLESS_DISREGARD"})

# --- Pagination (PRD section 2.3) ---
DEFAULT_LIMIT = 10
MIN_LIMIT = 1
MAX_LIMIT = 100
DEFAULT_OFFSET = 0

# --- Enum domains ---
MINE_TYPES = frozenset({"UNDERGROUND", "SURFACE"})
CERTIFICATIONS = frozenset({"UNDERGROUND", "SURFACE", "BOTH"})
INSPECTION_KINDS = frozenset({"REGULAR", "SPOT", "FOLLOW_UP", "ACCIDENT_INVESTIGATION"})
CITATION_KINDS = frozenset({"CITATION", "ORDER"})
NEGLIGENCE_LEVELS = frozenset(NEGLIGENCE_POINTS.keys())
GRAVITY_LIKELIHOODS = frozenset(LIKELIHOOD_POINTS.keys())
GRAVITY_SEVERITIES = frozenset(SEVERITY_POINTS.keys())
PLAN_TYPES = frozenset({"VENTILATION", "ROOF_CONTROL", "EMERGENCY_RESPONSE"})
ACCIDENT_SEVERITIES = frozenset({"FATAL", "LOST_TIME", "NO_LOST_TIME"})
CONTEST_OUTCOMES = frozenset({"AFFIRMED", "MODIFIED", "VACATED"})

# Occupied statuses for inspector double-booking (PRD section 3.3)
OCCUPIED_INSPECTION_STATUSES = frozenset({"ASSIGNED", "FILE_REVIEWED", "IN_PROGRESS", "SUSPENDED"})

# Hazard text for the automatic IDO created when an S&S citation is issued at a
# POV_FINAL mine (PRD section 3.5 pins the behavior but not the text).
AUTO_IDO_HAZARD_DESCRIPTION = "AUTO-ISSUED: S&S citation at a POV_FINAL mine"
