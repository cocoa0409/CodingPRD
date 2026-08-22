"""ISO-8601 UTC helpers.

PRD §2.4: timestamps are ISO 8601 UTC with exactly three fractional digits.
PRD §2.7: day counts truncate downward; calendar-day addition preserves the
time of day exactly.
"""
import math
import re
from datetime import datetime, timedelta, timezone

_ISO_RE = re.compile(
    r"^\d{4}-\d{2}-\d{2}[Tt ]\d{2}:\d{2}(:\d{2})?(\.\d+)?"
    r"([Zz]|[+-]\d{2}:?\d{2})?$"
)


def parse_iso8601(value):
    """Parse an ISO-8601 instant into an aware UTC datetime, or None."""
    if not isinstance(value, str):
        return None
    text = value.strip()
    if not text or not _ISO_RE.match(text):
        return None
    normalized = text.replace(" ", "T").replace("t", "T")
    if normalized.endswith("Z") or normalized.endswith("z"):
        normalized = normalized[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(normalized)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def to_iso(dt):
    if dt is None:
        return None
    dt = dt.astimezone(timezone.utc)
    return "%04d-%02d-%02dT%02d:%02d:%02d.%03dZ" % (
        dt.year,
        dt.month,
        dt.day,
        dt.hour,
        dt.minute,
        dt.second,
        dt.microsecond // 1000,
    )


def now_real_iso():
    return to_iso(datetime.now(timezone.utc))


def elapsed_days(start, end):
    """floor((end - start) / 86400 s) — truncated downward, never rounded."""
    seconds = (end - start).total_seconds()
    return int(math.floor(seconds / 86400.0))


def add_days(instant, days):
    return instant + timedelta(days=days)


def utc_date(instant):
    return instant.astimezone(timezone.utc).date()
