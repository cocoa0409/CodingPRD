"""Domain thresholds and canonical literals (PRD §2.5, §3.4, §3.6, §3.7)."""

# Logical clock defaults (PRD §2.5)
CLOCK_DEFAULT = "2026-09-01T00:00:00Z"
EMBARGO_LIFT_AT = "2026-10-15T00:00:00Z"

# Canonical methodology knobs used by the canonical fixture chains.
CANONICAL_MIN_DURATION_SECONDS = 180
CANONICAL_STRAIGHTLINE_MIN_ITEMS = 12
CANONICAL_POOLED_SD_1000 = 60
CANONICAL_Z_VALUE = 1.96
CANONICAL_TIE_EPSILON = 3
CANONICAL_WEIGHTS = (("QUAL", "Quality & Reliability", 6000), ("FEAT", "Features & Controls", 4000))

# Canonical operator user ids (opaque role identities; recorded on pin for SoD).
U_METHODOLOGY_LEAD = "u_ml_001"
U_AWARDS_OFFICER = "u_ao_001"

# License fee constants (PRD §3.6).
BASE_CENTS = {"DIGITAL": 250000, "NATIONAL": 600000, "GLOBAL": 1500000}
INCLUDED_MARKETS = {"DIGITAL": 1, "NATIONAL": 3, "GLOBAL": 999}
PER_MARKET_CENTS = 150000
TERM_DISCOUNT = 0.85
TERM_DISCOUNT_MIN_MONTHS = 24
PRIOR_VIOLATION_MULT = 1.25
MIN_FEE_CENTS = 220000

# Usage-audit suspension threshold (PRD §3.7): the second concurrently
# ESCALATED MINOR audit suspends an ACTIVE license.
MINOR_SUSPENSION_THRESHOLD = 2

# Canonical subscription window used by insights fixtures.
SUB_WINDOW_START = "2026-09-01T00:00:00Z"
SUB_WINDOW_END = "2027-08-31T00:00:00Z"
