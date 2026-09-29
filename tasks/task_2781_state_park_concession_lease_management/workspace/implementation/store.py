"""In-memory data store, logical clock and row bookkeeping.

Storage is process-local Python dicts only. Nothing is seeded at import time or
at boot: every row is created through a declared endpoint.
"""
import uuid
from datetime import datetime, timezone, timedelta

from flask import g

# The logical clock reads exactly this instant before it is ever repositioned.
INITIAL_CLOCK = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)


class Store(object):
    def __init__(self):
        self.reset()

    def reset(self):
        self.parks = {}
        self.opportunities = {}
        self.prospectuses = {}
        self.offerors = {}
        self.proposals = {}
        self.evaluations = {}
        self.leases = {}
        self.bonds = {}
        self.improvements = {}
        self.plans = {}
        self.reports = {}
        self.reconciliations = {}
        self.audits = {}
        self.compliance_actions = {}
        self.clock = INITIAL_CLOCK
        self._seq = 0

    def next_seq(self):
        self._seq += 1
        return self._seq


db = Store()


def now():
    """The logical clock instant — the only source of 'now'."""
    return db.clock


def clock_date():
    return db.clock.date()


def iso(dt):
    """ISO 8601 UTC with exactly three fractional-second digits."""
    return "%04d-%02d-%02dT%02d:%02d:%02d.%03dZ" % (
        dt.year, dt.month, dt.day, dt.hour, dt.minute, dt.second,
        dt.microsecond // 1000,
    )


def now_iso():
    return iso(now())


def new_id():
    return str(uuid.uuid4())


def insert(collection, row, common_fields=True):
    """Mint identity/system fields and store the row."""
    stamp = now_iso()
    body = {"id": new_id()}
    body.update(row)
    body["created_at"] = stamp
    if common_fields:
        body["updated_at"] = stamp
        body["version"] = 1
    body["_seq"] = db.next_seq()
    collection[body["id"]] = body
    return body


def _touched():
    if not hasattr(g, "prd_touched"):
        g.prd_touched = set()
    return g.prd_touched


def touch(row):
    """Advance version by exactly one and refresh updated_at.

    A row touched several times inside one request still advances by exactly
    one (PRD 2.10: a single request advancing both lease dimensions still
    advances version by one).
    """
    if row is None or "version" not in row:
        return row
    marks = _touched()
    if row["id"] in marks:
        return row
    marks.add(row["id"])
    row["version"] = row["version"] + 1
    row["updated_at"] = now_iso()
    return row


def parse_iso_instant(value):
    """Parse an ISO 8601 UTC instant. Returns None when malformed."""
    if not isinstance(value, str):
        return None
    text = value.strip()
    if not text:
        return None
    if text.endswith("Z") or text.endswith("z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    offset = parsed.utcoffset()
    if offset is None or offset != timedelta(0):
        return None
    return parsed.astimezone(timezone.utc)
