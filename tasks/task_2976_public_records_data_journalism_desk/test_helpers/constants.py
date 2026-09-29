"""Domain constants for the Public Records Data Journalism Desk API test suite.

Every value here is transcribed from the PRD: paths from PRD S4, enum members
from PRD S3, and numeric constants from the calculation rules of PRD S2.7,
S2.10, S3.3, S3.7, S3.8 and S3.9.
"""

# --------------------------------------------------------------------------
# Paths (PRD S4; every resource lives under /records-desk except the clock)
# --------------------------------------------------------------------------

API_PREFIX = "/records-desk"
CLOCK_PATH = "/_clock/set_current_utc"

DESKS_PATH = f"{API_PREFIX}/desks"
AGENCIES_PATH = f"{API_PREFIX}/agencies"
RECORDS_REQUESTS_PATH = f"{API_PREFIX}/records-requests"
APPEALS_PATH = f"{API_PREFIX}/appeals"
DATASETS_PATH = f"{API_PREFIX}/datasets"
INVESTIGATIONS_PATH = f"{API_PREFIX}/investigations"
ANALYSIS_RUNS_PATH = f"{API_PREFIX}/analysis-runs"
FINDINGS_PATH = f"{API_PREFIX}/findings"
EXPERT_REVIEWERS_PATH = f"{API_PREFIX}/expert-reviewers"
REVIEW_ASSIGNMENTS_PATH = f"{API_PREFIX}/review-assignments"
SUBJECT_RESPONSE_REQUESTS_PATH = f"{API_PREFIX}/subject-response-requests"
SECURE_ENCLAVES_PATH = f"{API_PREFIX}/secure-enclaves"
ENCLAVE_SESSIONS_PATH = f"{API_PREFIX}/enclave-sessions"

# --------------------------------------------------------------------------
# Roles (PRD S2.1) -- the six recognised X-User-Role values
# --------------------------------------------------------------------------

ROLE_RECORDS_COORDINATOR = "RecordsCoordinator"
ROLE_DATA_REPORTER = "DataReporter"
ROLE_PEER_REVIEWER = "PeerReviewer"
ROLE_EXPERT_REVIEWER = "ExpertReviewer"
ROLE_MANAGING_EDITOR = "ManagingEditor"
ROLE_LEGAL_COUNSEL = "LegalCounsel"

ALL_ROLES = (
    ROLE_RECORDS_COORDINATOR,
    ROLE_DATA_REPORTER,
    ROLE_PEER_REVIEWER,
    ROLE_EXPERT_REVIEWER,
    ROLE_MANAGING_EDITOR,
    ROLE_LEGAL_COUNSEL,
)

# Roles whose X-User-ID is an opaque operator identifier (PRD S2.1).
OPAQUE_ROLES = (
    ROLE_RECORDS_COORDINATOR,
    ROLE_DATA_REPORTER,
    ROLE_PEER_REVIEWER,
    ROLE_MANAGING_EDITOR,
    ROLE_LEGAL_COUNSEL,
)

# --------------------------------------------------------------------------
# Logical clock (PRD S2.6)
# --------------------------------------------------------------------------

# "Before any client sets it, the logical clock reads exactly
# 2026-08-01T00:00:00Z" (PRD S2.6).
DEFAULT_CLOCK = "2026-08-01T00:00:00Z"

# The instant the worked examples of PRD S3.2 submit from.
STD_CLOCK = "2026-08-03T09:00:00Z"

# --------------------------------------------------------------------------
# Identifiers
# --------------------------------------------------------------------------

# A syntactically valid UUID that never resolves to a row. The framework ships
# its own NON_EXISTENT_UUID (all-zero); this one is a well-formed v4 shape so it
# cannot be mistaken for a sentinel by a stricter parser.
UNRESOLVABLE_ID = "00000000-0000-4000-8000-000000000000"

# --------------------------------------------------------------------------
# Deadline / retention stamping (PRD S2.6, S3.6)
# --------------------------------------------------------------------------

