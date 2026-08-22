"""Domain constants read verbatim from PRD.md and SCAFFOLD.yaml.

Nothing here is entity data: these are the enum domains, role names and scoring
constants the specification pins.  The store itself boots empty.
"""

# ---- roles (PRD 2.1) -------------------------------------------------------
ELECTION_COMMISSIONER = "ElectionCommissioner"
FACULTY_ADVISOR = "FacultyAdvisor"
REGISTRAR = "Registrar"
CANDIDATE = "Candidate"
STUDENT_VOTER = "StudentVoter"

ALL_ROLES = (
    ELECTION_COMMISSIONER,
    FACULTY_ADVISOR,
    REGISTRAR,
    CANDIDATE,
    STUDENT_VOTER,
)

# ---- logical clock (PRD 2.4) ----------------------------------------------
CLOCK_DEFAULT_ISO = "2026-08-01T00:00:00Z"

# ---- enum domains (SCAFFOLD 1.1) ------------------------------------------
CLASS_YEARS = ("FRESHMAN", "SOPHOMORE", "JUNIOR", "SENIOR", "GRADUATE")
ENROLLMENT_STATUSES = ("ENROLLED", "LEAVE", "WITHDRAWN")

ELECTION_STATUSES = (
    "DRAFT", "PETITIONING", "BALLOT_BUILDING", "BALLOT_PUBLISHED", "VOTING_OPEN",
    "VOTING_CLOSED", "TALLYING", "CERTIFIED", "RUNOFF_SCHEDULED", "CLOSED",
)
BALLOT_INTEGRITY_STATUSES = ("INTACT", "RECOUNT_REQUIRED")

OFFICE_STATUSES = ("OPEN", "CONTESTED", "RUNOFF_REQUIRED", "DECIDED", "VACANT_SEAT")

CANDIDACY_STATUSES = (
    "DRAFT", "UNDER_REVIEW", "RETURNED", "ELIGIBLE", "PETITION_DEFICIENT",
    "SLATE_SUSPENDED", "ON_BALLOT", "RUNOFF_QUALIFIED", "ELECTED", "ELIMINATED",
    "VACATED", "WITHDRAWN", "DISQUALIFIED",
)
TRANSITION_STATUSES = ("NOT_APPLICABLE", "PENDING", "TRAINING_COMPLETE", "ACTIVE", "LAPSED")

SIGNATURE_STATUSES = ("SUBMITTED", "VERIFIED", "REJECTED", "VOIDED")
ELIGIBILITY_RESULTS = (
    "UNKNOWN", "ELIGIBLE", "INELIGIBLE_NOT_ENROLLED", "INELIGIBLE_CLASS_YEAR",
    "INELIGIBLE_HOLD",
)
ADJUDICATION_OUTCOMES = ("VERIFIED", "REJECTED")

EXPENSE_CATEGORIES = ("POSTER", "DIGITAL", "MERCH", "EVENT")
EXPENSE_STATUSES = ("REPORTED", "APPROVED", "REVERSED")

CASE_SEVERITIES = ("MINOR", "MAJOR", "SEVERE")
CASE_STATUSES = ("FILED", "UPHELD", "DISMISSED")

DRAFTING_STATUSES = ("DRAFT", "SUBMITTED", "RETURNED", "APPROVED_FOR_BALLOT", "ON_BALLOT")
OUTCOME_STATUSES = ("PENDING", "PASSED", "FAILED", "QUORUM_NOT_MET")
REVIEW_OUTCOMES = ("APPROVE", "RETURN")

BALLOT_STATUSES = ("DRAFT", "LOCKED", "PUBLISHED", "CLOSED", "VOIDED")
LINE_TYPES = ("CANDIDATE", "REFERENDUM")
LINE_STATUSES = ("ACTIVE", "VOIDED")

VOTE_STATUSES = ("CAST", "VOIDED")
VOTE_CHOICES = ("YES", "NO", "ABSTAIN")

APPEAL_STATUSES = ("FILED", "SUSTAINED", "DENIED")
REMEDIES = ("RECOUNT", "REINSTATEMENT", "VOID_ELECTION")

# ---- candidacy status sets used by the rule ladder --------------------------
# PRD 2.5 rule 9 / 3.4 / 3.3: expense reporting and signature creation are both
# refused when the referenced candidacy sits in one of these three postures.
CANDIDACY_CLOSED_FOR_LEDGER = ("WITHDRAWN", "DISQUALIFIED", "VACATED")
# PRD 3.5: upholding a case is permitted unless the respondent is one of these.
CANDIDACY_CLOSED_FOR_COMPLIANCE = ("WITHDRAWN", "VACATED")
# PRD 3.2: a live candidacy for the duplicate-filing rule.
CANDIDACY_DEAD_FOR_DUPLICATE = ("WITHDRAWN", "VACATED")
# PRD 3.2: postures a candidate may withdraw from.
CANDIDACY_WITHDRAWABLE = (
    "DRAFT", "UNDER_REVIEW", "RETURNED", "ELIGIBLE", "PETITION_DEFICIENT",
    "SLATE_SUSPENDED",
)

# ---- compliance scoring constants (SCAFFOLD 1.3 compliance_penalty_points) ---
PENALTY_BASE = {"MINOR": 5, "MAJOR": 15, "SEVERE": 40}
REPEAT_STEP = "0.5"
VOTING_WINDOW_FACTOR = "1.5"
OVERSPEND_CENTS_PER_POINT = 1000
OVERSPEND_POINTS_CAP = 25
PENALTY_POINTS_MAX = 100
DISQUALIFICATION_POINT_THRESHOLD = 60

# ---- interval geometry (PRD 2.10) ------------------------------------------
TEARDOWN_BUFFER_MINUTES = 30

# ---- defaults (PRD 3.1 / 3.6) ----------------------------------------------
DEFAULT_QUIET_PERIOD_HOURS = 24
DEFAULT_SEAT_COUNT = 1
DEFAULT_MIN_GPA = "2.00"
DEFAULT_MIN_CREDITS = 0
DEFAULT_REQUIRED_TRAINING_MODULES = 3
DEFAULT_APPROVAL_THRESHOLD_PCT = "66.67"

# ---- pagination (SCAFFOLD response_envelope.pagination_defaults) ------------
PAGE_LIMIT_DEFAULT = 10
PAGE_LIMIT_MIN = 1
PAGE_LIMIT_MAX = 100
PAGE_OFFSET_DEFAULT = 0
