"""Core primitives: response envelope, errors, logical clock, id/time helpers.

Structural names (envelope fields, error ids, header names) are taken verbatim
from SCAFFOLD.yaml (response_envelope / errors / validations) and from PRD.md
sections 2.1, 2.2, 2.4 and 2.8.
"""

import random
import string
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP

# ---------------------------------------------------------------- constants

# SCAFFOLD constants (calculations[].constants)
DAY_SECONDS = 86400
STREAK_DAY_CLOSE_BUFFER_SECONDS = 3600

FREE_HEARTS_PER_DAY = 5
ENERGY_START_UNITS = 10
ENERGY_CAP = 30
ENERGY_REGEN_SECONDS = 900
ENERGY_UNITS_PER_INTERVAL = 5

FAST_MS = 3000
MEDIUM_MS = 8000
BASE_BY_STATE = {
    "UNLOCKED": 10,
    "BRONZE": 8,
    "SILVER": 6,
    "GOLD": 4,
    "LEGENDARY": 2,
    "DECAYED": 2,
    "LOCKED": 0,
}

SUBSCORE_DIVISOR = 40
ITEMS_PER_UNIT = 5
PLACEMENT_MAX_UNIT_INDEX = 12
PLACEMENT_PROBE_SPAN = 5
BAND_CUTOFFS_COMBINED = [("C1", 180), ("B2", 140), ("B1", 100), ("A2", 60)]
CEFR_BANDS = ["A1", "A2", "B1", "B2", "C1"]

DECAY_GRACE_DAYS = 2
DECAY_POINTS_PER_TIER = 5
MAX_REVIEW_DEPTH_DAYS = 10
DECAY_LEVEL_FLOOR = 4
INTERVAL_DAYS_BY_STATE = {
    "UNLOCKED": 1,
    "BRONZE": 1,
    "SILVER": 2,
    "GOLD": 3,
    "LEGENDARY": 5,
}

LEAGUE_WEEK_DAYS = 7
PROMOTION_CUTOFF_RANK = 3
DEMOTION_SPAN = 3
LEAGUE_SIZE = 10
CHEAT_REF_THRESHOLD = 8
AGGRESSION_MIN = 2000
FAST_ANSWER_MS = 800
ACCURACY_BREAK_MIN = 0.5

TIER_RATE_GEMS = [1, 2, 4, 6, 8]
LENGTH_BONUS_RATE = Decimal("0.05")
REPAIR_INFLATION_RATE = Decimal("0.5")
MONTHLY_REPAIR_CAP_GEMS = 20
MONTHLY_REPAIR_CAP = 3
REPAIR_WINDOW_DAYS = 7

BAND_CUTOFFS_CERT = [("DISTINCTION", 85), ("STRONG_PASS", 75), ("PASS", 60)]
ONE_STEP_DEMOTION_PENALTY = -10
PROCTOR_WINDOW_HOURS = 24
CERT_BAND_ORDER = ["NOT_CERTIFIED", "PASS", "STRONG_PASS", "DISTINCTION"]

NOTIFY_BASE_DAILY_CAP = 3
NOTIFY_FATIGUE_CAP = 3
OFFER_WINDOW_DAYS = 7

BASE_DISCOUNT_PCT = 10
MAX_DISCOUNT_PCT = 40
STREAK_BONUS_STEP_PCT = 2
STREAK_BONUS_CAP_PCT = 10
MILESTONE_DISCOUNT = {
    "STREAK_7": 5,
    "STREAK_30": 15,
    "PLACEMENT_SKIP": 10,
    "LEAGUE_PROMOTION": 10,
    "HEART_DEPLETION": 20,
}
BASE_MONTHLY_FEE_CENTS = 6999
PERIOD_DAYS = 30
GRACE_DAYS = 7

