"""Domain thresholds and canonical values — every literal derived from PRD.md.

Section citations point at the PRD prose where the value is pinned.
"""

# --- Logical clock (PRD §2.4) ------------------------------------------------
# "the logical clock reads exactly 2026-09-01T00:00:00Z"
INITIAL_CLOCK_UTC = "2026-09-01T00:00:00Z"

# --- Statutory launch score (PRD §3.1) ---------------------------------------
FATALITY_BASE_POINTS = 40            # "otherwise 40 points"
CATASTROPHIC_FATALITY_THRESHOLD = 5  # "when the count reaches five or more"
CATASTROPHIC_FATALITY_BONUS = 15     # "plus a further 15"
DAMAGE_TIER_MID_MIN_CENTS = 1_000_000    # "15 points from one million cents"
DAMAGE_TIER_HIGH_MIN_CENTS = 10_000_000  # "25 points at ten million cents or more"
DAMAGE_POINTS_LOW = 5                # "5 points below one million cents"
DAMAGE_POINTS_MID = 15
DAMAGE_POINTS_HIGH = 25
INJURY_CAP = 10                      # "capped at ten points"
PUBLIC_TRANSPORT_POINTS = 20         # "adds 20 points"
MODAL_BUMP_POINTS = 10               # "plus 10 more"
MODAL_BUMP_CATEGORIES = ("AVIATION", "RAIL")  # "when the category is aviation or rail"
SCORE_MAX = 100                      # "clamped between 0 and 100"
FULL_LAUNCH_THRESHOLD = 60           # "FULL_GO_TEAM when the score is at least 60"
LIMITED_LAUNCH_THRESHOLD = 20        # "LIMITED when it is at least 20 but below 60"

# --- Risk-adjusted launch score (PRD §3.1) -----------------------------------
FATALITY_WEIGHT = 1.0                # "fatalities by 1.0"
INJURY_WEIGHT = 1.25                 # "injuries by 1.25"
PUBLIC_INTEREST_WEIGHT = 0.5         # "public interest by 0.5"
CATEGORY_DAMAGE_MULTIPLIER = {
    "AVIATION": 1.0,
    "RAIL": 1.0,
    "HIGHWAY": 1.0,
    "MARINE": 1.25,
    "PIPELINE": 1.5,
    "HAZMAT": 2.0,
}

# --- Party conduct (PRD §3.4) ------------------------------------------------
SUSPENSION_STRIKE_THRESHOLD = 2      # "the count reaches two — the threshold is inclusive"

# --- Recommendation closure (PRD §3.7) ---------------------------------------
UNACCEPTABLE_STREAK_FOR_CLOSE = 2    # "an unacceptable_streak of at least two"
CLOSED_RECOMMENDATION_STATUSES = (
    "CLOSED_ACCEPTABLE",
    "CLOSED_UNACCEPTABLE",
    "CLOSED_EXCEEDS",
)

# --- Recommendation aging (PRD §3.7) -----------------------------------------
RESPONSE_WINDOW_DAYS = 90            # "more than ninety calendar days"
AGING_AMBER_MIN_BUSINESS_DAYS = 60   # "AMBER from sixty through eighty-nine inclusive"
AGING_RED_MIN_BUSINESS_DAYS = 90     # "RED at ninety business days or beyond"

# --- Board meetings (PRD §3.8) -----------------------------------------------
MIN_SITTING_MEMBERS = 3              # "at least three distinct members"
ROOM_TURNAROUND_BUFFER_MINUTES = 60  # "sixty-minute post-meeting turnaround buffer"

# --- Pagination (PRD §2.3) ---------------------------------------------------
PAGINATION_DEFAULT_LIMIT = 10        # "it defaults to 10 when omitted"
PAGINATION_MIN_LIMIT = 1             # "accepts a minimum of 1"
PAGINATION_MAX_LIMIT = 100           # "and a maximum of 100"

# --- Investigation phase order (PRD §3.5) ------------------------------------
# "GO_TEAM_ASSEMBLED → ON_SCENE → FACTUAL → ANALYSIS → BOARD_REVIEW"
PHASE_ORDER = ["GO_TEAM_ASSEMBLED", "ON_SCENE", "FACTUAL", "ANALYSIS", "BOARD_REVIEW"]

# --- Statutorily excluded party types (PRD §3.3) -----------------------------
EXCLUDED_ORG_TYPES = ("CLAIMANT_COUNSEL", "INSURER")

# --- Canonical operator identities used by fixtures --------------------------
# These match the identities threaded through the canonical setup chains; any
# string is acceptable to the API, but fixtures and tests should share these.
DEFAULT_IIC_USER_ID = "iic-1"
DEFAULT_CHAIRMAN_USER_ID = "gc-1"
DEFAULT_SITTING_MEMBER_IDS = ["bm-1", "bm-2", "bm-3"]
DEFAULT_ROOM_ID = "room-1"
DEFAULT_BENCH_ID = "bench-1"

# --- Canonical future windows (strictly after INITIAL_CLOCK_UTC) -------------
DEFAULT_MEETING_WINDOW_START = "2026-09-02T09:00:00Z"
DEFAULT_MEETING_WINDOW_END = "2026-09-02T10:00:00Z"
DEFAULT_SESSION_WINDOW_START = "2026-09-02T10:00:00Z"
DEFAULT_SESSION_WINDOW_END = "2026-09-02T12:00:00Z"

__all__ = [
    "INITIAL_CLOCK_UTC",
    "FATALITY_BASE_POINTS",
    "CATASTROPHIC_FATALITY_THRESHOLD",
    "CATASTROPHIC_FATALITY_BONUS",
    "DAMAGE_TIER_MID_MIN_CENTS",
    "DAMAGE_TIER_HIGH_MIN_CENTS",
    "DAMAGE_POINTS_LOW",
    "DAMAGE_POINTS_MID",
    "DAMAGE_POINTS_HIGH",
    "INJURY_CAP",
    "PUBLIC_TRANSPORT_POINTS",
    "MODAL_BUMP_POINTS",
    "MODAL_BUMP_CATEGORIES",
    "SCORE_MAX",
    "FULL_LAUNCH_THRESHOLD",
    "LIMITED_LAUNCH_THRESHOLD",
    "FATALITY_WEIGHT",
    "INJURY_WEIGHT",
    "PUBLIC_INTEREST_WEIGHT",
    "CATEGORY_DAMAGE_MULTIPLIER",
    "SUSPENSION_STRIKE_THRESHOLD",
    "UNACCEPTABLE_STREAK_FOR_CLOSE",
    "CLOSED_RECOMMENDATION_STATUSES",
    "RESPONSE_WINDOW_DAYS",
    "AGING_AMBER_MIN_BUSINESS_DAYS",
    "AGING_RED_MIN_BUSINESS_DAYS",
    "MIN_SITTING_MEMBERS",
    "ROOM_TURNAROUND_BUFFER_MINUTES",
    "PAGINATION_DEFAULT_LIMIT",
    "PAGINATION_MIN_LIMIT",
    "PAGINATION_MAX_LIMIT",
    "PHASE_ORDER",
    "EXCLUDED_ORG_TYPES",
    "DEFAULT_IIC_USER_ID",
    "DEFAULT_CHAIRMAN_USER_ID",
    "DEFAULT_SITTING_MEMBER_IDS",
    "DEFAULT_ROOM_ID",
    "DEFAULT_BENCH_ID",
    "DEFAULT_MEETING_WINDOW_START",
    "DEFAULT_MEETING_WINDOW_END",
    "DEFAULT_SESSION_WINDOW_START",
    "DEFAULT_SESSION_WINDOW_END",
]
