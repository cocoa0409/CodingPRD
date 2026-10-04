"""Domain thresholds and defaults for the accelerator allocation API."""

# Seat-tier per-seat annual fees, in cents.
TIER_SEAT_FEE = {
    "BASIC": 12000,
    "BUSINESS": 36000,
    "ENTERPRISE": 90000,
}

# Seat bounds: the chronological settled fee clamps into [SEAT_MIN, SEAT_CAP].
SEAT_MIN = 40
SEAT_CAP = 1000

# support_credit_units multipliers, below vs at/above the seat minimum.
CREDIT_BELOW_MIN = 3
CREDIT_AT_OR_ABOVE_MIN = 5

# Value scoring weights and saturating caps.
W_TIME = 10.0
W_UNIT = 1.0
TIME_MAX = 30
UNIT_MAX = 500

# Ranking penalty per recorded qualification attempt.
PENALTY_ATTEMPT = 5.0

# Friction tier ordering.
TIER_INDEX = {"COOL": 0, "WARM": 1, "HOT": 2, "SCALDING": 3}

# Commitment multiplier by the confirming forecast's horizon band.
COMMITMENT_RATE_TABLE = {"SHORT": 0.2, "MEDIUM": 0.35, "LONG": 0.5}
CENT_SCALE = 100

# Export performance-density band boundary and rounding step, in watts.
DENSITY_BOUNDARY = 1400
DENSITY_STEP = 100

# Qualification attempt penalty base and cap.
ATTEMPT_PENALTY_BASE = 5
ATTEMPT_PENALTY_CAP = 20

# Forecast horizon-band boundary day and deadline gaps, in days.
FORECAST_BOUNDARY_DAY = 15
SHORT_DEADLINE_OFFSET_DAYS = 1
MEDIUM_GAP_DAYS = 45
LONG_GAP_DAYS = 90

# Forfeit-rate bands and overage surcharge.
FORFEIT_BAND_RATE = {"SHORT": 0.1, "MEDIUM": 0.25, "LONG": 0.25}
FORFEIT_OVERAGE_PENALTY = 0.05
OVERAGE_CAP = 0.75

# Cancellation notice days by horizon band.
CANCELLATION_NOTICE_DAYS = {"SHORT": 14, "MEDIUM": 30, "LONG": 60}

# Evaluation ring fence ratio of the supply ceiling.
EVAL_RESERVE_RATIO = 0.1

# Hotness-tier committed-rate thresholds (inclusive at each boundary).
HOTNESS_WARM_RATE = 2.0
HOTNESS_HOT_RATE = 7.0
HOTNESS_SCALDING_RATE = 10.5

# Non-monotonic band-ceiling mapping.
BAND_CEILING = {"COOL": "COOL", "WARM": "COOL", "HOT": "WARM", "SCALDING": "COOL"}

# Unit-based committed-rate schedule.
RATE_PER_UNIT = 1.75
RATE_BAND_WIDTH_UNITS = 100
RATE_BAND_STEP = 0.25
RATE_CAP = 4.5
CUTOVER_EPOCH_INDEX = 3

# Evaluation-loan late fee.
LATE_FEE_PER_DAY_UNITS = 0.5
LATE_FEE_CAP_UNITS = 15.0

# Developer-program provisioning allowances.
TIER_KIT_UNITS = {"COMMUNITY": 0, "REGISTERED": 2, "PREFERRED": 6, "ELITE": 12}
TIER_INCIDENT_UNITS = {"COMMUNITY": 0, "REGISTERED": 1, "PREFERRED": 3, "ELITE": 8}
ELITE_ADVANCE_MINUTES = 600

# Membership grace period, in days.
MEMBERSHIP_GRACE_DAYS = 90

# Lifecycle-commitment floor constants.
LIFECYCLE_GRACE_DAYS = 365
EMBEDDED_EXTENSION_DAYS = 730
COMMITMENT_FLOOR_MIN_DAYS = 1825

# Partner priority-class thresholds.
TIER1_ENTITLEMENT_MIN = 2000
TIER1_ON_TIME_RATIO_MIN = 0.8
TIER2_ENTITLEMENT_MIN = 500

# Entitlement ceiling on partner.entitlement_units_held.
ENTITLEMENT_CEILING_UNITS = 100000

# Server-startup logical clock.
STARTUP_CLOCK = "2026-09-01T00:00:00Z"

# Common request defaults used by factories and fixtures.
TEST_DEFAULTS = {
    "SKU_CODE": "AC-100-PCIE",
    "SUPPLY_CEILING_UNITS": 10000,
    "SUPPLY_CEILING_UNITS_RING_FENCE": 10000,
    "TDP_WATTS": 1350,
    "LONG_TERM_AVAILABILITY_THROUGH": "2029-01-01T00:00:00Z",
    "PARTNER_LEGAL_NAME": "Helios Cloud Systems",
    "PARTNER_TYPE": "CLOUD_PROVIDER",
    "PARTNER_DESTINATION": "US",
    "PARTNER_ORIGIN_EPOCH_INDEX": 5,
    "BLUEPRINT_CODE": "RA-8X-HGX",
    "BLUEPRINT_TYPE": "TRAINING_CLUSTER",
    "BLUEPRINT_TARGET_TDP_WATTS": 1400,
    "BLUEPRINT_REQUIRED_VALIDATION_MINUTES": 120,
    "BLUEPRINT_EVALUATION_DEADLINE_DAYS": 30,
    "VALIDATION_MINUTES": 240,
    "VALIDATION_TEST_COUNT": 6,
    "NODE_CAPACITY_UNITS": 1000,
    "NODE_REGION": "AMERICAS",
    "STACK_ENTITLEMENT_UNITS": 250,
    "STACK_MIN_PACKAGE_VERSION": "1.0.0",
    "DEPLOYMENT_DESTINATION": "US",
    "SUBSCRIPTION_SUPPORT_TIER": "BUSINESS",
    "SUBSCRIPTION_SEAT_COUNT": 25,
}