DEADLINE_TIME_OF_DAY = "23:59:59.000Z"
RETENTION_TIME_OF_DAY = "23:59:59.000Z"
MAX_CLARIFICATION_ROUNDS = 3

CALENDAR_DAYS = "CALENDAR_DAYS"
BUSINESS_DAYS = "BUSINESS_DAYS"
DEADLINE_BASES = (CALENDAR_DAYS, BUSINESS_DAYS)

# --------------------------------------------------------------------------
# Fee waiver and net fee (PRD S3.3)
# --------------------------------------------------------------------------

SMALL_BALANCE_WAIVE_THRESHOLD_CENTS = 1500
MAX_WAIVER_PCT = 0.95
TIER_1_MAX_GROSS_CENTS = 5000
TIER_1_PCT = 0.5
TIER_2_MAX_GROSS_CENTS = 20000
TIER_2_PCT = 0.75
TIER_3_PCT = 0.9
BONUS_HIGH_MIN_SCORE = 80
BONUS_HIGH_PCT = 0.1
BONUS_MID_MIN_SCORE = 60
BONUS_MID_PCT = 0.05

# --------------------------------------------------------------------------
# Analysis cost allocation (PRD S3.7)
# --------------------------------------------------------------------------

LABOR_RATE_CENTS_PER_HOUR = 6500

# --------------------------------------------------------------------------
# Disclosure risk scoring (PRD S3.9)
# --------------------------------------------------------------------------

PUBLISH_RISK_CEILING = 60
SOURCE_FIELD_AGGREGATE_BUMP = 10
SOURCE_FIELD_COMPOSITE_PENALTY = 25
SIZE_TIER_1_MAX_RECORDS = 1000
SIZE_MULT_1 = 1.0
SIZE_TIER_2_MAX_RECORDS = 100000
SIZE_MULT_2 = 1.25
SIZE_MULT_3 = 1.5
RISK_SCALE = 10

VARIANT_AGGREGATE_MAX = "AGGREGATE_MAX"
VARIANT_COMPOSITE_WEIGHTED = "COMPOSITE_WEIGHTED"
VARIANT_NONE = "NONE"

# "or NONE when publication would succeed" (PRD S3.9, preview endpoint).
BLOCKING_REASON_NONE = "NONE"

# --------------------------------------------------------------------------
# Subject notice sufficiency (PRD S3.9)
# --------------------------------------------------------------------------

MIN_NOTICE_HOURS = 72
MIN_DOCUMENTED_ATTEMPTS = 2
NOTICE_WINDOW_HOURS = 72

# --------------------------------------------------------------------------
# Readiness / security posture (PRD S3.7, S2.9)
# --------------------------------------------------------------------------

MIN_CONFIRMED_FINDINGS = 1
LOCKDOWN_MIN_SOURCE_INCIDENTS = 1
RESTRICTED_MIN_LITIGATION = 1

# --------------------------------------------------------------------------
# Field-definition ceiling (PRD S3.6)
# --------------------------------------------------------------------------

MAX_FIELD_DEFINITIONS = 40

# --------------------------------------------------------------------------
# Pagination (PRD S2.3)
# --------------------------------------------------------------------------

DEFAULT_LIMIT = 10
MIN_LIMIT = 1
MAX_LIMIT = 100
DEFAULT_OFFSET = 0

# --------------------------------------------------------------------------
# Enumerations (PRD S3)
# --------------------------------------------------------------------------

# Desk security posture (PRD S2.9)
POSTURE_OPEN = "OPEN"
POSTURE_RESTRICTED = "RESTRICTED"
POSTURE_LOCKDOWN = "LOCKDOWN"
SECURITY_POSTURES = (POSTURE_OPEN, POSTURE_RESTRICTED, POSTURE_LOCKDOWN)

