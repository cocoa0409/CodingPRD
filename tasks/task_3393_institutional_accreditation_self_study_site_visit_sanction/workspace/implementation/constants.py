"""All constants transcribed exactly from PRD.md / SCAFFOLD.yaml.

Every numeric constant (CFI weights/bands, dues rates/multipliers, readiness
weights, tally points/tiers, quorum, cure-score formula, CDR/EMI bounds,
buffers, caps) appears here exactly once, per the PRD's pinned values.
"""
from decimal import Decimal

# --- Roles (PRD §2.1) ---------------------------------------------------------
ROLES = ["CommissionAdmin", "CommissionStaff", "InstitutionLiaison", "PeerReviewer"]

# --- Enum vocabularies --------------------------------------------------------
LEGAL_STATUSES = ["PUBLIC", "PRIVATE_NONPROFIT", "PRIVATE_FORPROFIT"]
DEGREE_LEVELS = ["ASSOCIATE", "BACCALAUREATE", "MASTERS", "DOCTORAL"]
CRITERION_CODES = [
    "CRIT_MISSION",
    "CRIT_INTEGRITY",
    "CRIT_TEACHING_QUALITY",
    "CRIT_TEACHING_EVALUATION",
    "CRIT_RESOURCES_PLANNING",
]
EVIDENCE_TYPES = ["INSTITUTIONAL_DATA", "ASSESSMENT_RESULT", "FINANCIAL_INDICATOR", "POLICY_DOCUMENT"]
PATHWAYS = ["STANDARD", "ACCELERATED"]
CYCLE_TYPES = ["INITIAL_ACCREDITATION", "REAFFIRMATION"]
VISIT_MODALITIES = ["ON_SITE", "VIRTUAL"]
REPORT_RECOMMENDATIONS = ["REAFFIRM", "GRANT", "NOTICE", "PROBATION", "SHOW_CAUSE", "DENY"]
VOTE_CHOICES = ["REAFFIRM", "GRANT", "NOTICE", "PROBATION", "SHOW_CAUSE", "DENY", "WITHDRAW"]
CRITERION_RATING_VALUES = ["MET", "MET_WITH_CONCERNS", "NOT_MET"]
CHANGE_TYPES = ["NEW_LOCATION", "PROGRAM_LEVEL", "OWNERSHIP_CHANGE", "DISTANCE_DELIVERY"]
SANCTION_TRANSITION_ACTIONS = ["OPEN_CURE_REVIEW", "CURE", "ESCALATE"]
ADJUDICATION_DECISIONS = ["APPROVE", "DENY", "REQUEST_COMPLETION"]
CHANGE_DECISIONS = ["APPROVE", "DENY", "DEFER"]
ASSIGNMENT_RESPONSES = ["ACCEPT", "DECLINE"]

# --- Logical clock (PRD §2.4) --------------------------------------------------
CLOCK_DEFAULT_ISO = "2026-09-01T00:00:00Z"

# --- Annual dues assessment (PRD §3.1) -----------------------------------------
BASE_DUES_CENTS = 250000
DUES_RATE_CENTS = {"ASSOCIATE": 33, "BACCALAUREATE": 45, "MASTERS": 61, "DOCTORAL": 83}
DUES_MULT = {
    "ASSOCIATE": Decimal("1.00"),
    "BACCALAUREATE": Decimal("1.00"),
    "MASTERS": Decimal("1.15"),
    "DOCTORAL": Decimal("1.35"),
}

# --- Composite financial index (PRD §3.9) --------------------------------------
CFI_SCALE_MIN = Decimal("-4.00")
CFI_SCALE_MAX = Decimal("10.00")
W_PRR_PRIVATE = Decimal("0.40")
W_VIAB_PRIVATE = Decimal("0.35")
W_NOR_PRIVATE = Decimal("0.25")
W_PRR_PUBLIC = Decimal("0.50")
W_VIAB_PUBLIC = Decimal("0.50")
APPROPRIATION_BONUS = Decimal("0.50")
APPROPRIATION_MIN_RATIO = Decimal("0.20")
CFI_CLEAR_ABOVE = Decimal("1.10")
CFI_PANEL_AT_OR_BELOW = Decimal("-0.90")

