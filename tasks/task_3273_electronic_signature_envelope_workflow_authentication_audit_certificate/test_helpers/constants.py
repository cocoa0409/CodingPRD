"""Domain constants: thresholds, rates and arithmetic inputs from the PRD."""

# ---------------------------------------------------------------------------
# Credit spend consumption
# ---------------------------------------------------------------------------
PAGE_BLOCK = 10
FREE_SIGNERS = 5
SUSPENDED_DOUBLE = 2
TIER_MULTIPLIERS = {"STANDARD": 1.0, "PRO": 0.8, "ENTERPRISE": 0.5}

# ---------------------------------------------------------------------------
# Page fee / fee quote
# ---------------------------------------------------------------------------
PER_DOC_RATE = 12.335
PAGE_BASE = 1500.00
DISCOUNT_TIER_1_MAX = 500
DISCOUNT_TIER_2_MAX = 2000
RATE_TIER_1 = 0.02
RATE_TIER_2 = 0.03
RATE_TIER_3 = 0.04

# ---------------------------------------------------------------------------
# Authentication risk scoring
# ---------------------------------------------------------------------------
AUTH_BASE = {
    "EMAIL_ACCESS": 10,
    "ACCESS_CODE": 30,
    "KBA": 55,
    "ID_DOCUMENT": 80,
}
KBA_FAIL_STEP = 5
IDENTITY_BONUS = 15
RISK_CEILING = 100
PEER_TERM = 10
KBA_MAX_FAILURES = 3
RISK_ESCALATE_KBA = 60
RISK_ESCALATE_ID_DOCUMENT = 80

# ---------------------------------------------------------------------------
# Retention schedule (jurisdiction -> years from completion)
# ---------------------------------------------------------------------------
RETENTION_SCHEDULE = {"CA": 7, "IL": 5, "TX": 10}
RETENTION_DEFAULT_YEARS = 3

# ---------------------------------------------------------------------------
# Time
# ---------------------------------------------------------------------------
CLOCK_EPOCH = "2026-09-01T00:00:00Z"
REMINDER_COOLDOWN_HOURS = 24
EXPIRY_TIME_OF_DAY = "T23:59:59Z"

# ---------------------------------------------------------------------------
# Hash digests
# ---------------------------------------------------------------------------
HASH_HEX_LENGTH = 64

# ---------------------------------------------------------------------------
# Account defaults
# ---------------------------------------------------------------------------
DEFAULT_CREDIT_BALANCE = 1000
DEFAULT_PAGE_ALLOWANCE = 25
DEFAULT_TIER = "STANDARD"
DEFAULT_ACCOUNT_STATUS = "ACTIVE"

# ---------------------------------------------------------------------------
# Envelope / recipient / template defaults
# ---------------------------------------------------------------------------
DEFAULT_ROUTING_MODE = "SEQUENTIAL"
DEFAULT_EXPIRES_AFTER_DAYS = 120
DEFAULT_SENDER_VISIBLE_WINDOW_DAYS = 30
DEFAULT_AUTH_LEVEL = "EMAIL_ACCESS"
DEFAULT_TEMPLATE_AUTH_LEVEL = "EMAIL_ACCESS"

# Values the tests reuse.
TEST_ACCOUNT_NAME = "Acme Signing"
TEST_STATE_CODE = "CA"
TEST_SEED_ADJUSTMENT = 10000
TEST_SEED_REASON = "seed for tests"
DEFAULT_ACCESS_CODE = "P-7781"