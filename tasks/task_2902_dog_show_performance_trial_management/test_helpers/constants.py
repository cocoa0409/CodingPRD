"""Domain thresholds and defaults stated in the PRD's business-logic sections."""

# ─── Logical clock ────────────────────────────────────────────────────────────
DEFAULT_CLOCK_INSTANT = "2026-08-01T00:00:00Z"
# The instant nearly every scenario pins before it starts building state.
SETUP_CLOCK_INSTANT = "2026-08-10T09:00:00Z"

# ─── Pagination ───────────────────────────────────────────────────────────────
PAGINATION = {
    "LIMIT_DEFAULT": 10,
    "LIMIT_MIN": 1,
    "LIMIT_MAX": 100,
    "OFFSET_DEFAULT": 0,
    "OFFSET_MIN": 0,
}

# ─── Roster defaults ──────────────────────────────────────────────────────────
ANNUAL_EVENT_ALLOWANCE_DEFAULT = 2
MAX_DAILY_DOG_COUNT_DEFAULT = 175
MAX_DOGS_PER_JUDGE_PER_DAY = 175
MAX_SLOTS_PER_JUDGE_PER_SHOW = 3
MAX_SHOWS_PER_JUDGE_PER_DAY = 1
MIN_DOG_AGE_MONTHS = 6

# ─── Agility jump-height ladder (inclusive at the top of each band) ───────────
JUMP_HEIGHT_LADDER = [
    (25.0, 20),
    (35.0, 30),
    (45.0, 40),
    (55.0, 50),
]
JUMP_HEIGHT_ABOVE_LADDER = 60
VALID_JUMP_HEIGHTS_CM = [20, 30, 40, 50, 60]

# ─── Entry fee assessment ─────────────────────────────────────────────────────
BASE_ENTRY_FEE_CENTS = 3500
PERFORMANCE_ENTRY_FEE_CENTS = 2800
FIRST_ENTRY_SURCHARGE_CENTS = 900
CATALOG_LEVY_PCT = 7.5
LEVY_ON_BASE_3500_CENTS = 263
LEVY_ON_BASE_2800_CENTS = 210
SAME_DOG_DISCOUNT_PCT = 15
HOUSEHOLD_DISCOUNT_PCT = 10
HOUSEHOLD_DISCOUNT_MIN_ENTRIES = 3
PROVISIONAL_COUNTED_STATUSES = ["CONFIRMED", "CHECKED_IN", "JUDGED"]
FINAL_COUNTED_STATUSES = ["CONFIRMED", "CHECKED_IN"]

# ─── Withdrawal retention tiers, keyed on pre-refund fee_collected_cents ──────
RETENTION_TIERS = [
    (20_000, 10),
    (10_000, 5),
    (0, 0),
]

# ─── Ring timetable ───────────────────────────────────────────────────────────
RING_NUMBER_MIN = 1
RING_NUMBER_MAX = 12
PERFORMANCE_DOGS_PER_HOUR = 15
STANDARD_DOGS_PER_HOUR = 25
GROUP_JUDGING_OVERHEAD_MINUTES = 10
DEFERRED_DOG_MINUTES = 3
JUDGE_REST_BUFFER_MINUTES = 30
RING_TURNAROUND_BUFFER_MINUTES = 0

# ─── Heat advisory ────────────────────────────────────────────────────────────
HUMIDITY_ADJUSTMENTS = [
    (40, 0.0),
    (60, 1.5),
    (80, 3.0),
]
HUMIDITY_ADJUSTMENT_ABOVE = 5.0
ADVISORY_AMBER_MIN_C = 26.0
ADVISORY_RED_MIN_C = 32.0

# ─── Championship points ──────────────────────────────────────────────────────
POINTS_TABLE = [
    (1, 0),
    (4, 1),
    (9, 2),
    (17, 3),
    (29, 4),
]
POINTS_TABLE_TOP = 5
POINTS_CAP = 5
GROUP_LEVEL_BONUS = 2
BEST_IN_SHOW_LEVEL_BONUS = 3
MAJOR_MIN_POINTS = 2
MAX_PLACEMENTS = 4
SCALE_A_COUNTED_STATUSES = ["CONFIRMED", "CHECKED_IN", "JUDGED", "ABSENT"]
SCALE_B_COUNTED_STATUSES = ["CHECKED_IN", "JUDGED"]

# ─── Performance run scoring ──────────────────────────────────────────────────
AGILITY_START_SCORE = 100.0
AGILITY_FAULT_POINTS = 5.0
AGILITY_REFUSAL_POINTS = 5.0
AGILITY_ELIMINATION_REFUSALS = 3
OBEDIENCE_START_SCORE = 200.0
OBEDIENCE_QUALIFY_MIN_SCORE = 170.0
RALLY_START_SCORE = 100.0
RALLY_FAULT_POINTS = 3.0
RALLY_QUALIFY_MIN_SCORE = 70.0
AGILITY_YARDAGE_RATE_M_PER_S = 5.0

# ─── Protests, titles and filings ─────────────────────────────────────────────
MIN_PROTEST_DEPOSIT_CENTS = 5000
PROTEST_WINDOW_HOURS = 24
TITLE_CH_MIN_POINTS = 3
TITLE_CH_MIN_MAJORS = 1
TITLE_LEG_MIN_COUNT = 3
TITLE_APPEND_ORDER = ["CH", "AX", "CD", "RN"]

# ─── Values reused across scenario setups ─────────────────────────────────────
TEST_DEFAULTS = {
    "CLUB_NAME": "Northshore Kennel Club",
    "CLUB_CODE": "NSKC",
    "REGION_CODE": "NE",
    "JUDGE_NUMBER": "J-77",
    "JUDGE_NAME": "Rex Calder",
    "HANDLER_NAME": "Ada Vance",
    "MEMBER_NUMBER": "M-1001",
    "SHOW_NAME": "Autumn Classic",
    "SHOW_DATE": "2026-09-12",
    "VENUE_NAME": "Northshore Park",
    "ENTRY_OPEN_AT": "2026-08-05T00:00:00Z",
    "ENTRY_CLOSE_AT": "2026-09-01T23:59:59Z",
    "MAX_TOTAL_ENTRIES": 100,
    "BREED_CODE": "GOLDEN_RETRIEVER",
    "GROUP_CODE": "SPORTING",
    "BIRTH_DATE": "2024-05-10",
    "ENTRY_LIMIT": 10,
}

DOG_NAMES = ["Ripple", "Bramble", "Cinder", "Dune", "Ember", "Fjord", "Gale"]
DOG_REGISTRATION_NUMBERS = [
    "SR-0001", "SR-0002", "SR-0003", "SR-0004", "SR-0005", "SR-0006", "SR-0007",
]