VALID_PROGRAM_TIERS = ["FREE", "PLUS_FAMILY", "CERTIFICATION_ELITE"]
VALID_PLAN_CODES = ["FREE", "PLUS_FAMILY", "CERTIFICATION_ELITE"]
VALID_SEAT_ROLES = ["OWNER", "MEMBER"]
VALID_MEMBERSHIP_STATUSES = ["INVITED", "ACTIVE", "REMOVED"]
VALID_SUBSCRIPTION_STATUSES = ["FREE", "ACTIVE", "IN_GRACE", "EXPIRED"]
VALID_UNIT_STATES = ["LOCKED_UNIT", "AVAILABLE", "IN_PROGRESS", "COMPLETED"]
VALID_NODE_STATES = [
    "LOCKED",
    "UNLOCKED",
    "BRONZE",
    "SILVER",
    "GOLD",
    "LEGENDARY",
    "DECAYED",
]
CROWN_STATES = ["BRONZE", "SILVER", "GOLD", "LEGENDARY"]
PRACTICEABLE_STATES = ["UNLOCKED", "BRONZE", "SILVER", "GOLD", "LEGENDARY"]
CROWN_ORDER = ["UNLOCKED", "BRONZE", "SILVER", "GOLD", "LEGENDARY"]
VALID_ATTEMPT_OUTCOMES = ["ACCEPTED", "REJECTED_LIMIT", "REJECTED_DECAY_CAP"]
VALID_STREAK_STATUSES = [
    "EVALUATING",
    "QUALIFIED",
    "FROZEN",
    "BROKEN",
    "REPAIRED",
    "ALIVE",
]
VALID_PLACEMENT_STATUSES = [
    "CREATED",
    "IN_PROGRESS",
    "SCORED",
    "CALIBRATED",
    "ABANDONED",
    "CERTIFIED",
]
VALID_LEAGUE_TIERS = ["BRONZE", "SILVER", "GOLD", "SAPPHIRE", "RUBY"]
VALID_LEAGUE_STATUSES = ["FORMING", "ACTIVE", "SETTLING", "CLOSED"]
VALID_STANDINGS = ["GOOD_STANDING", "FLAGGED", "PROMOTED", "DEMOTED"]
VALID_SETTLED_OUTCOMES = ["NONE", "PROMOTED", "DEMOTED", "HELD"]
VALID_PRODUCT_CODES = ["DET_BASIC", "DET_PRO", "DET_INSTITUTIONAL"]
VALID_EXAM_STATUSES = [
    "PURCHASED",
    "PROCTORING",
    "SUBMITTED",
    "SCORED",
    "REPORTED",
    "VOID",
    "EXPIRED",
]
VALID_MILESTONES = [
    "STREAK_7",
    "STREAK_30",
    "PLACEMENT_SKIP",
    "LEAGUE_PROMOTION",
    "HEART_DEPLETION",
]
VALID_OFFER_STATUSES = ["ISSUED", "REDEEMED", "EXPIRED", "SUPPRESSED"]
VALID_SCORED_TIERS = ["PLUS", "PLUS_FAMILY"]

DEFAULT_CLOCK = datetime(2026, 9, 1, 0, 0, 0, tzinfo=timezone.utc)


# ---------------------------------------------------------------- error ids