# --- Assurance readiness score (PRD §3.4) --------------------------------------
MIN_EVIDENCE_PER_CRITERION = 3
ARGUMENT_MIN_TOTAL_EVIDENCE = 15
READINESS_WEIGHTS = {
    "CRIT_MISSION": Decimal("0.15"),
    "CRIT_INTEGRITY": Decimal("0.25"),
    "CRIT_TEACHING_QUALITY": Decimal("0.25"),
    "CRIT_TEACHING_EVALUATION": Decimal("0.15"),
    "CRIT_RESOURCES_PLANNING": Decimal("0.20"),
}
MAX_ARGUMENT_REVISIONS = 2

# --- Recommended action determination (PRD §3.6) -------------------------------
RATING_POINTS = {"MET": 4, "MET_WITH_CONCERNS": 2, "NOT_MET": 0}
REAFFIRM_MIN_POINTS = 18
NOTICE_MIN_POINTS = 12
PROBATION_MIN_POINTS = 8

# --- Sanction cure determination (PRD §3.8) ------------------------------------
BASE_CURE_SCORE = 60
SANCTION_LEVEL_OFFSET = {"NOTICE": 0, "PROBATION": 15, "SHOW_CAUSE": 30}
CLEARED_REPORT_POINTS = 25
CURE_SCORE_CAP = 100
SANCTION_CURE_MONTHS = {"NOTICE": 12, "PROBATION": 24, "SHOW_CAUSE": 12}
SANCTION_LADDER_NEXT = {"NOTICE": "PROBATION", "PROBATION": "SHOW_CAUSE"}
SANCTION_LEVELS = ["NOTICE", "PROBATION", "SHOW_CAUSE"]

# --- Cohort default rate assessment (PRD §3.3) ---------------------------------
CDR_SINGLE_YEAR_PCT = Decimal("40.0")
CDR_CONSECUTIVE_YEAR_PCT = Decimal("30.0")
CDR_MAX_RATES = 3

# --- Enrollment momentum index (PRD §3.9) --------------------------------------
COMPLETION_NEUTRAL_PCT = Decimal("50.0")
RETENTION_NEUTRAL_PCT = Decimal("70.0")
EMI_FLAG_BELOW = Decimal("-5.00")

# --- Panel decision tally (PRD §3.7) -------------------------------------------
PANEL_SIZE = 7
PANEL_QUORUM = 5
TALLY_SEVERITY = {
    "WITHDRAW": 7,
    "SHOW_CAUSE": 6,
    "PROBATION": 5,
    "NOTICE": 4,
    "DENY": 3,
    "REAFFIRM": 2,
    "GRANT": 1,
}
CHOICE_TO_ACTION_TYPE = {
    "GRANT": "GRANT_INITIAL",
    "DENY": "DENIAL",
    "WITHDRAW": "WITHDRAWAL",
    "REAFFIRM": "REAFFIRMATION",
    "NOTICE": "NOTICE",
    "PROBATION": "PROBATION",
    "SHOW_CAUSE": "SHOW_CAUSE",
}

# --- Reviewer selection ranking (PRD §3.5) -------------------------------------
TEAM_MEMBER_MIN = 3
CHAIR_MIN_PRIOR_VISITS = 2
MAX_CONCURRENT_ASSIGNMENTS = 3

# --- Visit window buffers (PRD §3.6) -------------------------------------------
ONSITE_BUFFER_DAYS = 1
VIRTUAL_BUFFER_DAYS = 0

# --- Candidacy pathway lengths in years (PRD §3.2) -----------------------------
CANDIDACY_YEARS = {"STANDARD": 4, "ACCELERATED": 2}

# --- Pagination (PRD §2.3) ------------------------------------------------------
PAGE_DEFAULT_LIMIT = 10
PAGE_MIN_LIMIT = 1
PAGE_MAX_LIMIT = 100
PAGE_DEFAULT_OFFSET = 0
