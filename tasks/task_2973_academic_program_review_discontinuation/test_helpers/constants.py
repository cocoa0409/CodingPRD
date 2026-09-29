"""PRD-declared literals: clock defaults, weights, statutory intervals, benchmarks."""

# --- §2.5 logical clock -----------------------------------------------------
# "Before the first clock write the logical clock reads exactly 2026-08-01T00:00:00Z"
CLOCK_STARTUP_DEFAULT = "2026-08-01T00:00:00Z"

# --- §2.3 pagination --------------------------------------------------------
DEFAULT_LIMIT = 10
MIN_LIMIT = 1
MAX_LIMIT = 100
DEFAULT_OFFSET = 0

# --- §3.1 program registration ---------------------------------------------
DEFAULT_HOST_CAPACITY_PER_DAY = 2
MIN_HOST_CAPACITY_PER_DAY = 1
MAX_HOST_CAPACITY_PER_DAY = 5

# --- §3.2 viability scoring -------------------------------------------------
ROLLING_WINDOW_SIZE = 3
EFFICIENCY_BENCHMARK_CENTS = 50000
ENROLLMENT_GAIN = 2.5
ENROLLMENT_MIDPOINT = 50
COMPLETION_SCALE = 250
EFFICIENCY_GAIN = 60
SMALL_PROGRAM_HEADCOUNT_THRESHOLD = 60
SMALL_PROGRAM_SCORE_CEILING = 39.99
BAND_CONTINUE_LOWER_BOUND = 60.00
BAND_IMPROVEMENT_LOWER_BOUND = 40.00

# degree_level -> (enrollment, completion, demand, efficiency)
VIABILITY_WEIGHTS = {
    "UNDERGRADUATE": (0.35, 0.25, 0.20, 0.20),
    "GRADUATE": (0.25, 0.30, 0.15, 0.30),
    "CERTIFICATE": (0.30, 0.20, 0.35, 0.15),
}

# --- §3.7 agency notice deadlines (whole days x 24h) ------------------------
NOTICE_DAYS_BY_AGENCY_TYPE = {
    "ACCREDITOR": 30,
    "STATE_AGENCY": 45,
    "FEDERAL": 60,
}
AUTO_MINTED_ACCREDITOR_CODE = "REGIONAL-ACC"
AUTO_MINTED_STATE_AGENCY_CODE = "STATE-CHE"

# --- §3.11 staffing waterfall ----------------------------------------------
SECTIONS_PER_FTE = 6
SEVERANCE_CAP_FRACTION = 0.15
STATUTORY_NOTICE_DAYS = {
    "TENURED": 365,
    "TENURE_TRACK": 180,
    "NON_TENURE_TRACK": 90,
    "ADJUNCT": 30,
}
TENURE_TIER_RANK = {
    "ADJUNCT": 1,
    "NON_TENURE_TRACK": 2,
    "TENURE_TRACK": 3,
    "TENURED": 4,
}
NOTICE_PAY_DAYS_DIVISOR = 365

# --- §3.10 displaced students ----------------------------------------------
CREDITS_PER_COURSE_SEAT = 3
MIN_CREDITS_PER_TERM = 1
MAX_CREDITS_PER_TERM = 21

# --- §2.10 loop bounds ------------------------------------------------------
SELF_STUDY_REVISION_LIMIT = 2
ADDENDUM_ROUND_LIMIT = 2
PLAN_REVISION_LIMIT = 3

# --- §3.4 reviewer defaults -------------------------------------------------
DEFAULT_TRAVEL_BUFFER_HOURS = 48
MIN_TRAVEL_BUFFER_HOURS = 0
MAX_TRAVEL_BUFFER_HOURS = 168