ERR_INVALID_REQUEST = "ERR_INVALID_REQUEST"
ERR_UNAUTHENTICATED = "ERR_UNAUTHENTICATED"
ERR_INSUFFICIENT_GEMS = "ERR_INSUFFICIENT_GEMS"
ERR_PLACEMENT_PROBE_USED = "ERR_PLACEMENT_PROBE_USED"
ERR_UNAUTHORIZED = "ERR_UNAUTHORIZED"
ERR_LEARNER_NOT_FOUND = "ERR_LEARNER_NOT_FOUND"
ERR_LESSON_NODE_NOT_FOUND = "ERR_LESSON_NODE_NOT_FOUND"
ERR_SUBSCRIPTION_NOT_FOUND = "ERR_SUBSCRIPTION_NOT_FOUND"
ERR_UNIT_NOT_FOUND = "ERR_UNIT_NOT_FOUND"
ERR_PREREQUISITE_NOT_MET = "ERR_PREREQUISITE_NOT_MET"
ERR_NODE_LOCKED = "ERR_NODE_LOCKED"
ERR_NODE_NOT_DECAYED = "ERR_NODE_NOT_DECAYED"
ERR_STREAK_NOT_BROKEN = "ERR_STREAK_NOT_BROKEN"
ERR_SUBSCRIPTION_INACTIVE = "ERR_SUBSCRIPTION_INACTIVE"
ERR_SEAT_QUOTA_EXCEEDED = "ERR_SEAT_QUOTA_EXCEEDED"
ERR_PLACEMENT_NOT_ACTIVE = "ERR_PLACEMENT_NOT_ACTIVE"
ERR_EXAM_NOT_PROCTORING = "ERR_EXAM_NOT_PROCTORING"
ERR_LEAGUE_NOT_SETTLING = "ERR_LEAGUE_NOT_SETTLING"
ERR_DECAY_RETENTION_FLOOR = "ERR_DECAY_RETENTION_FLOOR"
ERR_HEARTS_EXHAUSTED = "ERR_HEARTS_EXHAUSTED"
ERR_ENERGY_EXHAUSTED = "ERR_ENERGY_EXHAUSTED"
ERR_REPAIR_MONTHLY_CAP = "ERR_REPAIR_MONTHLY_CAP"
ERR_OFFER_NOT_REDEEMABLE = "ERR_OFFER_NOT_REDEEMABLE"
ERR_STALE_VERSION = "ERR_STALE_VERSION"
ERR_CHEAT_PATTERN_DETECTED = "ERR_CHEAT_PATTERN_DETECTED"
ERR_REPAIR_WINDOW_EXPIRED = "ERR_REPAIR_WINDOW_EXPIRED"
ERR_PROCTOR_WINDOW_EXPIRED = "ERR_PROCTOR_WINDOW_EXPIRED"
ERR_PLACEMENT_UNIT_OUT_OF_RANGE = "ERR_PLACEMENT_UNIT_OUT_OF_RANGE"

ERROR_HTTP = {
    ERR_INVALID_REQUEST: 400,
    ERR_UNAUTHENTICATED: 401,
    ERR_INSUFFICIENT_GEMS: 402,
    ERR_PLACEMENT_PROBE_USED: 402,
    ERR_UNAUTHORIZED: 403,
    ERR_LEARNER_NOT_FOUND: 404,
    ERR_LESSON_NODE_NOT_FOUND: 404,
    ERR_SUBSCRIPTION_NOT_FOUND: 404,
    ERR_UNIT_NOT_FOUND: 404,
    ERR_PREREQUISITE_NOT_MET: 409,
    ERR_NODE_LOCKED: 409,
    ERR_NODE_NOT_DECAYED: 409,
    ERR_STREAK_NOT_BROKEN: 409,
    ERR_SUBSCRIPTION_INACTIVE: 409,
    ERR_SEAT_QUOTA_EXCEEDED: 409,
    ERR_PLACEMENT_NOT_ACTIVE: 409,
    ERR_EXAM_NOT_PROCTORING: 409,
    ERR_LEAGUE_NOT_SETTLING: 409,
    ERR_DECAY_RETENTION_FLOOR: 409,
    ERR_HEARTS_EXHAUSTED: 409,
    ERR_ENERGY_EXHAUSTED: 409,
    ERR_REPAIR_MONTHLY_CAP: 409,
    ERR_OFFER_NOT_REDEEMABLE: 409,
    ERR_STALE_VERSION: 412,
    ERR_CHEAT_PATTERN_DETECTED: 422,
    ERR_REPAIR_WINDOW_EXPIRED: 422,
    ERR_PROCTOR_WINDOW_EXPIRED: 422,
    ERR_PLACEMENT_UNIT_OUT_OF_RANGE: 422,
}

