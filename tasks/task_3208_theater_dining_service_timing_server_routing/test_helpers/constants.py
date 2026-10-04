"""Domain thresholds and numeric constants from the PRD's calculations.

Every value here is a named constant the PRD publishes: the point-to-minute
ceilings, the two capacity-band thresholds, the routing invariants, the
weighted-scoring weights, and the pinned derivation figures.
"""
from datetime import datetime, timedelta

# --- Named service constants (PRD §2.9, §2.10, §2.11, §2.12, §3.5, §3.9) ---
SERVICE_WINDOW_LEAD_MINUTES = 10
PRE_SHOW_MIN_MINUTES = 10
PRE_SHOW_MAX_MINUTES = 40
IN_KITCHEN_LEAD_MINUTES = 30
ENTREE_DEADLINE_FRACTION = 0.75
MINUTES_FROM_ENTREE_TO_START = 30
CLUSTER_WINDOW_MINUTES = 120
CLUSTER_ANCHOR_LEAD_MINUTES = 60
SERVO_BUFFER_MINUTES = 15
DAILY_SECTION_CAP = 3
READY_LEAD_MINUTES = 30
NEARLY_READY_LEAD_MINUTES = 30
AUTO_COMP_REFUND_PCT = 0.30
THEME_DISCOUNT_PCT = 0.05
LOAD_PCT_LATE = 90
LOAD_PCT_BLOCKED = 100
SERVER_QUALITY_WINDOW_DAYS = 30
PENALTY_PCT_PER_LOW_ASSIGNMENT = 0.05
QUALITY_INDEX_FLOOR = 0.0
STRIKE_WINDOW_DAYS = 1
WARN_AT_STRIKES = 1
EJECT_AT_STRIKES = 2
SETTLED_TOTAL = 0
ALLERGY_WEIGHT = 3
LARGE_PARTY_WEIGHT = 2
LARGE_PARTY_UNITS = 4

# --- Section-assignment scoring (PRD §3.9) ---
BASE_POINTS = {"A": 1, "B": 3, "C": 6, "UNRATED": 2}
EJECTION_MULTIPLIER = 2.0
REFUND_MULTIPLIER = 1.5
CANCEL_MULTIPLIER = 0.5

# --- Server quality index grade weights (PRD §3.9) ---
GRADE_WEIGHT = {"A": 1.0, "B": 0.8, "C": 0.5}

# --- Response-envelope pagination defaults (PRD §2.3) ---
PAGINATION_DEFAULT_LIMIT = 10
PAGINATION_MAX_LIMIT = 100
PAGINATION_DEFAULT_OFFSET = 0

# --- Physical section labels (PRD §2.11) ---
SECTION_LABELS = ["LEFT", "CENTER", "RIGHT"]

# --- The fixed logical clock the platform starts on (PRD §2.4) ---
CLOCK_EPOCH_ISO = "2026-09-01T00:00:00Z"

# --- Reasonable build defaults for fixtures ---
TEST_DEFAULTS = {
    "SEAT_CAPACITY": 60,
    "SCREEN_LEAD_TIME_MINUTES": 20,
    "KITCHEN_POINT_RATE": 1,
    "ALCOVE_POINT_RATE": 3,
    "RUNTIME_MINUTES": 100,
}


def iso(dt: datetime) -> str:
    """Render a datetime as a derived PRD instant.

    The logical clock and every instant the platform derives from it land on
    whole seconds, and PRD §2.4 states the clock's own literal as
    `2026-09-01T00:00:00Z`, so the sub-second part is omitted.
    """
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def at(hour: int, minute: int = 0, day: int = 1) -> str:
    """A 2026-09-<day>THH:MM:00Z instant, for readable test clocks."""
    return f"2026-09-{day:02d}T{hour:02d}:{minute:02d}:00Z"


def showtime_instants(start_at_utc: str, runtime_minutes: int,
                      pre_show_minutes: int = 20) -> dict:
    """Derive the three window instants the PRD pins for a showtime.

    dining_open_at_utc       = start - pre_show_minutes
    entree_ready_deadline_utc = start + floor(runtime * 0.75)
    dining_close_at_utc       = deadline - IN_KITCHEN_LEAD_MINUTES
    """
    start = datetime.strptime(start_at_utc, "%Y-%m-%dT%H:%M:%SZ")
    deadline = start + timedelta(
        minutes=int(runtime_minutes * ENTREE_DEADLINE_FRACTION)
    )
    return {
        "dining_open_at_utc": iso(start - timedelta(minutes=pre_show_minutes)),
        "entree_ready_deadline_utc": iso(deadline),
        "dining_close_at_utc": iso(deadline - timedelta(minutes=IN_KITCHEN_LEAD_MINUTES)),
    }


def entree_fire_at(start_at_utc: str) -> str:
    """The cold-line anchor: start_at_utc minus MINUTES_FROM_ENTREE_TO_START."""
    start = datetime.strptime(start_at_utc, "%Y-%m-%dT%H:%M:%SZ")
    return iso(start - timedelta(minutes=MINUTES_FROM_ENTREE_TO_START))