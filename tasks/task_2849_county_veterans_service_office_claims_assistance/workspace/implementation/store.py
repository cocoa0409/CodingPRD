"""In-memory store, logical clock and shared time helpers.

Everything lives in process memory only.  Nothing is written to disk, so a
fresh `start.sh` invocation always begins with a completely empty store.
"""

import datetime
import re
import threading
import uuid

from errors import ApiError

# --------------------------------------------------------------------------
# logical clock (PRD 2.4)
# --------------------------------------------------------------------------

CLOCK_START = datetime.datetime(2026, 8, 1, 0, 0, 0, tzinfo=datetime.timezone.utc)

_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_DT_RE = re.compile(
    r"^(\d{4})-(\d{2})-(\d{2})[Tt](\d{2}):(\d{2}):(\d{2})(?:\.(\d+))?[Zz]$"
)


class Store(object):
    """All mutable server state."""

    def __init__(self):
        self.lock = threading.RLock()
        self.reset()

    def reset(self):
        self.clock = CLOCK_START
        self._seq = 0
        self.representatives = {}
        self.veterans = {}
        self.discharge_documents = {}
        self.eligibility_screens = {}
        self.powers_of_attorney = {}
        self.claims = {}
        self.evidence_items = {}
        self.exam_sites = {}
        self.exam_appointments = {}
        self.decision_reviews = {}
        self.state_programs = {}
        self.state_benefit_applications = {}
        self.outreach_events = {}
        self.outcome_reports = {}

    def next_seq(self):
        self._seq += 1
        return self._seq


db = Store()


def new_id():
    return str(uuid.uuid4())


def fmt_instant(dt):
    """ISO-8601 UTC instant with exactly three fractional-second digits."""
    dt = dt.astimezone(datetime.timezone.utc)
    return "%04d-%02d-%02dT%02d:%02d:%02d.%03dZ" % (
        dt.year, dt.month, dt.day, dt.hour, dt.minute, dt.second,
        dt.microsecond // 1000,
    )


def fmt_date(d):
    return "%04d-%02d-%02d" % (d.year, d.month, d.day)


def now_instant():
    """The current logical-clock instant, canonically formatted."""
    return fmt_instant(db.clock)


def now_date():
    """The current logical-clock date as a `datetime.date`."""
    return db.clock.astimezone(datetime.timezone.utc).date()


def now_date_str():
    return fmt_date(now_date())


def parse_date(raw):
    """Strict calendar date `YYYY-MM-DD`; ApiError(ERR_VALIDATION) otherwise."""
    if not isinstance(raw, str) or not _DATE_RE.match(raw):
        raise ApiError("ERR_VALIDATION", "malformed date: %r" % (raw,))
    try:
        return datetime.date(int(raw[0:4]), int(raw[5:7]), int(raw[8:10]))
    except ValueError:
        raise ApiError("ERR_VALIDATION", "malformed date: %r" % (raw,))


def parse_instant(raw):
    """Strict ISO-8601 UTC instant ending in `Z`."""
    if not isinstance(raw, str):
        raise ApiError("ERR_VALIDATION", "malformed datetime: %r" % (raw,))
    m = _DT_RE.match(raw)
    if not m:
        raise ApiError("ERR_VALIDATION", "malformed datetime: %r" % (raw,))
    frac = m.group(7) or ""
    micro = int((frac + "000000")[:6]) if frac else 0
    try:
        return datetime.datetime(
            int(m.group(1)), int(m.group(2)), int(m.group(3)),
            int(m.group(4)), int(m.group(5)), int(m.group(6)), micro,
            tzinfo=datetime.timezone.utc,
        )
    except ValueError:
        raise ApiError("ERR_VALIDATION", "malformed datetime: %r" % (raw,))


def d(raw):
    """Parse a stored date string back into a date (never user input)."""
    return datetime.date(int(raw[0:4]), int(raw[5:7]), int(raw[8:10]))


def dt(raw):
    """Parse a stored instant string back into a datetime (never user input)."""
    return parse_instant(raw)


# --------------------------------------------------------------------------
# row helpers
# --------------------------------------------------------------------------

def new_row(with_audit=True):
    row = {"id": new_id(), "created_at": now_instant()}
    if with_audit:
        row["updated_at"] = row["created_at"]
        row["version"] = 1
    row["_seq"] = db.next_seq()
    return row


def bump(row):
    """A row mutated: version +1 and updated_at refreshed (PRD 2.5)."""
    row["version"] = row.get("version", 1) + 1
    row["updated_at"] = now_instant()
    return row


def public(row):
    return {k: v for k, v in row.items() if not k.startswith("_")}


def ordered(rows):
    """Default list order: ascending creation order (PRD 2.3)."""
    return sorted(rows, key=lambda r: r["_seq"])