ERROR_MESSAGES = {
    ERR_INVALID_REQUEST: "A required field is missing or an enum field carries an undeclared member.",
    ERR_UNAUTHENTICATED: "The X-User-ID header is absent or empty.",
    ERR_INSUFFICIENT_GEMS: "The learner's gem balance is below the computed repair price.",
    ERR_PLACEMENT_PROBE_USED: "The learner's free placement probe has already been consumed.",
    ERR_UNAUTHORIZED: "The acting role is not permitted for this operation.",
    ERR_LEARNER_NOT_FOUND: "The named learner does not exist.",
    ERR_LESSON_NODE_NOT_FOUND: "The named lesson node does not exist.",
    ERR_SUBSCRIPTION_NOT_FOUND: "The named subscription does not exist.",
    ERR_UNIT_NOT_FOUND: "The named course unit does not exist.",
    ERR_PREREQUISITE_NOT_MET: "The lesson node's prerequisite has not been mastered.",
    ERR_NODE_LOCKED: "The lesson node is not open for practice.",
    ERR_NODE_NOT_DECAYED: "The lesson node is not decayed.",
    ERR_STREAK_NOT_BROKEN: "The streak row is not broken.",
    ERR_SUBSCRIPTION_INACTIVE: "The subscription is not active.",
    ERR_SEAT_QUOTA_EXCEEDED: "The family seat quota is fully used.",
    ERR_PLACEMENT_NOT_ACTIVE: "The placement session is not in an operable state.",
    ERR_EXAM_NOT_PROCTORING: "The certification exam is not in the proctoring state.",
    ERR_LEAGUE_NOT_SETTLING: "The league is not in a settleable state.",
    ERR_DECAY_RETENTION_FLOOR: "The decayed node has reached the retention floor.",
    ERR_HEARTS_EXHAUSTED: "No hearts remain for this practice attempt.",
    ERR_ENERGY_EXHAUSTED: "No energy units remain for this practice attempt.",
    ERR_REPAIR_MONTHLY_CAP: "The monthly repair budget is exhausted.",
    ERR_OFFER_NOT_REDEEMABLE: "The engagement offer is not redeemable.",
    ERR_STALE_VERSION: "The supplied version does not match the stored version.",
    ERR_CHEAT_PATTERN_DETECTED: "The attempt matches a detected cheat pattern.",
    ERR_REPAIR_WINDOW_EXPIRED: "The streak repair window has closed.",
    ERR_PROCTOR_WINDOW_EXPIRED: "The proctoring window has closed.",
    ERR_PLACEMENT_UNIT_OUT_OF_RANGE: "The placement item lies outside the permitted unit range.",
}


class ApiError(Exception):
    def __init__(self, error_id, message=None):
        self.error_id = error_id
        self.http_status = ERROR_HTTP.get(error_id, 400)
        self.message = message or ERROR_MESSAGES.get(error_id, "Request failed.")
        super().__init__(self.message)


# ---------------------------------------------------------------- logical clock


class Clock:
    """Logical clock. Starts at exactly 2026-09-01T00:00:00Z and never falls
    back to wall time before an operator sets it (PRD 2.8)."""

    def __init__(self, now=None):
        self.now = now or DEFAULT_CLOCK

    def get(self):
        return self.now

    def set(self, dt):
        self.now = dt


def parse_iso8601(value):
    """Parse an ISO 8601 instant supplied by a client."""
    if value is None or not isinstance(value, str):
        raise ApiError(ERR_INVALID_REQUEST)
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        raise ApiError(ERR_INVALID_REQUEST)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def to_iso(dt):
    """ISO 8601 UTC with exactly three fractional digits (PRD 2.4)."""
    if dt is None:
        return None
    if isinstance(dt, str):
        dt = parse_iso8601(dt)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def now_iso(clock):
    return to_iso(clock.get())


# ---------------------------------------------------------------- helpers


def new_id():
    """Server-minted UUID with no type prefix (PRD 2.4)."""
    return str(uuid.uuid4())


def new_request_id():
    alphabet = string.ascii_letters + string.digits
    return "req_" + "".join(random.choice(alphabet) for _ in range(18))


