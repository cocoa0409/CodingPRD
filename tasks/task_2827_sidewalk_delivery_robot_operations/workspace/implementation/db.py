"""In-memory store, logical clock and common-field helpers.

Nothing is seeded here: every collection starts empty on every boot and all
state lives in process memory only.
"""

import re
import uuid
from datetime import datetime, timedelta, timezone

from flask import g

TS_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z$")

CLOCK_DEFAULT = "2026-08-01T00:00:00.000Z"

COLLECTIONS = (
    "zones",
    "segments",
    "closures",
    "merchants",
    "robots",
    "bays",
    "reservations",
    "orders",
    "missions",
    "plans",
    "interventions",
    "incidents",
)


class Store(object):
    def __init__(self):
        self.reset()

    def reset(self):
        for name in COLLECTIONS:
            setattr(self, name, {})
        self.clock = parse_ts(CLOCK_DEFAULT)
        self._seq = 0

    def next_seq(self):
        self._seq += 1
        return self._seq


def parse_ts(text):
    """Parse a strict ISO-8601 UTC instant with exactly three fractional digits."""
    return datetime(
        int(text[0:4]),
        int(text[5:7]),
        int(text[8:10]),
        int(text[11:13]),
        int(text[14:16]),
        int(text[17:19]),
        int(text[20:23]) * 1000,
        tzinfo=timezone.utc,
    )


def format_ts(moment):
    return moment.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (moment.microsecond // 1000)


def valid_ts(text):
    if not isinstance(text, str) or not TS_RE.match(text):
        return False
    try:
        parse_ts(text)
    except ValueError:
        return False
    return True


db = Store()


def now():
    """The logical clock as a datetime."""
    return db.clock


def now_iso():
    return format_ts(db.clock)


def new_id():
    return str(uuid.uuid4())


def _bumped():
    if not hasattr(g, "bumped_rows"):
        g.bumped_rows = set()
    return g.bumped_rows


def create_row(collection, fields):
    row = dict(fields)
    row["id"] = new_id()
    stamp = now_iso()
    row["created_at"] = stamp
    row["updated_at"] = stamp
    row["version"] = 1
    row["_seq"] = db.next_seq()
    collection[row["id"]] = row
    _bumped().add(id(row))
    return row


def bump(row):
    """Refresh updated_at and increase version by exactly one per request."""
    if row is None:
        return row
    marker = id(row)
    if marker in _bumped():
        row["updated_at"] = now_iso()
        return row
    _bumped().add(marker)
    row["version"] = row.get("version", 1) + 1
    row["updated_at"] = now_iso()
    return row


def sort_key_created(row):
    return (row["created_at"], row["_seq"])


def public(row):
    return {k: v for k, v in row.items() if not k.startswith("_")}


def plus_minutes(moment, minutes):
    return moment + timedelta(minutes=minutes)


def plus_hours(moment, hours):
    return moment + timedelta(hours=hours)
