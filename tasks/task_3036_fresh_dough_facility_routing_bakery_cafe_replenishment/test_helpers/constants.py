"""Domain thresholds and pricing constants from the PRD workflows."""

# Logical clock default (PRD §2.5): the clock reads exactly this before any call.
CLOCK_DEFAULT_ISO = "2026-09-01T00:00:00Z"

# Transfer pricing (PRD §3.8)
COMPANY_MARKUP_PCT = 18
FRANCHISE_MARKUP_PCT = 12
ARTISAN_PRICE_FLOOR = 4.00
CONVENTIONAL_PRICE_FLOOR = 3.50

# Effective-unit capacity weights (PRD §3.1 / §3.4)
ARTISAN_UNIT_WEIGHT = 2
CONVENTIONAL_UNIT_WEIGHT = 1

# Donation credit (PRD §3.9)
DONATION_CREDIT_RATE = 0.25

# Overhead burden shares (PRD §3.10)
FRANCHISE_BURDEN_SHARE = 0.60
COMPANY_BURDEN_SHARE = 0.45

# Demand adjustment bounds (PRD §3.3)
DEMAND_DELTA_MIN_PCT = -80
DEMAND_DELTA_MAX_PCT = 100

# Canonical dough types used across the suite.
CXL_DOUGH = {
    "code": "CXL",
    "category": "CONVENTIONAL",
    "shelf_life_hours": 36,
    "order_cutoff_local": "13:00",
    "substitution_allowed": False,
    "flat_transfer_price": 4.00,
}
BMT_DOUGH = {
    "code": "BMT",
    "category": "ARTISAN",
    "shelf_life_hours": 48,
    "order_cutoff_local": "18:00",
    "substitution_allowed": False,
    "flat_transfer_price": 5.00,
}

# Derived unit prices: round_half_up(flat * (1 + markup/100), 2), floor dormant here.
CXL_FRANCHISE_UNIT_PRICE = 4.48   # 4.00 * 1.12
CXL_COMPANY_UNIT_PRICE = 4.72     # 4.00 * 1.18
BMT_COMPANY_UNIT_PRICE = 5.90     # 5.00 * 1.18
BMT_FRANCHISE_UNIT_PRICE = 5.60   # 5.00 * 1.12
