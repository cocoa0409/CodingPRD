"""Domain constants: store-policy defaults, the drive-time model, pricing tiers,
the reimbursement schedule and the shared literal geometry every test builds on.

All money values are integer cents. All instants are ISO 8601 UTC with exactly
three fractional-second digits, except where the API accepts the shorter
``...Z`` form on input.
"""

# --- The logical clock --------------------------------------------------------
# The service boots with its logical clock at this instant.
SERVER_BOOT_CLOCK = "2026-08-01T00:00:00Z"

# Off-peak default working instant used by nearly every setup. UTC hour 9 is not
# one of 17, 18, 19 or 20, so no peak surcharge applies.
DEFAULT_CLOCK = "2026-08-05T09:00:00Z"
# A mid-day instant used by setups that later need to move the clock forward.
NOON_CLOCK = "2026-08-05T12:00:00Z"
# A peak instant: UTC hour 18 is inside the 17-20 peak-hour band.
PEAK_CLOCK = "2026-08-05T18:00:00Z"

# --- Store policy defaults ----------------------------------------------------
STORE_DEFAULTS = {
    "promise_minutes": 30,
    "delivery_fee_cents": 399,
    "cash_limit_cents": 5000,
    "hot_bag_count": 4,
    "max_stacked_stops": 3,
    "handoff_minutes_per_stop": 6,
    "dispatch_reset_buffer_minutes": 10,
    "service_posture": "OPEN",
}

# --- Delivery-area / drive-time model ----------------------------------------
# Micro-degrees per grid mile.
MICRO_PER_MILE = 15000

# Coordinate bounds on micro-degree inputs.
LAT_MICRO_MIN = -90000000
LAT_MICRO_MAX = 90000000
LON_MICRO_MIN = -180000000
LON_MICRO_MAX = 180000000

ZONE_VERSION_DEFAULTS = {
    "max_drive_time_minutes": 25,
    "base_drive_minutes": 6,
    "minutes_per_mile": 3,
    "peak_surcharge_minutes": 7,
    "barrier_surcharge_minutes": 4,
}

# The drive-time model every shared fixture publishes. The 40-minute ceiling is
# wide enough that the whole ring is IN_ZONE except the two far corners, which
# is what lets one polygon serve both in-zone and edge scenarios.
TEST_ZONE_MODEL = {
    "max_drive_time_minutes": 40,
    "base_drive_minutes": 6,
    "minutes_per_mile": 3,
    "peak_surcharge_minutes": 7,
    "barrier_surcharge_minutes": 4,
}

# The peak-hour band: the surcharge applies when the UTC hour of the logical
# clock is one of these.
PEAK_HOURS = (17, 18, 19, 20)

# --- Shared literal geometry --------------------------------------------------
# Store origin.
STORE_LAT_MICRO = 39000000
STORE_LON_MICRO = -84000000

# The ring: 38.90..39.20 north by 84.20..83.80 west, expressed as four vertices
# closing implicitly from the last back to the first.
TEST_POLYGON = [
    {"latitude_micro": 38900000, "longitude_micro": -84200000},
    {"latitude_micro": 39200000, "longitude_micro": -84200000},
    {"latitude_micro": 39200000, "longitude_micro": -83800000},
    {"latitude_micro": 38900000, "longitude_micro": -83800000},
]

ZONE_EFFECTIVE_FROM = "2026-07-01T00:00:00Z"
ZONE_EFFECTIVE_TO = "2026-09-01T00:00:00Z"

# Pre-computed address coordinates against the store origin, the ring above and
# TEST_ZONE_MODEL, evaluated off peak with crosses_barrier false:
#
#   key   coordinates                grid_miles  drive_time  zone_state    fee_tier
#   A     (39030000, -84015000)           3.00          15   IN_ZONE       BASE
#   A2    (39015000, -84030000)           3.00          15   IN_ZONE       BASE
#   D     (39094950, -84000000)           6.33          25   IN_ZONE       MID
#   D_UP  (39095100, -84000000)           6.34          26   IN_ZONE       FAR
#   P     (39003750, -84000000)           0.25           7   IN_ZONE       BASE
#   R     (39066750, -84033375)           6.68          27   IN_ZONE       FAR
#   NINE  (39135000, -84000000)           9.00          33   IN_ZONE       FAR
#   E     (39000000, -84200000)          13.33          46   EDGE          FAR
#   O     (39000000, -84200001)          13.33          46   OUT_OF_ZONE   FAR
#   C     (39400000, -84000000)          26.67          87   OUT_OF_ZONE   FAR
ADDRESS_COORDS = {
    "A": (39030000, -84015000),
    "A2": (39015000, -84030000),
    "D": (39094950, -84000000),
    "D_UP": (39095100, -84000000),
    "P": (39003750, -84000000),
    "R": (39066750, -84033375),
    "NINE": (39135000, -84000000),
    "E": (39000000, -84200000),
    "O": (39000000, -84200001),
    "C": (39400000, -84000000),
}

