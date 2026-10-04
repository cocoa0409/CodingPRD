"""Domain constants for the Protective Coating Specification API.

Every value below is pinned by a PRD sentence (logical clock, quality-score
arithmetic, surface-preparation limits, film/holiday acceptance, VOC and
thinner ceilings, warranty split and reinstatement limits). Tests import these
instead of restating magic numbers.
"""

# ── Roles (PRD §2.1: exactly seven, spelled exactly so) ─────────────────────
ROLE_PLATFORM_ADMIN = "PlatformAdmin"
ROLE_TECHNICAL_SERVICE_ENGINEER = "TechnicalServiceEngineer"
ROLE_PROJECT_ENGINEER = "ProjectEngineer"
ROLE_OWNER_REPRESENTATIVE = "OwnerRepresentative"
ROLE_APPLICATOR_REP = "ApplicatorRep"
ROLE_INSPECTOR = "Inspector"
ROLE_COMPLIANCE_OFFICER = "ComplianceOfficer"

# ── Logical clock (PRD §2.5) ────────────────────────────────────────────────
# Before any clock-setting call, the logical clock reads exactly this instant.
BASE_CLOCK_UTC = "2026-09-01T00:00:00Z"

# ── Quality history score (PRD §3.3) ────────────────────────────────────────
SCORE_INITIAL = 500
SCORE_FLOOR = 0
SCORE_CEILING = 1000
PREP_FAILURE_PENALTY = 25
INSPECTION_PASS_BONUS = 10
INSPECTION_FAILURE_PENALTY = 75
VOC_VIOLATION_PENALTY = 100
PROBATION_PENALTY = 150
MONTHLY_DECAY = 5
REINSTATE_SUSPENSION_LIMIT = 3
PROBATION_RECERTIFY_STREAK = 2

# ── Surface preparation verdict (PRD §3.5) ──────────────────────────────────
SALT_LIMIT_DEFAULT_UG_CM2 = 10.0
SALT_LIMIT_TANK_INTERIOR_UG_CM2 = 5.0
DEW_POINT_SPREAD_MIN_C = 3.0

# ── Film thickness / holiday acceptance (PRD §3.6) ──────────────────────────
SPOT_FLOOR_FRACTION = 0.8
MIN_SPOT_COUNT = 3
HOLIDAY_LIMIT_DEFAULT = 0.1
HOLIDAY_LIMIT_TANK_INTERIOR = 0.0
CURE_WINDOW_HOURS_PER_COAT = 24

# ── VOC compliance (PRD §3.2) ───────────────────────────────────────────────
THINNER_HARD_CAP = 0.25

# ── Warranty liability split (PRD §3.7) ─────────────────────────────────────
DEFAULT_FAULT_PCT = 50

# ── Common instants used by the composite fixtures ──────────────────────────
REGULATION_WINDOW_FROM = "2026-01-01T00:00:00Z"
REGULATION_WINDOW_TO = "2027-01-01T00:00:00Z"
WORK_ORDER_WINDOW_START = "2026-09-05T00:00:00Z"
WORK_ORDER_WINDOW_END = "2026-09-15T00:00:00Z"
COAT_APPLIED_AT = "2026-09-06T09:00:00Z"
SECOND_COAT_APPLIED_AT = "2026-09-07T09:00:00Z"
CURE_CLOCK_ONE_COAT = "2026-09-08T09:00:00Z"
CURE_CLOCK_TWO_COATS = "2026-09-09T09:00:00Z"
