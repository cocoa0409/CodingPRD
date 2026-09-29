"""Domain constants for the Student Data Privacy Vendor Vetting API.

Every literal here is taken from the PRD: role names, enum members, the
logical-clock default, the numeric range endpoints, the element-tier lookup
and the pinned justification / purpose strings whose *lengths* are what the
scoring rules actually read.
"""

# ---------------------------------------------------------------------------
# Roles (PRD §2.1)
# ---------------------------------------------------------------------------
ROLE_TEACHER = "Teacher"
ROLE_PRIVACY_ANALYST = "PrivacyAnalyst"
ROLE_VENDOR_LIAISON = "VendorLiaison"
ROLE_PRIVACY_OFFICE_ADMIN = "PrivacyOfficeAdmin"
ROLE_TELEMETRY_AGENT = "TelemetryAgent"

ALL_ROLES = (
    ROLE_TEACHER,
    ROLE_PRIVACY_ANALYST,
    ROLE_VENDOR_LIAISON,
    ROLE_PRIVACY_OFFICE_ADMIN,
    ROLE_TELEMETRY_AGENT,
)

# ---------------------------------------------------------------------------
# Logical clock (PRD §2.4 / §4)
# ---------------------------------------------------------------------------
CLOCK_DEFAULT = "2026-08-01T00:00:00Z"
CLOCK_DEFAULT_RENDERED = "2026-08-01T00:00:00.000Z"

# ---------------------------------------------------------------------------
# Vendor (PRD §3.1)
# ---------------------------------------------------------------------------
VENDOR_REGISTERED = "REGISTERED"
VENDOR_UNDER_REVIEW = "UNDER_REVIEW"
VENDOR_APPROVED = "APPROVED"
VENDOR_CONDITIONAL = "CONDITIONAL"
VENDOR_REJECTED = "REJECTED"
VENDOR_SUSPENDED = "SUSPENDED"

POSTURE_CLEAR = "CLEAR"
POSTURE_WATCH = "WATCH"
POSTURE_RESTRICTED = "RESTRICTED"
POSTURE_FROZEN = "FROZEN"

# PRD §2.9: the WATCH rung is inclusive at 45.
WATCH_THRESHOLD = 45
RISK_SCORE_CEILING = 100.00

# PRD §3.1 contractual-term penalty bands.
CONTRACT_PENALTY_FREE_HOURS = 72
CONTRACT_PENALTY_MID_HOURS = 168

# PRD §3.1 incident severity weights and the age-decay shelves.
INCIDENT_SEVERITY_WEIGHTS = {"LOW": 3, "MODERATE": 8, "HIGH": 18, "CRITICAL": 30}
DECAY_FULL_WEIGHT_DAYS = 90
DECAY_HALF_WEIGHT_DAYS = 365

FOREIGN_SUBPROCESSOR_PENALTY = 10

# ---------------------------------------------------------------------------
# Subprocessor (PRD §3.1)
# ---------------------------------------------------------------------------
SUBPROCESSOR_DISCLOSED = "DISCLOSED"
SUBPROCESSOR_VERIFIED = "VERIFIED"
SUBPROCESSOR_FLAGGED = "FLAGGED"
SUBPROCESSOR_REMOVED = "REMOVED"

DISPOSITION_VERIFY = "VERIFY"
DISPOSITION_FLAG = "FLAG"
DISPOSITION_REMOVE = "REMOVE"

# ---------------------------------------------------------------------------
# Application (PRD §3.1)
# ---------------------------------------------------------------------------
APPLICATION_CANDIDATE = "CANDIDATE"
APPLICATION_IN_REVIEW = "IN_REVIEW"
APPLICATION_APPROVED = "APPROVED"
APPLICATION_APPROVED_WITH_CONDITIONS = "APPROVED_WITH_CONDITIONS"
APPLICATION_BLOCKED = "BLOCKED"

CATEGORY_INSTRUCTIONAL_CONTENT = "INSTRUCTIONAL_CONTENT"
CATEGORY_ASSESSMENT = "ASSESSMENT"
CATEGORY_COMMUNICATION = "COMMUNICATION"
CATEGORY_ANALYTICS = "ANALYTICS"
CATEGORY_ADMINISTRATIVE = "ADMINISTRATIVE"

