"""Domain constants: roles, statuses, CDT codes, and thresholds.

Only names a reader of the PRD would recognize live here; every value is
pinned to a number or enum literal that appears in the PRD prose.
"""

# ─── API mount ────────────────────────────────────────────────────────────

API_PREFIX = "/dental"
CLOCK_PATH = API_PREFIX + "/_clock/set_current_utc"

# The PRD fixes the logical clock's pre-settlement instant.
CLOCK_INITIAL_INSTANT = "2026-09-01T00:00:00Z"

# ─── Roles ────────────────────────────────────────────────────────────────

ROLE_PLAN_ADMIN = "PlanAdmin"
ROLE_NETWORK_MANAGER = "NetworkManager"
ROLE_CLINICAL_REVIEWER = "ClinicalReviewer"
ROLE_CLAIMS_EXAMINER = "ClaimsExaminer"
ROLE_MEMBER = "Member"
ROLE_PROVIDER = "Provider"

# ─── Entity statuses ──────────────────────────────────────────────────────

PLAN_DRAFT = "DRAFT"
PLAN_ACTIVE = "ACTIVE"
PLAN_SUSPENDED = "SUSPENDED"
PLAN_RETIRED = "RETIRED"

PROVIDER_ACTIVE = "ACTIVE"
PROVIDER_TERMINATED = "TERMINATED"

SCHEDULE_PENDING = "PENDING"
SCHEDULE_ACTIVE = "ACTIVE"
SCHEDULE_SUPERSEDED = "SUPERSEDED"
SCHEDULE_RETIRED = "RETIRED"

SUBSCRIBER_ACTIVE = "ACTIVE"
SUBSCRIBER_TERMINATED = "TERMINATED"

DEPENDENT_ACTIVE = "ACTIVE"
DEPENDENT_TERMINATED = "TERMINATED"

RULE_ACTIVE = "ACTIVE"
RULE_RETIRED = "RETIRED"

PREDET_SUBMITTED = "SUBMITTED"
PREDET_UNDER_REVIEW = "UNDER_REVIEW"
PREDET_APPROVED = "APPROVED"
PREDET_DENIED = "DENIED"
PREDET_WITHDRAWN = "WITHDRAWN"
PREDET_EXPIRED = "EXPIRED"

CLAIM_RECEIVED = "RECEIVED"
CLAIM_PENDED_ATTACHMENTS = "PENDED_ATTACHMENTS"
CLAIM_PENDED_REVIEW = "PENDED_REVIEW"
CLAIM_ADJUDICATED = "ADJUDICATED"
CLAIM_PAID = "PAID"
CLAIM_DENIED = "DENIED"
CLAIM_VOID = "VOID"

LINE_PENDING = "PENDING"
LINE_PRICED = "PRICED"
LINE_PAYABLE = "PAYABLE"
LINE_DENIED = "DENIED"

# ─── Enums that appear in payloads ────────────────────────────────────────

TIER_PREMIER = "PREMIER"
TIER_PPO = "PPO"
TIER_OUT_OF_NETWORK = "OUT_OF_NETWORK"

CATEGORY_PREVENTIVE = "PREVENTIVE"
CATEGORY_BASIC = "BASIC"
CATEGORY_MAJOR = "MAJOR"

COB_PRIMARY = "PRIMARY"
COB_SECONDARY = "SECONDARY"
COB_NONE = "NONE"

RELATIONSHIP_SPOUSE = "SPOUSE"
RELATIONSHIP_CHILD = "CHILD"
RELATIONSHIP_DOMESTIC_PARTNER = "DOMESTIC_PARTNER"

RULE_FREQUENCY = "FREQUENCY"
RULE_AGE_MAX = "AGE_MAX"
RULE_AGE_MIN = "AGE_MIN"
RULE_REPLACEMENT_INTERVAL = "REPLACEMENT_INTERVAL"
RULE_MISSING_TOOTH = "MISSING_TOOTH"

ATTACHMENT_RADIOGRAPH = "RADIOGRAPH"
ATTACHMENT_NARRATIVE = "NARRATIVE"
ATTACHMENT_PERIO_CHART = "PERIO_CHART"
ATTACHMENT_PHOTO = "PHOTO"

DENIAL_WAITING_PERIOD = "WAITING_PERIOD"
DENIAL_FREQUENCY = "FREQUENCY"
DENIAL_AGE_LIMIT = "AGE_LIMIT"
DENIAL_MISSING_TOOTH = "MISSING_TOOTH"
DENIAL_TIMELY_FILING = "TIMELY_FILING"
DENIAL_ATTACHMENT_MISSING = "ATTACHMENT_MISSING"
DENIAL_NO_COVERAGE = "NO_COVERAGE"

# ─── CDT codes used across the suite ──────────────────────────────────────

CDT_PERIODIC_EVAL = "D0120"      # preventive oral evaluation
CDT_FILING_BASIC = "D2391"       # basic one-surface composite
CDT_CROWN_MAJOR = "D2740"        # major porcelain crown
CDT_CROWN_ALT = "D2799"          # alternate crown (ABP target)
CDT_SEALANT = "D1351"            # preventive sealant

# ─── Numeric thresholds pinned by the PRD ─────────────────────────────────

# Predetermination validity window: expires_on = approval + this many days.
PREDETERMINATION_VALIDITY_DAYS = 90

# Timely filing: received_date must be within this many days of service_date.
CLAIM_TIMELY_FILING_DAYS = 365

# Voiding a PAID claim is permitted only within this many days of payment.
VOID_WINDOW_DAYS = 30
