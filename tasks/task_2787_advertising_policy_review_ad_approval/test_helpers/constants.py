"""Domain constants quoted from the PRD's numeric and enumeration prose.

Everything here is lifted from PRD §2.3, §2.6, §2.8, §2.11, §3.1-§3.9. Nothing is
invented and nothing is recomputed: the suite compares against these literals so
a drifting implementation constant is caught at its source.
"""

# --- The logical clock (PRD §2.8) -------------------------------------------
# "Before any call is made the logical clock reads exactly `2026-08-01T00:00:00Z`"
CLOCK_START_INSTANT = "2026-08-01T00:00:00.000Z"

# --- Pagination (PRD §2.3) ---------------------------------------------------
PAGINATION = {
    "DEFAULT_LIMIT": 10,
    "DEFAULT_OFFSET": 0,
    "MIN_LIMIT": 1,
    "MAX_LIMIT": 100,
}

# --- Roles (PRD §2.1) --------------------------------------------------------
ROLES = ["Advertiser", "PolicyReviewer", "IntegrityAnalyst", "PolicyAdmin"]

# --- Policy rule defaults and ranges (PRD §3.1) ------------------------------
POLICY_RULE_DEFAULTS = {
    "requires_certification": False,
    "requires_disclaimer": False,
    "confidence_auto_disapprove_threshold": 0.90,
    "confidence_manual_threshold": 0.55,
    "review_sla_hours": 48,
    "default_queue": "STANDARD",
}

POLICY_RULE_RANGES = {
    "BASE_SEVERITY_WEIGHT_MIN": 0.01,
    "BASE_SEVERITY_WEIGHT_MAX": 20.00,
    "SEVERITY_MULTIPLIER_MIN": 0.50,
    "SEVERITY_MULTIPLIER_MAX": 3.00,
    "CONFIDENCE_MIN": 0.01,
    "CONFIDENCE_MAX": 1.00,
    "REVIEW_SLA_HOURS_MIN": 1,
    "REVIEW_SLA_HOURS_MAX": 336,
}

# "`severity_multiplier` ... defaults to `1.00` when omitted" (PRD §3.1)
DEFAULT_SEVERITY_MULTIPLIER = 1.00
# "a country with no variation for the rule contributes `1.00`" (PRD §3.1)
NEUTRAL_COUNTRY_MULTIPLIER = 1.00

CATEGORY_CLASSES = ["PROHIBITED", "RESTRICTED", "REGULATED"]
DISPOSITIONS = [
    "BLOCKED",
    "RESTRICTED_CERT_REQUIRED",
    "ALLOWED_WITH_DISCLAIMER",
    "ALLOWED",
]
# "harshness order `BLOCKED` > `RESTRICTED_CERT_REQUIRED` >
#  `ALLOWED_WITH_DISCLAIMER` > `ALLOWED`" (PRD §3.1)
DISPOSITION_HARSHNESS = {
    "BLOCKED": 4,
    "RESTRICTED_CERT_REQUIRED": 3,
    "ALLOWED_WITH_DISCLAIMER": 2,
    "ALLOWED": 1,
}
# The tier fallback when a rule has no variation in a country (PRD §3.1)
TIER_FALLBACK_DISPOSITION = {
    "PROHIBITED": "BLOCKED",
    "RESTRICTED": "RESTRICTED_CERT_REQUIRED",
    "REGULATED": "ALLOWED",
}

QUEUES = ["STANDARD", "REGULATED_CERT", "POLITICAL"]

# --- Advertiser posture (PRD §3.2) -------------------------------------------
VERIFICATION_DIMENSIONS = [
    "IDENTITY",
    "BUSINESS_STANDING",
    "INDUSTRY_AUTHORIZATION",
    "POLITICAL_ELIGIBILITY",
]
VERIFICATION_OUTCOMES = {
    "IDENTITY": ["PENDING", "VERIFIED", "FAILED"],
    "BUSINESS_STANDING": ["PENDING", "VERIFIED", "FAILED"],
    "INDUSTRY_AUTHORIZATION": ["NOT_REQUIRED", "PENDING", "GRANTED", "DENIED"],
    "POLITICAL_ELIGIBILITY": ["NOT_REQUESTED", "PENDING", "ELIGIBLE", "INELIGIBLE"],
}
ACCOUNT_STATUSES = ["ACTIVE", "WARNED", "RESTRICTED", "SUSPENDED"]
# "an in-force `WARNING` yields `WARNED`, an in-force `RESTRICTION` yields
#  `RESTRICTED`, and an in-force `SUSPENSION` yields `SUSPENDED`" (PRD §3.2)
ACTION_TYPE_TO_ACCOUNT_STATUS = {
    "WARNING": "WARNED",
    "RESTRICTION": "RESTRICTED",
    "SUSPENSION": "SUSPENDED",
}