# PRD §3.1: max_permitted_tier is looked up from category at creation.
CATEGORY_MAX_PERMITTED_TIER = {
    CATEGORY_INSTRUCTIONAL_CONTENT: 2,
    CATEGORY_COMMUNICATION: 3,
    CATEGORY_ANALYTICS: 3,
    CATEGORY_ASSESSMENT: 4,
    CATEGORY_ADMINISTRATIVE: 4,
}

SSO_NONE = "NONE"
SSO_SAML2 = "SAML2"
SSO_OIDC = "OIDC"
SSO_LTI13 = "LTI13"

ACCESSIBILITY_NONE = "NONE"
ACCESSIBILITY_WCAG21_A = "WCAG21_A"
ACCESSIBILITY_WCAG21_AA = "WCAG21_AA"
ACCESSIBILITY_WCAG21_AAA = "WCAG21_AAA"

VISIBILITY_VISIBLE = "VISIBLE"
VISIBILITY_HIDDEN = "HIDDEN"

# ---------------------------------------------------------------------------
# Teacher / PrivacyAnalyst (PRD §3.2, §3.3)
# ---------------------------------------------------------------------------
STAFF_ACTIVE = "ACTIVE"
STAFF_INACTIVE = "INACTIVE"

CREDENTIAL_JUNIOR = "JUNIOR"
CREDENTIAL_SENIOR = "SENIOR"
CREDENTIAL_LEAD = "LEAD"

# ---------------------------------------------------------------------------
# ApplicationRequest (PRD §3.2)
# ---------------------------------------------------------------------------
REQUEST_DRAFT = "DRAFT"
REQUEST_SUBMITTED = "SUBMITTED"
REQUEST_RETURNED = "RETURNED"
REQUEST_TRIAGED_FOR_REVIEW = "TRIAGED_FOR_REVIEW"
REQUEST_DENIED = "DENIED"
REQUEST_CLOSED_APPROVED = "CLOSED_APPROVED"
REQUEST_CLOSED_BLOCKED = "CLOSED_BLOCKED"

REQUEST_OPEN_STATUSES = (
    REQUEST_SUBMITTED,
    REQUEST_RETURNED,
    REQUEST_TRIAGED_FOR_REVIEW,
)

TRIAGE_ACCEPT_FOR_REVIEW = "ACCEPT_FOR_REVIEW"
TRIAGE_RETURN = "RETURN"
TRIAGE_DENY = "DENY"

BAND_HIGH = "HIGH"
BAND_STANDARD = "STANDARD"
BAND_LOW = "LOW"

# PRD §3.2 priority scoring.
PRIORITY_SPAN_MULTIPLIER = 20
PRIORITY_BAND_HIGH_FLOOR = 60
PRIORITY_BAND_STANDARD_FLOOR = 30
PRIORITY_MULTIPLIERS = {BAND_HIGH: 1.20, BAND_STANDARD: 1.10, BAND_LOW: 0.85}
JUSTIFICATION_BONUS_TOP_CHARS = 400
JUSTIFICATION_BONUS_MID_CHARS = 240
JUSTIFICATION_BONUS_TOP_POINTS = 15
JUSTIFICATION_BONUS_MID_POINTS = 8

# PRD §3.2 submission gates.
JUSTIFICATION_MIN_CHARS = 120
REVISION_LIMIT = 2

# ---------------------------------------------------------------------------
# DataPracticeReview (PRD §3.3 - §3.6)
# ---------------------------------------------------------------------------
REVIEW_SCREENING = "SCREENING"
REVIEW_FINDINGS_ISSUED = "FINDINGS_ISSUED"
REVIEW_REMEDIATION_SUBMITTED = "REMEDIATION_SUBMITTED"
REVIEW_CLEARED = "CLEARED"
REVIEW_CONDITIONAL = "CONDITIONAL"
REVIEW_BLOCKED = "BLOCKED"

REVIEW_OPEN_STATUSES = (
    REVIEW_SCREENING,
    REVIEW_FINDINGS_ISSUED,
    REVIEW_REMEDIATION_SUBMITTED,
)

FRAMEWORK_FERPA = "FERPA"
FRAMEWORK_COPPA = "COPPA"
FRAMEWORK_PPRA = "PPRA"
FRAMEWORK_STATE_ADDENDUM = "STATE_ADDENDUM"
ALL_FRAMEWORKS = [
    FRAMEWORK_FERPA,
    FRAMEWORK_COPPA,
    FRAMEWORK_PPRA,
    FRAMEWORK_STATE_ADDENDUM,
]

DECISION_CLEAR = "CLEAR"
DECISION_CONDITIONAL = "CONDITIONAL"
DECISION_BLOCK = "BLOCK"

