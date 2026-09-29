"""In-memory data store, logical clock, and shared primitives.

Storage is process-local Python dicts only. The store starts completely empty on
every boot: no entity is seeded, preloaded or hardcoded anywhere in this module.
"""
import itertools
import re
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP

from flask import g

# ---------------------------------------------------------------------------
# Logical clock start (PRD 2.4): exactly 2026-08-01T00:00:00Z. The server never
# falls back to wall-clock time for domain instants.
# ---------------------------------------------------------------------------
CLOCK_START = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)

ROLES = (
    "AttendingProvider",
    "NurseManager",
    "StaffingCoordinator",
    "Sitter",
    "RemoteObserver",
    "SafetyOfficer",
    "SystemAdmin",
)

RISK_CATEGORIES = ("FALL", "ELOPEMENT", "SELF_HARM")
MODALITIES = ("ONE_TO_ONE_SITTER", "VIDEO_MONITORING")
SOURCE_POOLS = ("INTERNAL_FLOAT", "AGENCY", "VOLUNTEER")
COMPETENCY_LEVELS = ("NOT_TRAINED", "BASIC", "ADVANCED")
ORDER_STATUSES = (
    "ACTIVE",
    "REASSESSMENT_DUE",
    "ESCALATED",
    "DISCONTINUATION_REVIEW",
    "DISCONTINUED",
    "LAPSED",
)
ORDER_NON_TERMINAL = ("ACTIVE", "REASSESSMENT_DUE", "ESCALATED", "DISCONTINUATION_REVIEW")
WATCH_STATUSES = ("SCHEDULED", "ON_WATCH", "ON_BREAK", "COMPLETED", "VOIDED")
DOC_STATUSES = ("PENDING", "HANDOFF_DRAFTED", "HANDOFF_SIGNED", "WAIVED")
STATION_STATUSES = ("IDLE", "ACTIVE_MONITORING", "OFFLINE")
FEED_STATUSES = ("ACTIVE", "RELEASED")
EVENT_KINDS = ("ELOPEMENT_ATTEMPT", "AGGRESSION", "FALL_WITH_INJURY", "SELF_HARM_ATTEMPT")
ESCALATING_EVENT_KINDS = ("ELOPEMENT_ATTEMPT", "AGGRESSION")
HARM_EVENT_KINDS = ("FALL_WITH_INJURY", "SELF_HARM_ATTEMPT")
EVENT_STATUSES = ("REPORTED", "ESCALATED_RESPONSE", "INCIDENT_REVIEW", "CLOSED")
RESOLUTIONS = ("CONTINUE_OBSERVATION", "MODALITY_ESCALATED", "STAFF_RETRAINING_REQUIRED")
INTERVENTIONS = ("VERBAL_REDIRECTION", "DISTRACTION", "FAMILY_PRESENCE", "BED_ALARM", "NONE")
ENTRY_KINDS = ("PROVISIONAL", "FINAL_SEGMENT")
ENTRY_STATUSES = ("POSTED", "REVERSED")
DOC_STATES = ("DRAFTED", "SIGNED")
COMPLETION_REASONS_CALLER = ("HANDOFF_COMPLETE", "SHIFT_END_NO_SUCCESSOR")
RECOMMENDATIONS = ("DISCONTINUE", "CONTINUE")
DECISIONS = ("APPROVE", "REJECT")
PATIENT_STATUSES = ("ADMITTED", "DISCHARGED")
STAFF_STATUSES = ("AVAILABLE", "ON_ASSIGNMENT", "SUSPENDED")
UNIT_STATUSES = ("OPEN", "RESTRICTED")

# ---- calculation constants (PRD 3.2, 3.3, 3.4, 3.5, 3.7, 3.9) --------------
RISK_CATEGORY_WEIGHTS = {
    "FALL": Decimal("1.5"),
    "ELOPEMENT": Decimal("2.5"),
    "SELF_HARM": Decimal("3.0"),
}
FEED_ACUITY_WEIGHTS = {
    "FALL": Decimal("1.0"),
    "ELOPEMENT": Decimal("2.0"),
    "SELF_HARM": Decimal("3.0"),
}
POOL_MULTIPLIER = {
    "INTERNAL_FLOAT": Decimal("1.00"),
    "AGENCY": Decimal("1.45"),
    "VOLUNTEER": Decimal("0.00"),
}
NIGHT_DIFFERENTIAL = Decimal("1.15")
NIGHT_START_HOUR_UTC = 23
NIGHT_END_HOUR_UTC = 7
AGE_ADJUSTMENT_THRESHOLD_YEARS = 75
AGE_ADJUSTMENT_POINTS = Decimal("1.0")
ATTEMPT_EVENT_POINTS = Decimal("1.0")
HARM_EVENT_POINTS = Decimal("2.0")
ATTEMPT_WINDOW_HOURS = 24
SCORE_CEILING = Decimal("10.0")
TIER_4H_MIN_SCORE = Decimal("8.0")
TIER_8H_MIN_SCORE = Decimal("6.0")
TIER_12H_MIN_SCORE = Decimal("3.0")
DEFAULT_INTERVAL_HOURS = 24
REASSESSMENT_GRACE_HOURS = 6
VIDEO_SCORE_CEILING = Decimal("6.0")
PENALTY_TIER_2_MIN_WEIGHT = Decimal("6.0")
PENALTY_TIER_1_MIN_WEIGHT = Decimal("4.0")
SPAN_FLOOR = 1
EARLY_START_GRACE_MINUTES = 15
BREAK_ELIGIBILITY_MINUTES = 120
MIN_BREAK_MINUTES = 15
MIN_REST_BUFFER_MINUTES = 480
MAX_SHIFT_MINUTES = 720
SURCHARGE_TIERS = (
    (150000, Decimal("0.12")),
    (60000, Decimal("0.08")),
    (20000, Decimal("0.04")),
)

