"""In-memory data store, logical clock and common-field helpers.

The store starts completely empty on every boot: no entity is ever seeded,
preloaded or hardcoded.  Tests build every precondition through the API.
"""
import uuid
from datetime import datetime, timezone, date, timedelta

# PRD 2.4: at server startup the logical clock reads exactly 2026-08-01T00:00:00Z
CLOCK_DEFAULT = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)


class Store:
    def __init__(self):
        self.reset()

    def reset(self):
        self.clock = CLOCK_DEFAULT
        self._seq = 0
        self.franchisees = {}
        self.territories = {}
        self.clubs = {}
        self.relocation_requests = {}
        self.plan_templates = {}
        self.promotions = {}
        self.members = {}
        self.corporate_accounts = {}
        self.agreements = {}
        self.transfer_requests = {}
        self.guest_usage_events = {}
        self.usage_settlements = {}
        self.billing_events = {}
        self.royalty_reports = {}
        self.inspections = {}

    def next_seq(self):
        self._seq += 1
        return self._seq


db = Store()


# --------------------------------------------------------------------------
# logical clock
# --------------------------------------------------------------------------
def now_dt():
    return db.clock


def now_iso():
    """ISO 8601 UTC with exactly three fractional digits."""
    dt = db.clock.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (dt.microsecond // 1000)


def clock_date():
    return db.clock.astimezone(timezone.utc).date()


def clock_date_str():
    return clock_date().isoformat()


# --------------------------------------------------------------------------
# date helpers -- whole-day calendar arithmetic, 30-day month convention
# --------------------------------------------------------------------------
def parse_date(value):
    return date(int(value[0:4]), int(value[5:7]), int(value[8:10]))


def add_days(d, n):
    return d + timedelta(days=int(n))


def days_between(later, earlier):
    """Whole days from `earlier` to `later` (may be negative)."""
    return (later - earlier).days


def month_key(value):
    """'YYYY-MM' from a 'YYYY-MM-DD' string or a date."""
    if isinstance(value, str):
        return value[0:7]
    return "%04d-%02d" % (value.year, value.month)


def month_last_day(period_month):
    year = int(period_month[0:4])
    month = int(period_month[5:7])
    if month == 12:
        return date(year, 12, 31)
    return date(year, month + 1, 1) - timedelta(days=1)


# --------------------------------------------------------------------------
# common resource properties
# --------------------------------------------------------------------------
def new_id():
    return str(uuid.uuid4())


def common_fields():
    ts = now_iso()
    return {
        "id": new_id(),
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
        "_seq": db.next_seq(),
    }


def ledger_fields():
    """BillingEvent / GuestUsageEvent: only id and created_at."""
    return {
        "id": new_id(),
        "created_at": now_iso(),
        "_seq": db.next_seq(),
    }


def touch(record):
    """Every mutation -- including cascaded ones -- bumps version and updated_at."""
    record["version"] = record.get("version", 0) + 1
    record["updated_at"] = now_iso()
    return record


def public(record):
    return {k: v for k, v in record.items() if not k.startswith("_")}


def by_seq(records):
    return sorted(records, key=lambda r: r["_seq"])