# --- Creative state axes (PRD §3.3) -----------------------------------------
REVIEW_STATUSES = [
    "DRAFT",
    "SCREENING",
    "AUTO_APPROVED",
    "PENDING_MANUAL_REVIEW",
    "APPROVED_LIMITED",
    "DISAPPROVED",
    "SUSPENDED_HOLD",
    "WITHDRAWN",
]
DESTINATION_STATUSES = [
    "NOT_CHECKED",
    "DESTINATION_PENDING",
    "DESTINATION_CLEARED",
    "MISMATCH_FLAGGED",
    "CLOAKING_CONFIRMED",
]

# --- The serving gate (PRD §2.11) -------------------------------------------
BLOCKING_REASON_CODES = [
    "REVIEW_NOT_APPROVED",
    "DESTINATION_NOT_CLEARED",
    "ACCOUNT_ENFORCEMENT",
    "POLITICAL_ARCHIVE_MISSING",
]
# "a freshly created creative ... `blocking_reason_codes` exactly
#  `[REVIEW_NOT_APPROVED, DESTINATION_NOT_CLEARED]`" (PRD §2.11)
FRESH_BLOCKING_REASON_CODES = ["REVIEW_NOT_APPROVED", "DESTINATION_NOT_CLEARED"]
SERVING_APPROVED_REVIEW_STATUSES = ["AUTO_APPROVED", "APPROVED_LIMITED"]
SERVING_OK_ACCOUNT_STATUSES = ["ACTIVE", "WARNED"]

# --- Screening (PRD §3.4) ---------------------------------------------------
DISPOSITION_AUTO_DISAPPROVE = "AUTO_DISAPPROVE"
DISPOSITION_ROUTE_MANUAL = "ROUTE_MANUAL"
DISPOSITION_BELOW_THRESHOLD = "BELOW_THRESHOLD"
SCREENING_OUTCOMES = ["AUTO_APPROVED", "ROUTED_MANUAL", "AUTO_DISAPPROVED"]
QUALIFYING_DISPOSITIONS = ["AUTO_DISAPPROVE", "ROUTE_MANUAL"]

# --- Risk scoring (PRD §3.4) ------------------------------------------------
RISK = {
    "MIN": 0.00,
    "MAX": 100.00,
    # "40.00 when `destination_status` is `CLOAKING_CONFIRMED`, 15.00 when it is
    #  `MISMATCH_FLAGGED`, and 0.00 otherwise"
    "PENALTY_CLOAKING_CONFIRMED": 40.00,
    "PENALTY_MISMATCH_FLAGGED": 15.00,
    "PENALTY_NONE": 0.00,
    # "8.00 multiplied by the number of distinct finding rules ... capped at 24.00"
    "CERTIFICATION_CREDIT_PER_RULE": 8.00,
    "CERTIFICATION_CREDIT_CAP": 24.00,
}

# --- Review task priority (PRD §3.6) ---------------------------------------
PRIORITY = {
    "QUEUE_BASE": {"STANDARD": 30.00, "REGULATED_CERT": 45.00, "POLITICAL": 60.00},
    "SEVERITY_FACTOR": 2.00,
    "SEVERITY_CAP": 30.00,
    "HISTORY_DIVISOR": 10.00,
    "HISTORY_STEP": 5.00,
    "HISTORY_CAP": 15.00,
    "VERIFICATION_GAP": 10.00,
    "DISCLOSURE_GAP": 12.00,
    "CAP": 100.00,
}
DEFAULT_MAX_CONCURRENT_CLAIMS = 3
MAX_CONCURRENT_CLAIMS_RANGE = (1, 10)
# "when there is no primary rule the deadline is the creation instant plus 48 hours"
DEFAULT_SLA_HOURS = 48

TASK_STATUSES = ["QUEUED", "CLAIMED", "RESOLVED", "ESCALATED", "EXPIRED"]
TASK_RESOLUTIONS = [
    "PENDING",
    "APPROVE",
    "APPROVE_WITH_LIMITS",
    "DISAPPROVE",
    "ESCALATE",
]
REVIEWER_STATUSES = ["ACTIVE", "OFFLINE"]

# --- Certifications (PRD §3.5) ---------------------------------------------
CERTIFICATION_STATUSES = ["SUBMITTED", "ACTIVE", "EXPIRED", "REVOKED"]
CERTIFICATION_TERMINAL_STATUSES = ["EXPIRED", "REVOKED"]

