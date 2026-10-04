"""Domain thresholds and magic numbers — every literal greps to PRD prose.

Logical clock (PRD §2.4):
  LOGICAL_CLOCK_START   "the logical clock stands at exactly 2026-09-01T00:00:00Z"
Review gates (PRD §3.3):
  CAMPUS_QUORUM         "at least two CAMPUS-stage scores"
  NATIONAL_QUORUM       "at least two NATIONAL-stage scores must be present"
  WEIGHT_*              "0.40 ... 0.35 ... 0.25 times the language average"
  RECOMMEND_SCORE_THRESHOLD  "at least 70.00, inclusive"
  MIN_AVG_FEASIBILITY        "the feasibility average to be at least 50, inclusive"
  LANGUAGE_GATE_PROFICIENT   "PROFICIENT demands a language average of at least 80"
  LANGUAGE_GATE_BASIC        "BASIC demands at least 60"
Money terms (PRD §3.2, §3.6):
  DEPENDENT_CAP         "never more than two dependents are counted"
  DEP_CAP_PCT_OF_BASE   "one quarter — 25% — of that base total"
Early termination (PRD §3.8):
  DAYS_PER_MONTH        "divided by thirty and rounded down"
Residency (PRD §3.7, §3.9):
  RESIDENCY_REQUIRED_DAYS  "required_days set to 730" / "at least 730"
Reporting (PRD §3.7, §3.9):
  INTERIM_REPORT_DUE_MONTHS  "four calendar months after start_date"
  FINAL_REPORT_DUE_DAYS      "thirty days after end_date"
  MAX_COMPLIANCE_STRIKES     "the strikes number fewer than two"
Alumni engagement (PRD §3.9):
  ENGAGEMENT_BASE_POINTS     "a base of 50 points"
  REPORT_ACCEPT_POINTS       "adds 10 points for every report"
  STRIKE_PENALTY_POINTS      "subtracts 20 points per compliance strike"
Placement (PRD §3.5):
  MAX_PLACEMENT_ROUNDS       "hard-capped at three rounds in total"
Slot accounting (PRD §3.4):
  SLOT_CONSUMING_STATES      "SELECTED, PLACEMENT, GRANT_PENDING, or AWARDED"
Visa (PRD §3.7):
  SPONSOR_PROGRAM_PREFIX     'the letters "EV-" followed by a six-digit sequence'
"""

# Logical clock
LOGICAL_CLOCK_START = "2026-09-01T00:00:00Z"

# Review quorums and weighted-score gates
CAMPUS_QUORUM = 2
NATIONAL_QUORUM = 2
WEIGHT_FEASIBILITY = 0.40
WEIGHT_COUNTRY_FIT = 0.35
WEIGHT_LANGUAGE = 0.25
RECOMMEND_SCORE_THRESHOLD = 70.00
MIN_AVG_FEASIBILITY = 50
LANGUAGE_GATE_PROFICIENT = 80
LANGUAGE_GATE_BASIC = 60

# Grant money terms (integer cents throughout)
DEPENDENT_CAP = 2
DEP_CAP_PCT_OF_BASE = 0.25

# Early-termination reconciliation
DAYS_PER_MONTH = 30

# Two-year home residency
RESIDENCY_REQUIRED_DAYS = 730

# Reporting obligations
INTERIM_REPORT_DUE_MONTHS = 4
FINAL_REPORT_DUE_DAYS = 30
MAX_COMPLIANCE_STRIKES = 2

# Alumni engagement index
ENGAGEMENT_BASE_POINTS = 50
REPORT_ACCEPT_POINTS = 10
STRIKE_PENALTY_POINTS = 20
ENGAGEMENT_INDEX_MIN = 0
ENGAGEMENT_INDEX_MAX = 100

# Placement negotiation cap
MAX_PLACEMENT_ROUNDS = 3

# Slot accounting: states that consume a country-program quota slot
SLOT_CONSUMING_STATES = frozenset(
    {"SELECTED", "PLACEMENT", "GRANT_PENDING", "AWARDED"}
)

# Visa sponsorship program-number format: "EV-" + six-digit sequence
SPONSOR_PROGRAM_PREFIX = "EV-"
SPONSOR_PROGRAM_NUMBER_LENGTH = 6

# Canonical dates shared by the base pipeline fixtures. All are at or after
# the logical-clock start (2026-09-01T00:00:00Z) and mutually consistent:
# the deadline is in the clock's future at creation, the confirmation window
# (2027-09-01..2028-07-01) is 10 whole calendar months, and the orientation
# timestamp precedes the orientation-setting clock instant.
DEFAULT_CYCLE_ACADEMIC_YEAR = "2027-2028"
DEFAULT_CYCLE_DEADLINE = "2026-10-15T23:59:59Z"
DEFAULT_GRANT_START_DATE = "2027-09-01T00:00:00Z"
DEFAULT_GRANT_END_DATE = "2028-07-01T00:00:00Z"
DEFAULT_GRANT_DURATION_MONTHS = 10  # (2028-2027)*12 + (7-9)
DEFAULT_OFFER_DEADLINE = "2027-03-01T00:00:00Z"
ORIENTATION_CLOCK = "2027-06-15T00:00:00Z"
ORIENTATION_COMPLETED_AT = "2027-06-01T00:00:00Z"
