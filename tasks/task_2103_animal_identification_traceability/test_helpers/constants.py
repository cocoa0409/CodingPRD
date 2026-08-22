"""Domain thresholds and fixed numeric constants stated by the PRD."""

# --- Programme clock -------------------------------------------------------
# Before any client sets it, the logical clock reads exactly 2026-08-01T00:00:00Z.
DEFAULT_CLOCK_UTC = "2026-08-01T00:00:00Z"
DEFAULT_CLOCK_STAMP = "2026-08-01T00:00:00.000Z"

# --- Tag lot issuance fee --------------------------------------------------
BASE_FEE_CENTS = 25_000
PER_TAG_CENTS = 42
PROBATION_SURCHARGE_PCT = 0.04
DISCOUNT_TIERS = (
    # (inclusive subtotal floor, discount percentage)
    (400_000, 0.18),
    (150_000, 0.12),
    (50_000, 0.05),
    (0, 0.00),
)

# --- Supplier conformance --------------------------------------------------
DEFECT_WEIGHT = 12.0
RETENTION_WEIGHT = 20.0
PROBATION_THRESHOLD = 85.00
SUSPEND_THRESHOLD = 70.00
REVOKE_THRESHOLD = 40.00
DEFAULT_ISSUANCE_CAP = 10_000
ISSUANCE_CAP_TIERS = (
    (95.00, 10_000),
    (85.00, 5_000),
    (70.00, 2_000),
    (0.00, 0),
)

# --- Movement reporting timeliness ----------------------------------------
ON_TIME_MAX_HOURS = 72.00

# --- Reconciliation --------------------------------------------------------
VARIANCE_TOLERANCE_PCT = 0.50

# --- Traceback -------------------------------------------------------------
ENV_WINDOW_DAYS = 14
W_RESPONDED = 40.0
W_RESOLVED = 35.0
W_REACH = 25.0
STALE_PREMISES_PENALTY = 10.0
DISPUTE_PENALTY_EACH = 5.0
DISPUTE_PENALTY_CAP = 15.0
TRACE_GOAL_HOURS = 48.00
MIN_COMPLETENESS = 80.00

# --- Quarantine holds ------------------------------------------------------
HOLD_COOLDOWN_HOURS = 72

# --- Incentive award -------------------------------------------------------
BASE_RATE_CENTS_PER_HEAD = 137
TIER_FACTORS = {
    "TIER_0": 0.00,
    "TIER_1": 1.00,
    "TIER_2": 1.15,
    "TIER_3": 1.30,
}
COMPLIANCE_MULTIPLIERS = (
    (95.00, 1.25),
    (80.00, 1.00),
    (50.00, 0.60),
    (0.00, 0.00),
)

# --- Bounded repetition ----------------------------------------------------
MAX_CORRECTIONS = 3
MAX_APPEALS = 2

# --- AIN / serial space ----------------------------------------------------
SERIAL_MIN = 100_000_000_000
SERIAL_MAX = 999_999_999_999
DEFAULT_AID_PREFIX = "840"
DEFAULT_SERIAL_START = 100_000_000_001

# --- Pagination ------------------------------------------------------------
DEFAULT_LIMIT = 10
MAX_LIMIT = 100
MIN_LIMIT = 1
