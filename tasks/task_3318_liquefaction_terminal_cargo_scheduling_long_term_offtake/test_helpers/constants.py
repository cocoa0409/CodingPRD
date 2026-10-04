"""Domain thresholds — numeric constants from PRD calculation rules."""

# Laytime accounting (PRD laytime section).
LOADING_RATE_MMBTU_PER_HOUR = 240000
BERTH_ALLOWANCE_HOURS = 4
NOR_GRACE_HOURS = 6
CONNECTION_ALLOWANCE_HOURS = 2

# Feed gas requirement (ten percent fuel and loss over delivered LNG).
FEED_GAS_RATIO = 1.10

# Proration waterfall.
PRORATION_FLOOR_MIN_MMBTU = 5000

# Cancellation settlement.
HANDLING_FEE_PCT = 0.02
PIPELINE_TARIFF_USD_PER_MMBTU = 0.35

# Logical clock startup default (PRD logical-clock section).
CLOCK_DEFAULT_ISO = "2026-09-01T00:00:00Z"

# Default commercial terms used by test fixtures.
DEFAULT_FIXED_FEE = 3.50
DEFAULT_COMMODITY_MULTIPLIER = 1.15
DEFAULT_ESTIMATED_INDEX_PRICE = 2.85
DEFAULT_ACTUAL_INDEX_PRICE = 3.10
DEFAULT_REFERENCE_INDEX_PRICE = 3.10
DEFAULT_DEMURRAGE_RATE_PER_DAY = 85000
DEFAULT_CANCELLATION_NOTICE_DAYS = 30
DEFAULT_TOLERANCE_PCT = 0.05

# Expected invoice figures for the canonical 3,600,000 mmbtu cargo under the
# default commercial terms: provisional (est 2.85) and final (actual 3.10).
CANONICAL_SLOT_QTY = 3600000
CANONICAL_PROVISIONAL_INVOICE_USD = 24399000.00
CANONICAL_FINAL_INVOICE_USD = 25434000.00

# Allowed laytime for the canonical cargo:
# ceil(3600000 / 240000) + 4 == 15 + 4 == 19.
CANONICAL_ALLOWED_LAYTIME_HOURS = 19
