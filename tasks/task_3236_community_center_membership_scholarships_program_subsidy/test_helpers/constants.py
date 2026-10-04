"""Business constants declared by the Community Center Membership PRD.

Every value here is a literal the PRD states. Tests import these instead of
re-typing magic numbers, so a boundary case such as "exactly 120 hold days"
reads as the rule it exercises.
"""

# ── Logical clock ──────────────────────────────────────────────────────────
# The clock starts at this instant on a fresh deployment and only moves when an
# AssociationAdmin sets it.
CLOCK_STARTUP_DEFAULT = "2026-09-01T00:00:00Z"

# ── Roles ──────────────────────────────────────────────────────────────────
ROLE_ASSOCIATION_ADMIN = "AssociationAdmin"
ROLE_BRANCH_DIRECTOR = "BranchDirector"
ROLE_PROGRAM_COORDINATOR = "ProgramCoordinator"
ROLE_FRONT_DESK = "FrontDesk"
ROLE_MEMBER = "Member"
ROLE_BOARD_MEMBER = "BoardMember"

ALL_ROLES = (
    ROLE_ASSOCIATION_ADMIN,
    ROLE_BRANCH_DIRECTOR,
    ROLE_PROGRAM_COORDINATOR,
    ROLE_FRONT_DESK,
    ROLE_MEMBER,
    ROLE_BOARD_MEMBER,
)

# ── Pagination ─────────────────────────────────────────────────────────────
DEFAULT_LIMIT = 10
MIN_LIMIT = 1
MAX_LIMIT = 100
DEFAULT_OFFSET = 0

# ── Household composition ──────────────────────────────────────────────────
ADULT_MIN_AGE = 18
HOUSEHOLD_SIZE_MIN = 1
HOUSEHOLD_SIZE_MAX = 12
HOUSEHOLD_TYPES = ("ADULT", "TWO_ADULT", "FAMILY", "SENIOR", "YOUNG_ADULT", "TEEN")

# ── Sliding-scale award tiers ──────────────────────────────────────────────
TIER1_CEILING = 0.30   # ratio strictly below -> award 0.75
TIER2_CEILING = 0.50   # ratio in [0.30, 0.50) -> award 0.50
TIER3_CEILING = 0.80   # ratio in [0.50, 0.80) -> award 0.25; >= 0.80 ineligible
AWARD_PCTS = (0.25, 0.50, 0.75)
AWARD_TERM_DAYS = 365

# ── Holds ──────────────────────────────────────────────────────────────────
HOLD_MIN_DAYS = 30
HOLD_MAX_DAYS = 180
HOLD_ALLOWANCE_DAYS = 120
HOLD_TRAILING_WINDOW_DAYS = 365
DEFAULT_HOLD_FEE_CENTS = 1000
ANNIVERSARY_DAY_CAP = 28

# ── Billing / delinquency ──────────────────────────────────────────────────
DRAFT_MAX_ATTEMPTS = 3
DELINQUENT_LAPSE_DAYS = 45
REINSTATE_WINDOW_DAYS = 90
REJOIN_FEE_WAIVER_DAYS = 30

# ── Programs and registration ──────────────────────────────────────────────
PUBLIC_WINDOW_LEAD_DAYS = 14
LATE_CANCEL_FORFEIT_HOURS = 48
RECIPROCITY_SURCHARGE = 1.25
DEFAULT_NON_MEMBER_MULTIPLIER = 1.5
DEFAULT_MIN_AGE = 0
DEFAULT_MAX_AGE = 99

# ── Reservation buffers by type ────────────────────────────────────────────
BUFFER_MINUTES_BY_TYPE = {
    "PROGRAM": 15,
    "RENTAL": 30,
    "MAINTENANCE": 0,
    "BLACKOUT": 0,
}

# ── Campaign match tiers ───────────────────────────────────────────────────
MATCH_TIER1_ATTAINMENT = 0.50   # attainment >= 0.50 -> match 0.10
MATCH_TIER2_ATTAINMENT = 1.00   # attainment >= 1.00 -> match 0.25
MATCH_PCT_LOW = 0.0
MATCH_PCT_MID = 0.10
MATCH_PCT_HIGH = 0.25

# ── Documentation kinds ────────────────────────────────────────────────────
DOCUMENTATION_KINDS = ("TAX_RETURN", "PAY_STUB", "BENEFITS_LETTER")