# PRD §3.5: remediation_due_at is the clock plus fourteen days - 336 hours.
REMEDIATION_WINDOW_HOURS = 336
REMEDIATION_ROUND_LIMIT = 3

# PRD §3.5 six weighted factors.
FACTOR_FRAMEWORK_POINTS = 30
FACTOR_MINIMIZATION_POINTS = 25
FACTOR_RETENTION_POINTS = 15
FACTOR_SUBPROCESSOR_POINTS = 15
FACTOR_ACCESSIBILITY_POINTS = 10
FACTOR_SSO_POINTS = 5
PENALTY_PER_FINDING = 8
PENALTY_PER_FLAGGED_SUBPROCESSOR = 12
PENALTY_MISSING_ADDENDUM = 20

# ---------------------------------------------------------------------------
# DataElementCommitment (PRD §3.4)
# ---------------------------------------------------------------------------
COMMITMENT_PROPOSED = "PROPOSED"
COMMITMENT_ACCEPTED = "ACCEPTED"
COMMITMENT_REJECTED = "REJECTED"
COMMITMENT_SUPERSEDED = "SUPERSEDED"

DISPOSITION_ACCEPT = "ACCEPT"
DISPOSITION_REJECT = "REJECT"

HARD_DELETE = "HARD_DELETE"
ANONYMIZE = "ANONYMIZE"
AGGREGATE_ONLY = "AGGREGATE_ONLY"

# PRD §3.4 element codes by sensitivity tier.
ELEMENT_STUDENT_NAME = "STUDENT_NAME"
ELEMENT_GRADE_LEVEL = "GRADE_LEVEL"
ELEMENT_PARENT_CONTACT = "PARENT_CONTACT"
ELEMENT_STUDENT_ID = "STUDENT_ID"
ELEMENT_EMAIL = "EMAIL"
ELEMENT_DOB = "DOB"
ELEMENT_GEOLOCATION = "GEOLOCATION"
ELEMENT_BEHAVIORAL_TELEMETRY = "BEHAVIORAL_TELEMETRY"
ELEMENT_PHOTO_VIDEO = "PHOTO_VIDEO"
ELEMENT_IEP_STATUS = "IEP_STATUS"
ELEMENT_HEALTH_RECORD = "HEALTH_RECORD"
ELEMENT_BIOMETRIC = "BIOMETRIC"
ELEMENT_DISCIPLINE_RECORD = "DISCIPLINE_RECORD"

ELEMENT_TIERS = {
    ELEMENT_STUDENT_NAME: 1,
    ELEMENT_GRADE_LEVEL: 1,
    ELEMENT_PARENT_CONTACT: 1,
    ELEMENT_STUDENT_ID: 2,
    ELEMENT_EMAIL: 2,
    ELEMENT_DOB: 2,
    ELEMENT_GEOLOCATION: 3,
    ELEMENT_BEHAVIORAL_TELEMETRY: 3,
    ELEMENT_PHOTO_VIDEO: 3,
    ELEMENT_IEP_STATUS: 4,
    ELEMENT_HEALTH_RECORD: 4,
    ELEMENT_BIOMETRIC: 4,
    ELEMENT_DISCIPLINE_RECORD: 4,
}

# PRD §3.4 statutory retention ceilings by tier.
TIER_RETENTION_CEILING = {1: 1825, 2: 1825, 3: 730, 4: 365}

# PRD §3.4 element_points factors.
TIER_WEIGHTS = {1: 1.00, 2: 2.50, 3: 6.00, 4: 13.00}
DELETION_MULTIPLIERS = {HARD_DELETE: 1.00, ANONYMIZE: 1.15, AGGREGATE_ONLY: 1.45}

# PRD §3.4 is_minimized soft caps.
MINIMIZED_RETENTION_CAP_DAYS = 365
PURPOSE_MIN_CHARS = 40

# ---------------------------------------------------------------------------
# CatalogEntry (PRD §3.7)
# ---------------------------------------------------------------------------
ENTRY_PUBLISHED = "PUBLISHED"
ENTRY_EXPIRING_SOON = "EXPIRING_SOON"
ENTRY_EXPIRED = "EXPIRED"
ENTRY_SUSPENDED_HOLD = "SUSPENDED_HOLD"
ENTRY_REVOKED = "REVOKED"
ENTRY_SUPERSEDED = "SUPERSEDED"

