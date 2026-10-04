"""Domain thresholds — numeric constants named by the PRD calculations."""

# Logical clock startup reading (PRD §2.4).
CLOCK_START_ISO = "2026-09-01T00:00:00Z"

# Eligibility income-cap base table, in cents (PRD §3.2: 15,650.00 dollars
# for a household of one, plus 5,560.00 dollars per additional member).
FPL_BASE_CENTS = 1565000
FPL_INCREMENT_CENTS = 556000

# Tiered purchase quote schedule (PRD §3.3).
TIER1_LIMIT_CENTS = 100000000
TIER1_RATE = 0.025
TIER2_LIMIT_CENTS = 400000000
TIER2_RATE = 0.015
TIER3_RATE = 0.008
ORG_FACTOR = {"HOSPITAL": 1.0, "PHYSICIAN_GROUP": 0.9, "DEBT_BUYER": 0.75}

# Per-donation processing fee (PRD §3.5).
FEE_PCT = 0.029

# Notification letter attempt ceiling (PRD §3.7: three attempts).
MAX_LETTER_ATTEMPTS = 3

# Credit-deletion-request resubmission ceiling (PRD §3.8: two resubmissions).
MAX_CDR_RESUBMISSIONS = 2

# Pagination defaults (PRD §2.3).
DEFAULT_PAGE_LIMIT = 10
MAX_PAGE_LIMIT = 100
