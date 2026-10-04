"""Domain thresholds — every value stated verbatim in PRD.md prose and used
by a live code path in test_helpers or test_suite."""

# PRD §2.4: "At server startup, before any administrative clock action, the
# logical clock reads exactly 2026-09-01T00:00:00Z."
LOGICAL_CLOCK_START_ISO = "2026-09-01T00:00:00Z"
LOGICAL_CLOCK_START_DATE = "2026-09-01"

# PRD §2.3: "The `limit` parameter defaults to 10".
PAGINATION_DEFAULT_LIMIT = 10

# PRD §3.1 jurisdiction national-standard defaults: "`min_total_experience_hours`
# (default 3740), `ce_hours_required` (default 24...), `ce_hsw_hours_required`
# (default 12...)".
DEFAULT_MIN_TOTAL_EXPERIENCE_HOURS = 3740
DEFAULT_CE_HOURS_REQUIRED = 24
DEFAULT_CE_HSW_HOURS_REQUIRED = 12

# PRD §3.2: "an `ALTERNATIVE_PATH` evaluation must declare at least 64 semester
# credit hours".
ALTERNATIVE_PATH_MIN_CREDITS = 64

# PRD §3.3: "locks 100 percent credit ... locks 50 percent".
FULL_CREDIT_PCT = 100
HALF_CREDIT_PCT = 50

# PRD §3.3: "A single report must carry at least 1 hour and at most 2000
# hours".
MIN_HOURS_PER_REPORT = 1
MAX_HOURS_PER_REPORT = 2000

# PRD §3.3: "every one of the six areas must meet its minimum credited hours —
# at least 160 in `PRACTICE_MANAGEMENT`, at least 360 in
# `PROJECT_MANAGEMENT`, at least 260 in `PROGRAMMING_ANALYSIS`, at least 1360
# in `PROJECT_PLANNING_DESIGN`, at least 1520 in
# `PROJECT_DEVELOPMENT_DOCUMENTATION`, and at least 80 in
# `CONSTRUCTION_EVALUATION`".
AREA_MIN_HOURS = {
    "PRACTICE_MANAGEMENT": 160,
    "PROJECT_MANAGEMENT": 360,
    "PROGRAMMING_ANALYSIS": 260,
    "PROJECT_PLANNING_DESIGN": 1360,
    "PROJECT_DEVELOPMENT_DOCUMENTATION": 1520,
    "CONSTRUCTION_EVALUATION": 80,
}
# PRD §3.3: "The six area minima sum to exactly 3740 hours" — the national
# floor of the completion gate.
NATIONAL_TOTAL_HOURS_REQUIRED = 3740

# PRD §3.4: the exam-progress list "is ordered by `division_code` ascending,
# which produces the sequence CE, PA, PCM, PDD, PJM, PPD".
DIVISION_CODES_ASC = ["CE", "PA", "PCM", "PDD", "PJM", "PPD"]

# PRD §3.7: "an integer `hours` of at least 1 and at most 24".
MAX_CE_ENTRY_HOURS = 24
