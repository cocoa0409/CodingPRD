"""Domain thresholds and canonical fixture literals for the NMTC deployment API.

Every value here is stated in PRD.md; nothing is invented.  Money is always
expressed in integer cents, and every instant is a full ISO-8601 UTC timestamp
with exactly three fractional digits.
"""

# --- Logical clock (PRD 2.4) -------------------------------------------------

#: The clock's value before any test moves it.
CLOCK_DEFAULT_UTC = "2026-08-01T00:00:00.000Z"

#: "A "year" in this domain means exactly 365 days, that is 31,536,000 seconds."
SECONDS_PER_YEAR = 31_536_000
DAYS_PER_YEAR = 365

# --- Pagination (PRD 2.3) ---------------------------------------------------

PAGINATION = {
    "DEFAULT_LIMIT": 10,
    "MIN_LIMIT": 1,
    "MAX_LIMIT": 100,
}

# --- Deadlines and windows measured in days --------------------------------

WINDOW_DAYS = {
    "DEPLOYMENT": 365,          # QEI.deployment_deadline_at = issued_at + 365 days
    "CURE": 180,                # cure_deadline_at = clock + 180 days
    "REINVESTMENT": 365,        # reinvest_by_at = arose_at + 365 days
    "RECERTIFICATION": 365,     # strictly more than 365 days since last_certified_at
    "COMPLIANCE_PERIOD": 365,   # annual test window_days is always 365
    "QALICB_BUFFER": 30,        # symmetric compliance-period conflict buffer
    "OPTION_WINDOW_OPEN": 2555,  # option_window_open_at = issued_at + 2555 days
    "OPTION_WINDOW_LENGTH": 90,  # option_window_close_at = open + 90 days
}

# --- Census tract distress profile (PRD 3.2) -------------------------------

TRACT_THRESHOLDS = {
    "LIC_POVERTY_PCT": 20.00,
    "LIC_MFI_RATIO_PCT": 80.00,
    "CONTIGUITY_POVERTY_PCT": 15.00,
    "SEVERE_POVERTY_PCT": 30.00,
    "SEVERE_MFI_RATIO_PCT": 60.00,
    "SEVERE_UNEMPLOYMENT_RATIO": 1.50,
    "TIER_SEVERE_SCORE": 75.00,
    "TIER_HIGH_SCORE": 50.00,
}

DISTRESS_SCORE_WEIGHTS = {
    "POVERTY": 40,
    "MFI": 35,
    "UNEMPLOYMENT": 25,
}

DISTRESS_SCORE_MAX = 100.00

# --- Six-prong project-company eligibility test (PRD 3.3) -----------------

PRONG_THRESHOLDS = {
    "GROSS_INCOME_MIN_PCT": 50.00,
    "SERVICES_MIN_PCT": 40.00,
    "TANGIBLE_PROPERTY_MIN_PCT": 40.00,
    "COLLECTIBLES_MAX_PCT": 5.00,
    "NQFP_MAX_PCT": 5.00,
}

#: The fixed order in which failed prongs are reported.
FAILED_PRONG_ORDER = [
    "LOCATION",
    "GROSS_INCOME",
    "SERVICES",
    "TANGIBLE_PROPERTY",
    "COLLECTIBLES",
    "NQFP",
]

#: Two consecutive failures disqualify the project company.
CONSECUTIVE_FAILURES_TO_DISQUALIFY = 2

#: Two consecutive CURE_REQUIRED certifications breach the agreement.
CONSECUTIVE_CURES_TO_BREACH = 2

# --- Reserve tiers and fees (PRD 3.4, PRD 3.8) ----------------------------

#: Half-open gross-amount bands, in cents, mapped to reserve basis points.
RESERVE_TIERS = [
    (0, 500_000_000, 500),
    (500_000_000, 1_500_000_000, 400),
    (1_500_000_000, None, 300),
]

FEE_ALLOCATION_BPS = 50           # annual asset-management fee, basis points of gross
BPS_DENOMINATOR = 10_000

