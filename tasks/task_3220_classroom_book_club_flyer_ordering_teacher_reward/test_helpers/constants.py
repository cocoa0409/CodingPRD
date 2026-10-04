"""Domain thresholds and numeric constants from the API contract.

These values are pinned by the contract's calculation narratives: tier
discount thresholds, the shipping waiver threshold, the club pricing factor,
the royalty rate, the points economy rates, the fair overlap cap, the points
expiry horizon, and the logical clock's startup default.
"""

# Tier discount bands: (inclusive minimum subtotal in cents, basis points).
TIER_1_MIN_CENTS = 5000
TIER_1_BP = 500
TIER_2_MIN_CENTS = 15000
TIER_2_BP = 1000
TIER_3_MIN_CENTS = 40000
TIER_3_BP = 1500

# Shipping.
SHIPPING_FLAT_CENTS = 750
FREE_SHIP_MIN_CENTS = 2500

# Club pricing factor for CLUB_PAPERBACK offerings (70% of list, floored).
CLUB_PRICE_FACTOR_NUM = 70
CLUB_PRICE_FACTOR_DEN = 100

# Royalties.
ROYALTY_PER_UNIT_CENTS = 90

# Points economy.
CENTS_PER_POINT = 100
PROMO_BASE_BP = 100
SUPPLY_UNIT_POINTS_COST = 200
POINTS_EXPIRY_MONTHS = 12

# Book fair title overlap cap.
TITLE_FAIR_OVERLAP_LIMIT = 2

# Logical clock startup default (ISO 8601).
CLOCK_DEFAULT_ISO = "2026-09-01T00:00:00Z"

# Generic enrollment date used by fixtures (before the clock default).
DEFAULT_ENROLLED_ON = "2026-08-15"

# Default flyer cycle month used by fixtures.
DEFAULT_CYCLE_MONTH = "2026-10"
