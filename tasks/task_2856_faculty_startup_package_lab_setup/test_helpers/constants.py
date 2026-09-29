"""Domain thresholds and calculation constants from the Faculty Startup Package PRD.

Every value here is stated verbatim in the PRD narrative; nothing is invented.
Generic helpers such as NON_EXISTENT_UUID come from the framework package.
"""

# The logical clock's startup default (PRD 2.5).
CLOCK_STARTUP_DEFAULT = "2026-08-01T00:00:00Z"

# Renovation cost allocation (PRD 3.6).
RENOVATION_SUBSIDY_PCT = {
    "COSMETIC": 0,
    "MODERATE": 25,
    "GUT": 40,
}
RENOVATION_SUBSIDY_CAP_CENTS = 20_000_000
OVERRUN_TOLERANCE_PCT = 10

# Fiscal year-end rollover (PRD 3.9).
MIN_SPENDDOWN_RATIO_FOR_CARRYFORWARD = 0.5000

# Internal-transfer settlement (PRD 3.9).
COLLEGE_HOLDBACK_PCT = 15

# Retention counteroffer recommitment floor (PRD 3.9).
MIN_NEW_MONEY_CENTS = 2_500_000

# Construction phase changeover buffer (PRD 3.6).
PHASE_BUFFER_DAYS = 2

# The fixed funder ordering used to break largest-remainder ties (PRD 2.7).
FUNDER_ORDINAL = ["DEPARTMENT", "COLLEGE", "DEAN_OFFICE"]

# Precision rules (PRD 2.6).
SPEND_DOWN_RATIO_DECIMALS = 4
POWER_KW_DECIMALS = 2

# Pagination contract (PRD 2.3).
PAGINATION = {
    "DEFAULT_LIMIT": 10,
    "MIN_LIMIT": 1,
    "MAX_LIMIT": 100,
    "DEFAULT_OFFSET": 0,
}

# Fiscal year label bounds (PRD 2.5).
FISCAL_YEAR_MIN = 2020
FISCAL_YEAR_MAX = 2100

# Shared test data defaults, so scenarios across the suite line up.
TEST_DEFAULTS = {
    "COLLEGE_POOL_CENTS": 900_000_000,
    "DEPARTMENT_POOL_CENTS": 400_000_000,
    "DEAN_OFFICE_POOL_CENTS": 300_000_000,
    "DEPT_SHARE_PCT": 45,
    "COLLEGE_SHARE_PCT": 35,
    "DEAN_SHARE_PCT": 20,
    "PROPOSED_TOTAL_CENTS": 20_000_000,
    "SPEND_DEADLINE_ON": "2028-06-30",
    "FACULTY_NAME": "Ada Reyes",
    "FACULTY_RANK": "ASSISTANT",
    "PLANNED_START_DATE": "2026-08-15",
    "DEAN_OFFICE_USER_ID": "U-DEANOFFICE-1",
    "FACILITIES_USER_ID": "U-FACILITIES-1",
}

# Fiscal year 2027 runs 2026-07-01 inclusive to 2027-07-01 exclusive (PRD 2.5).
FY2027_AVAILABLE_ON = "2026-07-01T00:00:00Z"
FY2027_EXPIRES_ON = "2027-07-01T00:00:00Z"
FY2028_AVAILABLE_ON = "2027-07-01T00:00:00Z"
FY2028_EXPIRES_ON = "2028-07-01T00:00:00Z"
