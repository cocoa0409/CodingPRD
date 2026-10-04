"""In-memory data store, logical clock and common-field helpers.

The store starts completely empty on every boot: no entity is ever seeded,
preloaded, registered or hardcoded.  Tests build every precondition through the
declared API surface.  Nothing is persisted to disk, so re-invoking start.sh
wipes every byte of state.
"""
import uuid
from datetime import datetime, timezone, timedelta

from config import CLOCK_DEFAULT_ISO

# PRD 2.13 -- the logical clock's startup default.
CLOCK_DEFAULT = datetime(2026, 9, 1, 0, 0, 0, tzinfo=timezone.utc)


def parse_instant(value):
    """Parse an ISO 8601 instant (with or without a trailing Z) to aware UTC."""
    raw = value
    if raw.endswith("Z"):
        raw = raw[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(raw)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def iso_of(dt):
    """Domain instant: ISO 8601 UTC, whole seconds.

    The PRD's workflow instants (`sla_due_iso`, `expires_on`, `*_clock_iso`,
    `remediation_due_iso`, ...) are not given a fractional precision anywhere in
    §2, unlike the two common fields; every instant the system derives is a whole
    second, so they are rendered without a fractional part.
    """
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def iso_of_precise(dt):
    """ISO 8601 UTC with exactly three fractional digits.

    Reserved for `created_at` / `updated_at`, which PRD §2.11 requires to carry
    three fractional digits.
    """
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (dt.microsecond // 1000)


def add_months(dt, months):
    """Advance `dt` by `months` calendar months, clamping the day of month.

    A 31 January instant plus one month lands on 28/29 February rather than
    overflowing into March, which is the ordinary calendar-month convention.
    """
    months = int(months)
    total = dt.month - 1 + months
    year = dt.year + total // 12
    month = total % 12 + 1
    day = dt.day
    while True:
        try:
            return dt.replace(year=year, month=month, day=day)
        except ValueError:
            day -= 1


class Store:
    """Process-local world.  Every table is an id-keyed plain dict."""

    def __init__(self):
        self.reset()

    def reset(self):
        self.clock = CLOCK_DEFAULT
        self._seq = 0
        self.brands = {}
        self.franchisees = {}
        self.territories = {}
        self.agreements = {}
        self.referrals = {}
        self.leads = {}
        self.national_accounts = {}
        self.work_orders = {}
        self.audits = {}
        self.statements = {}
        self.territory_assignments = {}
        self.transfer_applications = {}

    def next_seq(self):
        self._seq += 1
        return self._seq


db = Store()


# ---------------------------------------------------------------------------
# logical clock
# ---------------------------------------------------------------------------
def now_dt():
    return db.clock


def now_iso():
    return iso_of(db.clock)


def now_iso_precise():
    """The clock instant with three fractional digits (PRD 2.11 common fields)."""
    return iso_of_precise(db.clock)


# ---------------------------------------------------------------------------
# common resource properties (PRD 2.11)
# ---------------------------------------------------------------------------
def new_id():
    return str(uuid.uuid4())


def common_fields():
    ts = now_iso_precise()
    return {
        "id": new_id(),
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
        "_seq": db.next_seq(),
    }


def touch(record):
    """Every mutation -- including cascaded ones -- bumps version and updated_at."""
    record["version"] = record.get("version", 0) + 1
    record["updated_at"] = now_iso_precise()
    return record


def public(record):
    """Strip private bookkeeping keys before serialisation."""
    return {k: v for k, v in record.items() if not k.startswith("_")}


def by_seq(records):
    return sorted(records, key=lambda r: r["_seq"])


def hours_from(instant, hours):
    return instant + timedelta(hours=int(hours))


def days_from(instant, days):
    return instant + timedelta(days=int(days))