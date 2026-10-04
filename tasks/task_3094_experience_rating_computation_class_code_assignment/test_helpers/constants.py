"""Domain thresholds - numeric constants used by the PRD's computations.

The canonical bureau parameters come from the standard bureau fixture; the
logical clock starts at 2026-09-01T00:00:00Z before any call is made.
"""

# Canonical bureau parameter set used by most fixtures.
BUREAU = {
    "eligibility_threshold_cents": 500000,
    "split_point_cents": 1000000,
    "credibility_ballast_bp": 4000,
    "credibility_excess_divisor_bp": 6000,
    "underwriting_threshold_cents": 2500000,
}

# Logical clock instant before any clock-setting call.
DEFAULT_CLOCK_UTC = "2026-09-01T00:00:00Z"

# Canonical rating values for class code 3632 in Texas.
RATE_PER_100_PAYROLL_CENTS_3632 = 250
ELR_PER_100_PAYROLL_CENTS_3632 = 150
D_RATIO_BP_3632 = 4000

TEST_DEFAULTS = {
    "STATE_CODE": "TX",
    "CLASS_CODE": "3632",
}