ADDRESS_GRID_MILES = {
    "A": 3.00,
    "A2": 3.00,
    "D": 6.33,
    "D_UP": 6.34,
    "P": 0.25,
    "R": 6.68,
    "NINE": 9.00,
    "E": 13.33,
    "O": 13.33,
    "C": 26.67,
}

ADDRESS_DRIVE_MINUTES = {
    "A": 15,
    "A2": 15,
    "D": 25,
    "D_UP": 26,
    "P": 7,
    "R": 27,
    "NINE": 33,
    "E": 46,
    "O": 46,
    "C": 87,
}

ADDRESS_ZONE_STATE = {
    "A": "IN_ZONE",
    "A2": "IN_ZONE",
    "D": "IN_ZONE",
    "D_UP": "IN_ZONE",
    "P": "IN_ZONE",
    "R": "IN_ZONE",
    "NINE": "IN_ZONE",
    "E": "EDGE",
    "O": "OUT_OF_ZONE",
    "C": "OUT_OF_ZONE",
}

# --- Delivery-charge pricing --------------------------------------------------
# Drive-time fee tiers: at most 15 minutes is BASE, above 15 through 25 is MID,
# above 25 is FAR.
FEE_TIER_BASE_MAX_MINUTES = 15
FEE_TIER_MID_MAX_MINUTES = 25

FEE_TIER_SURCHARGE_CENTS = {"BASE": 0, "MID": 150, "FAR": 350}

# Waiver percentage picked from food_subtotal_cents alone.
WAIVER_FULL_THRESHOLD_CENTS = 3000
WAIVER_HALF_THRESHOLD_CENTS = 2000
WAIVER_PCT_FULL = 100
WAIVER_PCT_HALF = 50
WAIVER_PCT_NONE = 0

# --- Driver qualification -----------------------------------------------------
MVR_POINTS_MAX = 5
MVR_POINTS_MIN = 0
MVR_POINTS_UPPER_BOUND = 20
INSURANCE_MIN_LIABILITY_CENTS = 10_000_000

# --- Routing ------------------------------------------------------------------
HOT_BAG_SLOTS_MIN = 1
HOT_BAG_SLOTS_MAX = 2

# --- Service recovery ---------------------------------------------------------
REMAKE_GRACE_MINUTES = 5
REMAKE_LIMIT = 1
DISPUTE_ROUND_LIMIT = 2
SAFE_DROP_VOID_WINDOW_SECONDS = 3600

LATE_REMEDY_TIERS = (
    # (minimum overage in minutes, food percentage, refunds the delivery fee)
    (20, 100, True),
    (10, 50, False),
    (1, 20, False),
    (0, 0, False),
)
FEE_DISCLOSURE_PENALTY_CENTS = 500
QUALITY_REMEDY_PCT = 50

# --- Reimbursement schedules --------------------------------------------------
# The CAR schedule every shared fixture publishes.
CAR_COST_MODEL = {
    "vehicle_class": "CAR",
    "per_delivery_cents": 150,
    "tier1_cap_miles": 5.00,
    "tier1_per_mile_cents": 62,
    "tier2_per_mile_cents": 41,
    "min_reimbursement_per_stop_cents": 100,
    "effective_from": "2026-07-01T00:00:00Z",
}

# A scooter schedule whose per-stop floor genuinely bites.
SCOOTER_COST_MODEL = {
    "vehicle_class": "SCOOTER",
    "per_delivery_cents": 90,
    "tier1_cap_miles": 3.00,
    "tier1_per_mile_cents": 35,
    "tier2_per_mile_cents": 20,
    "min_reimbursement_per_stop_cents": 250,
    "effective_from": "2026-07-01T00:00:00Z",
}

# --- Pagination ---------------------------------------------------------------
PAGINATION = {
    "default_limit": 10,
    "min_limit": 1,
    "max_limit": 100,
    "default_offset": 0,
    "min_offset": 0,
}
