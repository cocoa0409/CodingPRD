"""Domain thresholds and shared test constants.

Every figure here is a literal stated in the PRD's calculation sections
(§3.6-§3.10) or in the system-wide rounding rules (§2.6).
"""
import math

# --- Regional monthly pricing (§3.7) ---
PARITY_MULTIPLIER_THRESHOLD = 1.50        # strict >
PARITY_BLEND_FACTOR = 0.90
REGIONAL_MULTIPLIER_MIN = 0.50

# --- Streaming capacity allocation (§3.7) ---
SLOTS_PER_INDEX_CENT = 0.5
LAUNCH_SPIKE_WINDOW_DAYS = 14
LAUNCH_SPIKE_MULTIPLIER_EXCESS = 0.40
OVERHEAD_SLOTS_PER_REGION = 200
SLOTS_PER_CEILING_UNIT = 30

# --- Title engagement weighting (§3.7) ---
TIER_WEIGHTS = {"ESSENTIAL": 1.00, "PREMIUM": 1.50, "ULTIMATE": 2.00}

# --- Member purchase discount (§3.8) ---
RETENTION_DISCOUNT_BONUS = 0.05
MAX_MEMBER_DISCOUNT_PCT = 0.40

# --- Day-one release economics (§3.9) ---
HOURS_PER_LOST_SALE = 1.25
NET_NEW_SUBSCRIBER_FRACTION = 0.60
TIER_UPLIFT_RATE = 0.05
TIER_UPLIFT_CAP_CENTS = 250000
DAY_ONE_APPROVE_THRESHOLD_CENTS = 0
HOLD_THRESHOLD_CENTS = -50000
UNIT_SALES_CANNIBALIZATION_FRACTION = 0.30

# --- Compensation (§3.6) ---
HYBRID_ENGAGEMENT_SHARE = 0.25

# --- Engagement scoring (§3.6) ---
ENGAGEMENT_SCORE_CEILING = 100.00
HOUR_PRECISION_DECIMALS = 4

# --- Tier analytics (§3.10) ---
RETENTION_WEIGHT = 0.60
CONVERSION_WEIGHT = 0.25
ENGAGEMENT_WEIGHT = 0.15
ENGAGEMENT_HOURS_PER_INDEX_POINT = 2.0

# --- Removal notice minima and the revert cutoff (§3.4) ---
DAY_ONE_MIN_NOTICE_DAYS = 14
CATALOG_ADD_MIN_NOTICE_DAYS = 7
BACK_CATALOG_MIN_NOTICE_DAYS = 0
REMOVAL_REVERT_CUTOFF_DAYS = 3

# --- Logical clock (§2.12) ---
# The service's clock starts at 2026-09-01T00:00:00Z and never moves backwards,
# so every scenario below is anchored at or after that instant.
SERVER_DEFAULT_CLOCK = "2026-09-01T00:00:00Z"
SEED_CLOCK = "2026-09-01T00:00:00Z"
SCENARIO_CLOCK = "2026-09-02T00:00:00Z"


def round_half_up(value: float, places: int = 2) -> float:
    """Round half up, matching the PRD's stated convention."""
    factor = 10 ** places
    return math.floor(abs(value) * factor + 0.5) / factor * (1 if value >= 0 else -1)


# --- Reusable scenario defaults ---
TEST_DEFAULTS = {
    "PUBLISHER_NAME": "Nova Interactive",
    "PUBLISHER_HOME_REGION": "NA",
    "TITLE_NAME": "Crimson Drift",
    "TITLE_PLATFORM_SET": ["CONSOLE", "PC", "CLOUD"],
    "TITLE_LIST_PRICE_CENTS": 7000,
    "TITLE_UNIT_SALES_30D": 25000,
    "REGION_CODE": "NA",
    "REGION_CURRENCY": "USD",
    "REGION_PRICE_MULTIPLIER": 1.20,
    "REGION_CEILING_TITLES": 4000,
    "REGION_TIER_FLOOR": "ESSENTIAL",
    "TIER_CODE": "PREMIUM",
    "TIER_MONTHLY_PRICE_CENTS": 1799,
    "TIER_MEMBER_DISCOUNT_PCT": 0.075,
    "TIER_DISCOUNT_RETENTION_DAYS": 30,
    "TIER_ANNUAL_PREPAY_CREDIT_RATIO": 0.25,
    "ESSENTIAL_MONTHLY_PRICE_CENTS": 999,
    "DEAL_GUARANTEED_COMPENSATION_CENTS": 150000,
    "DEAL_MONTHLY_ENGAGEMENT_CAP_CENTS": 300000,
    "DEAL_ENGAGEMENT_RATE_CENTS_PER_HOUR": 251,
    "DEAL_TERM_START": "2026-09-01T00:00:00Z",
    "DEAL_TERM_END": "2027-03-01T00:00:00Z",
    "DEAL_ADD_EFFECTIVE": "2026-09-05T00:00:00Z",
    "ENTRY_ANNOUNCED_ADD": "2026-09-02T00:00:00Z",
    "ENTRY_REMOVAL": "2026-11-30T00:00:00Z",
    "ENTRY_POPULARITY": 6000,
    "ENTRY_POPULARITY_30D": 3000,
    "SUBSCRIBER_EMAIL": "mira@example.com",
    "SUBSCRIBER_DISPLAY_NAME": "Mira",
}

# --- Later instants used by the longer scenarios ---
BACK_CATALOG_REMOVAL = "2026-12-30T00:00:00Z"      # 119 days of notice
TERM_MONTHS = 6                                     # 2026-09-01 .. 2027-03-01
REMOVAL_EFFECTIVE_DATE = "2027-02-27T00:00:00Z"     # term end minus two days
EXPIRING_CLOCK = "2027-02-27T00:00:00Z"             # sweeps both deals to EXPIRING