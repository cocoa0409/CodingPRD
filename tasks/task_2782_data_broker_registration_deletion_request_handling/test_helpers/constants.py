"""Domain thresholds and numeric constants used by the PRD calculations.

Every literal here is stated in the PRD; tests import them rather than
re-deriving values so that expected outcomes stay traceable to the contract.
"""

# --- logical clock -----------------------------------------------------------
CLOCK_STARTUP_DEFAULT = "2026-08-01T00:00:00Z"
CLOCK_TEST_INSTANT = "2026-09-01T00:00:00Z"

# --- filing fee assessment ---------------------------------------------------
BASE_FILING_FEE_CENTS = 40000
CATEGORY_SURCHARGE_CENTS = {
    "SOURCES": 1500,
    "RECIPIENTS": 2500,
    "RETENTION": 1200,
    "SENSITIVE_CATEGORIES": 6000,
    "OPT_OUT_MECHANISM": 1800,
    "MINORS_DATA": 7500,
}
SENSITIVE_MULTIPLIER = 1.35
COVERAGE_DAY_DIVISOR = 365

# --- disclosure completeness -------------------------------------------------
CATEGORY_WEIGHTS = {
    "SOURCES": 20.00,
    "RECIPIENTS": 25.00,
    "RETENTION": 15.00,
    "OPT_OUT_MECHANISM": 20.00,
    "SENSITIVE_CATEGORIES": 12.00,
    "MINORS_DATA": 8.00,
}
MIN_CONTENT_CHARS = 40
SHORT_CONTENT_FACTOR = 0.50
SUBMIT_COMPLETENESS_THRESHOLD = 80.00
REQUIRED_DISCLOSURE_CATEGORIES = [
    "SOURCES",
    "RECIPIENTS",
    "RETENTION",
    "OPT_OUT_MECHANISM",
]
OPTIONAL_DISCLOSURE_CATEGORIES = ["SENSITIVE_CATEGORIES", "MINORS_DATA"]

# --- identity assurance ------------------------------------------------------
METHOD_BASE = {
    "GOVT_ID": 55.00,
    "TWO_DATA_POINTS": 30.00,
    "PLATFORM_ASSERTION": 25.00,
    "AGENT_LOA": 35.00,
}
EVIDENCE_POINT_VALUE = 7.50
MAX_EVIDENCE_POINTS_COUNTED = 4
DOCUMENT_QUALITY_WEIGHT = 0.20
FRAUD_PENALTY_PER_PRIOR_FAIL = 12.00
PLATFORM_ASSERTED_FLOOR = 70.00
ATTEMPT_PASS_THRESHOLD = 70.00
ATTEMPT_INCONCLUSIVE_THRESHOLD = 50.00
MAX_SCORE = 100.00

# --- propagation plan and completion ----------------------------------------
TARGET_WEIGHT = {
    "ACTIVE_DATABASE": 40,
    "BACKUP_ARCHIVE": 20,
    "DERIVED_DATASET": 20,
    "DOWNSTREAM_RECIPIENT": 20,
}
INTERNAL_SLA_DAYS = {
    "ACTIVE_DATABASE": 5,
    "BACKUP_ARCHIVE": 45,
    "DERIVED_DATASET": 15,
}
WAIVER_CREDIT_FACTOR = 0.50
COMPLETION_BREACH_THRESHOLD = 0.7500

# --- downstream recipient reliability ---------------------------------------
RELIABILITY_START = 90.00
ACK_ON_TIME_BONUS = 2.00
ACK_LATE_PENALTY = 5.00
FAIL_PENALTY = 20.00
WAIVE_PENALTY = 25.00
RELIABILITY_FLOOR = 0.00
RELIABILITY_CEILING = 100.00
RECIPIENT_SUSPEND_THRESHOLD = 70.00

# --- temporal defaults -------------------------------------------------------
STANDING_SUSPEND_DAYS = 90
SUPPRESSION_DEFAULT_DAYS = 730
RECOLLECTION_BUFFER_DAYS = 30
AUDIT_RETENTION_DAYS = 2555
SIGNAL_HONOR_DEADLINE_DAYS = 45
TASK_ABANDON_GRACE_DAYS = 30

# --- regulator response adequacy --------------------------------------------
EVIDENCE_POINT_PER_CITED_EVENT = 15.00
MAX_CITED_EVENTS_COUNTED = 5
COVERAGE_BONUS = 15.00
MANDATORY_COVERAGE_EVENT_TYPES = [
    "DELETION_REQUEST_RECEIVED",
    "DELETION_EXECUTED",
    "SUPPRESSION_CREATED",
]
LATE_RESPONSE_PENALTY = 10.00
ADEQUATE_THRESHOLD = 65.00
RESPONSE_GRACE_DAYS = 30

# --- pagination --------------------------------------------------------------
PAGINATION_DEFAULT_LIMIT = 10
PAGINATION_MIN_LIMIT = 1
PAGINATION_MAX_LIMIT = 100
PAGINATION_DEFAULT_OFFSET = 0

# --- shared test defaults ----------------------------------------------------
TEST_DEFAULTS = {
    "FEE_DEPOSIT_CENTS": 500000,
    "COVERAGE_PERIOD_START": "2026-09-01T00:00:00Z",
    "COVERAGE_PERIOD_END": "2027-03-01T00:00:00Z",
    "ACK_SLA_DAYS": 20,
}
