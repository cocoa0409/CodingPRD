"""Clock, identifier, timestamp and interval helpers.

Nothing in this API is evaluated against real wall-clock time (§2.5). The
logical clock starts at exactly 2026-09-01T00:00:00Z and only moves when an
operator advances it through POST /op/_clock/set_current_utc.
"""

import random
import string
import uuid
from datetime import datetime, timedelta, timezone

STARTUP_CLOCK = datetime(2026, 9, 1, 0, 0, 0, tzinfo=timezone.utc)

# Hard review dates named by §2.5.
DISTRIBUTION_LOCK_DATE = datetime(2026, 10, 15, 0, 0, 0, tzinfo=timezone.utc)
ROTATION_DATE = datetime(2026, 10, 15, 0, 0, 0, tzinfo=timezone.utc)
REPRINT_PUBLISH_CUTOFF = datetime(2026, 12, 1, 0, 0, 0, tzinfo=timezone.utc)

# Occupancy windows (§3.3): six-hour event length, padded by half an hour each side.
EVENT_LENGTH_HOURS = 6
BUFFER_MINUTES = 30


_ALPHABET = string.ascii_uppercase + string.digits


# --------------------------------------------------------------------------
# Logical clock
# --------------------------------------------------------------------------

class Clock:
    def __init__(self):
        self.current_utc = STARTUP_CLOCK

    def set(self, value):
        self.current_utc = value

    def now(self):
        return self.current_utc


clock = Clock()


# --------------------------------------------------------------------------
# Identifier and timestamp helpers
# --------------------------------------------------------------------------

def new_id():
    """UUID with no type prefix and no embedded entity name (§2.8)."""
    return str(uuid.uuid4())


def request_id():
    suffix = "".join(random.choice(_ALPHABET) for _ in range(18))
    return "req_" + suffix


def now_iso():
    """ISO 8601 UTC with three fractional digits, derived from the logical clock."""
    return to_iso(clock.now())


def to_iso(dt):
    """ISO 8601 UTC at whole-second precision, e.g. 2026-09-01T00:00:00Z.

    The logical clock is whole-second (it is set from values such as
    `2026-09-01T00:00:00Z`), so every logical-clock timestamp — the
    `created_at` / `updated_at` stamps and the calendar fields such as
    `street_date`, `scheduled_date` and `reporting_due_by` — is rendered in the
    same form the program names its instants in. No domain value carries
    sub-second precision.
    """
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_dt(value):
    """Parse an ISO 8601 timestamp; returns None when the value is not one."""
    if not isinstance(value, str):
        return None
    text = value.strip()
    if not text:
        return None
    if text.endswith("Z") or text.endswith("z"):
        text = text[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def utc_day_key(dt):
    """The UTC calendar day of an instant, used by the daily tier-slot rule (§3.3)."""
    return dt.astimezone(timezone.utc).date()


# --------------------------------------------------------------------------
# Occupancy windows
# --------------------------------------------------------------------------

def occupancy_window(scheduled_date):
    """Half-open [scheduled_date, scheduled_date + 6 hours] (§1.4 priority 12)."""
    return (scheduled_date, scheduled_date + timedelta(hours=EVENT_LENGTH_HOURS))


def padded_window(scheduled_date):
    """[scheduled_date - 30m, scheduled_date + 6h + 30m] (§1.4 priority 11)."""
    return (
        scheduled_date - timedelta(minutes=BUFFER_MINUTES),
        scheduled_date + timedelta(hours=EVENT_LENGTH_HOURS) + timedelta(minutes=BUFFER_MINUTES),
    )


def half_open_overlap(a, b):
    """True when the half-open windows a and b share an instant.

    Boundary equality is legal: a prior event ending exactly at this event's
    scheduled_date does not overlap (§1.4 priority 12 note).
    """
    return a[0] < b[1] and b[0] < a[1]


def interval_covers(outer, inner):
    return outer[0] <= inner[0] and inner[1] <= outer[1]


def max_concurrent(intervals):
    """Peak number of buffered occupancy intervals covering any single instant.

    The aggregate event-space rule treats its padded windows as CLOSED intervals,
    which is what makes adjacency a conflict here even though the identical pair
    is legal under the half-open pairwise rule: two windows meeting at a shared
    instant both cover that instant. A starting edge therefore sorts before an
    ending edge at the same timestamp.
    """
    events = []
    for start, end in intervals:
        events.append((start, 1))
        events.append((end, -1))
    events.sort(key=lambda pair: (pair[0], -pair[1]))
    peak = 0
    running = 0
    for _, delta in events:
        running += delta
        if running > peak:
            peak = running
    return peak


# --------------------------------------------------------------------------
# Integer arithmetic (§2.9)
# --------------------------------------------------------------------------

def floor_div(numerator, denominator):
    """Integer floor division; the single named rounding point of a calculation."""
    return numerator // denominator