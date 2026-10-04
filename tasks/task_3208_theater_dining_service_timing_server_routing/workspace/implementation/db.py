"""In-memory data store, logical clock and identifier helpers.

Everything lives in process memory. There is no SQLite file, no JSON dump, no
/tmp cache and no external persistence, so a fresh `start.sh` invocation begins
with a completely empty world. Nothing is seeded or preloaded here.
"""

import random
import string
import uuid
from datetime import datetime, timezone

DEFAULT_CLOCK = datetime(2026, 9, 1, 0, 0, 0, tzinfo=timezone.utc)


def iso_z(dt):
    """ISO 8601 UTC instant.

    The logical clock and every instant derived from it land on whole seconds,
    and the PRD's own clock literal is `2026-09-01T00:00:00Z`, so the fractional
    part is emitted only when a sub-second component actually exists.
    """
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt = dt.astimezone(timezone.utc)
    if dt.microsecond == 0:
        return dt.strftime("%Y-%m-%dT%H:%M:%SZ")
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (dt.microsecond // 1000)


def iso_z3(dt):
    """ISO 8601 UTC with three fractional digits.

    Reserved for the fields the PRD pins to that exact form: `created_at`,
    `updated_at` (2.6) and `api_request_timestamp` (2.2).
    """
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (dt.microsecond // 1000)


def parse_iso(value):
    if value is None:
        return None
    if isinstance(value, datetime):
        dt = value
    else:
        text = str(value).strip()
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        try:
            dt = datetime.fromisoformat(text)
        except ValueError:
            return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def new_id():
    return str(uuid.uuid4())


def request_id():
    alphabet = string.ascii_letters + string.digits
    suffix = "".join(random.choice(alphabet) for _ in range(18))
    return "req_" + suffix


class Store(object):
    """All collections, keyed by id. Populated only through the declared API."""

    COLLECTIONS = (
        "auditoriums",
        "showtimes",
        "programming_events",
        "menu_items",
        "themed_menu_items",
        "servers",
        "section_assignments",
        "order_slips",
        "kitchen_tickets",
        "checks",
        "disturbance_events",
    )

    def __init__(self):
        for name in self.COLLECTIONS:
            setattr(self, name, {})
        self.now = DEFAULT_CLOCK
        self.reserved_starts = {}
        self.order = {}
        self.seq = 0

    def register(self, collection, row):
        row["id"] = new_id()
        row["created_at"] = self.now
        self.order[row["id"]] = self.seq
        self.seq += 1
        getattr(self, collection)[row["id"]] = row
        return row

    def register_keyed(self, collection, key, row):
        """Register under an explicit id (a CheckTab is keyed by its slip's id)."""
        row["id"] = key
        row["created_at"] = self.now
        self.order[key] = self.seq
        self.seq += 1
        getattr(self, collection)[key] = row
        return row

    def order_key(self, row):
        return self.order.get(row.get("id"), 0)

    def rows(self, collection):
        return list(getattr(self, collection).values())

    def sorted_rows(self, collection):
        return sorted(self.rows(collection), key=self.order_key)


db = Store()