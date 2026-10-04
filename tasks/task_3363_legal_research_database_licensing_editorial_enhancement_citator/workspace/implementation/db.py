"""In-memory data store and the logical clock (PRD 2.4).

The store starts empty on every boot: no seeding, no preloading, no disk
persistence. All state lives in plain dicts keyed by id, so every start.sh
re-launch wipes everything.
"""

import uuid
from datetime import datetime, timezone

from constants import CLOCK_DEFAULT_ISO


def _parse_iso8601(value):
    """Parse an ISO 8601 instant (accepts trailing Z or numeric offset)."""
    text = value.strip()
    if text.endswith(("Z", "z")):
        text = text[:-1] + "+00:00"
    dt = datetime.fromisoformat(text)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


class Store:
    def __init__(self):
        self.clock = _parse_iso8601(CLOCK_DEFAULT_ISO)
        self.seq = 0  # global insertion sequence for stable list ordering
        self.documents = {}
        self.references = {}
        self.headnotes = {}
        self.plans = {}
        self.accounts = {}
        self.subscriptions = {}
        self.users = {}
        self.usage_events = {}
        self.invoices = {}
        self.agreements = {}
        self.statements = {}
        self.orders = {}

    def next_seq(self):
        self.seq += 1
        return self.seq


store = Store()


def new_id():
    """Server-minted UUID with no type prefix (PRD 2.5) — canonical hyphenated form."""
    return str(uuid.uuid4())


def fmt_dt(dt):
    """ISO 8601 UTC timestamp with exactly three fractional digits (PRD 2.5)."""
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (dt.microsecond // 1000)


def iso_now():
    """Current logical-clock reading, formatted per PRD 2.5."""
    return fmt_dt(store.clock)


def stamp_new(entity):
    """Attach common system fields to a freshly created entity (PRD 2.5)."""
    entity["id"] = new_id()
    entity["created_at"] = iso_now()
    entity["updated_at"] = iso_now()
    entity["version"] = 1
    entity["_seq"] = store.next_seq()
    return entity


def stamp_ledger(entity):
    """UsageEvent / RoyaltyStatement carry only id + created_at (PRD 2.5)."""
    entity["id"] = new_id()
    entity["created_at"] = iso_now()
    entity["_seq"] = store.next_seq()
    return entity


def touch(entity):
    """Refresh updated_at and bump version on a mutation (PRD 2.5)."""
    entity["updated_at"] = iso_now()
    entity["version"] += 1
