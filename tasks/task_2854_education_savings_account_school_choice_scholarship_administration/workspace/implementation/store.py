"""In-memory data store, id/timestamp minting and the logical programme clock.

The store starts completely empty on every boot: no entity is ever seeded,
preloaded or hardcoded here.  Every record is created by an API call.
"""
import re
import threading
import uuid
from datetime import datetime, timedelta, timezone

# PRD 2.5: before any operator sets it the logical clock reads exactly this.
DEFAULT_CLOCK = "2026-08-01T00:00:00.000Z"

_FRAC_RE = re.compile(r"\.(\d+)")
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

lock = threading.RLock()


def fmt_instant(dt):
    """Canonical ISO-8601 UTC with exactly three fractional-second digits."""
    dt = dt.astimezone(timezone.utc)
    return "%04d-%02d-%02dT%02d:%02d:%02d.%03dZ" % (
        dt.year, dt.month, dt.day, dt.hour, dt.minute, dt.second,
        dt.microsecond // 1000,
    )


def parse_instant(value):
    """Parse an ISO-8601 instant.  Returns an aware UTC datetime or None."""
    if not isinstance(value, str):
        return None
    text = value.strip()
    if not text:
        return None
    if text[-1] in ("Z", "z"):
        text = text[:-1] + "+00:00"

    def _trim(match):
        digits = match.group(1)
        return "." + digits[:6]

    text = _FRAC_RE.sub(_trim, text, count=1)
    try:
        dt = datetime.fromisoformat(text)
    except (ValueError, TypeError):
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def canonical_instant(value):
    dt = parse_instant(value)
    return None if dt is None else fmt_instant(dt)


def parse_date(value):
    """Strict YYYY-MM-DD.  Returns the string back, or None."""
    if not isinstance(value, str) or not _DATE_RE.match(value.strip()):
        return None
    text = value.strip()
    try:
        datetime.strptime(text, "%Y-%m-%d")
    except ValueError:
        return None
    return text


def day_start_instant(date_str):
    return date_str + "T00:00:00.000Z"


def day_last_second_instant(date_str):
    return date_str + "T23:59:59.000Z"


def add_days(instant, days):
    dt = parse_instant(instant)
    return fmt_instant(dt + timedelta(days=int(days)))


def whole_months_between(earlier, later):
    """Whole months from `earlier` to `later`, floored, never negative."""
    a = parse_instant(earlier)
    b = parse_instant(later)
    if a is None or b is None:
        return 0
    months = (b.year - a.year) * 12 + (b.month - a.month)
    if (b.day, b.hour, b.minute, b.second, b.microsecond) < (
        a.day, a.hour, a.minute, a.second, a.microsecond
    ):
        months -= 1
    return max(0, months)


class Store(object):
    def __init__(self):
        self.program_years = {}
        self.students = {}
        self.applications = {}
        self.eligibility_determinations = {}
        self.accounts = {}
        self.providers = {}
        self.fraud_screenings = {}
        self.expense_categories = {}
        self.purchase_requests = {}
        self.disbursements = {}
        self.misuse_cases = {}
        self.clawback_entries = {}
        self.renewal_reviews = {}
        self.appeals = {}
        self.clock = DEFAULT_CLOCK
        self._seq = 0
        self._last_created = None

    # --- minting ----------------------------------------------------------
    def next_seq(self):
        self._seq += 1
        return self._seq

    def next_created_at(self):
        """Wall-clock creation instant, forced strictly increasing so that
        `created_at` is unique per insert (PRD 3.3 relies on that)."""
        stamp = fmt_instant(datetime.now(timezone.utc))
        if self._last_created is not None and stamp <= self._last_created:
            bumped = parse_instant(self._last_created) + timedelta(milliseconds=1)
            stamp = fmt_instant(bumped)
        self._last_created = stamp
        return stamp

    def now(self):
        """The logical programme clock."""
        return self.clock


store = Store()


def new_id():
    return str(uuid.uuid4())


def by_seq(records):
    return sorted(records, key=lambda r: r["_seq"])
