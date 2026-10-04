"""Domain thresholds — numeric constants from PRD calculations and rules."""

# Logical clock (PRD section 2.4): fixed default reading before any clock-set.
CLOCK_START_ISO = "2026-09-01T00:00:00Z"
CLOCK_START_DATE = "2026-09-01"

# Bioequivalence adequacy (PRD sections 2.9 / 3.3): inclusive 2dp bounds.
BE_CI_LOWER_BOUND_PCT = 80.00
BE_CI_UPPER_BOUND_PCT = 125.00

# Review goal bases and extension (PRD section 3.5).
STANDARD_REVIEW_MONTHS = 10
PRIORITY_REVIEW_MONTHS = 8
MAJOR_AMENDMENT_EXTENSION_MONTHS = 3

# Paragraph-IV notice / litigation stay (PRD section 3.4).
P4_NOTICE_WINDOW_DAYS = 20
SUIT_WINDOW_DAYS = 45
LITIGATION_STAY_MONTHS = 30

# Deficiency response clock (PRD section 3.5).
DEFICIENCY_RESPONSE_MONTHS = 12

# NCE submission bars (PRD section 3.3).
NCE_PIV_BAR_MONTHS = 48
NCE_FULL_BAR_MONTHS = 60

# Domestic waiver prior-pass window (PRD section 3.6).
DOMESTIC_WAIVER_PRIOR_PASS_MONTHS = 24

# First-filer exclusivity (PRD section 3.8).
EXCLUSIVITY_DAYS = 180
FAILURE_TO_MARKET_DAYS = 75
TA_FAILURE_MONTHS = 30

# Supplement effectivity (PRD section 3.9).
CBE30_EFFECTIVE_DAYS = 30
