"""Domain thresholds and rates — numeric constants from PRD §3."""

# PRD §3.1 assessment consumption estimate
KG_PER_HOUR = 0.9
PEAK_SHIFT_SHORT_MAX_HOURS = 8
SHIFT_FACTOR_SHORT = 1.0
SHIFT_FACTOR_LONG = 1.15

# PRD §3.6 tiered supply pricing
TIER2_DISCOUNT = 0.92
DELIVERED_LIQUID_MARKUP = 1.08
SHORTFALL_RATE = 0.25

# PRD §3.5 availability credit
HOURS_PER_MONTH = 730
AVAILABILITY_CREDIT_RATE = 0.10

# PRD §3.7 incentive qualification (FEDERAL_ITC)
CAPEX_PER_UNIT_CENTS = 1500000
ITC_RATE = 0.30

# PRD §3.7 productivity measurement variants
SELF_REPORTED_CONFIDENCE = 0.90

# PRD §2.7 indoor fire-code storage ceiling
INDOOR_STORAGE_MAX_KG = 200

# PRD §2.5 logical-clock startup default
CLOCK_DEFAULT = "2026-09-01T00:00:00Z"
# Common "current" instant used by test setups
CLOCK_OCT_2026 = "2026-10-01T00:00:00Z"
