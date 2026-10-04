"""Domain thresholds and reference tables (PRD §2.7, §2.8, §3.2, §3.7, §3.9)."""

# ---------------------------------------------------------------------------
# Logical clock (PRD §2.4)
# ---------------------------------------------------------------------------
CLOCK_START = "2026-09-01T00:00:00Z"
CLOCK_PATH = "/_clock/set_current_utc"

# A few instants the seal/license recipes pin.
CLOCK_2026_10_01 = "2026-10-01T00:00:00Z"
CLOCK_2027_09_01 = "2027-09-01T00:00:00Z"
CLOCK_2027_09_16 = "2027-09-16T00:00:00Z"
CLOCK_2027_12_01 = "2027-12-01T00:00:00Z"

# ---------------------------------------------------------------------------
# Unit multipliers (PRD §3.5)
# ---------------------------------------------------------------------------
UNIT_MULTIPLIER = {
    "USD_WHOLE": 100,
    "USD_THOUSANDS": 100000,
    "USD_MILLIONS": 100000000,
    "PLAIN_INTEGER": 100,
}

CONFIDENCE_BY_FORMAT = {
    "USD_WHOLE": 99.0,
    "PLAIN_INTEGER": 99.0,
    "USD_THOUSANDS": 92.0,
    "USD_MILLIONS": 85.0,
}

# ---------------------------------------------------------------------------
# Closed reference tables (PRD §2.7)
# ---------------------------------------------------------------------------
FORM_VERSION_LINE_MAP = {
    2019: ["TOTREV", "PROGREV", "CONTRIB", "SALARIES", "OCCUPANCY", "PROF_FUNDRAISING"],
    2020: ["TOTREV", "PROGREV", "CONTRIB", "SALARIES", "OCCUPANCY", "PROF_FUNDRAISING",
           "GOV_GRANTS"],
    2021: ["TOTREV", "PROGREV", "CONTRIB", "SALARIES", "OCCUPANCY", "PROF_FUNDRAISING",
           "GOV_GRANTS"],
    2022: ["TOTREV", "PROGREV", "CONTRIB", "SALARIES", "OCCUPANCY", "PROF_FUNDRAISING",
           "GOV_GRANTS", "NET_ASSETS"],
    2023: ["TOTREV", "PROGREV", "CONTRIB", "SALARIES", "OCCUPANCY", "PROF_FUNDRAISING",
           "GOV_GRANTS", "NET_ASSETS"],
    2024: ["TOTREV", "PROGREV", "CONTRIB", "SALARIES", "OCCUPANCY", "PROF_FUNDRAISING",
           "GOV_GRANTS", "NET_ASSETS", "CRYPTO_HOLDINGS"],
}

PERMITTED_USES_BY_TIER = {
    "RESEARCHER": ["AGGREGATE_RESEARCH"],
    "FUNDER": ["AGGREGATE_RESEARCH", "GRANTMAKING_DUE_DILIGENCE"],
    "PLATFORM": ["AGGREGATE_RESEARCH", "GRANTMAKING_DUE_DILIGENCE",
                 "PLATFORM_REDISTRIBUTION", "MARKETING_PROSPECTING"],
}

# ---------------------------------------------------------------------------
# Completeness / disclosure weights (PRD §3.2)
# ---------------------------------------------------------------------------
DIMENSION_WEIGHTS = {
    "PROGRAMS": 0.15,
    "FINANCES": 0.25,
    "LEADERSHIP": 0.20,
    "DEMOGRAPHICS": 0.15,
    "MISSION": 0.10,
    "GOVERNANCE": 0.15,
}

DISCLOSURE_WEIGHTS = {
    "PROGRAMS": 0.15,
    "FINANCES": 0.30,
    "LEADERSHIP": 0.20,
    "DEMOGRAPHICS": 0.15,
    "MISSION": 0.10,
    "GOVERNANCE": 0.10,
}

PROFILE_COMPLETENESS_FLOOR = 50

# ---------------------------------------------------------------------------
# Transparency seals (PRD §3.7)
# ---------------------------------------------------------------------------
SEAL_RANK = {"BRONZE": 1, "SILVER": 2, "GOLD": 3, "PLATINUM": 4}
SEAL_BASE_FEE_CENTS = {"BRONZE": 0, "SILVER": 25000, "GOLD": 75000, "PLATINUM": 200000}
SEAL_DISCLOSURE_FLOOR = 0.50
DISCLOSURE_PLATINUM = 0.90
DISCLOSURE_GOLD = 0.75
SEAL_TERM_DAYS = 365
RENEWAL_WINDOW_DAYS = 60
LEADERSHIP_VERIFIED_FLOOR = 0.50
PLATINUM_MIN_VERIFIED_FILINGS = 2
GOLD_MIN_VERIFIED_FILINGS = 1
SEAL_LATE_PCT = {0: 0.0, 1: 0.10, 2: 0.25, 3: 0.50}

# Disclosure floors that revoke an ACTIVE seal whose level they fall below.
SEAL_REVOCATION_FLOOR = {"BRONZE": 0.50, "SILVER": 0.50, "GOLD": 0.75, "PLATINUM": 0.90}

# ---------------------------------------------------------------------------
# Data licensing (PRD §3.9)
# ---------------------------------------------------------------------------
TIER_BASE_FEE_CENTS = {"RESEARCHER": 500000, "FUNDER": 2500000, "PLATFORM": 10000000}
TIER_INCLUDED_RECORDS = {"RESEARCHER": 10000, "FUNDER": 100000, "PLATFORM": 1000000}
TIER_OVERAGE_RATE_CENTS = {"RESEARCHER": 5, "FUNDER": 2, "PLATFORM": 1}
QUOTA_HARD_CAP_MULTIPLIER = 4

# ---------------------------------------------------------------------------
# Grant recipient matching (PRD §3.9)
# ---------------------------------------------------------------------------
EIN_MATCH_POINTS = 60
NAME_EXACT_POINTS = 30
NAME_PREFIX_POINTS = 18
NAME_PREFIX_CHARS = 12
SUBJECT_MATCH_POINTS = 10
MATCHED_MIN_SCORE = 70
AMBIGUOUS_MIN_SCORE = 40
NAME_SUFFIX_TOKENS = ["INC", "INCORPORATED", "CORP", "CORPORATION", "LLC", "LTD",
                      "FOUNDATION", "FUND", "TRUST", "ASSOCIATION", "SOCIETY"]

# ---------------------------------------------------------------------------
# Prospect research (PRD §3.9)
# ---------------------------------------------------------------------------
GEO_MATCH_POINTS = 25
PROSPECT_SUBJECT_MATCH_POINTS = 35
SIZE_BAND_POINTS = 20
HISTORY_POINTS = 20
SIZE_BAND_LOW_MULTIPLIER = 0.5
SIZE_BAND_HIGH_MULTIPLIER = 2.0

# ---------------------------------------------------------------------------
# Test defaults
# ---------------------------------------------------------------------------
DEFAULT_SERVICE_START = "2024-01-01T00:00:00Z"
DEFAULT_COVERAGE_START = "2025-01-01T00:00:00Z"
DEFAULT_COVERAGE_END = "2025-12-31T00:00:00Z"
DEFAULT_TERM_START = CLOCK_START
DEFAULT_TERM_END = CLOCK_2027_09_01
DEFAULT_EIN_BASE = 900100200
