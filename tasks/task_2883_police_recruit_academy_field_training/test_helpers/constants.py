"""Literal constants and reference calculators drawn from the API contract.

Nothing here is invented: every table, factor and threshold is the value the
contract states.  The small calculators at the bottom exist so tests can state
an expected number as an independent computation rather than as a magic
literal.
"""
from decimal import Decimal, ROUND_HALF_UP, ROUND_FLOOR, ROUND_CEILING
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

# --- logical clock -----------------------------------------------------------
# The service's logical UTC clock starts here on a fresh server.
CLOCK_EPOCH = "2026-08-01T00:00:00Z"

# --- envelope ----------------------------------------------------------------
REQUEST_ID_PREFIX = "req_"
RESPONSE_TYPE_OBJECT = "object"
RESPONSE_TYPE_ARRAY = "array"
RESPONSE_TYPE_ERROR = "error"
META_KEYS = [
    "api_request_id",
    "api_request_timestamp",
    "limit",
    "offset",
    "total_count",
    "has_more",
]

# --- pagination --------------------------------------------------------------
DEFAULT_LIMIT = 10
MIN_LIMIT = 1
MAX_LIMIT = 100
DEFAULT_OFFSET = 0

# --- common property sets ----------------------------------------------------
COMMON_FIELDS = ["id", "created_at", "updated_at", "version"]
# A training record entry is append-only: it carries only these two.
APPEND_ONLY_FIELDS = ["id", "created_at"]

# --- certification standard defaults ----------------------------------------
DEFAULT_FITNESS_EVENT_FLOOR_POINTS = 10
DEFAULT_FITNESS_PASS_SCORE = 60

# --- course session ----------------------------------------------------------
DEFAULT_MIN_ENROLLMENT = 3
ROOM_TURNAROUND_MINUTES = 15

# --- attendance --------------------------------------------------------------
ATTENDANCE_FACTORS = {
    "PRESENT": Decimal("1.00"),
    "PARTIAL": Decimal("0.75"),
    "ABSENT_EXCUSED": Decimal("0.00"),
    "ABSENT_UNEXCUSED": Decimal("0.00"),
}
# Rows whose attendance status contributes whole scheduled_hours on the
# scheduled (seat-time) basis.
SCHEDULED_BASIS_STATUSES = ["PRESENT", "PARTIAL", "ABSENT_EXCUSED"]

# --- probation ---------------------------------------------------------------
DEFAULT_PROBATION_BASE_DAYS = 365
PROBATION_EXTENSION_TIERS = [
    # (inclusive lower bound on milestone score, extension days)
    (Decimal("5.00"), 0),
    (Decimal("4.00"), 30),
]
PROBATION_EXTENSION_BELOW_FOUR_DAYS = 60

# --- field training ----------------------------------------------------------
FTO_MAX_CONCURRENT_TRAINEES = 2
REMEDIAL_THRESHOLD = Decimal("4.00")
DOR_RATING_MIN = 1
DOR_RATING_MAX = 7
DOR_ACCEPTABLE_RATING = 4
TERMINAL_WEIGHT_RECENT = Decimal("0.60")
TERMINAL_WEIGHT_EARLIER = Decimal("0.40")
TERMINAL_RECENT_BUCKET_SIZE = 3
MIN_PHASE_NUMBER = 1
MAX_PHASE_NUMBER = 4

# --- physical fitness scoring ------------------------------------------------
FITNESS_REFERENCES = {
    "AGE_20_29": {
        "push_ups": Decimal("30"),
        "sit_ups": Decimal("38"),
        "run_1_5_mile_seconds": Decimal("750"),
        "vertical_jump_inches": Decimal("18"),
    },
    "AGE_30_39": {
        "push_ups": Decimal("24"),
        "sit_ups": Decimal("32"),
        "run_1_5_mile_seconds": Decimal("810"),
        "vertical_jump_inches": Decimal("16"),
    },
    "AGE_40_49": {
        "push_ups": Decimal("18"),
        "sit_ups": Decimal("26"),
        "run_1_5_mile_seconds": Decimal("900"),
        "vertical_jump_inches": Decimal("14"),
    },
}
FITNESS_EVENT_KEYS = [
    "push_ups",
    "sit_ups",
    "run_1_5_mile_seconds",
    "vertical_jump_inches",
]
# Ratio lower bound (inclusive) -> points.  Evaluated from the top down.
FITNESS_TIERS = [
    (Decimal("1.20"), 25),
    (Decimal("1.00"), 20),
    (Decimal("0.85"), 12),
    (Decimal("0.70"), 6),
]
FITNESS_FLOOR_CAP = 59
FITNESS_MAX_COMPOSITE = 100

# --- certification skip reason codes, in the order they are evaluated -------
SKIP_REASON_ORDER = [
    "PROBATION_NOT_PASSED",
    "HOURS_SHORTFALL",
    "TOPIC_SHORTFALL",
    "EXAM_NOT_PASSED",
]

# --- attrition / forecast ----------------------------------------------------
ATTRITION_STAGE_ORDER = ["SCREENING", "ACADEMY", "FIELD_TRAINING", "PROBATION"]
ATTRITION_RATE_DECIMALS = 4
HOURS_DECIMALS = 2
SCORE_DECIMALS = 2

EXAM_NOT_TAKEN = "NOT_TAKEN"
SYSTEM_ACTOR = "system"

BASIS_ATTENDED = "ATTENDED"
BASIS_SCHEDULED = "SCHEDULED"


