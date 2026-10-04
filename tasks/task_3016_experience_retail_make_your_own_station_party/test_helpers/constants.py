"""Domain thresholds and prices — numeric constants from the PRD (§3)."""

# Logical clock startup default (PRD §2.4).
CLOCK_START_ISO = "2026-09-01T00:00:00Z"

# Deposit rule (PRD §3.6): ULTIMATE uses max(guest_count * 1000, 20000);
# other tiers use a flat 10000.
PER_GUEST_DEPOSIT_CENTS = 1000
FIXED_DEPOSIT_CENTS = 10000
ULTIMATE_DEPOSIT_FLOOR_CENTS = 20000
MIN_BOOKING_LEAD_HOURS = 72

# Final bill (PRD §3.7): per-guest tier price + 15% service charge,
# rounded half up per guest line before summation.
SERVICE_CHARGE_PCT = 15
PACKAGE_PRICES = {"BASIC": 1899, "CELEBRATION": 4299, "ULTIMATE": 7999}

# Station occupancy (PRD §3.3): [start - 15min, start + 45min + 15min).
SETUP_BUFFER_MIN = 15
TEARDOWN_BUFFER_MIN = 15
DEFAULT_SESSION_DURATION_MIN = 45

# Sound chip surcharge (PRD §3.1, §3.3).
SOUND_CHIP_PRICE_CENTS = 1500

# Consignment settlement (PRD §3.8).
COMMISSION_PCT = 18

# Party block duration (PRD §3.6).
PARTY_DURATION_MINUTES = 120
GUEST_COUNT_MIN = 6
GUEST_COUNT_MAX = 20
