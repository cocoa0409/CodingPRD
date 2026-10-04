"""Domain thresholds and fixed reference values stated in the PRD.

Every constant here is a number the PRD commits to in prose (§2.6, §3.5–§3.13),
so a test may assert against it without re-deriving it.
"""

# --------------------------------------------------------------- logical clock
INITIAL_CLOCK_UTC = "2026-09-01T00:00:00Z"

# --------------------------------------------------------------- capacity (§2.6)
DEFAULT_BRANCH_CAPACITY_HOURS = 80
HOURS_PRECISION = 2

# ----------------------------------------------------------- quoting (§3.5, §3.6)
AUTHORIZATION_CEILING_MULTIPLIER = 1.20
OVERRIDE_MARKUP_MULTIPLIER = 1.25
OVERRIDE_HEADROOM_MULTIPLIER = 1.10

# --------------------------------------------------------- completion (§3.7)
DESCRIPTION_MIN_WORDS = 10
DESCRIPTION_WORDS_PER_MINUTE_FRACTION = 0.05
DISCOUNT_FLOOR_FRACTION = 0.20

# --------------------------------------------------------- membership (§3.8)
DOWN_PAYMENT_FRACTION = 0.30
DEFAULT_TERM_MONTHS = 12
DEFAULT_PLAN_NAME = "Comfort Club"
DEFAULT_PLAN_PRICE_CENTS = 100000
DEFAULT_PLAN_VISIT_COUNT = 4
DEFAULT_PLAN_INTERVAL_DAYS = 30
DEFAULT_PLAN_LABOR_DISCOUNT_PCT = 0.10

# ------------------------------------------------------- incentive pay (§3.11)
INCENTIVE_TIER1_UPPER_CENTS = 20000
INCENTIVE_TIER2_UPPER_CENTS = 50000
INCENTIVE_RATE_T1 = 0.02
INCENTIVE_RATE_T2 = 0.04
INCENTIVE_RATE_T3 = 0.06
INCENTIVE_GROSS_CAP_CENTS = 150000
INCENTIVE_STRIKE_CHARGE_CENTS = 1500
INCENTIVE_PAY_TIER1_UPPER_CENTS = 25000
INCENTIVE_PAY_TIER2_UPPER_CENTS = 75000
INCENTIVE_PAY_RATE_T1 = 0.020
INCENTIVE_PAY_RATE_T2 = 0.035
INCENTIVE_PAY_RATE_T3 = 0.050

# ---------------------------------------------------- performance review (§3.11)
PERFORMANCE_WINDOW_DAYS = 90
GRADE_MEETS_FLOOR_CENTS = 400000
GRADE_EXCEEDS_FLOOR_CENTS = 600000
GRADE_EXCEEDS_CEILING_CENTS = 900000

# ------------------------------------------------------------- load trace (§3.4)
LOAD_BUCKET1_MAX_EXCLUSIVE = 500
LOAD_BUCKET2_MAX_EXCLUSIVE = 1500
LOAD_INCREMENT_BUCKET1 = 300
LOAD_INCREMENT_BUCKET2 = 600
LOAD_INCREMENT_BUCKET3 = 900
LOAD_APPLIANCE_NUMERATOR = 115
LOAD_DEFAULT_NUMERATOR = 100

# ------------------------------------------------------------- pagination (§2.3)
DEFAULT_PAGE_LIMIT = 10
MAX_PAGE_LIMIT = 100
MIN_PAGE_LIMIT = 1
DEFAULT_PAGE_OFFSET = 0

# --------------------------------------------------------------- common payloads
TECHNICIAN_SKILL_HVAC = "HVAC"
TECHNICIAN_SKILL_PLUMBING = "PLUMBING"
POSTAL_CODE_AUSTIN = "78701"
POSTAL_CODE_AUSTIN_SUBURB = "78702"
POSTAL_CODE_DALLAS = "75201"

# A completion description comfortably above every word floor used in the suite.
LONG_COMPLETION_DESCRIPTION = (
    "Opened the cabinet, recovered the refrigerant, replaced the failed component, "
    "pressure tested the line set, verified the temperature split and confirmed the "
    "blower amperage before closing the panel and briefing the homeowner carefully."
)

# A twelve-word description: exactly the floor for a 4.0-hour job (4 * 60 * 0.05).
TWELVE_WORD_DESCRIPTION = (
    "Replaced the filter, flushed the drain, verified the split and tightened every panel"
)


def required_completion_words(estimated_hours: float) -> int:
    """Words a completion description must carry for a job of this size (§3.7)."""
    import math

    minutes = estimated_hours * 60
    return max(DESCRIPTION_MIN_WORDS, math.ceil(minutes * DESCRIPTION_WORDS_PER_MINUTE_FRACTION))