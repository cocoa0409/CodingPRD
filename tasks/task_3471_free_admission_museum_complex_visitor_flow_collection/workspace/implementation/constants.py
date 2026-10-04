"""Constants transcribed from PRD.md / SCAFFOLD.yaml for task 3471.

Every numeric/enum constant referenced anywhere in the codebase is defined
exactly once here (PRD prose values are the source of truth).
"""

API_PREFIX = "/campus"

# --- Logical clock (PRD 2.4) ---
# Startup default before any set call: exactly 2026-09-01T00:00:00Z.
CLOCK_DEFAULT_RAW = "2026-09-01T00:00:00Z"

# --- Quarter-hour entry grid (PRD 2.4) ---
# Museum entry day runs 10:00-17:30 UTC = 30 quarter-hour slots (index 0..29).
ENTRY_DAY_START_MINUTE = 600  # 10:00 UTC in minutes since midnight
SLOT_COUNT_PER_DAY = 30
SLOT_MINUTES = 15
ADMIT_GRACE_SLOTS = 2  # 30-minute grace window beyond the reserved slot

# --- Loan premium tiers (PRD 3.4, calculation loan_premium_cents) ---
TIER1_CAP_CENTS = 100000000
TIER1_RATE = "0.006"
TIER2_WIDTH_CENTS = 400000000
TIER2_RATE = "0.0035"
TIER3_RATE = "0.0015"
COURIER_SURCHARGE_RATE = "0.12"
PROVISIONAL_FLAT_RATE = "0.008"
INDEMNITY_MIN_DECLARED_VALUE_CENTS = 500000000
COURIER_MIN_DECLARED_VALUE_CENTS = 100000000

# --- Member pricing (PRD 3.2, calculation member_unit_price_cents) ---
MEMBER_DISCOUNT_PCT = "0.20"

# --- Education gallery setup buffer (PRD 3.3, calculation gallery_schedule_overlap) ---
SETUP_BUFFER_MINUTES = 30

# --- Pagination (PRD 2.3) ---
PAGE_DEFAULT_LIMIT = 10
PAGE_MIN_LIMIT = 1
PAGE_MAX_LIMIT = 100
PAGE_DEFAULT_OFFSET = 0

# --- Roles (PRD 2.1): exactly the fifteen recognized role names ---
ROLES = [
    "PlatformAdmin",
    "VisitorServices",
    "SecurityScreener",
    "ExhibitionManager",
    "ProgramCoordinator",
    "Docent",
    "Public",
    "Member",
    "LoansOfficer",
    "BorrowerRep",
    "Registrar",
    "Curator",
    "CommitteeChair",
    "FinanceOfficer",
    "Scholar",
]

DAY_CODES = ["MON", "TUE", "WED", "THU", "FRI", "SAT", "SUN"]

CERTIFICATION_RANK = {"BASIC": 1, "ADVANCED": 2, "EXPERT": 3}

FEDERAL_PERMITTED_ACTIVITIES = {"OPERATIONS", "EDUCATION"}
TRUST_PERMITTED_ACTIVITIES = {"OPERATIONS", "EDUCATION", "ACQUISITION", "EXHIBITION"}

COVERAGE_TYPES = ("INSURANCE", "INDEMNITY")
DISPOSAL_METHODS = ("TRANSFER", "SALE", "DESTRUCTION", "REPATRIATION")
ACTIVITY_TYPES = ("OPERATIONS", "EDUCATION", "ACQUISITION", "EXHIBITION")
REPORT_KINDS = ("OUTBOUND", "RETURN")
REVIEW_KINDS = ("ACQUISITION", "DEACCESSION")
FUND_TYPES = ("FEDERAL", "TRUST")
