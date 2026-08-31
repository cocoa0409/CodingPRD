"""Domain thresholds and shared literals drawn from the PRD's calculations."""

# Numeric thresholds named in the PRD.
THRESHOLDS = {
    # §3.1 filing profile resolution
    "VOLUME_EXEMPTION_LIMIT": 500,               # strict <  on each prior-year count
    "ASSET_EXEMPTION_LIMIT_CENTS": 1000000000000,  # <= ten billion dollars
    "QUARTERLY_FILER_THRESHOLD": 60000,          # >= on the sum of both counts
    "REQUIRED_FIELDS_PARTIAL_EXEMPT": 26,
    "REQUIRED_FIELDS_FULL": 48,
    # §3.6 edit battery
    "ULI_MIN_LENGTH": 23,
    "LOAN_TO_INCOME_MULTIPLE": 5,
    "INCOME_THOUSANDS_TO_CENTS": 100000,
    "DECISION_LAG_DAYS": 180,
    "SMALL_LOAN_CENTS": 100000,
    "MACRO_WITHDRAWN_PCT": 30.0,
    "QUOTA_FRACTION": 0.10,
    # §3.7 disclosure suppression
    "SUPPRESSION_MIN_RECORDS": 5,
    "SUPPRESSION_MIN_OWNER_OCCUPIED_UNITS": 500,
    "REDACTED_FIELDS_PER_SUPPRESSED_RECORD": 3,
    # §3.8 audit sampling
    "AUDIT_MIN_SAMPLE": 5,
    "AUDIT_MAX_SAMPLE": 50,
    # §3.9 fair lending
    "DISPARITY_CAP": 999.99,
    "DISPARITY_EQUAL": 100.00,
    "SEVERE_THRESHOLD": 200.0,
    "ELEVATED_THRESHOLD": 125.0,
    "SECONDS_PER_DAY": 86400,
}

# Shared test literals: the register lives inside one activity year.
DEFAULT_ACTIVITY_YEAR = 2026
DEFAULT_CLOCK = "2026-08-01T00:00:00Z"
DEFAULT_FILING_DEADLINE = "2027-03-01T23:59:59.000Z"

TEST_DEFAULTS = {
    "PRIMARY_LEI": "5493001KJTIIGC8Y1R12",
    "SECONDARY_LEI": "5493001KJTIIGC8Y1R99",
    "EXEMPT_LEI": "5493001KJTIIGC8Y1R77",
    "PRIMARY_NAME": "First Meridian Bank",
    "SECONDARY_NAME": "Second Harbor Savings",
    "ASSET_SIZE_CENTS": 250000000000,
    "CLOSED_END_ORIGINATIONS": 700,
    "OPEN_END_ORIGINATIONS": 40,
    "LOAN_AMOUNT_CENTS": 35000000,
    "INCOME_THOUSANDS": 120,
    "RATE_SPREAD": 1.75,
}

# Census tract reference literals used across the fixtures.
TRACT_A = {
    "tract_code": "06075010100",
    "county_fips": "06075",
    "state_code": "CA",
    "msa_md_code": "41860",
    "minority_population_pct": 42.5,
    "tract_to_msa_income_pct": 88.4,
    "owner_occupied_units": 1200,
    "median_family_income_cents": 9500000,
}

TRACT_B = {
    "tract_code": "06075010200",
    "county_fips": "06075",
    "state_code": "CA",
    "msa_md_code": "41860",
    "minority_population_pct": 51.2,
    "tract_to_msa_income_pct": 74.9,
    "owner_occupied_units": 430,
    "median_family_income_cents": 8100000,
}

TRACT_TX = {
    "tract_code": "48201310100",
    "county_fips": "48201",
    "state_code": "TX",
    "msa_md_code": "26420",
    "minority_population_pct": 61.0,
    "tract_to_msa_income_pct": 65.5,
    "owner_occupied_units": 380,
    "median_family_income_cents": 6400000,
}

# Property literals matching TRACT_A's jurisdiction.
PROPERTY_CA = {
    "street_address": "1 Market St",
    "city": "San Francisco",
    "state_code": "CA",
    "zip_code": "94105",
    "county_fips": "06075",
}

# Operator identifiers threaded through the filing chain.
ANALYST_NOVA = "analyst-nova"
ANALYST_VEGA = "analyst-vega"
OFFICER_ALPHA = "officer-alpha"
OFFICER_BETA = "officer-beta"
EXAMINER_RHO = "examiner-rho"
SHARED_USER = "shared-user-1"
