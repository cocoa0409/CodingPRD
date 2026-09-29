"""In-process, in-memory data store.

Plain Python dicts only — nothing is persisted, nothing is seeded. A fresh
process therefore always starts with an empty store and the logical clock at
its documented default (PRD §2.5).
"""

import datetime as _dt

from util import UTC, fmt_instant, new_id, now_real

#: Instant the logical clock reads before it has ever been set (PRD §2.5).
CLOCK_DEFAULT = _dt.datetime(2026, 8, 1, 0, 0, 0, 0, tzinfo=UTC)

COLLECTIONS = (
    "clients",
    "permit_accounts",
    "mail_jobs",
    "hygiene_runs",
    "entry_facilities",
    "commingle_batches",
    "batch_members",
    "sort_containers",
    "drop_shipments",
    "postage_statements",
    "verification_findings",
    "service_level_records",
    "client_invoices",
)


class Store:
    def __init__(self):
        for name in COLLECTIONS:
            setattr(self, name, {})
        self.clock = CLOCK_DEFAULT
        self._seq = 0

    # -------------------------------------------------------------- identity ---
    def next_seq(self):
        self._seq += 1
        return self._seq

    def now(self):
        """Current logical clock instant."""
        return self.clock

    # ------------------------------------------------------------- lifecycle ---
    def insert(self, collection, record, versioned=True):
        """Attach identity/system fields and file the record."""
        stamp = now_real()
        record["id"] = new_id()
        record["created_at"] = stamp
        if versioned:
            record["updated_at"] = stamp
            record["version"] = 1
        record["_seq"] = self.next_seq()
        getattr(self, collection)[record["id"]] = record
        return record

    def ordered(self, collection):
        """Every record of a collection in created_at ascending order."""
        return sorted(getattr(self, collection).values(), key=lambda r: r["_seq"])


def touch(record):
    """Refresh updated_at and increment version by exactly one (PRD §2.4)."""
    record["updated_at"] = now_real()
    record["version"] = record.get("version", 0) + 1
    return record


def order_by_created(records):
    return sorted(records, key=lambda r: r["_seq"])


db = Store()


def clock_iso():
    return fmt_instant(db.clock)
