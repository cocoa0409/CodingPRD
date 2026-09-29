"""Domain thresholds and canonical test literals for the Broadcast Operations API.

Every value here is stated in PRD.md; nothing is invented.
"""

# --- The logical clock (PRD 2.4) -------------------------------------------
CLOCK_EPOCH = "2026-08-01T00:00:00Z"
CLOCK_EPOCH_STAMP = "2026-08-01T00:00:00.000Z"

# --- Camera plot and the signal-loss budget (PRD 3.2) ---------------------
LOSS_DB_PER_100_FEET = 1.35
MAX_SIGNAL_LOSS_BUDGET_DB = 10.13
MAX_SURVEY_REVISIONS = 3

# --- Fleet, travel logistics and the service cycle (PRD 3.3, 3.9) --------
DEFAULT_SERVICE_INTERVAL_HOURS = 500
DEFAULT_ENGINE_HOURS_SINCE_SERVICE = 0
TRAVEL_IN_HOURS = 24
TEARDOWN_OUT_HOURS = 12
TRAVEL_HOURS_PER_EVENT = 8
SETUP_TEARDOWN_HOURS = 4

# --- Transmission (PRD 3.4) ----------------------------------------------
DEFAULT_GUARD_BAND_MINUTES = 10
MAX_TEST_ATTEMPTS = 3

# --- Data feeds and preparation (PRD 3.5) --------------------------------
MAX_FEED_LATENCY_MS = 250
DEFAULT_MAX_CONCURRENT_CONSUMERS = 2

# --- Crew, union rules and the labor ledger (PRD 3.6) --------------------
STRAIGHT_TIME_MINUTES_CAP = 600
DOUBLE_TIME_MINUTES_CAP = 720
OVERTIME_MULTIPLIER = 1.5
DOUBLE_TIME_MULTIPLIER = 2.0
MEAL_WINDOW_MINUTES = 360
MEAL_PENALTY_INCREMENT_MINUTES = 30
MEAL_PENALTY_UNIT_CENTS = 3500
MEAL_PENALTY_UNIT_CAP = 4
TIER_1_PENALTY_MULTIPLIER = 1.5
TURNAROUND_MINUTES = 600

# --- Tier-derived staffing requirements (PRD 3.1) ------------------------
REQUIRED_CREW_POSITIONS = {"TIER_1": 12, "TIER_2": 4, "TIER_3": 2}
REQUIRED_VALIDATED_PREPS = {"TIER_1": 3, "TIER_2": 2, "TIER_3": 1}

# --- Readiness weights (PRD 3.7) -----------------------------------------
SURVEY_COMPONENT_POINTS = 40
TRANSMISSION_COMPONENT_POINTS = 25
SYSTEMS_COMPONENT_POINTS = 20
CREW_COMPONENT_POINTS = 15

# --- Air and contingency (PRD 3.8) ---------------------------------------
MAX_TECHNICAL_DOWNTIME_MINUTES = 20

# --- Settlement brackets (PRD 3.9) ---------------------------------------
OVERRUN_BRACKET_MID_CENTS = 500_000
OVERRUN_BRACKET_HIGH_CENTS = 2_000_000
OVERRUN_RATE_LOW_CENTS_PER_MINUTE = 1200
OVERRUN_RATE_MID_CENTS_PER_MINUTE = 1800
OVERRUN_RATE_HIGH_CENTS_PER_MINUTE = 2400

# --- Pagination bounds (PRD 2.3) -----------------------------------------
DEFAULT_LIMIT = 10
MIN_LIMIT = 1
MAX_LIMIT = 100
DEFAULT_OFFSET = 0

# --- Canonical event envelope used by most scenarios ---------------------
# A TIER_3 remote out of Riverside Arena: air 18:00Z-22:00Z on 2026-08-15,
# building dark by 06:00Z the next morning.
CANONICAL_EVENT = {
    "event_tier": "TIER_3",
    "league_code": "NBL",
    "venue_name": "Riverside Arena",
    "venue_power_capacity_amps": 400,
    "venue_roof_type": "OPEN",
    "venue_curfew_utc": "2026-08-16T06:00:00Z",
    "scheduled_start_utc": "2026-08-15T18:00:00Z",
    "scheduled_end_utc": "2026-08-15T22:00:00Z",
    "labor_budget_total_cents": 2_000_000,
}

# Canonical instants reused across scenarios.
BOOKING_WINDOW_START = "2026-08-15T12:00:00Z"
BOOKING_WINDOW_END = "2026-08-16T02:00:00Z"
TEST_WINDOW_START = "2026-08-15T12:00:00Z"
TEST_WINDOW_END = "2026-08-15T13:00:00Z"
TEST_FILING_CLOCK = "2026-08-15T12:30:00Z"
CALL_TIME = "2026-08-15T14:00:00Z"
CALL_SCHEDULED_RELEASE = "2026-08-16T00:00:00Z"
REHEARSAL_START = "2026-08-15T16:00:00Z"
AIR_CLOCK = "2026-08-15T18:00:00Z"

# A 600-minute call at 9000 cents/hour reserves exactly this much.
STAFF_HOURLY_RATE_CENTS = 9000
CANONICAL_PROVISIONAL_TOTAL_CENTS = 104_000

# UUIDs that never resolve to a row (used for not-found probes).
UNKNOWN_UUIDS = {
    "production": "00000000-0000-4000-8000-000000000001",
    "truck": "00000000-0000-4000-8000-000000000002",
    "survey": "00000000-0000-4000-8000-000000000003",
    "booking": "00000000-0000-4000-8000-000000000004",
    "crew_call": "00000000-0000-4000-8000-000000000005",
    "feed": "00000000-0000-4000-8000-000000000006",
    "prep": "00000000-0000-4000-8000-000000000007",
    "rehearsal": "00000000-0000-4000-8000-000000000008",
    "path": "00000000-0000-4000-8000-000000000999",
    "crew_member": "00000000-0000-4000-8000-000000000010",
    "show": "00000000-0000-4000-8000-000000000011",
}
