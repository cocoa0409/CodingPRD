"""Domain thresholds — numeric constants from the PRD's calculation rules (section 3)."""

# Order tax: only AGE_RESTRICTED lines are taxed (PRD section 3.5, "Third, tax").
TOBACCO_TAX_RATE = 0.07

# Loyalty accrual (PRD section 3.7): min(cap, rate * (subtotal + fee)).
LOYALTY_RATE = 0.03
LOYALTY_CAP_CENTS = 500

# Loyalty application (PRD section 3.5): the wallet floor is zero.
WALLET_FLOOR_CENTS = 0

# Age verification (PRD section 3.6/3.7): at least 21 years old at the logical clock.
MIN_AGE_RESTRICTED = 21

# Membership billing close (PRD section 3.4).
TENURE_DISCOUNT_BPS = 500
TENURE_THRESHOLD_PERIODS = 12
BILLING_PERIOD_DAYS = 30

# Demand forecast multipliers (PRD section 3.9).
NIGHT_LIFT_PCT = 0.40
WEATHER_LIFT_PCT = 0.25
FORECAST_HORIZON_HOURS = 24
NIGHT_WINDOW_START_HOUR = 22
NIGHT_WINDOW_END_HOUR = 4

# Logical clock startup default (PRD section 2.4).
CLOCK_STARTUP_DEFAULT = "2026-09-01T00:00:00Z"

# Standard reference values shared by many setups.
STANDARD_FEE_SCHEDULE = {
    "base_cents": 199,
    "per_mile_cents": 99,
    "included_miles": 1,
    "peak_surcharge_cents": 150,
    "min_fee_cents": 99,
    "max_fee_cents": 999,
}
STANDARD_CLOCK = "2026-09-10T14:00:00Z"
ADULT_BIRTHDATE = "1990-01-01T00:00:00Z"
