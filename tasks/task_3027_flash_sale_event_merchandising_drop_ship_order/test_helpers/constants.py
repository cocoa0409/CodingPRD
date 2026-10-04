"""Domain thresholds and calculation constants.

Every value here is a named constant of a rule stated in the PRD. They are used to
drive boundary arithmetic rather than to restate the rule.
"""

# ─── Event window and ship-time disclosure ────────────
SHIP_TIME_QUOTE_DAYS_ALLOWED = [10, 14, 21, 30]
EVENT_WINDOW_MAX_HOURS = 72

# ─── Brand-window buffering ───────────────────────────
BRAND_WINDOW_BUFFER_HOURS = 2
SHOP_SKU_LIMIT = 40

# ─── Cancellation window ──────────────────────────────
CANCELLATION_GRACE_HOURS = 30

# ─── Fill-rate ramp ───────────────────────────────────
DUE_DAYS_TOTAL = 14
FLOOR_EXCELLENT = 0.9000
FLOOR_GOOD = 0.8500
FLOOR_PROBATION = 0.9500
FLOOR_SUSPENDED = 1.0000
STANDING_TIERS = {
    "EXCELLENT_MIN": 0.9700,
    "GOOD_MIN": 0.9000,
    "PROBATION_MIN": 0.7500,
}
ROLLING_WINDOW_DAYS = 90
OVERSELL_MAX_PCT = 0.20

# ─── Cross-dock buckets ───────────────────────────────
DOCK_BUCKET_HOURS = 6
DOCK_BUCKET_CAPACITY_UNITS = 100

# ─── Dispatch estimate ────────────────────────────────
DISPATCH_CUTOFF_HOUR_UTC = 17
TRANSPARENCY_EMBARGO_HOURS = 6

# ─── Event net contribution ───────────────────────────
STRATEGIC_SPIFF_RATE = 0.03
BUFFER_CREDIT_PER_UNIT_CENTS = 2500
MAX_PENALTY_RATE = 0.40
MIN_CONTRIBUTION_RATE = 0.15
OVERSELL_PENALTY_MULTIPLIER = 1.50
PROJECTED_TAIL_MIN_SELL_THROUGH = 0.9000

# ─── Goodwill credit cap ──────────────────────────────
ANNUAL_CAP_CENTS = 50000
CS_GOODWILL_BASE_CENTS = 500
GOODWILL_PCT_OF_LINE = 0.50
LINE_GOODWILL_CEILING_CENTS = 20000
RESTRICTED_CANCELLATION_THRESHOLD = 3

# ─── Common test values ───────────────────────────────
TEST_DEFAULTS = {
    "CLOCK_START": "2026-09-01T00:00:00Z",
    "LEGAL_NAME": "Northwind Outfitters",
    "SHOP_NAME": "Northwind Brand Shop",
    "EVENT_TITLE": "Fall Outerwear Daily",
    "UNIT_PRICE_CENTS": 300,
    "UNIT_COST_CENTS": 180,
    "ALLOCATION_UNITS": 10,
    "SHIP_TIME_QUOTE_DAYS": 14,
}

# A syntactically valid identifier that resolves to nothing.
UNALLOCATED_UUID = "00000000-0000-4000-8000-000000000000"
UNALLOCATED_SHOP_UUID = "00000000-0000-4000-8000-000000000009"