def round_half_up(value):
    """Round to the nearer whole value, halves always moving upward."""
    if isinstance(value, Decimal):
        dec = value
    else:
        dec = Decimal(str(value))
    return int(dec.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def to_decimal(value):
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def local_day_index(clock, offset_days):
    """Whole-day index anchoring a learner's local calendar (PRD 3.3)."""
    seconds = int(clock.get().timestamp()) + int(offset_days) * DAY_SECONDS
    return seconds // DAY_SECONDS


def focus_date_of(clock, offset_days):
    """The local midnight currently under evaluation, as a UTC instant with a
    zero clock time so that purely date-comparative rules match on the caller's
    plain local date."""
    return datetime.fromtimestamp(local_day_index(clock, offset_days) * DAY_SECONDS, tz=timezone.utc)


def parse_date_arg(value):
    """Read a plain local calendar date, tolerating a full timestamp."""
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    if "T" in text:
        text = text.split("T", 1)[0]
    if " " in text:
        text = text.split(" ", 1)[0]
    try:
        d = datetime.strptime(text, "%Y-%m-%d")
    except ValueError:
        raise ApiError(ERR_INVALID_REQUEST)
    return d.replace(tzinfo=timezone.utc)


def add_days(dt, days):
    return dt + timedelta(days=days)


def as_int(value, field):
    if isinstance(value, bool) or value is None:
        raise ApiError(ERR_INVALID_REQUEST, "Field '%s' must be an integer." % field)
    try:
        return int(value)
    except (TypeError, ValueError):
        raise ApiError(ERR_INVALID_REQUEST, "Field '%s' must be an integer." % field)


def as_bool(value, field):
    if isinstance(value, bool):
        return value
    raise ApiError(ERR_INVALID_REQUEST, "Field '%s' must be a boolean." % field)


def as_str(value, field):
    if value is None or not isinstance(value, str):
        raise ApiError(ERR_INVALID_REQUEST, "Field '%s' must be a string." % field)
    return value


def enum_check(value, allowed, field):
    as_str(value, field)
    if value not in allowed:
        raise ApiError(
            ERR_INVALID_REQUEST,
            "Field '%s' carries an undeclared member." % field,
        )
    return value


def get_field(body, field):
    """Fetch a required body field."""
    if not isinstance(body, dict) or field not in body or body[field] is None:
        raise ApiError(ERR_INVALID_REQUEST, "Field '%s' is required." % field)
    return body[field]


def has_field(body, field):
    return isinstance(body, dict) and field in body and body[field] is not None


def paginate(items, limit_raw, offset_raw):
    """Apply limit/offset and report the full result-set size (PRD 2.3)."""
    total = len(items)
    limit = 10
    if limit_raw is not None and str(limit_raw) != "":
        limit = as_int(limit_raw, "limit")
        if limit < 1 or limit > 100:
            raise ApiError(ERR_INVALID_REQUEST, "limit must be between 1 and 100.")
    offset = 0
    if offset_raw is not None and str(offset_raw) != "":
        offset = as_int(offset_raw, "offset")
        if offset < 0:
            raise ApiError(ERR_INVALID_REQUEST, "offset must be at least 0.")
    page = items[offset : offset + limit]
    has_more = (offset + len(page)) < total
    return page, {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": has_more,
    }


# ---------------------------------------------------------------- envelope


def envelope_object(data, extra_meta=None):
    meta = {
        "api_request_id": new_request_id(),
        "api_request_timestamp": to_iso_meta(),
    }
    if extra_meta:
        meta.update(extra_meta)
    return {"meta": meta, "response_type": "object", "data": data}


def envelope_array(items, extra_meta=None):
    meta = {
        "api_request_id": new_request_id(),
        "api_request_timestamp": to_iso_meta(),
    }
    if extra_meta:
        meta.update(extra_meta)
    return {"meta": meta, "response_type": "array", "data": items}


def error_envelope(error_id, message):
    return {
        "meta": {
            "api_request_id": new_request_id(),
            "api_request_timestamp": to_iso_meta(),
        },
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }


def to_iso_meta():
    """Envelope timestamps come from the server's real wall clock, never from
    the logical clock the tests drive."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"