ENTRY_ACTIVE_STATUSES = (ENTRY_PUBLISHED, ENTRY_EXPIRING_SOON, ENTRY_SUSPENDED_HOLD)
ENTRY_VISIBLE_STATUSES = (ENTRY_PUBLISHED, ENTRY_EXPIRING_SOON)

# PRD §3.7: reauthorization_due_at is expires_at minus 30 days.
REAUTHORIZATION_LEAD_DAYS = 30

REVOKED_REASON_REVIEW_BLOCKED = "REVIEW_BLOCKED"

SWEEP_COUNTERS = (
    "evaluated_entry_count",
    "expiring_soon_count",
    "expired_count",
    "overdue_notification_count",
    "recomputed_vendor_count",
)

# ---------------------------------------------------------------------------
# TelemetryDetection (PRD §3.8)
# ---------------------------------------------------------------------------
DETECTION_NEW = "NEW"
DETECTION_CONFIRMED_AUTHORIZED = "CONFIRMED_AUTHORIZED"
DETECTION_BLOCKED = "BLOCKED"
DETECTION_WHITELISTED = "WHITELISTED"
DETECTION_ESCALATED = "ESCALATED"

SOURCE_NETWORK_DNS = "NETWORK_DNS"
SOURCE_BROWSER_EXTENSION = "BROWSER_EXTENSION"
SOURCE_MDM_INVENTORY = "MDM_INVENTORY"

CLASSIFICATION_AUTHORIZED = "AUTHORIZED"
CLASSIFICATION_EXPIRED_AUTHORIZATION = "EXPIRED_AUTHORIZATION"
CLASSIFICATION_UNAUTHORIZED = "UNAUTHORIZED"
CLASSIFICATION_UNKNOWN_DOMAIN = "UNKNOWN_DOMAIN"

TRIAGE_CONFIRM_AUTHORIZED = "CONFIRM_AUTHORIZED"
TRIAGE_BLOCK = "BLOCK"
TRIAGE_WHITELIST = "WHITELIST"
TRIAGE_ESCALATE = "ESCALATE"

# PRD §3.8 exposure_score coefficients and classification bases.
EXPOSURE_PER_DISTINCT_USER = 0.4
EXPOSURE_PER_SESSION = 0.05
CLASSIFICATION_BASE = {
    CLASSIFICATION_AUTHORIZED: 0,
    CLASSIFICATION_EXPIRED_AUTHORIZATION: 25,
    CLASSIFICATION_UNAUTHORIZED: 45,
    CLASSIFICATION_UNKNOWN_DOMAIN: 30,
}
EXPOSURE_SCORE_CEILING = 100.00
ESCALATION_DEFAULT_MAX_DATA_TIER = 3

# ---------------------------------------------------------------------------
# VendorIncident (PRD §3.9)
# ---------------------------------------------------------------------------
INCIDENT_REPORTED = "REPORTED"
INCIDENT_CONTAINED = "CONTAINED"
INCIDENT_REMEDIATED = "REMEDIATED"
INCIDENT_ESCALATED = "ESCALATED"

INCIDENT_OPEN_RESPONSE_STATUSES = (
    INCIDENT_REPORTED,
    INCIDENT_CONTAINED,
    INCIDENT_ESCALATED,
)

NOTIFICATION_PENDING = "PENDING"
NOTIFICATION_SENT = "SENT"
NOTIFICATION_OVERDUE = "OVERDUE"
NOTIFICATION_SENT_LATE = "SENT_LATE"

INCIDENT_BREACH = "BREACH"
INCIDENT_SUBPROCESSOR_CHANGE = "SUBPROCESSOR_CHANGE"
INCIDENT_RETENTION_VIOLATION = "RETENTION_VIOLATION"
INCIDENT_UNAUTHORIZED_DISCLOSURE = "UNAUTHORIZED_DISCLOSURE"

RESOLVE_REMEDIATE = "REMEDIATE"
RESOLVE_ESCALATE = "ESCALATE"

# PRD §3.9 severity thresholds.
SEVERITY_CRITICAL = "CRITICAL"
SEVERITY_HIGH = "HIGH"
SEVERITY_MODERATE = "MODERATE"
SEVERITY_LOW = "LOW"

SEVERITY_CRITICAL_STUDENT_FLOOR = 1000
SEVERITY_CRITICAL_TIER = 4
SEVERITY_HIGH_STUDENT_FLOOR = 100
SEVERITY_MODERATE_STUDENT_FLOOR = 10

