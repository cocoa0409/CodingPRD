"""Named constants for the Pasture-Raised Farm Network API.

Every numeric threshold, rate table, day-window, and role name referenced
anywhere in the implementation is defined exactly once, here.
Traces: PRD sections 2.3, 2.5, 2.7, 2.8, 2.9, 3.2, 3.3, 3.6, 3.7, 3.8.
"""
from decimal import Decimal

# Logical clock boot value (PRD 2.5)
CLOCK_BOOT_ISO = "2026-09-01T00:00:00Z"

# Farm capacity arithmetic (PRD 2.8)
MIN_PASTURE_SQFT_PER_BIRD = Decimal("108.0")
MIN_BARN_SQFT_PER_BIRD = Decimal("1.2")
BIRDS_PER_NEST_BOX = 5

# Production forecast rates (PRD 3.7)
LAY_RATE = {
    "SPRING": Decimal("0.82"),
    "SUMMER": Decimal("0.78"),
    "AUTUMN": Decimal("0.72"),
    "WINTER": Decimal("0.61"),
}
WEATHER_OPTIMISTIC = {
    "NONE": Decimal("1.00"),
    "MODERATE": Decimal("0.95"),
    "SEVERE": Decimal("0.88"),
}
WEATHER_CONSERVATIVE = {
    "NONE": Decimal("0.98"),
    "MODERATE": Decimal("0.88"),
    "SEVERE": Decimal("0.75"),
}
DAYS_PER_WEEK = 7
EGGS_PER_DOZEN = 12

# Commitment cap (PRD 3.7)
MAX_COMMIT_RATIO = Decimal("0.9")

# Quality grading thresholds (PRD 3.6)
GRADE_AA_MIN = 95.0
GRADE_A_MIN = 85.0
GRADE_B_MIN = 70.0

# Farmer payment quality multipliers (PRD 3.8)
QUALITY_MULT = {
    "AA": Decimal("1.10"),
    "A": Decimal("1.00"),
    "B": Decimal("0.85"),
}

# Commitment fill evaluation (PRD 3.8)
MIN_FILL_RATE = Decimal("0.85")

# Certification validity (PRD 2.7)
CERT_VALIDITY_DAYS = 365

# Corrective-action deadlines in days by severity (PRD 3.3)
CA_DUE_DAYS = {"MINOR": 90, "MAJOR": 30, "CRITICAL": 7}

# Audit scheduling rules (PRD 3.2)
MIN_AUDIT_GAP_DAYS = 30
AUDIT_WINDOW_EARLY_DAYS = 3
AUDIT_WINDOW_LATE_DAYS = 7

# Unit conversions (PRD 2.9)
DOZENS_PER_CASE = 30
DOZENS_PER_CARTON = 1

# Pagination (PRD 2.3)
PAGE_LIMIT_DEFAULT = 10
PAGE_LIMIT_MIN = 1
PAGE_LIMIT_MAX = 100
PAGE_OFFSET_DEFAULT = 0

# The six declared roles (PRD 2.1)
ROLES = (
    "PlatformAdmin",
    "NetworkManager",
    "Auditor",
    "QualityManager",
    "PlantOperator",
    "RetailerBuyer",
)

# Enum sets
SEASONS = ("SPRING", "SUMMER", "AUTUMN", "WINTER")
WEATHER_SEVERITIES = ("NONE", "MODERATE", "SEVERE")
AUDIT_TYPES = ("INITIAL", "ANNUAL", "FOR_CAUSE", "RE_AUDIT")
AUDIT_OUTCOMES = ("PASSED", "FAILED", "CORRECTIVE_ACTION_REQUIRED")
CA_SEVERITIES = ("MINOR", "MAJOR", "CRITICAL")
INCIDENT_SEVERITIES = ("LOW", "MODERATE", "HIGH", "CRITICAL")
INCIDENT_DISPOSITIONS = ("NONE", "PROBATION", "SUSPENSION", "REMOVAL")
HOLD_DISPOSITIONS = ("RELEASE", "REJECT")
CA_DECISIONS = ("VERIFY_CLOSED", "REJECT")
PACK_SIZES = ("MEDIUM", "LARGE", "EXTRA_LARGE")
