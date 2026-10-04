"""Domain thresholds and test defaults.

Numeric constants from the contract's calculation rules (administrative
charge brackets, access-fee tiering) and the logical clock's startup
reading.
"""

ADMIN_BRACKETS = {
    "BRACKET1_CAP": 10000,
    "BRACKET2_CAP": 100000,
    "RATE1": 0.05,
    "RATE2": 0.03,
    "RATE3": 0.01,
}

CLOCK_START = "2026-09-01T00:00:00Z"
BASE_CLOCK = "2026-08-01T00:00:00Z"

TEST_DEFAULTS = {
    "BILLED_AMOUNT_CENTS": 20000,
    "NEGOTIATED_RATE_CENTS": 30000,
    "TIER1_CAP_CENTS": 10000,
    "TIER1_FEE_CENTS": 150,
    "TIER2_RATE": 0.02,
}
