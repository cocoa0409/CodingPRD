"""Domain constants for the Motor Carrier Operating Authority API test suite.

Every value here is transcribed from the PRD: the fifty-one state codes of
S3.1, the logical-clock startup default of S2.5, the insurance minimums and
filing-fee schedule of S3.2, the risk-score weights of S3.6/S3.7, the audit
threshold of S3.7, the interval disciplines of S3.4/S3.5 and the disruption
liability constants of S3.9.
"""

# ---------------------------------------------------------------------------
# S2.5 The logical compliance clock
# ---------------------------------------------------------------------------
CLOCK_STARTUP_DEFAULT = "2026-08-01T00:00:00.000Z"

# Instants the suite pins repeatedly.
T_ENROLL = "2026-08-01T00:00:00Z"
T_PUBLISH = "2026-08-05T00:00:00Z"
T_ELIGIBLE = "2026-08-26T00:00:00Z"

# ---------------------------------------------------------------------------
# S2.3 Pagination
# ---------------------------------------------------------------------------
DEFAULT_LIMIT = 10
MIN_LIMIT = 1
MAX_LIMIT = 100
DEFAULT_OFFSET = 0

# ---------------------------------------------------------------------------
# S2.4 Registry identifier formats
# ---------------------------------------------------------------------------
USDOT_NUMBER_PATTERN = r"^USDOT-[0-9]{7}$"
DOCKET_NUMBER_PATTERN = r"^MC-[0-9]{6}$"
ISO_INSTANT_PATTERN = r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z$"

# ---------------------------------------------------------------------------
# S3.1 The fifty-one valid two-letter state codes
# ---------------------------------------------------------------------------
VALID_STATE_CODES = [
    "AL", "AK", "AZ", "AR", "CA", "CO", "CT", "DE", "DC", "FL",
    "GA", "HI", "ID", "IL", "IN", "IA", "KS", "KY", "LA", "ME",
    "MD", "MA", "MI", "MN", "MS", "MO", "MT", "NE", "NV", "NH",
    "NJ", "NM", "NY", "NC", "ND", "OH", "OK", "OR", "PA", "RI",
    "SC", "SD", "TN", "TX", "UT", "VT", "VA", "WA", "WV", "WI",
    "WY",
]
INVALID_STATE_CODE = "ZZ"

# S3.1 registration clock
BIENNIAL_WINDOW_DAYS = 730

# ---------------------------------------------------------------------------
# S3.2 The three required insurance minimums (integer cents)
# ---------------------------------------------------------------------------
BIPD_PROPERTY_BASE_CENTS = 75000000
BIPD_PASSENGER_SMALL_CENTS = 150000000
BIPD_PASSENGER_LARGE_CENTS = 500000000
BIPD_HAZMAT_NONBULK_CENTS = 100000000
BIPD_HAZMAT_BULK_CENTS = 500000000
CARGO_HOUSEHOLD_GOODS_CENTS = 1000000
BROKER_BOND_CENTS = 7500000
PASSENGER_SEAT_BREAK = 15
MULTISTATE_UPLIFT_THRESHOLD = 25
MULTISTATE_UPLIFT_CENTS = 25000000

# ---------------------------------------------------------------------------
# S3.2 The filing fee schedule
# ---------------------------------------------------------------------------
DOCKET_BASE_CENTS = 30000
PER_STATE_SURCHARGE_CENTS = 137
HAZMAT_ENDORSEMENT_FEE_CENTS = 10500
ADMIN_SURCHARGE_PCT = 0.0725
ADMIN_SURCHARGE_FACTOR = 1.0725
TYPE_FEE_CENTS = {
    "FOR_HIRE_PROPERTY": 30000,
    "HOUSEHOLD_GOODS": 45000,
    "PASSENGER": 45000,
    "PROPERTY_BROKER": 30000,
    "FREIGHT_FORWARDER": 30000,
}
KIND_MULTIPLIER = {
    "NEW": 1.0,
    "NAME_CHANGE": 0.5,
    "REINSTATEMENT": 1.25,
    "SUCCESSOR_IN_INTEREST": 0.75,
}
FEE_BREAKDOWN_KEYS = [
    "line_docket_cents",
    "line_states_cents",
    "line_type_cents",
    "line_hazmat_cents",
]

# Frozen fee figures for the recurring application shapes.
FEE_NEW_FOR_HIRE_THREE_STATES_CENTS = 64791
FEE_NEW_HOUSEHOLD_GOODS_THREE_STATES_CENTS = 80879

# ---------------------------------------------------------------------------
# S3.6 / S3.7 The compliance risk score
# ---------------------------------------------------------------------------
W_OOS = 0.45
W_DRIVER = 0.30
W_VEHICLE = 0.25
FLEET_NORMALIZER = 10
ACUTE_VIOLATION_PENALTY = 12.0
SCORE_FLOOR = 0.0
SCORE_CEILING = 100.0

# S3.7 audit outcome
AUDIT_FAILURE_SCORE_THRESHOLD = 40.00

# ---------------------------------------------------------------------------
# S3.6 activation windows / S3.8 cure period
# ---------------------------------------------------------------------------
ACTIVATION_WAITING_PERIOD_DAYS = 21
NEW_ENTRANT_AUDIT_WINDOW_MONTHS = 18
CURE_PERIOD_DAYS = 30

# ---------------------------------------------------------------------------
# S3.4 / S3.5 interval disciplines
# ---------------------------------------------------------------------------
DESIGNATION_TRANSITION_BUFFER_DAYS = 1

# ---------------------------------------------------------------------------
# S3.9 disruption liability
# ---------------------------------------------------------------------------
DAILY_DIVISOR = 30
EMBARGO_PENALTY_PCT = 0.15
GOODWILL_TIER_CENTS = 5000000
GOODWILL_WAIVER_PCT = 0.10

# ---------------------------------------------------------------------------
# Convenience literals used across the suite
# ---------------------------------------------------------------------------
THREE_STATES = ["TX", "OK", "NM"]
UNDESIGNATED_STATE = "WY"
DEFAULT_NAIC_CODE = "12345"
