"""Domain constants — numeric thresholds and dates from the PRD.

Every value below is stated verbatim in PRD.md:
- F_CRITICAL = 3.0, COVERAGE_K = 2, Z_PASS_THRESHOLD = 2.0 (§3.2, §3.4, §3.7)
- PT_PROBATION_FAIL_COUNT = 2, PT_SUSPENSION_FAIL_COUNT = 3 (§3.7)
- MIN_KC_RESULTS = 2 (§3.7)
- Tier weights FEDERAL 3 / ACCREDITED_LAB 2 / GENERAL 1 (§3.5)
- Logical clock startup default 2026-09-01T00:00:00Z (§2.4)
"""

F_CRITICAL = 3.0
COVERAGE_K = 2
Z_PASS_THRESHOLD = 2.0
PT_PROBATION_FAIL_COUNT = 2
PT_SUSPENSION_FAIL_COUNT = 3
MIN_KC_RESULTS = 2

TIER_WEIGHT_FEDERAL = 3
TIER_WEIGHT_ACCREDITED_LAB = 2
TIER_WEIGHT_GENERAL = 1

CLOCK_START = "2026-09-01T00:00:00Z"

# Default program pricing configuration used across fixtures.
DEFAULT_PROGRAM_PAYLOAD = {
    "program_code": "NIST-RM-01",
    "name": "RM Program",
    "material_unit_price_cents": 1000,
    "discount_pct_federal": 0,
    "discount_pct_accredited_lab": 10,
    "discount_pct_general": 0,
    "handling_fee_threshold_cents": 10000,
    "handling_fee_flat_cents": 500,
    "expedite_multiplier_pct": 150,
    "daily_lab_capacity_minutes": 480,
}

# Homogeneity payloads. FLAT yields f_ratio 0.0 (PASS) with u_hom 0.0 and
# consumes 4 bottles; FAILING yields f_ratio 12.0 (FAIL) with u_hom 3.391165.
FLAT_HOMOGENEITY = {
    "bottle_means": [10.0, 10.0, 10.0, 10.0],
    "within_bottle_std": 0.5,
    "replicates_per_bottle": 2,
}
FAILING_HOMOGENEITY = {
    "bottle_means": [7.0, 7.0, 13.0, 13.0],
    "within_bottle_std": 1.0,
    "replicates_per_bottle": 2,
}

# Standard independent method pair used by certification fixtures.
METHOD_ONE = {"method_code": "ID-ICP-MS", "method_mean": 100.0, "method_std_uncertainty": 2.0}
METHOD_TWO = {"method_code": "GRAV", "method_mean": 104.0, "method_std_uncertainty": 1.0}

# Opaque operator user ids (PRD §2.1: non-Customer roles carry opaque ids).
ANALYST_ONE = "met-1"
ANALYST_TWO = "met-2"
OFFICER_ONE = "co-1"
OFFICER_TWO = "co-2"

# Scheduling windows used by calibration fixtures (all after CLOCK_START).
WINDOW_START = "2026-10-05T09:00:00Z"
WINDOW_END = "2026-10-05T11:00:00Z"
LINK_CALIBRATED_DATE = "2026-06-01T00:00:00Z"
LINK_DUE_DATE = "2027-01-01T00:00:00Z"