# PRD §3.9 statutory notification ceilings in hours.
STATUTORY_NOTIFICATION_HOURS = {
    SEVERITY_CRITICAL: 24,
    SEVERITY_HIGH: 48,
    SEVERITY_MODERATE: 72,
    SEVERITY_LOW: 168,
}

# PRD §2.11: incident windows are widened 72 hours at both ends.
INCIDENT_WINDOW_BUFFER_HOURS = 72
UNCONTAINED_WINDOW_HOURS = 72

# ---------------------------------------------------------------------------
# Numeric ranges (PRD §2.5)
# ---------------------------------------------------------------------------
BREACH_NOTIFICATION_HOURS_MIN = 1
BREACH_NOTIFICATION_HOURS_MAX = 720
DATA_DELETION_DAYS_MIN = 1
DATA_DELETION_DAYS_MAX = 3650
RETENTION_DAYS_MIN = 1
RETENTION_DAYS_MAX = 1825
ESTIMATED_MINUTES_MIN = 15
ESTIMATED_MINUTES_MAX = 1200
REVIEW_CAPACITY_MINUTES_MIN = 15
REVIEW_CAPACITY_MINUTES_MAX = 12000
STUDENT_COUNT_ESTIMATE_MIN = 1
STUDENT_COUNT_ESTIMATE_MAX = 50000
MAX_DATA_TIER_MIN = 1
MAX_DATA_TIER_MAX = 4
AFFECTED_STUDENT_COUNT_MIN = 0
AFFECTED_STUDENT_COUNT_MAX = 500000
DISTINCT_USER_COUNT_MIN = 0
DISTINCT_USER_COUNT_MAX = 100000
SESSION_COUNT_MIN = 0
SESSION_COUNT_MAX = 1000000
GRADE_BAND_MIN = 0
GRADE_BAND_MAX = 12

# ---------------------------------------------------------------------------
# Pagination (PRD §2.3)
# ---------------------------------------------------------------------------
DEFAULT_LIMIT = 10
MIN_LIMIT = 1
MAX_LIMIT = 100

# ---------------------------------------------------------------------------
# Pinned text fixtures.  Their character counts are load-bearing: the
# justification bonus tiers of PRD §3.2, the 120-character submission floor
# and the 40-character minimization floor of PRD §3.4 all read length only.
# ---------------------------------------------------------------------------

# 426 characters -> justification bonus 15 (>= 400).
JUST_426 = (
    "Grade six through eight students use this product during the weekly "
    "formative assessment block, and teachers use the item-level reports "
    "during common planning time to build small reteaching groups, to adjust "
    "the pacing of the district scope and sequence, and to write the "
    "intervention notes that the multi-tiered support team reviews at every "
    "four-week data meeting held at each of the three participating middle "
    "school sites."
)

# 240 characters -> justification bonus 8 (>= 240, < 400).
JUST_240 = (
    "Grade seven and eight students use this tool for weekly formative "
    "practice aligned to the district scope and sequence, and teachers review "
    "item-level results during common planning time to regroup learners and "
    "plan targeted reteaching block"
)

# 140 characters -> above the 120-character floor, bonus 0.
JUST_140 = (
    "Weekly formative practice tool for two sections of grade six through "
    "eight; results guide small-group reteaching each Tuesday morning block."
)

# 122 characters -> above the 120-character floor, bonus 0.
JUST_122 = (
    "Students use this practice tool during the weekly formative block and "
    "teachers review the item reports to plan reteaching."
)

# 115 characters -> below the 120-character submission floor.
JUST_115 = (
    "Weekly practice tool for my two sections; results guide reteaching "
    "groups during common planning time each Tuesday."
)

# 61 characters -> at or above the 40-character minimization floor.
PURPOSE_61 = "Roster identity matching for gradebook sync and report cards."

# 35 characters -> below the 40-character minimization floor.
PURPOSE_35 = "Roster sync for gradebook and cards"

assert len(JUST_426) == 426
assert len(JUST_240) == 240
assert len(JUST_140) == 140
assert len(JUST_122) == 122
assert len(JUST_115) == 115
assert len(PURPOSE_61) == 61
assert len(PURPOSE_35) == 35

# ---------------------------------------------------------------------------
# A syntactically valid identifier that no row will ever carry.  It is a
# well-formed version-4 UUID so it clears the shape gate of PRD §2.5 and the
# request reaches the reference-resolution step that is under test.
# ---------------------------------------------------------------------------

UNKNOWN_UUID = "00000000-0000-4000-8000-000000000000"
