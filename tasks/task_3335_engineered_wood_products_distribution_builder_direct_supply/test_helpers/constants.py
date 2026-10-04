"""Domain thresholds — numeric constants from PRD calculations."""

# Logical clock startup default (PRD §2.4).
CLOCK_START_ISO = "2026-09-01T00:00:00Z"

# Order pricing tiers (PRD §3.6): no discount below 50 mbf, 3% for 50..99,
# 5% at 100 or more. Per-line round-half-up, then sum.
TIER1_QTY_MBF = 50
TIER1_DISCOUNT = 0.03
TIER2_QTY_MBF = 100
TIER2_DISCOUNT = 0.05

# Delivery fee (PRD §3.7): component-wise round-half-up then sum.
BASE_DELIVERY_FEE_CENTS = 7501
BOOM_SURCHARGE_CENTS = 4003
MULT_STANDARD = 1.0
MULT_TIGHT_ACCESS = 1.25
MULT_CRANE_ASSIST = 1.5

# Truck scheduling (PRD §3.7).
TRUCK_BUFFER_MINUTES = 45
DEFAULT_MAX_DROPS = 4

# Quote validity (PRD §3.5): strict greater-than at quoted_at + 14 days.
QUOTE_VALID_DAYS = 14

# Lien window (PRD §3.8): last_completed_delivery_date + 90 days, filing on
# the deadline day allowed.
LIEN_WINDOW_DAYS = 90

# Common monetary test defaults (cents).
DEFAULT_CREDIT_LIMIT_CENTS = 5_000_000
DEFAULT_JOB_CAP_CENTS = 100_000_000
DEFAULT_FIXED_UNIT_PRICE_CENTS = 100_000
DEFAULT_LOT_UNIT_COST_CENTS = 40_000

# Standard delivery window used across delivery/fleet setups.
DELIVERY_DATE = "2026-09-10"
DELIVERY_WINDOW_START = "2026-09-10T09:00:00Z"
DELIVERY_WINDOW_END = "2026-09-10T12:00:00Z"
SHIFT_WINDOW_START = "2026-09-10T08:00:00Z"
SHIFT_WINDOW_END = "2026-09-10T16:00:00Z"
