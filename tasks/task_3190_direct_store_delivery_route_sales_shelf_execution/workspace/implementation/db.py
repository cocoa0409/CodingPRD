"""In-memory data store. All state lives in module-level dicts keyed by id.

The store starts completely empty on every boot; nothing is seeded here.
The logical clock starts at exactly 2026-09-01T00:00:00Z and advances only
via POST /dsd/_clock/set_current_utc.
"""

from datetime import datetime, timezone

COLLECTIONS = [
    "reps",
    "stores",
    "products",
    "routes",
    "assignments",
    "route_days",
    "lots",
    "orders",
    "order_lines",
    "shelf_executions",
    "stale_credits",
    "promo_agreements",
    "promo_executions",
    "settlements",
    "snapshots",
]

db = {name: {} for name in COLLECTIONS}

CLOCK_START_ISO = "2026-09-01T00:00:00Z"


def _parse_iso(value):
    text = str(value).strip()
    if text.endswith(("Z", "z")):
        text = text[:-1] + "+00:00"
    dt = datetime.fromisoformat(text)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


class LogicalClock:
    def __init__(self):
        self.current = _parse_iso(CLOCK_START_ISO)

    def iso(self):
        return self.current.strftime("%Y-%m-%dT%H:%M:%SZ")

    def date(self):
        return self.current.date()

    def minute_of_day(self):
        return self.current.hour * 60 + self.current.minute

    def advance(self, current_utc):
        self.current = _parse_iso(current_utc)


clock = LogicalClock()
