"""Domain thresholds — numeric constants from the PRD calculations."""

# Per-buyer album-unit cap per chart week (PRD §3.4).
MAX_ALBUM_UNITS_PER_BUYER_PER_WEEK = 4

# Global price floor for title eligibility, in cents (PRD §3.5).
PRICE_FLOOR_CENTS = 300

# Points numeric contract (PRD §2.6).
POINTS_SCALE_DECIMAL_PLACES = 4

# Strike threshold driving label suspension (PRD §3.6).
THREE_STRIKES_THRESHOLD = 3

THRESHOLDS = {
    "MAX_ALBUM_UNITS_PER_BUYER_PER_WEEK": MAX_ALBUM_UNITS_PER_BUYER_PER_WEEK,
    "PRICE_FLOOR_CENTS": PRICE_FLOOR_CENTS,
    "THREE_STRIKES_THRESHOLD": THREE_STRIKES_THRESHOLD,
}

# Canonical methodology used by fixtures and calculation tests. The exact
# weights/divisors are pinned by the PRD narrative examples (§3.5): an input
# set of 500 sales / 10000 paid / 7500 ad / 5000 programmed / 100000 airplay
# yields 515.4000 points on a singles chart.
CANONICAL_METHODODOLOGY = {
    "version_label": "v1",
    "w_sales": 1.0,
    "w_on_demand": 0.5,
    "w_programmed": 0.2,
    "w_airplay": 0.0001,
    "paid_stream_divisor": 1250,
    "ad_stream_divisor": 3750,
    "prog_stream_divisor": 2500,
    "tea_rate": 10,
    "effective_from": "2026-09-01T00:00:00Z",
}

# Canonical weekly window used across fixtures.
DEFAULT_WEEK_OPENS_AT = "2026-09-04T00:00:00Z"
DEFAULT_WEEK_CLOSES_AT = "2026-09-11T00:00:00Z"
DEFAULT_EVENT_TIME = "2026-09-05T00:00:00Z"
DEFAULT_RELEASE_DATE = "2026-08-01T00:00:00Z"
DEFAULT_AVAILABLE_FROM = "2026-08-01T00:00:00Z"
