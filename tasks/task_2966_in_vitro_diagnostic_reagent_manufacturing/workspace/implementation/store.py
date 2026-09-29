"""In-memory data store, the server-side logical clock, and timestamp helpers.

Storage is process-local Python dictionaries keyed by id.  Nothing is persisted
and nothing is seeded: every boot starts with a completely empty store.
"""

import calendar
import random
import string
import uuid
from datetime import datetime, timedelta, timezone

UTC = timezone.utc

# PRD 2.4: before any caller has moved it, the logical clock reads exactly
# 2026-08-01T00:00:00Z, and it never falls back to real wall-clock time.
CLOCK_EPOCH = datetime(2026, 8, 1, 0, 0, 0, tzinfo=UTC)


class Store(object):
    def __init__(self):
        self.reset()

    def reset(self):
        self.material_specifications = {}
        self.material_lots = {}
        self.product_specifications = {}
        self.design_control_records = {}
        self.reagent_lots = {}
        self.lot_components = {}
        self.fill_runs = {}
        self.monitoring_samples = {}
        self.test_results = {}
        self.stability_studies = {}
        self.bridging_studies = {}
        self.complaints = {}
        self.distribution_orders = {}
        self.allocations = {}
        # Cold-chain events are not an exposed aggregate; they are the history
        # the cumulative cold-chain figures of PRD 3.9 are derived from.
        self.cold_chain_events = {}
        self.logical_clock = CLOCK_EPOCH
        self._seq = 0

    def next_seq(self):
        self._seq += 1
        return self._seq


db = Store()


def now_clock():
    """The logical clock (PRD 2.4)."""
    return db.logical_clock


def set_clock(instant):
    db.logical_clock = instant


def wall_now():
    """Real time, used only for created_at / updated_at / envelope metadata."""
    return datetime.now(UTC)


def new_id():
    return str(uuid.uuid4())


def request_id():
    alphabet = string.ascii_uppercase + string.digits
    return "req_" + "".join(random.choice(alphabet) for _ in range(20))


def fmt_ts(value):
    """ISO 8601 UTC with exactly three fractional digits."""
    if value is None:
        return None
    value = value.astimezone(UTC)
    return "%04d-%02d-%02dT%02d:%02d:%02d.%03dZ" % (
        value.year, value.month, value.day,
        value.hour, value.minute, value.second,
        value.microsecond // 1000,
    )


def parse_ts(raw):
    """Parse a client-supplied ISO 8601 instant; returns None when unparseable."""
    if not isinstance(raw, str):
        return None
    text = raw.strip()
    if not text:
        return None
    if text.endswith("Z") or text.endswith("z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def add_days(instant, days):
    return instant + timedelta(days=days)


def add_months(instant, months):
    """Calendar-month arithmetic: keep the day-of-month, clamping to the last
    day of the target month, and keep the time-of-day (PRD 3.5)."""
    total = instant.month - 1 + int(months)
    year = instant.year + total // 12
    month = total % 12 + 1
    day = min(instant.day, calendar.monthrange(year, month)[1])
    return instant.replace(year=year, month=month, day=day)


def create_row(collection, fields, common=True):
    """Create a row with the common resource properties of PRD 2.4."""
    created = wall_now()
    row = {"id": new_id()}
    row.update(fields)
    row["created_at"] = created
    if common:
        row["updated_at"] = created
        row["version"] = 1
    row["_seq"] = db.next_seq()
    collection[row["id"]] = row
    return row


def touch(row):
    """Refresh updated_at and increase version by exactly 1 (PRD 2.4 / 2.10)."""
    if row is None:
        return row
    if "version" in row:
        row["version"] = row["version"] + 1
        row["updated_at"] = wall_now()
    return row


def rows(collection):
    """All rows of a collection in creation order."""
    return sorted(collection.values(), key=lambda r: r["_seq"])