PAGINATION_DEFAULT_LIMIT = 10
PAGINATION_MIN_LIMIT = 1
PAGINATION_MAX_LIMIT = 100
PAGINATION_DEFAULT_OFFSET = 0


class Store(object):
    """Process-local in-memory store. Empty at boot, always."""

    def __init__(self):
        self.units = {}
        self.patients = {}
        self.staff = {}
        self.orders = {}
        self.assignments = {}
        self.stations = {}
        self.feeds = {}
        self.reassessments = {}
        self.handoffs = {}
        self.events = {}
        self.cost_entries = {}
        self.clock = CLOCK_START
        self._seq = itertools.count(1)

    def next_seq(self):
        return next(self._seq)


db = Store()


def new_id():
    return str(uuid.uuid4())


# ---------------------------------------------------------------------------
# Timestamp formatting: ISO-8601 UTC with exactly three fractional digits and a
# Z suffix. Centralised so precision is uniform across every response field.
# ---------------------------------------------------------------------------
def iso(dt):
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt = dt.astimezone(timezone.utc)
    return "%04d-%02d-%02dT%02d:%02d:%02d.%03dZ" % (
        dt.year,
        dt.month,
        dt.day,
        dt.hour,
        dt.minute,
        dt.second,
        dt.microsecond // 1000,
    )


_ISO_RE = re.compile(
    r"^(\d{4})-(\d{2})-(\d{2})[Tt ](\d{2}):(\d{2})(?::(\d{2}))?(?:[.,](\d{1,9}))?"
    r"(Z|z|[+-]\d{2}:?\d{2})?$"
)


def parse_instant(value):
    """Parse an ISO-8601 instant. Returns an aware UTC datetime or None."""
    if not isinstance(value, str):
        return None
    m = _ISO_RE.match(value.strip())
    if not m:
        return None
    year, month, day, hour, minute, second, frac, offset = m.groups()
    try:
        micro = 0
        if frac:
            micro = int((frac + "000000")[:6])
        base = datetime(
            int(year), int(month), int(day), int(hour), int(minute),
            int(second) if second else 0, micro, tzinfo=timezone.utc,
        )
    except ValueError:
        return None
    if offset and offset not in ("Z", "z"):
        sign = 1 if offset[0] == "+" else -1
        body = offset[1:].replace(":", "")
        oh, om = int(body[:2]), int(body[2:4])
        base = base - sign * timedelta(hours=oh, minutes=om)
    return base


def round_half_up(value, places=0):
    """Decimal half-up rounding to the given number of decimal places."""
    if not isinstance(value, Decimal):
        value = Decimal(str(value))
    exp = Decimal(1).scaleb(-places)
    return value.quantize(exp, rounding=ROUND_HALF_UP)


def cents(value):
    """Round a monetary Decimal half up to a whole integer count of cents."""
    return int(round_half_up(value, 0))


def one_dp(value):
    """Round to one decimal place, half up, returning a Decimal."""
    return round_half_up(value, 1)


def whole_minutes(delta):
    """Complete minutes elapsed, discarding any incomplete trailing minute."""
    return int(delta.total_seconds() // 60)


def sort_key(entity):
    return (entity["created_at"], entity["_seq"])


# ---------------------------------------------------------------------------
# Version bookkeeping (PRD 2.9): every mutated row has updated_at refreshed and
# version incremented by exactly 1 per request, no matter how many times the
# request touches it.
# ---------------------------------------------------------------------------
def _touched():
    t = getattr(g, "_touched_ids", None)
    if t is None:
        t = set()
        g._touched_ids = t
    return t


def touch(entity):
    if entity is None:
        return
    if "version" not in entity:
        return
    t = _touched()
    key = entity["id"]
    if key in t:
        return
    t.add(key)
    entity["updated_at"] = db.clock
    entity["version"] = entity["version"] + 1


def base_entity(versioned=True):
    """Common system fields. Newly created rows are exempt from touch()."""
    eid = new_id()
    row = {"id": eid, "created_at": db.clock, "_seq": db.next_seq()}
    if versioned:
        row["updated_at"] = db.clock
        row["version"] = 1
    try:
        _touched().add(eid)
    except RuntimeError:
        pass
    return row
