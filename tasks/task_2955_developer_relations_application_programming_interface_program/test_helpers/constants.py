"""Numeric tables, operator identities and canonical literals used across the suite.

Every table below is transcribed from the PRD; nothing here is invented.
"""

# --------------------------------------------------------------------------- clock
CLOCK_DEFAULT = "2026-08-01T00:00:00Z"

# --------------------------------------------------------------- operator identities
ADMIN_ID = "adm-1"
DEV_REL_MANAGER_ID = "drm-1"
DEV_REL_MANAGER_ALT_ID = "drm-2"
TRUST_OFFICER_ID = "tso-1"
TRUST_OFFICER_ALT_ID = "tso-2"
SUPPORT_AGENT_ID = "psa-1"
ANONYMOUS_ID = "anon-1"

# The id shape used by tests that address a syntactically valid but absent resource.
UNKNOWN_ID = "00000000-0000-4000-8000-000000000000"

# ---------------------------------------------------------------------- pagination
DEFAULT_LIMIT = 10
MAX_LIMIT = 100

# ------------------------------------------------------------------- trust scoring
TRUST_BASE = 50
CERTIFICATION_TRUST_POINTS = {"NONE": 0, "ASSOCIATE": 8, "PROFESSIONAL": 15}
DOCS_ACKNOWLEDGED_TRUST_POINTS = 6
HACKATHON_TRUST_POINTS_PER_AWARD = 4
HACKATHON_TRUST_AWARD_CAP = 3
CLEAN_WINDOW_TRUST_POINTS_EACH = 1
CLEAN_WINDOW_TRUST_CAP = 10
AUDITED_THROTTLE_PENALTY = 5
AUDITED_THROTTLED_WINDOW_THRESHOLD = 2
PENDING_POINTS_AUDIT_FACTOR = 0.50

# --------------------------------------------------------------- registration seeds
SEEDED_TRUST_SCORE = 50
DEFAULT_REQUIRED_TOS_VERSION = 1
CURRENT_DOCS_REVISION = 2

# --------------------------------------------------------------- provisioning table
TIER_BASE_SUSTAINED_RPM = {
    "SANDBOX": 60,
    "STANDARD": 600,
    "PARTNER": 3000,
    "PRIVILEGED": 12000,
}
TIER_MONTHLY_CALL_CAP = {
    "SANDBOX": 50000,
    "STANDARD": 1000000,
    "PARTNER": 10000000,
    "PRIVILEGED": 60000000,
}
TIER_SUSTAINED_RPM_CEILING = {
    "SANDBOX": 120,
    "STANDARD": 1200,
    "PARTNER": 6000,
    "PRIVILEGED": 24000,
}
TIER_RANK = {"SANDBOX": 0, "STANDARD": 1, "PARTNER": 2, "PRIVILEGED": 3}
TRUST_MULTIPLIER_BANDS = [
    (80, 100, 1.25),
    (60, 79, 1.00),
    (40, 59, 0.75),
    (0, 39, 0.50),
]
SCOPE_FACTOR_FLOOR = 0.60
BURST_FACTOR = {
    "SANDBOX": 1.5,
    "STANDARD": 2.0,
    "PARTNER": 3.0,
    "PRIVILEGED": 4.0,
}
BURST_CREDIT_MULTIPLIER = 10

# ---------------------------------------------------------------------- throttling
SOFT_THROTTLE_RATIO = 0.80
HARD_THROTTLE_RATIO = 1.00
WINDOW_MINUTES = 60

# ------------------------------------------------------------------- notice periods
NOTICE_DAYS_BASELINE = {"PUBLIC": 30, "PERSONAL": 60, "FINANCIAL": 90}
NOTICE_DAYS_BREAKING_SURCHARGE = 30
NOTICE_DAYS_PARTNER_PIN_SURCHARGE = 30
MAX_DEPRECATION_ANNOUNCED_PER_PRODUCT = 2

# ------------------------------------------------------------- justification floors
JUSTIFICATION_MIN_CHARS = {
    "SANDBOX": 0,
    "STANDARD": 40,
    "PARTNER": 120,
    "PRIVILEGED": 240,
}
MAX_REVISION_ROUNDS = 3

# --------------------------------------------------------------------- enforcement
VIOLATION_CATEGORY_BASE_POINTS = {
    "RATE_ABUSE": 10,
    "SCOPE_OVERREACH": 15,
    "DATA_RETENTION": 20,
    "RESALE": 25,
}
VIOLATION_SEVERITY_MULTIPLIER = {"LOW": 1, "MEDIUM": 2, "HIGH": 3}
REMEDIATION_DAYS = {"LOW": 30, "MEDIUM": 14, "HIGH": 7}
APPEAL_WINDOW_DAYS = 14
RESTRICTION_POINT_THRESHOLD = 50
REVOCATION_POINT_THRESHOLD = 100

# ------------------------------------------------------------------------- support
FIRST_RESPONSE_DUE_TICKET_MINUTES = {"S1": 30, "S2": 60, "S3": 240, "S4": 480}
FIRST_RESPONSE_DUE_INCIDENT_MINUTES = {"S1": 15, "S2": 30, "S3": 120, "S4": 240}
MAX_COMMUNICATION_GAP_MINUTES = {"S1": 30, "S2": 60, "S3": 240, "S4": 1440}
CREDIT_RATE_PER_DOWNTIME_MINUTE = {"S1": 0.10, "S2": 0.05, "S3": 0.02, "S4": 0.00}
CREDIT_GAP_BREACH_UPLIFT = 1.5
INCIDENT_COALESCE_BUFFER_MINUTES = 60

# ------------------------------------------------------------------------ feedback
FEEDBACK_SEVERITY_WEIGHT = {
    "DEFECT": 40,
    "MISSING_FEATURE": 25,
    "DX_FRICTION": 15,
    "DOC_GAP": 10,
}
FEEDBACK_TIER_WEIGHT = {
    "NONE": 0.25,
    "SANDBOX": 0.50,
    "STANDARD": 1.00,
    "PARTNER": 1.50,
    "PRIVILEGED": 2.00,
}
FEEDBACK_CERTIFICATION_BONUS = {"NONE": 0.00, "ASSOCIATE": 2.50, "PROFESSIONAL": 5.00}
DEMAND_INDEX_CAP = 0.50
DEMAND_INDEX_DIVISOR = 500

# ------------------------------------------------------- canonical fixture literals
CANONICAL_PRODUCT_NAME = "Catalog API"
CANONICAL_SCOPE = "catalog.read"
CANONICAL_WRITE_SCOPE = "catalog.write"
CANONICAL_SAMPLE_APP_SLUG = "catalog-quickstart"
CANONICAL_SUSTAINED_RPM_POOL = 20000
CANONICAL_MONTHLY_CALL_POOL = 50000000
CANONICAL_SEMVER = "1.0.0"
CANONICAL_REQUESTED_MONTHLY_CALLS = 500000

JUSTIFICATION_PARTNER = (
    "Our integration synchronises the public product catalogue into partner storefronts "
    "on a nightly schedule and requires sustained read throughput plus predictable monthly "
    "volume to complete each synchronisation run inside the agreed maintenance window."
)
JUSTIFICATION_STANDARD = (
    "We synchronise the public product catalogue nightly for a single storefront integration."
)
JUSTIFICATION_PRIVILEGED = JUSTIFICATION_PARTNER + " " + (
    "The privileged tier is additionally required because our clearing partners settle "
    "transactions against the same catalogue snapshot, so the integration must read the "
    "full catalogue within one settlement cycle and retain audit copies for reconciliation "
    "across every regional storefront that we operate under this programme agreement."
)
