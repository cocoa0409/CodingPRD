"""Domain constants — every threshold and default the PRD pins, plus the
fixture-level values the test design standardises on.

Two kinds of values live here:

1. PRD-pinned constants (the contract): dues tiers, quorum size, appeal
   window, clean-round bonus, score cap, weight-sum rule, clock start, and
   the SMALL population boundary.  Each carries its PRD section in a comment.
2. Fixture defaults (test data, not contract): the standard cycle window,
   the standard pass score, the standard criterion sets.  Tests may override
   any of these; they exist so fixtures and tests share one spelling.
"""

# ─── Routing ────────────────────────────────────────────────────────────────

API_PREFIX = "/gfoa"
# The logical-clock capability lives OUTSIDE the /gfoa mount (PRD §2.4).
CLOCK_PATH = "/_clock/set_current_utc"

# ─── Logical clock (PRD §2.4) ───────────────────────────────────────────────

# Startup default: "At startup the logical clock reads exactly
# 2026-09-01T00:00:00Z".
CLOCK_START_INSTANT = "2026-09-01T00:00:00Z"
# Standard test instant: inside the default submission window.
DEFAULT_TEST_INSTANT = "2026-09-15T00:00:00Z"
# One day past the default deadline (posture IN_REVIEW at this instant).
PAST_DEADLINE_INSTANT = "2026-10-16T00:00:00Z"

# ─── Member dues (PRD §3.2, pinned evaluation order) ───────────────────────

BAND_BASE_CENTS = {"SMALL": 15000, "MEDIUM": 30000, "LARGE": 60000}
AFFILIATION_FEE_CENTS = 5000
# Discount tier is keyed on the PRE-discount total (band base + fee).
DISCOUNT_TIER_LOW_MIN_CENTS = 30000   # >= 30000 -> 5%
DISCOUNT_TIER_HIGH_MIN_CENTS = 60000  # >= 60000 -> 10%
DISCOUNT_TIER_LOW_PCT = 0.05
DISCOUNT_TIER_HIGH_PCT = 0.10

# Worked values under the pinned order (handy for assertions):
#   SMALL + independent:  15000 + 5000 = 20000  -> no tier   -> 20000
#   MEDIUM plain:         30000          >= 30000 -> 5% off  -> 28500
#   MEDIUM + independent: 35000          >= 30000 -> 5% off  -> 33250
#   LARGE plain:          60000          >= 60000 -> 10% off -> 54000
DUES_SMALL_INDEPENDENT_CENTS = 20000
DUES_MEDIUM_PLAIN_CENTS = 28500
DUES_MEDIUM_INDEPENDENT_CENTS = 33250
DUES_LARGE_PLAIN_CENTS = 54000

# ─── Government size (PRD §3.2) ─────────────────────────────────────────────

# "SMALL means a population under 10,000".
SMALL_POPULATION_LIMIT = 10000

# ─── Review round (PRD §3.5, §3.6) ──────────────────────────────────────────

REQUIRED_FINDINGS_PER_ROUND = 3
MAX_OPEN_ASSIGNMENTS_PER_REVIEWER = 5
REVIEWER_ALIAS_PREFIX = "R"  # alias shape: R{appeal_round}-{seq}

# ─── Appeal window (PRD §3.6) ───────────────────────────────────────────────

APPEAL_WINDOW_DAYS = 30

# ─── Scoring (PRD §2.9, §3.1, §3.5, §3.6) ──────────────────────────────────

SCORE_MIN = 0
SCORE_MAX = 100
SCORE_DECIMAL_PLACES = 2
CRITERIA_WEIGHT_SUM = 1.0  # "weights ... must sum to exactly 1.000" (§3.1)
BUDGET_CLEAN_BONUS = 1.00  # clean-round bonus for BUDGET_PRESENTATION (§3.6)
SCORE_CAP = 100.00

# ─── Fixture-default program data (test data, not contract) ────────────────

DEFAULT_FISCAL_YEAR = 2026
DEFAULT_PASS_SCORE = 85.00

FR_CRITERION_CODES = ("C1", "C2")
FR_CRITERIA = [
    {"criterion_code": "C1", "weight": 0.5},
    {"criterion_code": "C2", "weight": 0.5},
]
BUDGET_CRITERION_CODES = ("P", "F", "C")
BUDGET_CRITERIA = [
    {"criterion_code": "P", "weight": 0.30},
    {"criterion_code": "F", "weight": 0.40},
    {"criterion_code": "C", "weight": 0.30},
]

# Default cycle window: opens at the clock-start instant; deadline 2026-10-15;
# review horizon closes 2026-12-01.  DEFAULT_TEST_INSTANT sits inside it.
DEFAULT_WINDOW_OPENS_AT = "2026-09-01T00:00:00Z"
DEFAULT_WINDOW_DEADLINE_AT = "2026-10-15T00:00:00Z"
DEFAULT_REVIEW_CLOSE_AT = "2026-12-01T00:00:00Z"

# Standards references (test data).
DEFAULT_STANDARD_TOPIC = "GASB-103"
DEFAULT_STANDARD_EFFECTIVE_DATE = "2026-09-10T00:00:00Z"

# Budget-document fixture defaults (test data; the three doc types are the
# contract — PRD §3.4).
BUDGET_DOC_TYPES_REQUIRED = ("POLICY", "FINANCIAL_PLAN", "COMMUNICATION")
DEFAULT_DOC_TITLES = {
    "POLICY": "Budget Policy",
    "FINANCIAL_PLAN": "Financial Plan",
    "COMMUNICATION": "Community Summary",
}
DEFAULT_DOC_PAGE_COUNTS = {"POLICY": 12, "FINANCIAL_PLAN": 40, "COMMUNICATION": 8}

# Publication comment-window fixture defaults (test data).
DEFAULT_COMMENT_CLOSES_AT = "2026-09-20T00:00:00Z"
AFTER_COMMENT_CLOSES_INSTANT = "2026-09-21T00:00:00Z"

# Scholarship fixture defaults (test data).
DEFAULT_POOL_TOTAL_CENTS = 100000
DEFAULT_PER_APPLICANT_CAP_CENTS = 50000
DEFAULT_REQUESTED_CENTS = 10000
