"""Business constants declared by the Police Professional Standards API contract.

Every value here is a literal the contract states. Tests import these instead of
re-typing magic numbers, so a boundary case such as "exactly 48 hours of notice"
reads as the rule it exercises.
"""

# ── Logical clock ──────────────────────────────────────────────────────────
# The clock starts at this instant on a fresh deployment and only moves when a
# SystemAdmin sets it.
CLOCK_STARTUP_DEFAULT = "2026-08-01T00:00:00Z"

# ── Roles ──────────────────────────────────────────────────────────────────
ROLE_COMPLAINANT = "Complainant"
ROLE_SUPERVISOR = "Supervisor"
ROLE_INVESTIGATOR = "Investigator"
ROLE_IA_COMMANDER = "IACommander"
ROLE_APPEALS_OFFICER = "AppealsOfficer"
ROLE_OFFICER_REPRESENTATIVE = "OfficerRepresentative"
ROLE_RECORDS_CUSTODIAN = "RecordsCustodian"
ROLE_SYSTEM_ADMIN = "SystemAdmin"

ALL_ROLES = (
    ROLE_COMPLAINANT,
    ROLE_SUPERVISOR,
    ROLE_INVESTIGATOR,
    ROLE_IA_COMMANDER,
    ROLE_APPEALS_OFFICER,
    ROLE_OFFICER_REPRESENTATIVE,
    ROLE_RECORDS_CUSTODIAN,
    ROLE_SYSTEM_ADMIN,
)

# ── Pagination ─────────────────────────────────────────────────────────────
DEFAULT_LIMIT = 10
MIN_LIMIT = 1
MAX_LIMIT = 100
DEFAULT_OFFSET = 0

# ── Intake ─────────────────────────────────────────────────────────────────
STATUTE_WINDOW_DAYS = 365
INTAKE_REFERENCE_PREFIX = "CMP-"
INTAKE_REFERENCE_DIGITS = 6
MAX_RECLASSIFICATIONS = 2

# ── Investigation windows, keyed by classification ─────────────────────────
STATUTORY_DAYS = {"CLASS_I": 180, "CLASS_II": 121, "CLASS_III": 90}
REQUIRED_CERTIFICATION_LEVEL = {"CLASS_I": 3, "CLASS_II": 2, "CLASS_III": 1}
PRIORITY_BY_CLASSIFICATION = {"CLASS_I": 1, "CLASS_II": 2, "CLASS_III": 3}

# ── Interviews ─────────────────────────────────────────────────────────────
MIN_NOTICE_HOURS = 48
REST_BUFFER_MINUTES = 60
MAX_POSTPONEMENTS = 2

# ── Findings and adjudication ──────────────────────────────────────────────
PREPONDERANCE_THRESHOLD_PCT = 50.00
MIN_EVIDENCE_WEIGHT = 0.00
MAX_EVIDENCE_WEIGHT = 100.00

# ── Discipline matrix ──────────────────────────────────────────────────────
# Base days indexed by offense class then prior tier (0, 1, 2).
MATRIX_BASE_DAYS = {
    "A": (30, 60, 120),
    "B": (10, 20, 45),
    "C": (3, 7, 15),
    "D": (1, 2, 5),
}
PRIOR_LOOKBACK_DAYS = 1095
AGGRAVATOR_DAYS_EACH = 5
MAX_CREDITED_MITIGATORS = 2
CLASS_A_FLOOR_DAYS = 30
GLOBAL_CAP_DAYS = 180
MAX_AGGRAVATOR_COUNT = 5
MAX_MITIGATOR_COUNT = 5

# ── Appeal, reinstatement and back pay ─────────────────────────────────────
APPEAL_WINDOW_DAYS = 15
BACK_PAY_PERIOD_DAYS = 10
BACK_PAY_WORKING_DAYS_PER_YEAR = 260
INTEREST_ANNUAL_RATE_PCT = 5
INTEREST_DAYS_PER_YEAR = 365

# ── Early intervention scoring ─────────────────────────────────────────────
EIS_WINDOW_DAYS = 365
EIS_DECAY_CUTOFF_DAYS = 180
EIS_DECAY_RECENT = 1.0
EIS_DECAY_AGED = 0.5
EIS_SCORE_SCALE = 2.5
EIS_INDICATOR_BONUS = 10
EIS_SCORE_MIN = 0
EIS_SCORE_MAX = 100
PEER_RELATIVE_SCALE = 40

EVENT_BASE_WEIGHTS = {
    "USE_OF_FORCE": 3,
    "PURSUIT": 2,
    "SICK_LEAVE_DAY": 1,
    "COMPLAINT_INTAKE": 1,
    "COMPLAINT_SUSTAINED": 4,
}
SEVERITY_MULTIPLIERS = {"LEVEL_1": 1.0, "LEVEL_2": 1.5, "LEVEL_3": 2.0, "NA": 1.0}
ASSIGNMENT_MULTIPLIERS = {"PATROL": 1.0, "INVESTIGATIVE": 0.8, "ADMIN": 0.6}

INDICATOR_THRESHOLDS = {
    "FORCE_COUNT": 3,
    "PURSUIT_COUNT": 2,
    "COMPLAINT_COUNT": 3,
    "SICK_LEAVE_DAYS": 12,
}
# The order the contract fixes for the breached_indicators array.
INDICATOR_ORDER = ("FORCE_COUNT", "PURSUIT_COUNT", "COMPLAINT_COUNT", "SICK_LEAVE_DAYS")

ALERT_BAND_CRITICAL = 75
ALERT_BAND_ALERT = 50
ALERT_BAND_WATCH = 30
ALERT_BANDS = ("NONE", "WATCH", "ALERT", "CRITICAL")

# ── Intervention plans ─────────────────────────────────────────────────────
REVIEW_DUE_DAYS = 30
MIN_REQUIRED_CHECKIN_COUNT = 2
MAX_REQUIRED_CHECKIN_COUNT = 6
ALLOWED_PLAN_DURATION_DAYS = (30, 60, 90)
COMPLIANCE_CONCERN_PENALTY = 15
PLAN_SUCCESS_COMPLIANCE_SCORE = 80

# ── Retention, disclosure and reporting ────────────────────────────────────
RETENTION_DAYS_BY_DISPOSITION = {
    "SUSTAINED": 2555,
    "POLICY_FAILURE": 1825,
    "NOT_SUSTAINED": 1825,
    "EXONERATED": 1095,
    "UNFOUNDED": 1095,
    "WITHDRAWN": 730,
}
# Most-serious-first precedence for choosing the governing disposition.
DISPOSITION_PRECEDENCE = (
    "SUSTAINED",
    "POLICY_FAILURE",
    "NOT_SUSTAINED",
    "EXONERATED",
    "UNFOUNDED",
    "WITHDRAWN",
)
DISCLOSURE_RETENTION_DAYS = 2555
SUPPRESSION_MIN_CELL = 3
SUPPRESSED_GROUP_KEY = "SUPPRESSED"
ALL_GROUP_KEY = "ALL"

# ── Ledger-bearing investigation statuses ──────────────────────────────────
OPEN_CASE_LOAD_STATUSES = ("ASSIGNED", "IN_PROGRESS", "TOLLED", "PENDING_REVIEW")
OPEN_ALERT_STATUSES = ("OPEN", "PLAN_REQUIRED", "PLAN_ACTIVE", "ESCALATED")