# --- Disapproval notices and the points assessment (PRD §3.9) --------------
NOTICE_REASON_CODES = [
    "AUTO_SCREENING",
    "MANUAL_REVIEW",
    "DESTINATION_MISMATCH",
    "CLOAKING",
    "CERT_MISSING",
    "POLITICAL_DISCLOSURE",
]
# "`AUTO_SCREENING` 0.80, `MANUAL_REVIEW` 1.00, `CERT_MISSING` 0.60, `CLOAKING`
#  2.00, `DESTINATION_MISMATCH` 1.25, `POLITICAL_DISCLOSURE` 1.50" (PRD §3.9)
REASON_FACTORS = {
    "AUTO_SCREENING": 0.80,
    "MANUAL_REVIEW": 1.00,
    "CERT_MISSING": 0.60,
    "CLOAKING": 2.00,
    "DESTINATION_MISMATCH": 1.25,
    "POLITICAL_DISCLOSURE": 1.50,
}
# "in this fixed sequence: `CERT_MISSING`, `CLOAKING`, `DESTINATION_MISMATCH`,
#  `POLITICAL_DISCLOSURE`" (PRD §3.9)
INTEGRITY_REASON_SEQUENCE = [
    "CERT_MISSING",
    "CLOAKING",
    "DESTINATION_MISMATCH",
    "POLITICAL_DISCLOSURE",
]
ASSESSMENT = {
    "INTEGRITY_LINE_BASE": 10.00,
    "POINTS_CAP": 100.00,
}
NOTICE_STATUSES = [
    "ISSUED",
    "APPEALED",
    "APPEAL_GRANTED",
    "APPEAL_UPHELD",
    "EXPIRED",
]
# "`appeal_window_hours` is 168 when `political_at_issue` is true and 72 otherwise"
APPEAL_WINDOW_HOURS_POLITICAL = 168
APPEAL_WINDOW_HOURS_STANDARD = 72

APPEAL_STATUSES = ["SUBMITTED", "GRANTED", "DENIED"]

# --- Violation ledger and decay (PRD §3.9) ---------------------------------
LEDGER_REASONS = ["DISAPPROVAL_ASSESSED", "APPEAL_REVERSAL"]
DECAY = {
    # "full weight while the age is strictly below 90 days, half weight from 90
    #  days up to but not including 180 days, and zero weight from 180 days on"
    "FULL_WEIGHT_MAX_DAYS": 90,
    "HALF_WEIGHT_MAX_DAYS": 180,
    "FULL_WEIGHT": 1.00,
    "HALF_WEIGHT": 0.50,
    "ZERO_WEIGHT": 0.00,
    "SECONDS_PER_DAY": 86400,
}

# --- Severity index and enforcement (PRD §3.9) -----------------------------
SEVERITY_INDEX = {
    # "5.00 multiplied by the number of the advertiser's enforcement actions in
    #  status SUPERSEDED, LIFTED or EXPIRED"
    "PRIOR_ACTION_POINTS": 5.00,
    "SURCHARGE_NONE": 0.00,
    "SURCHARGE_MID": 3.50,
    "SURCHARGE_HIGH": 9.00,
    "SURCHARGE_MID_FLOOR": 20.00,
    "SURCHARGE_HIGH_FLOOR": 35.00,
}
CLOSED_ACTION_STATUSES = ["SUPERSEDED", "LIFTED", "EXPIRED"]
# "`SUSPENSION` when the index is 40.00 or more, `RESTRICTION` at 25.00 or more,
#  `WARNING` at 10.00 or more, and no action at all below 10.00" (PRD §3.9)
ACTION_TYPE_THRESHOLDS = {
    "SUSPENSION": 40.00,
    "RESTRICTION": 25.00,
    "WARNING": 10.00,
}
ACTION_SEVERITY_RANK = {"WARNING": 1, "RESTRICTION": 2, "SUSPENSION": 3}
ENFORCEMENT_DURATION_DAYS = {"WARNING": 30, "RESTRICTION": 60, "SUSPENSION": 180}
# "the cooldown window of an existing action runs from its `effective_from`
#  through its `effective_until` plus 72 hours, inclusive at both ends"
ENFORCEMENT_COOLDOWN_HOURS = 72
LIFT_THRESHOLDS = {"WARNING": 10.00, "RESTRICTION": 25.00, "SUSPENSION": 40.00}
ACTION_STATUSES = ["ACTIVE", "LIFTED", "SUPERSEDED", "EXPIRED"]
ACTION_ORIGINS = ["SYSTEM_CASCADE", "MANUAL"]

# --- Political archive (PRD §3.7) ------------------------------------------
# "`retention_until` is `archived_at` plus 2555 days"
ARCHIVE_RETENTION_DAYS = 2555

# --- Destination checks (PRD §3.8) -----------------------------------------
CHECK_TYPES = ["INITIAL", "RECHECK"]
USER_AGENT_VARIANTS = ["CRAWLER", "USER"]
DESTINATION_RESULTS = ["CLEARED", "MISMATCH", "CLOAKING"]
MISMATCH_DETAILS = [
    "HOST_MISMATCH",
    "CATEGORY_MISMATCH",
    "UA_DIVERGENCE",
    "DEST_UNREACHABLE",
]
# "an `http_status` of 400 or above" (PRD §3.8)
UNREACHABLE_HTTP_STATUS_FLOOR = 400
GENERAL_CONTENT_CATEGORY = "GENERAL"

# --- The sweep counter block (PRD §2.8) ------------------------------------
SWEEP_COUNTERS = [
    "activated_certifications",
    "expired_certifications",
    "expired_notices",
    "expired_review_tasks",
    "requeued_review_tasks",
    "expired_enforcement_actions",
    "lifted_enforcement_actions",
    "released_hold_creatives",
    "decay_refreshed_advertisers",
]
