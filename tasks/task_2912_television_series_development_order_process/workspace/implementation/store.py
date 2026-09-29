"""In-memory store and the server-side logical development clock.

Storage is process-local Python dicts only -- nothing is persisted and nothing
is seeded.  Every boot starts with a completely empty store and the logical
clock at its startup default of 2026-08-01T00:00:00Z (PRD 2.4).
"""

import uuid
from datetime import datetime, timedelta, timezone, date

CLOCK_STARTUP_DEFAULT = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)


class Store(object):
    def __init__(self):
        self.reset()

    def reset(self):
        self.agencies = {}
        self.slates = {}
        self.writers = {}
        self.holding_deals = {}
        self.pitches = {}
        self.rights_checks = {}
        self.projects = {}
        self.script_deals = {}
        self.deal_steps = {}
        self.pilot_orders = {}
        self.screenings = {}
        self.negotiations = {}
        self.greenlights = {}
        self.clock = CLOCK_STARTUP_DEFAULT
        self._seq = 0

    # -- identity / ordering helpers ---------------------------------------
    def next_seq(self):
        self._seq += 1
        return self._seq

    def new_id(self):
        return str(uuid.uuid4())

    # -- logical clock -----------------------------------------------------
    def now(self):
        """The sole source of every server-stamped timestamp."""
        return self.clock

    def today(self):
        return self.clock.date()

    def set_clock(self, instant):
        self.clock = instant


store = Store()


# ---------------------------------------------------------------------------
# timestamp / date formatting and parsing
# ---------------------------------------------------------------------------

def iso3(instant):
    """ISO 8601 UTC with exactly three fractional digits (PRD 2.5)."""
    if instant is None:
        return None
    if instant.tzinfo is not None:
        instant = instant.astimezone(timezone.utc).replace(tzinfo=None)
    return "%04d-%02d-%02dT%02d:%02d:%02d.%03dZ" % (
        instant.year, instant.month, instant.day,
        instant.hour, instant.minute, instant.second,
        instant.microsecond // 1000,
    )


def parse_instant(raw):
    """Parse an ISO-8601 instant.  Returns None when unparseable."""
    if not isinstance(raw, str):
        return None
    text = raw.strip()
    if not text:
        return None
    if text.endswith(("z", "Z")):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def parse_date(raw):
    """Parse a strict YYYY-MM-DD calendar date.  Returns None when invalid."""
    if not isinstance(raw, str):
        return None
    text = raw.strip()
    if len(text) != 10 or text[4] != "-" or text[7] != "-":
        return None
    try:
        return date(int(text[0:4]), int(text[5:7]), int(text[8:10]))
    except (ValueError, TypeError):
        return None


def fmt_date(value):
    if value is None:
        return None
    return "%04d-%02d-%02d" % (value.year, value.month, value.day)


def add_days(instant, days):
    return instant + timedelta(days=days)


def months_between(start_date, end_date):
    """Whole calendar months from start_date to end_date, floored at 0."""
    months = (end_date.year - start_date.year) * 12 + (end_date.month - start_date.month)
    if end_date.day < start_date.day:
        months -= 1
    return months if months > 0 else 0


# ---------------------------------------------------------------------------
# row helpers
# ---------------------------------------------------------------------------

def new_row(with_version=True, **fields):
    row = dict(fields)
    row["id"] = store.new_id()
    row["created_at"] = store.now()
    if with_version:
        row["updated_at"] = store.now()
        row["version"] = 1
    row["_seq"] = store.next_seq()
    return row


def touch(row):
    """Refresh updated_at and increment version (PRD 2.5)."""
    row["updated_at"] = store.now()
    row["version"] = row.get("version", 0) + 1
    return row


def ordered(rows):
    """Default list ordering: created_at ascending, insertion order as tiebreak."""
    return sorted(rows, key=lambda r: (r["created_at"], r["_seq"]))
