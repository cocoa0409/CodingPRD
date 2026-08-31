"""Domain thresholds and constants stated by the PRD."""

# Coverage standard and revision allowance.
COVERAGE_MIN_SYNOPSIS_WORDS = 250
COVERAGE_MAX_REVISION_ROUNDS = 2

# Reader calibration anchor.
CALIBRATION_ANCHOR = 5.50

# Craft-score weights used to build the raw weighted score.
SCORE_WEIGHTS = {
    "logline": 0.10,
    "structure": 0.30,
    "character": 0.25,
    "dialogue": 0.15,
    "marketability": 0.20,
}

# Release-form requirement.
SIGNATORY_AGENCIES = ["CAA", "WME", "UTA", "GERSH", "APA"]

# Coverage turnaround budget in hours, selected by priority_flag.
TURNAROUND_HOURS = {"RUSH": 24, "STANDARD": 72, "BACKLOG": 168}

# Chain-of-title derivation.
REQUIRED_CHAIN_TYPES = ["CHAIN_OF_TITLE", "COPYRIGHT_CERT"]
CHAIN_CLEAR_MIN_DOCS = 3

# Tracking heat score.
RECOMMENDATION_BONUS = {
    "PASS": 0,
    "CONSIDER": 8,
    "RECOMMEND": 18,
    "STRONG_RECOMMEND": 30,
}
COMPETITION_BONUS_PER_RIVAL = 3
COMPETITION_BONUS_CAP = 15
CLEAR_CHAIN_BONUS = 10
REVISION_PENALTY = 5
TIER_WATCH_MIN = 60.00
TIER_HOT_MIN = 85.00
TIER_PRIORITY_MIN = 110.00
TIER_RANK_ORDER = ["NONE", "WATCH", "HOT", "PRIORITY"]

# Option pricing bands.
ESCALATION_BAND_MID_MIN = 2_000_000_000
ESCALATION_BAND_HIGH_MIN = 6_000_000_000
CREDIT_BAND_MID_MIN = 25_000_000
CREDIT_BAND_HIGH_MIN = 100_000_000

# Turnaround reversion clock.
TURNAROUND_REVERSION_MONTHS = 18

# Milestone templates: ordered (milestone_type, percentage_bps) pairs.
MILESTONE_TEMPLATES = {
    "ORIGINAL_DRAFT": [
        ("COMMENCEMENT", 3000),
        ("FIRST_DRAFT_DELIVERY", 4000),
        ("FIRST_DRAFT_ACCEPTANCE", 3000),
    ],
    "REWRITE": [("COMMENCEMENT", 4000), ("REWRITE_DELIVERY", 6000)],
    "POLISH": [("COMMENCEMENT", 5000), ("POLISH_DELIVERY", 5000)],
    "PRODUCTION_REWRITE": [
        ("COMMENCEMENT", 3334),
        ("REWRITE_DELIVERY", 3333),
        ("PRODUCTION_BONUS", 3333),
    ],
}
MILESTONE_DUE_OFFSET_DAYS = {
    "COMMENCEMENT": 0,
    "FIRST_DRAFT_DELIVERY": 84,
    "FIRST_DRAFT_ACCEPTANCE": 98,
    "REWRITE_DELIVERY": 56,
    "POLISH_DELIVERY": 28,
    "PRODUCTION_BONUS": 120,
}

# Writer fiscal rules.
DEV_BUDGET_WRITER_SHARE_BPS = 1200
GUILD_MINIMUM_FEE_CENTS = {
    "ORIGINAL_DRAFT": 7_500_000,
    "REWRITE": 5_000_000,
    "POLISH": 2_500_000,
    "PRODUCTION_REWRITE": 5_000_000,
}
WRITER_MAX_CONCURRENT_ENGAGEMENTS = 2

# Interval conventions.
READER_BUFFER_HOURS = 12

# Greenlight committee.
GREENLIGHT_QUORUM_PCT = 60.00
GREENLIGHT_APPROVAL_PCT = 66.67
GREENLIGHT_MIN_ACTIVE_MEMBERS = 3

# Logical clock default before any administrator sets it.
DEFAULT_CLOCK_UTC = "2026-08-01T00:00:00Z"

# Pagination.
DEFAULT_LIMIT = 10
MAX_LIMIT = 100

# Convenient defaults reused across setups.
TEST_DEFAULTS = {
    "CLOCK": "2026-09-01T00:00:00Z",
    "OPTION_FEE_CENTS": 5_000_000,
    "PURCHASE_PRICE_CENTS": 90_000_000,
    "INITIAL_PERIOD_MONTHS": 18,
    "OPTION_START_AT": "2026-09-01T00:00:00Z",
    "BUDGET_CENTS": 2_000_000_000,
    "SLATE_YEAR": 2028,
    "ORIGINAL_DRAFT_FEE_CENTS": 10_000_003,
    "ENGAGEMENT_START_DATE": "2026-09-05",
    "ENGAGEMENT_END_DATE": "2027-01-05",
}
