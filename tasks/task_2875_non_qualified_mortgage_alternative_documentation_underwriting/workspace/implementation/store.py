"""In-memory storage. Every byte of state lives in this process and dies with it.

No seeding of any kind: every entity is created through the declared endpoints.
"""
import copy
from datetime import datetime, timezone

from core import ApiError, iso_instant, new_id, utc_now

DEFAULT_CLOCK = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)

TABLES = (
    "programs",
    "overlays",
    "borrowers",
    "credit_events",
    "loan_files",
    "worksheets",
    "statement_months",
    "valuation_orders",
    "reviews",
    "fee_items",
    "exceptions",
    "audits",
    "findings",
    "pools",
)

NOT_FOUND = {
    "programs": "ERR_PROGRAM_NOT_FOUND",
    "overlays": "ERR_OVERLAY_NOT_FOUND",
    "borrowers": "ERR_BORROWER_NOT_FOUND",
    "loan_files": "ERR_LOAN_FILE_NOT_FOUND",
    "worksheets": "ERR_WORKSHEET_NOT_FOUND",
    "statement_months": "ERR_STATEMENT_MONTH_NOT_FOUND",
    "valuation_orders": "ERR_VALUATION_ORDER_NOT_FOUND",
    "reviews": "ERR_REVIEW_NOT_FOUND",
    "fee_items": "ERR_FEE_ITEM_NOT_FOUND",
    "exceptions": "ERR_EXCEPTION_NOT_FOUND",
    "audits": "ERR_AUDIT_NOT_FOUND",
    "findings": "ERR_FINDING_NOT_FOUND",
    "pools": "ERR_POOL_NOT_FOUND",
    "credit_events": "ERR_NOT_FOUND",
}


class Store(object):
    def __init__(self):
        self.data = {}
        self.clock = DEFAULT_CLOCK
        self._seq = 0
        for name in TABLES:
            self.data[name] = {}

    def next_seq(self):
        self._seq += 1
        return self._seq

    def table(self, name):
        return self.data[name]

    def rows(self, name):
        return list(self.data[name].values())

    def find(self, name, ident):
        if not isinstance(ident, str):
            return None
        return self.data[name].get(ident)

    def fetch(self, name, ident):
        row = self.find(name, ident)
        if row is None:
            raise ApiError(NOT_FOUND[name])
        return row

    def insert(self, name, fields, versioned=True):
        stamp = iso_instant(utc_now())
        row = {"id": new_id(), "created_at": stamp}
        row.update(fields)
        if versioned:
            row["updated_at"] = stamp
            row["version"] = 1
        row["_seq"] = self.next_seq()
        self.data[name][row["id"]] = row
        return row


db = Store()


# ---------------------------------------------------------------------------
# Per-request mutation tracking: one version bump per resource per request.
# ---------------------------------------------------------------------------
_IGNORED_KEYS = ("updated_at", "version", "_seq")


def _snapshot(row):
    return copy.deepcopy({k: v for k, v in row.items() if k not in _IGNORED_KEYS})


class Tx(object):
    def __init__(self):
        self.watched = {}
        self.forced = set()

    def watch(self, row):
        if row is None:
            return row
        key = id(row)
        if key not in self.watched:
            self.watched[key] = (row, _snapshot(row))
        return row

    def bump(self, row):
        """Force a version increment even when no field value changed."""
        if row is None:
            return row
        self.watch(row)
        self.forced.add(id(row))
        return row

    def commit(self):
        stamp = iso_instant(utc_now())
        for key, (row, snapshot) in self.watched.items():
            if "version" not in row:
                continue
            if key in self.forced or _snapshot(row) != snapshot:
                row["updated_at"] = stamp
                row["version"] = row["version"] + 1


def resolve_fk(raw, field, table):
    """Existence check for a body foreign key (validations priority 5).

    Runs before shape validation, so a missing or mistyped value is left for the
    shape rule to report; only a well-formed identifier that names nothing is a
    404 here.
    """
    value = raw.get(field)
    if isinstance(value, str):
        row = db.find(table, value)
        if row is None:
            raise ApiError(NOT_FOUND[table])
        return row
    return None
