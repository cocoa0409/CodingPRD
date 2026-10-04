"""Domain thresholds and shared literals for the concierge pre-sale advance program.

All numeric constants are pinned by the PRD (program rules and fee terms).
"""

# --- Program-pinned constants (PRD eligibility / fee rules) ---
MIN_EQUITY_RATIO = 1.10          # proceeds must exceed value * 1.10
ADVANCE_LIMIT_RATE = 0.15        # advance cap = floor(proceeds * 0.15)
LATE_GRACE_DAYS = 7              # completion_deadline = end_date + 7 days
PROGRAM_FEE_RATE_A = 0.03        # variant A: sold/listed within window
PROGRAM_FEE_RATE_B = 0.01        # variant B base: not sold within window
LATE_ACCRUAL_RATE = 0.005        # variant B monthly accrual
LATE_FEE_RATE = 0.002            # late fee per month late (variant B only)
VENDOR_FAULT_PENALTY_BP = 500
LATE_PENALTY_BP = 200
QUALITY_RECOVERY_BP = 50
QUALITY_SCORE_MAX_BP = 10000
DEFAULT_LISTING_WINDOW_DAYS = 180
LOGICAL_CLOCK_START = "2026-09-01T00:00:00Z"

# --- Shared fixture literals ---
TEST_DEFAULTS = {
    "ADDRESS_LINE": "123 Main St",
    "ESTIMATED_PROPERTY_VALUE_CENTS": 80_000_000,
    "EXPECTED_SALE_PROCEEDS_CENTS": 100_000_000,
    # floor(100_000_000 * 0.15) == 15_000_000
    "ADVANCE_LIMIT_CENTS": 15_000_000,
    "PROJECT_TITLE": "Kitchen",
    "PROJECT_LIFT_CENTS": 5_000_000,
    "PROJECT_COST_CENTS": 5_000_000,
    "AGREED_PRICE_CENTS": 5_000_000,
    "DISBURSEMENT_AMOUNT_CENTS": 5_000_000,
    "LIST_PRICE_CENTS": 105_000_000,
    "CAPACITY_CREW_DAYS": 100,
    "WINDOW_START": "2026-09-01T00:00:00Z",
    "WINDOW_END": "2026-12-31T23:59:59Z",
    "ENGAGEMENT_START": "2026-09-05T00:00:00Z",
    "ENGAGEMENT_END": "2026-09-20T00:00:00Z",
}

# Standard half-open capacity window covering the whole Fall 2026 season.
DEFAULT_WINDOW = (
    TEST_DEFAULTS["WINDOW_START"],
    TEST_DEFAULTS["WINDOW_END"],
    TEST_DEFAULTS["CAPACITY_CREW_DAYS"],
)
