"""Domain thresholds and constants for the Precision Ag Connectivity API.

Every numeric literal below is taken verbatim from PRD.md (sections 2.3-2.11
and 3.1-3.9).  Do not invent values here: if a number is not named in the PRD
it does not belong in this module.
"""

# --- Mount + logical clock (PRD sections 1 and 2.4) -------------------------

API_PREFIX = "/agdata"

#: The logical clock starts fixed at this instant when the server boots and
#: never falls back to wall-clock time.
CLOCK_START_UTC = "2026-09-01T00:00:00Z"

# --- Pagination defaults (PRD section 2.3) ----------------------------------

DEFAULT_PAGE_LIMIT = 10
MIN_PAGE_LIMIT = 1
MAX_PAGE_LIMIT = 100
DEFAULT_PAGE_OFFSET = 0

# --- Organization jurisdiction defaults (PRD section 3.1) -------------------

DEFAULT_RIGHT_TO_REPAIR_ENABLED = False
DEFAULT_INDEPENDENT_SESSION_MAX_MINUTES = 60

# --- Data plan tiers, prices, caps (PRD section 2.6) ------------------------

TIER_PRICE_CENTS = {
    "BASIC": 30000,
    "STANDARD": 60000,
    "UNLIMITED": 120000,
}

#: Monthly usage cap per tier; UNLIMITED has no cap at all.
TIER_CAP_MB = {
    "BASIC": 5120,
    "STANDARD": 20480,
    "UNLIMITED": None,
}

#: Usage posture thresholds on the exact used_mb / cap ratio (inclusive).
THROTTLE_AT_RATIO = 0.8
EXHAUST_AT_RATIO = 1.0

# --- THIRTY_DAY proration variant (PRD section 3.2) --------------------------

THIRTY_DAY_CYCLE_DAYS = 30

# --- Modem provisioning gate (PRD section 3.1) ------------------------------

#: Begin is allowed only while fewer than five attempts are recorded, so the
#: fifth begin is the last legal one.
PROVISIONING_MAX_ATTEMPTS = 5

# --- Uptime analytics (PRD section 3.8) -------------------------------------

UPTIME_WINDOW_HOURS = 720
OVERHAUL_BELOW_PCT = 70.0
SERVICE_BELOW_PCT = 85.0

#: Parts recommendation labels.
PARTS_OVERHAUL_KIT = "OVERHAUL_KIT"
PARTS_SERVICE_KIT = "SERVICE_KIT"
PARTS_NONE = "NONE"

# --- Warranty coverage gate and payout waterfall (PRD section 3.8) ----------

#: Claim submit requires the conservative uptime score to be at least this;
#: exactly 90.0 passes.
WARRANTY_MIN_COVERAGE_PCT = 90.0

AGE_FULL_COVER_MAX_MONTHS = 24
AGE_PARTIAL_COVER_MAX_MONTHS = 60

COVERAGE_PCT_FULL = 0.90
COVERAGE_PCT_PARTIAL = 0.70
COVERAGE_PCT_OLD = 0.50

LABOR_CAP_CENTS = {
    "STANDARD": 500000,
    "PREMIUM": 900000,
}

PAYOUT_MAX_CENTS = 2000000

# --- Feature license bundle fee (PRD section 3.7) ----------------------------

LICENSE_BASE_FEE_CENTS = {
    "AUTO_GUIDANCE": 120000,
    "SECTION_CONTROL": 180000,
    "VARIABLE_RATE_SPREAD": 90000,
    "TELEMATICS_PREMIUM": 60000,
}

BUNDLE_DISCOUNT_1 = 0.00
BUNDLE_DISCOUNT_2 = 0.10
BUNDLE_DISCOUNT_3_PLUS = 0.20

# --- Consent + certification time windows (PRD sections 2.4, 2.7, 3.9) -------

#: Every consent ticket is born REQUESTED with expires_at this many hours out.
CONSENT_TTL_HOURS = 72

#: CERTIFY sets certification_expires_on to the current date plus this many days.
CERT_VALIDITY_DAYS = 365

# --- Agronomic rounding precision (PRD sections 2.9, 3.3) --------------------

ZONE_QTY_DECIMALS = 2
AVG_RATE_DECIMALS = 3
UPTIME_SCORE_DECIMALS = 1
FIELD_AREA_DECIMALS = 2
