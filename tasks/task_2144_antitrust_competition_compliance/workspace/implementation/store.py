"""In-memory data store, logical clock and record helpers.

NO seeding of any kind happens here. Every collection starts empty on every
boot; all state is created by clients through the declared endpoints.
"""
import uuid
import random
import string
import threading
from datetime import datetime, timedelta, timezone

# ---------------------------------------------------------------- collections
COLLECTIONS = [
    "business_units",
    "employees",
    "curricula",
    "assignments",
    "associations",
    "participations",
    "meetings",
    "attendances",
    "contacts",
    "transactions",
    "hsr_analyses",
    "sites",
    "drills",
    "document_audits",
    "leniency_applications",
    "risk_assessments",
]

# The logical clock's startup default, per PRD 2.4 — EXACTLY 2026-08-01T00:00:00Z
CLOCK_DEFAULT = datetime(2026, 8, 1, 0, 0, 0)


class Store(object):
    def __init__(self):
        self.lock = threading.RLock()
        self.reset()

    def reset(self):
        for name in COLLECTIONS:
            setattr(self, name, {})
        self._seq = 0
        self.clock = CLOCK_DEFAULT

    # ------------------------------------------------------------- sequencing
    def next_seq(self):
        self._seq += 1
        return self._seq


db = Store()


# --------------------------------------------------------------- time helpers
def iso_ms(dt):
    """ISO 8601 UTC with exactly three fractional digits."""
    if dt is None:
        return None
    if dt.tzinfo is not None:
        dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
    return "%s.%03dZ" % (dt.strftime("%Y-%m-%dT%H:%M:%S"), dt.microsecond // 1000)


def parse_iso(value):
    """Parse an ISO 8601 UTC datetime string -> naive UTC datetime, or None."""
    if not isinstance(value, str):
        return None
    text = value.strip()
    if not text:
        return None
    if text.endswith("Z") or text.endswith("z"):
        text = text[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(text)
    except (ValueError, TypeError):
        return None
    if dt.tzinfo is None:
        return dt
    return dt.astimezone(timezone.utc).replace(tzinfo=None)


def now_wall():
    return datetime.now(timezone.utc).replace(tzinfo=None)


def clock_now():
    return db.clock


def add_days(dt, days):
    return dt + timedelta(days=int(days))


# --------------------------------------------------------------- id / request
def new_id():
    return str(uuid.uuid4())


_ALNUM = string.ascii_uppercase + string.digits


def new_request_id():
    return "req_" + "".join(random.choice(_ALNUM) for _ in range(20))


# ------------------------------------------------------------- record helpers
def new_record(extra=None):
    """Create a record carrying the four common fields."""
    ts = now_wall()
    row = {
        "id": new_id(),
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
        "_seq": db.next_seq(),
    }
    if extra:
        row.update(extra)
    return row


def sort_rows(rows):
    """Default list ordering: created_at ASC, stable w.r.t. insertion."""
    return sorted(rows, key=lambda r: (r["created_at"], r["_seq"]))
