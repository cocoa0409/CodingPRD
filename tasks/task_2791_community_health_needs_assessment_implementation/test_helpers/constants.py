"""Domain thresholds and canonical scenario literals drawn from the PRD."""
from __future__ import annotations

from decimal import Decimal

# --------------------------------------------------------------------------
# Logical clock
# --------------------------------------------------------------------------
#: Before any client sets it, the logical clock reads exactly this instant.
DEFAULT_CLOCK = "2026-08-01T00:00:00Z"

# --------------------------------------------------------------------------
# Scoring
# --------------------------------------------------------------------------
#: An indicator whose community rate exactly equals its benchmark scores 50.00.
BENCHMARK_PARITY_MULTIPLIER = 50
SEVERITY_SCORE_CEILING = 100.00
DISPARITY_POINTS_CEILING = 100.00
#: The attendance-weighted mean rating is multiplied by 20 onto a 0-to-100 scale.
CONCERN_SCALE_MULTIPLIER = 20
CONCERN_RATING_MIN = 1
CONCERN_RATING_MAX = 5
#: A composite score of exactly 60.00 passes selection.
PRIORITY_SCORE_THRESHOLD = 60.00

EQUAL_WEIGHTS = {"severity": 0.25, "disparity": 0.25, "concern": 0.25, "capacity": 0.25}
COMMUNITY_WEIGHTS = {"severity": 0.20, "disparity": 0.30, "concern": 0.35, "capacity": 0.15}

# --------------------------------------------------------------------------
# Objectives / attainment
# --------------------------------------------------------------------------
ATTAINMENT_FLOOR = 0.00
ATTAINMENT_CEILING = 150.00
ATTAINMENT_MET_THRESHOLD = 100.00
ATTAINMENT_PARTIAL_THRESHOLD = 50.00
#: A mid-cycle publication revises objectives strictly below this figure.
MID_CYCLE_REVISION_THRESHOLD = 50.00

# --------------------------------------------------------------------------
# Interviews
# --------------------------------------------------------------------------
#: Each existing session is notionally widened by 30 minutes on both sides.
FACILITATOR_BUFFER_MINUTES = 30
#: Four hours is the longest session the system will book.
MAX_SESSION_MINUTES = 240

# --------------------------------------------------------------------------
# Effort and money
# --------------------------------------------------------------------------
BASIS_POINTS_PER_FTE = 10000
MAX_FTE_CAPACITY_BP = 100000

#: Overhead tiers keyed on ``total_valued_cents``; boundaries belong to the
#: higher tier.
OVERHEAD_TIER_1_CEILING_CENTS = 5000000
OVERHEAD_TIER_2_CEILING_CENTS = 25000000
OVERHEAD_RATE_TIER_1 = 0.05
OVERHEAD_RATE_TIER_2 = 0.08
OVERHEAD_RATE_TIER_3 = 0.11

# --------------------------------------------------------------------------
# Evidence window
# --------------------------------------------------------------------------
#: ``collected_on`` must be on or after 1 January three years before the
#: cycle's ``fiscal_year``.
EVIDENCE_WINDOW_YEARS_BACK = 3

# --------------------------------------------------------------------------
# Literal reason strings the PRD pins by name
# --------------------------------------------------------------------------
DEFER_REASON_PRIORITY_LOCK = "NOT_SELECTED_AT_PRIORITY_LOCK"
RELEASE_REASON_STRATEGY_SUPERSEDED = "STRATEGY_SUPERSEDED"
RELEASE_REASON_PARTNERSHIP_TERMINATED = "PARTNERSHIP_TERMINATED"
RELEASE_REASON_STRATEGY_DISCONTINUED = "STRATEGY_DISCONTINUED"

# --------------------------------------------------------------------------
# Pagination
# --------------------------------------------------------------------------
DEFAULT_LIMIT = 10
MIN_LIMIT = 1
MAX_LIMIT = 100

# --------------------------------------------------------------------------
# Canonical scenario literals
#
# One consistent worked example threads the suite: a fiscal-year 2026 cycle for
# a county service area, one behavioural-health indicator running at 18.6
# against a benchmark of 12.0 with two subgroups at 24.8 and 15.5.
# --------------------------------------------------------------------------
FISCAL_YEAR = 2026
SERVICE_AREA_NAME = "Riverbend County"
#: PRD §2.9: cost-to-charge ratios carry *exactly four* decimal places, and "a
#: value with more or fewer than four decimal places is an ``ERR_VALIDATION``
#: failure".  A JSON float literal cannot preserve trailing zeros, so both
#: ratios are held as ``Decimal`` and serialised by the client with their exact
#: four-place text.
PRIOR_YEAR_RATIO = Decimal("0.3200")
AUDITED_RATIO = Decimal("0.2800")
#: A second, distinct four-place ratio for the second cycle in multi-cycle tests.
ALT_PRIOR_YEAR_RATIO = Decimal("0.3000")
TOTAL_OPERATING_EXPENSE_CENTS = 120000000

INDICATOR_NAME = "Adult depression prevalence"
BENCHMARK_VALUE = 12.0
OVERALL_VALUE = 18.6
SUBGROUP_HIGH_VALUE = 24.8
SUBGROUP_LOW_VALUE = 15.5
COLLECTED_ON = "2026-03-01"

#: Derived from the literals above: 18.6 / 12.0 * 50 = 77.50.
EXPECTED_SEVERITY_SCORE = 77.50
#: 24.8 / 15.5 = 1.60.
EXPECTED_DISPARITY_RATIO = 1.60
#: (1.60 - 1) * 100 = 60.00.
EXPECTED_DISPARITY_POINTS = 60.00
#: A unanimous rating of 5 yields an index of 100.00.
EXPECTED_CONCERN_INDEX = 100.00
HOSPITAL_CAPACITY_SCORE = 70
#: 0.25 * (77.50 + 60.00 + 100.00 + 70) = 76.875 -> 76.88.
EXPECTED_COMPOSITE_EQUAL_WEIGHT = 76.88
#: 0.20*77.50 + 0.30*60.00 + 0.35*100.00 + 0.15*70 = 79.00.
EXPECTED_COMPOSITE_COMMUNITY_WEIGHTED = 79.00

INTERNAL_PARTY_NAME = "Community Health Office"
PARTNER_PARTY_NAME = "Riverbend Community Coalition"
ORGANIZATION_NAME = "Riverbend Free Clinic"
INTERVIEW_STARTS_AT = "2026-04-06T14:00:00Z"
INTERVIEW_ENDS_AT = "2026-04-06T15:00:00Z"
ATTENDEE_COUNT = 12

STRATEGY_TITLE = "Integrated behavioural health access"
AUTHORIZED_BUDGET_CENTS = 5000000
OBJECTIVE_METRIC_NAME = "Depression screenings completed"
OBJECTIVE_BASELINE_VALUE = 1200
OBJECTIVE_TARGET_VALUE = 2400
OBJECTIVE_TARGET_DATE = "2027-06-30"

PLEDGED_CENTS = 2000000
ACCOUNTABILITY_METRIC = "Screenings completed in partner sites"
SHARED_ACCOUNTABILITY_PCT = 40.0
TERM_START = "2026-09-01"
TERM_END = "2027-08-31"

COMMITMENT_FTE_BP = 2500
COMMITMENT_FUNDING_CENTS = 1500000
COMMITMENT_EFFECTIVE_FROM = "2026-10-01"
COMMITMENT_EFFECTIVE_TO = "2027-04-01"

VOTES_FOR = 9
VOTES_AGAINST = 2
