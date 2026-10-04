"""Domain constants — thresholds and clock defaults from the PRD."""

# The logical clock reads exactly this instant before any clock call is made.
CLOCK_DEFAULT_ISO = "2026-09-01T00:00:00Z"
CLOCK_DEFAULT_DATE = "2026-09-01"

# Billing cycle length used by the pause proration credit.
BILLING_CYCLE_DAYS = 30

# Merch pricing percentages (per PRD merch pricing rules).
MEMBER_DISCOUNT_PCT = 10          # of subtotal, when current term is BAND_PRO
BUNDLE_DISCOUNT_PCT = 5           # of apparel subtotal, when apparel qty >= 3
BUNDLE_MIN_APPAREL_QTY = 3
DISCOUNT_CAP_PCT = 30             # of subtotal

# Early cancellation fee multipliers.
REMAINING_MONTHS_FEE_NUM = 1
REMAINING_MONTHS_FEE_DEN = 2      # 50% of monthly fee per remaining month
PAID_MONTHS_FEE_NUM = 1
PAID_MONTHS_FEE_DEN = 4           # 25% of monthly fee per paid month

# Metric formula denominators.
BASELINE_STRAIN_DIVISOR = 10.0
PUBLISHED_STRAIN_DIVISOR = 9.0
BASELINE_SLEEP_FULL_NIGHT_MINUTES = 480
PUBLISHED_SLEEP_FULL_NIGHT_MINUTES = 450
PUBLISHED_RECOVERY_SCALE = 0.9
PUBLISHED_RECOVERY_OFFSET = 5
STRAIN_CAP = 21
SCORE_CAP = 100

# Pagination defaults.
DEFAULT_PAGE_LIMIT = 10
MAX_PAGE_LIMIT = 100