# --- Design-index fixture A -------------------------------------------------
# One UNDERGRADUATE program with three term snapshots, from
# SCAFFOLD_DIFFICULTY_DESIGN.yaml. Every figure below is the value the PRD's
# arithmetic uniquely derives from these three rows.
FIXTURE_A_SNAPSHOTS = [
    {
        "term_code": "2025FA",
        "term_index": 1,
        "enrollment_headcount": 30,
        "credit_hours": 300,
        "direct_cost_cents": 12000000,
        "completions_count": 4,
        "market_demand_index": 42,
    },
    {
        "term_code": "2026SP",
        "term_index": 2,
        "enrollment_headcount": 24,
        "credit_hours": 240,
        "direct_cost_cents": 11000000,
        "completions_count": 3,
        "market_demand_index": 40,
    },
    {
        "term_code": "2026FA",
        "term_index": 3,
        "enrollment_headcount": 20,
        "credit_hours": 200,
        "direct_cost_cents": 11000000,
        "completions_count": 2,
        "market_demand_index": 42,
    },
]
# sum(direct_cost) = 34000000, sum(credit_hours) = 740 -> 45945.94... -> 45946
FIXTURE_A_ROLLING_CPH_CENTS = 45946
# newest snapshot alone: 11000000 / 200 = 55000
FIXTURE_A_LATEST_CPH_CENTS = 55000
# the forbidden divide-then-average order would give this value instead
FIXTURE_A_FORBIDDEN_AVERAGED_CPH_CENTS = 46944
# per-snapshot diagnostic figures, in term_index order
FIXTURE_A_PER_SNAPSHOT_CPH_CENTS = [40000, 45833, 55000]
FIXTURE_A_COMPOSITE_UNDERGRADUATE = 29.06
FIXTURE_A_COMPOSITE_GRADUATE = 35.01
FIXTURE_A_COMPOSITE_SPREAD = 5.95
FIXTURE_A_BAND = "NONVIABLE"
# floor(0.15 * 34000000) = 5100000
FIXTURE_A_SEVERANCE_CAP_CENTS = 5100000

# --- Design-index boundary fixture: composite exactly 40.00 ----------------
# Three flat snapshots; the composite lands on the inclusive band boundary.
FIXTURE_BOUNDARY_SNAPSHOTS = [
    {
        "term_code": "2025FA",
        "term_index": 1,
        "enrollment_headcount": 125,
        "credit_hours": 400,
        "direct_cost_cents": 20000000,
        "completions_count": 7,
        "market_demand_index": 35,
    },
    {
        "term_code": "2026SP",
        "term_index": 2,
        "enrollment_headcount": 125,
        "credit_hours": 400,
        "direct_cost_cents": 20000000,
        "completions_count": 7,
        "market_demand_index": 35,
    },
    {
        "term_code": "2026FA",
        "term_index": 3,
        "enrollment_headcount": 125,
        "credit_hours": 400,
        "direct_cost_cents": 20000000,
        "completions_count": 7,
        "market_demand_index": 35,
    },
]
FIXTURE_BOUNDARY_ROLLING_CPH_CENTS = 50000
FIXTURE_BOUNDARY_COMPOSITE = 40.00
FIXTURE_BOUNDARY_BAND = "IMPROVEMENT_ELIGIBLE"
# A fourth snapshot that nudges the cost up by a hair and drops the composite
# to 39.99, flipping the band to NONVIABLE.
FIXTURE_BOUNDARY_FOURTH_SNAPSHOT = {
    "term_code": "2027SP",
    "term_index": 4,
    "enrollment_headcount": 125,
    "credit_hours": 400,
    "direct_cost_cents": 20050400,
    "completions_count": 7,
    "market_demand_index": 35,
}
FIXTURE_BOUNDARY_ROLLING_CPH_AFTER_FOURTH = 50042
FIXTURE_BOUNDARY_LATEST_CPH_AFTER_FOURTH = 50126
FIXTURE_BOUNDARY_COMPOSITE_AFTER_FOURTH = 39.99
FIXTURE_BOUNDARY_BAND_AFTER_FOURTH = "NONVIABLE"

# --- Section / finding code vocabularies used across the suite -------------
REQUIRED_SECTION_CODES = ["CURRICULUM", "ASSESSMENT", "RESOURCES"]
FINDING_CODES = ["F-CURRICULUM", "F-ASSESSMENT"]

# A UUID-shaped identifier that resolves to nothing.
UNKNOWN_UUID = "00000000-0000-4000-8000-000000000000"
