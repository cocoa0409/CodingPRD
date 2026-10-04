"""Domain thresholds and shared numeric constants (PRD §2.5, §2.7, §3)."""

# Logical clock startup default (PRD §2.7).
CLOCK_DEFAULT_ISO = "2026-09-01T00:00:00Z"

# Royalty pipeline constants (PRD §2.5, §3.5).
BPS_DENOMINATOR = 10_000
REBATE_PCT = 50

# Cure deadline window for default cases (PRD §3.8).
CURE_DEADLINE_DAYS = 30

# De-identification window (PRD §3.8, §3.9).
DEIDENTIFY_WINDOW_DAYS = 60

# The five de-identification task categories spawned on termination (PRD §3.9).
DEIDENTIFICATION_CATEGORIES = (
    "SIGNAGE_REMOVAL",
    "MARKETING_WITHDRAWAL",
    "DATA_PURGE",
    "DOMAIN_RELEASE",
    "DIRECTORY_REMOVAL",
)

# Default commercial terms used across fixtures.
TEST_DEFAULTS = {
    "TERM_START": "2027-01-01T00:00:00Z",
    "TERM_END": "2031-12-31T00:00:00Z",
    "BASE_ROYALTY_RATE_BPS": 600,
    "ANNUAL_ROYALTY_CAP_CENTS": 900_000_000,
    "VOLUME_THRESHOLD_CENTS": 1_000_000_000,
    "VOLUME_RATE_BPS": 300,
    "AD_FUND_RATE_BPS": 200,
}
