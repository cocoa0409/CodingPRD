"""Domain thresholds and shared literals from the PRD (Sections 2.4, 3.3-3.8)."""

# Logical clock startup default (PRD Section 2.4).
DEFAULT_CLOCK_ISO = "2026-08-01T00:00:00Z"

# Revision loop bound (PRD Section 3.3): return allowed only while
# revision_count is below three; a fourth attempt is refused.
MAX_REVISIONS = 3

# Load-cap guard (PRD Section 3.5): prospective load may reach at most
# load_cap_units + overage allowance; strictly greater is refused.
OVERAGE_ALLOWANCE_UNITS = 1.00

# Cancellation partial-pay constants (PRD Section 3.6).
PRE_CENSUS_PCT = 0.10
LATE_FLOOR_PCT = 0.25
ONBOARDING_STIPEND_CENTS = 5000

# Evaluation composite weights (PRD Section 3.8).
W_TEACHING = 0.60
W_SERVICE = 0.25
W_COMPLIANCE = 0.15

# Canonical fall-term window used across tests:
# 2026-08-24 .. 2026-12-11 -> 110 inclusive days, 15 whole weeks.
TERM_2026FA = {
    "code": "2026FA",
    "start_date": "2026-08-24",
    "end_date": "2026-12-11",
    "early_census_date": "2026-09-14",
    "late_census_date": "2026-11-02",
}
TERM_2026FA_TOTAL_DAYS = 110
TERM_2026FA_WHOLE_WEEKS = 15
TERM_START_2026FA_ISO = "2026-08-24T00:00:00Z"
SETUP_CLOCK_ISO = "2026-06-01T00:00:00Z"

# Canonical PER_CONTACT_HOUR schedule: 3.0 weekly contact hours at
# contact_hour_value 1.00 -> load_units 3.00, gross 200000 * 3.0 * 15.
PCH_BASE_RATE_CENTS = 200000
PCH_STEP_CENTS = 5000
PCH_STEP_CAP = 5
CANONICAL_SECTION_HOURS = 3.0
CANONICAL_LOAD_UNITS = 3.00
CANONICAL_GROSS_CENTS = 9000000

# Precomputed cancellation tiers for the canonical gross (PRD Section 3.6).
PRE_CENSUS_PAYABLE_CENTS = 905000          # rhu(9000000*0.10) + 5000
LATE_AT_EARLY_CENSUS_PAYABLE_CENTS = 2250000  # floor wins over earned 1800000
LATE_OCT19_PAYABLE_CENTS = 4663636         # elapsed 57/110 beats floor

# Canonical 4-period split of the fall term (28/28/28/26 overlap days).
FALL_PERIODS = [
    ("2026FA-P1", "2026-08-24", "2026-09-20"),
    ("2026FA-P2", "2026-09-21", "2026-10-18"),
    ("2026FA-P3", "2026-10-19", "2026-11-15"),
    ("2026FA-P4", "2026-11-16", "2026-12-13"),
]
DAYS_WEIGHTED_9000000 = [2290909, 2290909, 2290909, 2127273]

# Well-formed but never-assigned identifier for 404 probes.
ABSENT_UUID = "8a3e1c0b-2f4d-4a91-9c8b-12e7b6a0f1d2"
