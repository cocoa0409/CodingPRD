"""Domain thresholds — numeric constants from PRD calculations."""

# Logical clock startup default (PRD §2.5).
CLOCK_START_DEFAULT = "2027-03-01T00:00:00Z"

# Accreditation (PRD §3.1).
TECHNICAL_TEST_PASS_SCORE = 80
IANA_NUMBER_MIN = 1
IANA_NUMBER_MAX = 99999

# Lifecycle windows (PRD §3.3).
AUTO_RENEW_GRACE_DAYS = 45
REDEMPTION_GRACE_DAYS = 30
PENDING_DELETE_DAYS = 5
MAX_TERM_YEARS = 10

# Premium surcharge (PRD §2.6).
PREMIUM_SURCHARGE_RATE = 0.10

# Price governance (PRD §2.7).
ANNUAL_CAP_RATE = 0.10
NOTICE_DAYS = 180

# Transfers (PRD §3.5).
TRANSFER_MIN_AGE_DAYS = 60
AUTH_CODE_TTL_DAYS = 14
TRANSFER_AUTO_ACK_DAYS = 5
DISPUTE_WINDOW_MONTHS = 6

# Court orders (PRD §3.6).
DEFERRED_ENFORCEMENT_HOURS = 48

# Capacity commitment (PRD §3.4).
CAPACITY_COMMITMENT_QPS = 8000
MIN_NAMESERVER_QPS = 2000

# Canonical default price schedule used by fixtures and tests.
DEFAULT_SCHEDULE_FEES = {
    "create_fee_cents": 700,
    "renew_fee_cents": 850,
    "restore_fee_cents": 12000,
    "transfer_fee_cents": 700,
}

TEST_DEFAULTS = {
    "APPLICATION_FEE_CENTS": 250000,
    "ANNUAL_FEE_CENTS": 400000,
    "ESCROW_DEPOSIT_CENTS": 1000000,
    "TECHNICAL_TEST_SCORE": 90,
}