# Source-exposure incident severity (PRD S3.1) -- audit only
SEVERITY_CODES = ("LOW", "MEDIUM", "HIGH", "CRITICAL")

# Appeal venue (PRD S3.1)
VENUE_INTERNAL = "INTERNAL"
VENUE_OMBUDS = "OMBUDS"
VENUE_COURT = "COURT"
APPEAL_VENUES = (VENUE_INTERNAL, VENUE_OMBUDS, VENUE_COURT)

# Formats (PRD S3.2, S3.6)
FORMAT_CSV = "CSV"
FORMAT_XLSX = "XLSX"
FORMAT_PDF_SCAN = "PDF_SCAN"
FORMAT_FIXED_WIDTH = "FIXED_WIDTH"
FORMAT_API_JSON = "API_JSON"
FORMATS = (
    FORMAT_CSV,
    FORMAT_XLSX,
    FORMAT_PDF_SCAN,
    FORMAT_FIXED_WIDTH,
    FORMAT_API_JSON,
)

# RecordsRequest status (PRD S3.2, S3.4, S3.5)
REQ_DRAFT = "DRAFT"
REQ_AWAITING_AGENCY_RESPONSE = "AWAITING_AGENCY_RESPONSE"
REQ_CLARIFICATION_REQUESTED = "CLARIFICATION_REQUESTED"
REQ_RELEASED = "RELEASED"
REQ_PARTIALLY_RELEASED = "PARTIALLY_RELEASED"
REQ_DENIED = "DENIED"
REQ_APPEAL_FILED = "APPEAL_FILED"
REQ_LITIGATION_AUTHORIZED = "LITIGATION_AUTHORIZED"
REQ_WITHDRAWN = "WITHDRAWN"

# Agency disposition outcomes (PRD S3.4)
OUTCOME_RELEASED_FULL = "RELEASED_FULL"
OUTCOME_RELEASED_PARTIAL = "RELEASED_PARTIAL"
OUTCOME_DENIED = "DENIED"

# Denial reason codes (PRD S3.4)
DENIAL_REASON_CODES = (
    "EXEMPT_PRIVACY",
    "EXEMPT_DELIBERATIVE",
    "EXEMPT_LAW_ENFORCEMENT",
    "NO_RECORDS",
    "FEE_UNPAID",
)

# Appeal status and ripeness basis (PRD S3.5)
APPEAL_FILED_STATUS = "FILED"
APPEAL_GRANTED = "GRANTED"
APPEAL_DENIED = "DENIED"
APPEAL_WITHDRAWN = "WITHDRAWN"

RIPENESS_DENIED = "DENIED"
RIPENESS_PARTIAL_RELEASE = "PARTIAL_RELEASE"
RIPENESS_OVERDUE = "OVERDUE"

# Dataset lifecycle (PRD S3.6)
DS_RAW = "RAW"
DS_CLEANING = "CLEANING"
DS_CLEAN_LOCKED = "CLEAN_LOCKED"
DS_QUARANTINED = "QUARANTINED"

FORMAT_NEG_REQUESTED = "REQUESTED"
FORMAT_NEG_AGREED = "AGREED"
FORMAT_NEG_REFUSED = "REFUSED"

DOC_STATUS_INCOMPLETE = "INCOMPLETE"
DOC_STATUS_COMPLETE = "COMPLETE"

SENSITIVITY_TIERS = ("PUBLIC", "RESTRICTED", "CONFIDENTIAL", "SOURCE_LINKED")

QUARANTINE_REASON_CODES = (
    "SOURCE_INTEGRITY",
    "MISMATCHED_TOTALS",
    "UNRESOLVED_NULLS",
    "LEGAL_HOLD",
)

# FieldDefinition (PRD S3.6)
DATA_TYPES = ("STRING", "INTEGER", "DECIMAL", "DATE", "BOOLEAN")
KNOWN_ISSUE_CODES = (
    "TRUNCATED",
    "MIXED_FORMAT",
    "INCONSISTENT_CODING",
    "OUT_OF_RANGE",
    "DUPLICATE_KEYS",
)
SUPPRESSION_METHODS = ("HASH_REDACT", "DROP_COLUMN", "COARSEN_BUCKET", "TOP_CODE")