# --- Substantially-all test (PRD 3.5, PRD 3.8) ----------------------------

SUBSTANTIALLY_ALL_THRESHOLD_PCT = 85.00
COMPLIANCE_PERIOD_YEARS = 7
MIN_COMPLIANCE_YEAR = 1
MAX_COMPLIANCE_YEAR = 7

#: Sub-allocation statuses that count toward the substantially-all numerator.
QUALIFYING_QLICI_STATUSES = ["DEPLOYED", "PARTIALLY_REPAID"]

# --- Recapture arithmetic (PRD 3.8) --------------------------------------

RECAPTURE_BPS_BY_YEAR = {
    1: 500,
    2: 1000,
    3: 1500,
    4: 2100,
    5: 2700,
    6: 3300,
    7: 3900,
}

RECAPTURE_INTEREST_BPS_PER_YEAR = 300

# --- Unwind pricing (PRD 3.9) -------------------------------------------

PUT_PRICE_CENTS = 100_000
CALL_PRICE_BPS = 250
CALL_PRICE_FLOOR_CENTS = 100_000

# --- Minimum amounts (PRD 3.1, 3.4, 3.5) --------------------------------

MIN_ALLOCATION_AMOUNT_CENTS = 100_000_000
MIN_QEI_AMOUNT_CENTS = 10_000_000
MIN_QLICI_PRINCIPAL_CENTS = 100_000

AWARD_YEAR_MIN = 2020
AWARD_YEAR_MAX = 2035

# --- Enumerations reproduced for parametrised tests ---------------------

SERVICE_AREA_SCOPES = ["NATIONAL", "MULTI_STATE", "STATEWIDE", "LOCAL"]
SUBSTANTIALLY_ALL_METHODS = ["DIRECT_TRACING", "AGGREGATE_BALANCE"]
MEASUREMENT_BASES = ["HEADCOUNT", "PAYROLL_HOURS"]
PAYROLL_HOURS_PER_FTE = 2080

# --- Canonical fixture literals ----------------------------------------

TEST_DEFAULTS = {
    "CLOCK_AT_SETUP": "2026-09-01T00:00:00.000Z",
    "CDE_LEGAL_NAME": "Gulf Coast CDE",
    "CDE_SERVICE_AREA_SCOPE": "MULTI_STATE",
    "AWARD_YEAR": 2026,
    "ALLOCATION_AMOUNT_CENTS": 5_000_000_000,
    "SERVICE_AREA_STATE_CODES": ["MS"],
    "MIN_SEVERE_DISTRESS_SHARE_PCT": 60.00,
    "SUBSTANTIALLY_ALL_METHOD": "DIRECT_TRACING",
    "SIGNATORY_NAME": "A. Rivers",
    "TRACT_CODE": "28049000100",
    "STATE_CODE": "MS",
    "TRACT_POVERTY_RATE_PCT": 32.00,
    "TRACT_MFI_RATIO_PCT": 55.00,
    "TRACT_UNEMPLOYMENT_RATIO": 1.80,
    "QALICB_LEGAL_NAME": "Delta Foods LLC",
    "QALICB_NAICS_CODE": "311412",
    "CBA_TARGET_FTE_COUNT": 25,
    "CBA_WAGE_FLOOR_CENTS_PER_HOUR": 1800,
    "CBA_LOCAL_HIRE_PCT_TARGET": 40.00,
    "CBA_MEASUREMENT_BASIS": "HEADCOUNT",
    "FUND_LEGAL_NAME": "NMTC Fund I LLC",
    "FUND_EQUITY_CONTRIBUTION_CENTS": 65_000_000,
    "FUND_LEVERAGE_LENDER_NAME": "Bayou National Bank",
    "FUND_LEVERAGE_LOAN_PRINCIPAL_CENTS": 35_000_000,
    "FUND_LEVERAGE_LOAN_RATE_BPS": 450,
    "QEI_AMOUNT_CENTS": 100_000_000,
    "QLICI_LOAN_CLASS": "A",
    "QLICI_PRINCIPAL_CENTS": 85_000_000,
}
