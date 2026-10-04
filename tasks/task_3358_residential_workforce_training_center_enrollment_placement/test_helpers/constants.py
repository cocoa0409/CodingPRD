"""Domain thresholds — numeric constants from the PRD's calculation rules.

Every literal here is pinned by PRD.md prose (eligibility determination, center
ranking, conduct rolling points, dorm occupancy, WBL hours, transition support
allowance, performance rates, operator payment).
"""

# Logical clock (PRD section 2.4): before any clock-setting call the clock
# reads exactly this instant.
DEFAULT_CLOCK_ISO = "2026-09-01T00:00:00Z"
DEFAULT_CLOCK_DATE = "2026-09-01"

# Eligibility determination (PRD section 3.1)
AGE_MIN_YEARS = 16
AGE_MAX_YEARS = 24
INCOME_BASE_CENTS = 1_500_000
INCOME_PER_MEMBER_CENTS = 500_000
HOUSEHOLD_SIZE_MAX = 12
BARRIER_MIN_COUNT = 1

# Shared applicant literals: at the default clock date 2026-09-01,
# DOB 2002-03-10 is 24 years old (inside the inclusive 16..24 window).
ELIGIBLE_DOB = "2002-03-10"
DOB_EXACTLY_24 = "2002-09-01"
DOB_EXACTLY_25 = "2001-09-01"
ELIGIBLE_HOUSEHOLD_SIZE = 1
ELIGIBLE_INCOME_CENTS = 1_200_000
HOUSEHOLD_1_INCOME_LIMIT_CENTS = INCOME_BASE_CENTS  # 1500000

# Center assignment ranking (PRD section 3.2)
TRADE_WEIGHT = 0.5
CAPACITY_WEIGHT = 0.3
GEO_WEIGHT = 0.2
SEAT_SCORE_CAP = 10
BED_SCORE_CAP = 10
GEO_MATCH_POINTS = 10

# Conduct rolling points (PRD section 3.4)
ROLLING_WINDOW_DAYS = 90
BOARD_REVIEW_THRESHOLD_POINTS = 10
SANCTION_POINTS_MIN = 1
SANCTION_POINTS_MAX = 5

# WBL hours credit (PRD section 3.6)
MAX_DAILY_HOURS = 10
WBL_COMPLETION_MIN_HOURS = 120
MAX_SUPERVISION_ACTIVE = 3

# Transition support allowance (PRD section 3.7)
TRANSPORT_T1_MAX_MILES = 25
TRANSPORT_T1_CENTS = 2_500
TRANSPORT_T2_MAX_MILES = 100
TRANSPORT_T2_CENTS = 7_500
TRANSPORT_T3_CENTS = 15_000
HOUSING_STIPEND_CENTS = 50_000
TRANSITION_WINDOW_MONTHS = 12

# Performance rates (PRD section 3.8)
GRADUATION_RATE_FLOOR = 0.6
PLACEMENT_RATE_FLOOR = 0.7

# Operator performance payment (PRD section 3.8)
PER_GRADUATE_BASE_CENTS = 200_000
WAGE_REFERENCE_CENTS = 150_000
WAGE_RATIO_CAP = 2.0

# Segregation-of-duties identity pair used across intake/review flows.
COUNSELOR_USER_ID = "counselor-1"
REVIEWER_USER_ID = "reviewer-1"