# --- rounding helpers --------------------------------------------------------
def half_up(value, places: int) -> Decimal:
    """Round half away from zero to ``places`` decimal places."""
    quantum = Decimal(1).scaleb(-places)
    return Decimal(str(value)).quantize(quantum, rounding=ROUND_HALF_UP)


def money2(value) -> Decimal:
    """Round to the 2 decimal places used for hours and scores."""
    return half_up(value, HOURS_DECIMALS)


def rate4(value) -> Decimal:
    """Round to the 4 decimal places used for attrition rates and survival."""
    return half_up(value, ATTRITION_RATE_DECIMALS)


def floor_int(value) -> int:
    return int(Decimal(str(value)).to_integral_value(rounding=ROUND_FLOOR))


def ceil_int(value) -> int:
    return int(Decimal(str(value)).to_integral_value(rounding=ROUND_CEILING))


def as_number(value: Decimal) -> float:
    """Render a Decimal as a JSON number for a request payload."""
    return float(value)


# --- fitness calculators -----------------------------------------------------
def fitness_event_points(event: str, result, age_bracket: str) -> int:
    """Points earned by one fitness event, per the five-tier scale."""
    reference = FITNESS_REFERENCES[age_bracket][event]
    result = Decimal(str(result))
    if event == "run_1_5_mile_seconds":
        # A lower elapsed time is a better run, so the ratio is inverted.
        ratio = reference / result
    else:
        ratio = result / reference
    for bound, points in FITNESS_TIERS:
        if ratio >= bound:
            return points
    return 0


def fitness_composite(raw_metrics: Dict[str, Any], age_bracket: str,
                      event_floor_points: int = DEFAULT_FITNESS_EVENT_FLOOR_POINTS) -> int:
    """The integer composite score of one physical fitness attempt."""
    points = [
        fitness_event_points(key, raw_metrics[key], age_bracket)
        for key in FITNESS_EVENT_KEYS
    ]
    raw_total = sum(points)
    if min(points) < event_floor_points:
        return min(raw_total, FITNESS_FLOOR_CAP)
    return min(raw_total, FITNESS_MAX_COMPOSITE)


# --- competency calculators --------------------------------------------------
def rating_sum(dimension_ratings: Dict[str, int]) -> int:
    return sum(int(v) for v in dimension_ratings.values())


def dor_mean(dimension_ratings: Dict[str, int]) -> Decimal:
    return money2(Decimal(rating_sum(dimension_ratings)) / Decimal(5))


def rolling_mean_score(rating_sums: List[int]) -> Optional[Decimal]:
    """Every rating pooled equally, rounded once at the end."""
    if not rating_sums:
        return None
    total = Decimal(sum(rating_sums))
    return money2(total / (Decimal(5) * Decimal(len(rating_sums))))


def terminally_weighted_score(rating_sums: List[int]) -> Optional[Decimal]:
    """Recency-weighted two-bucket mean, buckets left unrounded."""
    if not rating_sums:
        return None
    recent = rating_sums[-TERMINAL_RECENT_BUCKET_SIZE:]
    earlier = rating_sums[:-TERMINAL_RECENT_BUCKET_SIZE]
    recent_mean = Decimal(sum(recent)) / (Decimal(5) * Decimal(len(recent)))
    if earlier:
        earlier_mean = Decimal(sum(earlier)) / (Decimal(5) * Decimal(len(earlier)))
    else:
        earlier_mean = recent_mean
    return money2(TERMINAL_WEIGHT_RECENT * recent_mean
                  + TERMINAL_WEIGHT_EARLIER * earlier_mean)


def probation_extension_days(milestone_score) -> int:
    """Extension days chosen from the milestone score alone."""
    if milestone_score is None:
        return 0
    score = money2(milestone_score)
    if score >= Decimal("5.00"):
        return 0
    if score >= Decimal("4.00"):
        return 30
    return PROBATION_EXTENSION_BELOW_FOUR_DAYS


# --- date / instant helpers --------------------------------------------------
def parse_date(value: str) -> date:
    return date.fromisoformat(value)


def add_days(value: str, days: int) -> str:
    """Exact calendar addition on a YYYY-MM-DD date."""
    return (parse_date(value) + timedelta(days=days)).isoformat()


def milestone_due_date(probation_start: str, base_days: int) -> str:
    """probation_start plus the floor of half the base days."""
    return add_days(probation_start, floor_int(Decimal(base_days) / Decimal(2)))


def scheduled_end_date(probation_start: str, base_days: int, extension_days: int) -> str:
    return add_days(probation_start, base_days + extension_days)


def parse_instant(value: str) -> datetime:
    text = value.replace("Z", "+00:00")
    return datetime.fromisoformat(text).astimezone(timezone.utc)


def instant(value: datetime) -> str:
    """Render a datetime as the second-precision instant the contract uses."""
    return value.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def shift_instant(value: str, *, days: int = 0, hours: int = 0,
                  minutes: int = 0, seconds: int = 0) -> str:
    return instant(parse_instant(value) + timedelta(
        days=days, hours=hours, minutes=minutes, seconds=seconds))


def session_hours(starts_at: str, ends_at: str) -> Decimal:
    """Elapsed hours between two instants, rounded half up to 2 places."""
    seconds = (parse_instant(ends_at) - parse_instant(starts_at)).total_seconds()
    return money2(Decimal(str(seconds)) / Decimal(3600))
