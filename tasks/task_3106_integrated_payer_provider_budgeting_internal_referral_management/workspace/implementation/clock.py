"""The logical clock and the in-memory identifier/timestamp store.

PRD 2.11: the system never reads wall-clock time for a business decision.
The clock starts at exactly 2026-09-01T00:00:00Z and holds that instant until
an administrative capability advances it.
"""

import uuid
from datetime import datetime, timedelta, timezone

from constants import CLOCK_START_ISO

_ISO_FORMAT = "%Y-%m-%dT%H:%M:%S.%f"


def parse_iso8601(text):
    """Parse an ISO 8601 instant into a timezone-aware UTC datetime."""
    if not isinstance(text, str):
        raise ValueError("timestamp must be a string")
    raw = text.strip()
    if raw.endswith("Z") or raw.endswith("z"):
        raw = raw[:-1] + "+00:00"
    parsed = datetime.fromisoformat(raw)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def format_iso8601(moment):
    """Format an instant as ISO 8601 UTC with exactly three fractional digits."""
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    moment = moment.astimezone(timezone.utc)
    return moment.strftime(_ISO_FORMAT)[:23] + "Z"


class Clock:
    """A single settable logical clock shared by the whole server."""

    def __init__(self):
        self._now = parse_iso8601(CLOCK_START_ISO)

    def now(self):
        return self._now

    def now_iso(self):
        return format_iso8601(self._now)

    def set(self, to_iso8601):
        self._now = parse_iso8601(to_iso8601)
        return self._now

    def advance_days(self, days):
        self._now = self._now + timedelta(days=days)
        return self._now


CLOCK = Clock()


def new_id():
    """A server-minted opaque identifier formatted as a UUID."""
    return str(uuid.uuid4())


def now_iso():
    return CLOCK.now_iso()


def today_iso():
    return format_iso8601(CLOCK.now())


def days_between(start, end):
    """Calendar days from `start` to `end` as a Decimal, one-decimal precision."""
    delta = end - start
    return delta.total_seconds() / 86400.0