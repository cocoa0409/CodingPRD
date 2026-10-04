"""All pinned constants for the Crayon Works platform (PRD + SCAFFOLD)."""
from decimal import Decimal

# Logical clock startup default (PRD section 2.4) — never falls back to wall clock.
CLOCK_START = "2026-09-01T00:00:00Z"

# Season window (PRD section 2.10), inclusive at both ends.
SEASON_START = "2027-06-01T00:00:00Z"
SEASON_END = "2027-08-31T23:59:59Z"

# Production lead time (PRD section 2.10).
LEAD_TIME_DAYS = 60

# Color archival: archive_after_date = retired_on + 30 days (PRD section 3.1).
ARCHIVE_AFTER_DAYS = 30

# Session turnover buffer: occupied interval is
# [start_minute, start_minute + duration_minutes + 30), half-open (PRD section 3.7).
SESSION_BUFFER_MINUTES = 30

# vote_tally constants (SCAFFOLD calculations.vote_tally).
MIN_TURNOUT = 10
INTRO_THRESHOLD = Decimal("0.55")
RETIRE_THRESHOLD = Decimal("0.60")
VOTE_WEIGHTS = {
    "INTRODUCTION": {
        "KIDS": Decimal("1.0"),
        "PARENTS": Decimal("1.5"),
        "EDUCATORS": Decimal("2.0"),
        "COLLECTORS": Decimal("1.2"),
    },
    "RETIREMENT": {
        "KIDS": Decimal("1.0"),
        "PARENTS": Decimal("1.0"),
        "EDUCATORS": Decimal("1.5"),
        "COLLECTORS": Decimal("2.5"),
    },
}

# ticket_dynamic_price constants (SCAFFOLD calculations.ticket_dynamic_price).
LOW_TIER_CEIL = Decimal("0.5")
HIGH_TIER_FLOOR = Decimal("0.8")
LOW_MULT = Decimal("0.9")
MID_MULT = Decimal("1.0")
HIGH_MULT = Decimal("1.25")
GROUP20_MULT = Decimal("0.85")
GROUP50_MULT = Decimal("0.75")
GROUP20_MIN_UNITS = 20
GROUP50_MIN_UNITS = 50
WEEKEND_MULT = Decimal("1.15")
CHARTER_GROUP_MULT = Decimal("0.80")

# packing_penalty constants (SCAFFOLD calculations.packing_penalty).
UNDER_UNIT_PENALTY_CENTS = Decimal("18.75")
OVER_FACTOR = Decimal("1.5")
TOLERANCE_UNITS = 5

# Assortment spec structural rule (PRD section 3.4).
BOX_SIZES = (8, 16, 24, 64)

# recall_severity_classification constants.
CLASS_II_FLOOR = 1000
CLASS_I_FLOOR = 10000
COOLING_III_DAYS = 7
COOLING_II_DAYS = 14
COOLING_I_DAYS = 30

# Ticket group-size bounds (PRD section 3.7).
GROUP_SIZE_MIN = 10
GROUP_SIZE_MAX = 100

# Licensed-line royalty rate upper bound (PRD section 3.6).
ROYALTY_RATE_MAX = Decimal("0.5")

# Session field bounds (PRD section 3.7).
START_MINUTE_MAX = 1339
DURATION_MIN_MINUTES = 30

# Pagination defaults (SCAFFOLD response_envelope.pagination_defaults).
PAGE_DEFAULT_LIMIT = 10
PAGE_MIN_LIMIT = 1
PAGE_MAX_LIMIT = 100
PAGE_DEFAULT_OFFSET = 0

# Allocation waterfall: priority tiers ranked PLATINUM first.
TIER_RANK = {"PLATINUM": 0, "GOLD": 1, "STANDARD": 2}

# Stages whose planned_boxes count toward the projected allocation pool.
PROJECTED_STAGES = ("PLANNED", "MOLDING", "LABELING", "PACKING", "ON_HOLD")

# Role names (PRD section 2.1) — spelled exactly.
ROLE_PLATFORM_ADMIN = "PlatformAdmin"
ROLE_SOURCING_MANAGER = "SourcingManager"
ROLE_QUALITY_ASSURANCE = "QualityAssurance"
ROLE_FORMULATOR = "Formulator"
ROLE_SAFETY_OFFICER = "SafetyOfficer"
ROLE_LAB_TECHNICIAN = "LabTechnician"
ROLE_BRAND_MANAGER = "BrandManager"
ROLE_LICENSOR = "Licensor"
ROLE_ALLOCATION_PLANNER = "AllocationPlanner"
ROLE_BOX_OFFICE = "BoxOffice"
ROLE_CONSUMER = "Consumer"

ALL_ROLES = frozenset({
    ROLE_PLATFORM_ADMIN, ROLE_SOURCING_MANAGER, ROLE_QUALITY_ASSURANCE,
    ROLE_FORMULATOR, ROLE_SAFETY_OFFICER, ROLE_LAB_TECHNICIAN,
    ROLE_BRAND_MANAGER, ROLE_LICENSOR, ROLE_ALLOCATION_PLANNER,
    ROLE_BOX_OFFICE, ROLE_CONSUMER,
})

# "All operational roles" = every role except Consumer (PRD section 4).
OPS_ROLES = ALL_ROLES - {ROLE_CONSUMER}
