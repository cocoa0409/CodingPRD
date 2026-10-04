"""Domain thresholds and fixed constants stated by the PRD.

Every value here is quoted from the PRD's own arithmetic (billing rate, dimensional
tolerance, commitment grace bands, interval lengths, response-time ladders).
"""

# ─── Instrument billing ──────────────────────────────────────────────────────
SERVICE_LIST_PRICE_CENTS_PER_LOAD = 125000
LIVES_EXHAUSTION_SURCHARGE_CENTS = 45000

# ─── Placement fee ladder ────────────────────────────────────────────────────
DIMENSIONAL_UPLIFT_PER_TWO_CLEARANCES_CENTS = 150000
INTEGRATION_UPLIFT_PER_TIER_CENTS = 250000
IDN_VOLUME_DISCOUNT_PER_PEER = 0.02
IDN_VOLUME_DISCOUNT_CAP = 0.04

# ─── Site readiness / construction uplift ────────────────────────────────────
NEAR_MISS_TOLERANCE_CM = 5
CONSTRUCTION_UPLIFT_BASE_CENTS = 304800
CONSTRUCTION_UPLIFT_ESCALATION_CENTS = 76200

# ─── Commitment accounting ───────────────────────────────────────────────────
SHORTFALL_GRACE_PROCEDURES = 2
SHORTFALL_RATE_BASIS_POINTS = 200
TIER_SCALE_DIVISOR = 1000000
BASELINE_FLOOR_CASES = 8
HIGH_FLOOR_CASES = 15
EXPANSION_READY_FLOOR_CASES = 22

# ─── Coverage response-time ladder ───────────────────────────────────────────
SERVICE_TIER_INDEX = {
    "COMPREHENSIVE": 3,
    "STANDARD": 2,
    "LIMITED": 1,
    "PARTS_ONLY": 0,
}
BASE_RESPONSE_HOURS = 48
HOURS_REDUCTION_PER_TIER = 12
MIN_RESPONSE_HOURS = 4
MAX_RESPONSE_HOURS = 24

# ─── Incident penalties ──────────────────────────────────────────────────────
GRACE_HOURS = 6
ESCALATION_HOURS = 24
MAX_PENALTY_POINTS = 15
MONTHLY_DECAY_POINTS = 1

# ─── Scheduling / loaner windows ─────────────────────────────────────────────
TURNOVER_BUFFER_MINUTES = 30
LOANER_WINDOW_DAYS = 14
LOANER_BUFFER_HOURS = 4
LOANER_BORROW_LIMIT_DAYS = 17
TRANSFER_GRACE_DAYS = 3

# ─── Credentialing ───────────────────────────────────────────────────────────
MIN_SIMULATION_MODULES = 3
CREDENTIAL_VALIDITY_DAYS = 365
EVIDENCE_GRACE_DAYS = 60
ACTIVITY_TIER_FLOOR = 2

# ─── Interval lengths ────────────────────────────────────────────────────────
DAYS_PER_MONTH = 30
INTERVAL_DAYS = 30
ACCEPTANCE_WINDOW_DAYS = 30

# ─── Expansion capacity ──────────────────────────────────────────────────────
EXPANSION_VOLUME_TARGET = 22
REQUESTED_CAPACITY = 22

# ─── IDN pool ────────────────────────────────────────────────────────────────
MAX_POOL_UTILISATION_UNITS = 25
SURPLUS_POOL_BUDGET = 30

# ─── Fixed startup logical clock ─────────────────────────────────────────────
DEFAULT_CLOCK_ISO8601 = "2026-09-01T00:00:00Z"

# ─── Convenience values used across fixtures ─────────────────────────────────
TEST_DEFAULTS = {
    "ACCOUNT_NAME": "Cedar Ridge Health",
    "IDN_GROUP_CODE": "IDN-CEDAR",
    "REGION_CODE": "WEST",
    "PLACEMENT_CAP": 6,
    "MAXIMUM_PROCEDURE_COMMITMENT": 30,
    "BASE_PLACEMENT_FEE_CENTS": 4800000,
    "MAX_INSTRUMENT_LIVES": 12,
    "INTEGRATION_TIER": 1,
    "MIN_OR_LENGTH_CM": 780,
    "MIN_OR_WIDTH_CM": 700,
    "MIN_THROW_RADIUS_CM": 320,
    "MIN_CEILING_CLEARANCE_CM": 280,
    "BASE_MONTHLY_FEE_CENTS": 200000,
    "PLACEMENT_FEE_CENTS": 6000000,
    "SURGEON_NAME": "Dr. Corner",
    "REQUIRED_PROCTORED_CASES": 1,
    "EVIDENCE_ISSUED_UTC": "2026-08-01T00:00:00Z",
    "EVIDENCE_EXPIRES_UTC": "2027-08-01T00:00:00Z",
}