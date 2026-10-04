"""Domain thresholds and canonical values from the PRD (§3)."""

DEFAULT_CLOCK_ISO = "2026-09-01T00:00:00Z"

REGION = "US-WEST"
DEFAULT_PREFERRED_DAY = 10
DEFAULT_DELIVERY_MONTH = "2026-09"
DEFAULT_START_DATE = "2026-09-10"
DEFAULT_PRICE_CENTS = 1000
DEFAULT_CADENCE_MONTHS = 1
DEFAULT_QUANTITY = 1
DEFAULT_STOCK_UNITS = 50

THRESHOLDS = {
    # Tier boundaries (PRD §3.6 step 4): n >= 5 -> 0.10, n >= 3 -> 0.05, else 0.00.
    "TIER_MID_MIN_LINES": 3,
    "TIER_TOP_MIN_LINES": 5,
    "TIER_MID_PCT": 0.05,
    "TIER_TOP_PCT": 0.10,
    # Subscription field ranges (PRD §3.3).
    "MIN_CADENCE_MONTHS": 1,
    "MAX_CADENCE_MONTHS": 6,
    "MIN_QUANTITY": 1,
    "MAX_QUANTITY": 30,
    # Customer preferred delivery day range (PRD §3.2).
    "MIN_DELIVERY_DAY": 1,
    "MAX_DELIVERY_DAY": 28,
    "DEFAULT_DELIVERY_DAY": 15,
    # Start-date lead time (PRD §3.3).
    "MIN_START_LEAD_DAYS": 2,
    # Retention offer goodwill credit and expiry (PRD §3.4).
    "RETENTION_CREDIT_CENTS": 500,
    "RETENTION_OFFER_DAYS": 7,
    # Coupon stacking limit (PRD §3.7).
    "MAX_COUPONS_PER_PLAN": 2,
    # Price-increase notice threshold (PRD §3.6).
    "PRICE_INCREASE_THRESHOLD": 1.10,
    # Demand forecast half weight on paused subscriptions (PRD §3.12).
    "PAUSED_WEIGHT": 0.5,
}
