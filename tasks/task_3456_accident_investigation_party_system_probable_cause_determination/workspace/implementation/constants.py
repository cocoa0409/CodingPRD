"""Named constants for the accident-investigation API.

Every threshold, weight, window, buffer, and enum set referenced anywhere in
the codebase is defined exactly once, here (PRD section 3 / SCAFFOLD
calculations table). Modules import from this module only.
"""

# --- Declared roles (PRD section 2.1) ---------------------------------------
ROLES = (
    "DutyOfficer",
    "ManagingDirector",
    "IIC",
    "GroupChairman",
    "PartyCoordinator",
    "AddresseeContact",
    "RecorderCustodian",
    "DocketOfficer",
    "BoardAdmin",
    "BoardMember",
)

# --- Enum sets ---------------------------------------------------------------
CASE_CATEGORIES = ("AVIATION", "RAIL", "HIGHWAY", "MARINE", "PIPELINE", "HAZMAT")
ORG_TYPES = (
    "OPERATOR",
    "MANUFACTURER",
    "UNION",
    "REGULATOR",
    "INDUSTRY_OTHER",
    "CLAIMANT_COUNSEL",
    "INSURER",
)
EXCLUDED_PARTY_ORG_TYPES = ("CLAIMANT_COUNSEL", "INSURER")
LAUNCH_MODES = ("FULL_GO_TEAM", "LIMITED", "DECLINED")
GROUP_SPECIALTIES = ("OPERATIONS", "STRUCTURES", "HUMAN_PERFORMANCE", "RECORDERS")
REPORT_KINDS = ("GROUP_FACTUAL", "RECORDER_TRANSCRIPT", "SPECIALIST")
RECORDER_TYPES = ("CVR", "FDR", "OTHER")
RECORDER_CONDITIONS = ("INTACT", "DAMAGED", "SEVERELY_DAMAGED")
VIOLATION_KINDS = (
    "PREMATURE_PUBLIC_STATEMENT",
    "UNAUTHORIZED_ANALYSIS_DISCLOSURE",
    "EX_PARTE_CONTACT",
)
INVESTIGATION_PHASES = (
    "GO_TEAM_ASSEMBLED",
    "ON_SCENE",
    "FACTUAL",
    "ANALYSIS",
    "BOARD_REVIEW",
    "ADOPTED",
)
VOTE_POSITIONS = ("ADOPT", "REJECT", "ABSTAIN", "RETRACT")
CLASSIFICATIONS = ("ACCEPTABLE", "UNACCEPTABLE")
CLOSE_OUTCOMES = ("CLOSED_ACCEPTABLE", "CLOSED_UNACCEPTABLE", "CLOSED_EXCEEDS")
RECOMMENDATION_CLOSED_STATUSES = CLOSE_OUTCOMES
RECOMMENDATION_RESPONSIBLE_STATUSES = (
    "OPEN_AWAITING_RESPONSE",
    "OPEN_ACCEPTABLE",
    "OPEN_UNACCEPTABLE",
)

# --- Statutory launch score (SCAFFOLD calculations.statutory_launch_score) ---
FATALITY_BASE_POINTS = 40
CATASTROPHIC_FATALITY_THRESHOLD = 5
CATASTROPHIC_FATALITY_BONUS = 15
DAMAGE_TIER_MID_MIN_CENTS = 1000000
DAMAGE_TIER_HIGH_MIN_CENTS = 10000000
DAMAGE_POINTS_LOW = 5
DAMAGE_POINTS_MID = 15
DAMAGE_POINTS_HIGH = 25
INJURY_CAP = 10
PUBLIC_TRANSPORT_POINTS = 20
MODAL_BUMP_POINTS = 10
MODAL_BUMP_CATEGORIES = ("AVIATION", "RAIL")
SCORE_MIN = 0
SCORE_MAX = 100
FULL_LAUNCH_THRESHOLD = 60
LIMITED_LAUNCH_THRESHOLD = 20

# --- Risk-adjusted launch score (calculations.risk_adjusted_launch_score) ----
FATALITY_WEIGHT = 1.0
INJURY_WEIGHT = 1.25
PUBLIC_INTEREST_WEIGHT = 0.5
CATEGORY_DAMAGE_MULTIPLIER = {
    "AVIATION": 1.0,
    "RAIL": 1.0,
    "HIGHWAY": 1.0,
    "MARINE": 1.25,
    "PIPELINE": 1.5,
    "HAZMAT": 2.0,
}

# --- Recommendation aging (calculations.recommendation_aging) ----------------
SECONDS_PER_DAY = 86400
RESPONSE_WINDOW_DAYS = 90
AGING_AMBER_MIN_BUSINESS_DAYS = 60
AGING_RED_MIN_BUSINESS_DAYS = 90

# --- Conduct strikes (calculations.strike_accumulation) ----------------------
SUSPENSION_STRIKE_THRESHOLD = 2

# --- Recommendation closure (PRD 3.7) ----------------------------------------
UNACCEPTABLE_STREAK_CLOSE_MIN = 2

# --- Board meetings ----------------------------------------------------------
QUORUM_MIN_DISTINCT_MEMBERS = 3
ROOM_TURNAROUND_BUFFER_MINUTES = 60

# --- Logical clock (PRD section 2.4) -----------------------------------------
LOGICAL_CLOCK_DEFAULT = "2026-09-01T00:00:00Z"

# --- Pagination (PRD section 2.3) --------------------------------------------
PAGE_DEFAULT_LIMIT = 10
PAGE_MIN_LIMIT = 1
PAGE_MAX_LIMIT = 100
PAGE_DEFAULT_OFFSET = 0
