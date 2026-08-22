"""Domain thresholds and the canonical test calendar drawn from the PRD."""

# Numeric thresholds named in the PRD narratives.
THRESHOLDS = {
    "MIN_QUIZ_SCORE_PCT": 80.0,          # §3.1 training pass mark, inclusive
    "TRAINING_VALID_DAYS": 365,          # §3.1 certification decay
    "ROOM_TURNOVER_BUFFER_MINUTES": 15,  # §3.3 room occupancy buffer
    "SESSION_START_GRACE_MINUTES": 30,   # §3.6 early-open grace
    "MAKEUP_EXTENSION_DAYS": 7,          # §3.8 SCORING -> MAKEUP extension
    "MAX_RETURN_CYCLES": 2,              # §3.7 return-for-information cap
    "UNIT_REPLACEMENT_COST_CENTS": 1250,  # §3.5 per-booklet replacement cost
    "INTACT_SEAL_MULTIPLIER": 1.25,      # §3.5 security factor, seals intact
    "BROKEN_SEAL_MULTIPLIER": 1.75,      # §3.5 security factor, seals broken
    "WAIVER_TIER_1_MIN_CENTS": 5000,     # §3.5 10 percent waiver band floor
    "WAIVER_TIER_2_MIN_CENTS": 20000,    # §3.5 20 percent waiver band floor
    "SEPARATE_SETTING_SEAT_COST": 2,     # §3.4 extra seats per separate setting
    "PROCTOR_SPAN_FREE": 2,              # §3.4 free separate settings
    "PROCTOR_SPAN_DIVISOR": 3,           # §3.4 span divisor
    "PROCTOR_SPAN_SEAT_COST": 4,         # §3.4 seats lost per span step
    "DEFAULT_APPEAL_WINDOW_DAYS": 10,    # §3.2 default
    "DEFAULT_MIN_PARTICIPATION_PCT": 95.0,  # §3.2 default
}

# The logical clock reads exactly this instant before any request moves it (§2.5).
DEFAULT_LOGICAL_CLOCK_UTC = "2026-08-01T00:00:00.000Z"

# Canonical calendar shared by the composite fixtures.
TEST_CALENDAR = {
    "CLOCK_SETUP": "2026-09-01T08:00:00Z",
    "WINDOW_START": "2026-09-07T08:00:00Z",
    "WINDOW_END": "2026-09-18T18:00:00Z",
    "MAKEUP_START": "2026-09-21T08:00:00Z",
    "MAKEUP_END": "2026-09-25T18:00:00Z",
    "SESSION_START": "2026-09-08T09:00:00Z",
    "SESSION_END": "2026-09-08T12:00:00Z",
    "MAKEUP_SESSION_START": "2026-09-22T09:00:00Z",
    "MAKEUP_SESSION_END": "2026-09-22T12:00:00Z",
    "AFTER_WINDOW_END": "2026-09-19T08:00:00Z",
    "AFTER_MAKEUP_END": "2026-09-26T08:00:00Z",
}

# Accommodation catalogue attributes described in PRD §3.4.
STANDARD_CODES = ("EXTENDED_TIME", "SMALL_GROUP", "ASSISTIVE_TECH")
SPECIALIZED_CODES = ("SEPARATE_ROOM", "READ_ALOUD", "SCRIBE", "BRAILLE_FORM")
SEPARATE_SETTING_CODES = ("SMALL_GROUP", "SEPARATE_ROOM", "BRAILLE_FORM")

TEST_DEFAULTS = {
    "DISTRICT_NAME": "Northgate District",
    "STATE_CODE": "NG",
    "SCHOOL_MAX_SEATS": 60,
    "SESSION_SEAT_CAPACITY": 20,
    "LOT_QUANTITY": 10,
}