# Investigation status (PRD S3.7, S3.9)
INV_DRAFTING = "DRAFTING"
INV_ANALYSIS = "ANALYSIS"
INV_FINDINGS_LOCKED = "FINDINGS_LOCKED"
INV_HOLD_LEGAL_REVIEW = "HOLD_LEGAL_REVIEW"
INV_CLEARED = "CLEARED"
INV_PUBLISHED = "PUBLISHED"

READINESS_READY = "READY"
READINESS_NOT_READY = "NOT_READY"

HOLD_REASON_SOURCE_EXPOSURE_INCIDENT = "SOURCE_EXPOSURE_INCIDENT"
HOLD_REASON_LITIGATION_AUTHORIZED = "LITIGATION_AUTHORIZED"

# Publication mode (PRD S3.7)
MODE_FULL_DATA_RELEASE = "FULL_DATA_RELEASE"
MODE_AGGREGATES_ONLY = "AGGREGATES_ONLY"
MODE_METHODOLOGY_ONLY = "METHODOLOGY_ONLY"
PUBLICATION_MODES = (
    MODE_FULL_DATA_RELEASE,
    MODE_AGGREGATES_ONLY,
    MODE_METHODOLOGY_ONLY,
)

# AnalysisRun dimensions (PRD S3.7)
REVIEW_PENDING = "PENDING_REVIEW"
REVIEW_CHANGES_REQUESTED = "CHANGES_REQUESTED"
REVIEW_APPROVED = "APPROVED"

ALLOC_NOT_ALLOCATED = "NOT_ALLOCATED"
ALLOC_ALLOCATED = "ALLOCATED"

# Finding verification (PRD S3.8)
FIND_UNVERIFIED = "UNVERIFIED"
FIND_DOC_MATCHED = "DOC_MATCHED"
FIND_SME_CONFIRMED = "SME_CONFIRMED"
FIND_SME_DISPUTED = "SME_DISPUTED"

VERDICT_CONFIRMED = "CONFIRMED"
VERDICT_DISPUTED = "DISPUTED"

# ReviewAssignment status (PRD S3.8)
ASSIGN_ASSIGNED = "ASSIGNED"
ASSIGN_COMPLETED = "COMPLETED"
ASSIGN_RELEASED = "RELEASED"

# ExpertReviewer expertise (PRD S3.8)
EXPERTISE_CODES = (
    "HOUSING",
    "PUBLIC_HEALTH",
    "POLICING",
    "PROCUREMENT",
    "STATISTICS",
)
DEFAULT_MAX_CONCURRENT_ASSIGNMENTS = 2

# SubjectResponseRequest (PRD S3.9)
SUBJ_DRAFT = "DRAFT"
SUBJ_NOTICE_ELIGIBLE = "NOTICE_ELIGIBLE"
SUBJ_NOTICE_SENT = "NOTICE_SENT"
SUBJ_RESPONDED = "RESPONDED"
SUBJ_NO_RESPONSE = "NO_RESPONSE"
SUBJ_UNREACHABLE = "UNREACHABLE"

CONTACT_CHANNELS = ("EMAIL", "PHONE", "CERTIFIED_MAIL", "IN_PERSON")

# SecureEnclave / EnclaveSession (PRD S3.9)
DEFAULT_SANITIZATION_BUFFER_MINUTES = 30

SESSION_BOOKED = "BOOKED"
SESSION_CLOSED = "CLOSED"
SESSION_CANCELLED = "CANCELLED"

CANCEL_REASON_INVESTIGATION_LEGAL_HOLD = "INVESTIGATION_LEGAL_HOLD"
CANCEL_REASON_DESK_LOCKDOWN = "DESK_LOCKDOWN"
