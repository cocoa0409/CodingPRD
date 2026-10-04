"""ISO-8601 parsing and the two pinned output formats.

- fmt_logical: canonical UTC, no fractional part when whole seconds — used for
  user-supplied datetime echoes and logical-clock stamps (activated_at,
  accepted_at, committed_at, launched_at, current_utc).
- fmt_stamp: always three fractional digits (PRD §2.5) — used for created_at
  and updated_at.
"""

from datetime import datetime, timezone


def parse_iso(value):
    """Parse an ISO 8601 string into an aware UTC datetime.

    Accepts a trailing 'Z', explicit offsets, fractional seconds, and plain
    dates (interpreted as midnight UTC). Naive datetimes are assumed UTC.
    Raises ValueError on unparseable input.
    """
    if not isinstance(value, str):
        raise ValueError("not a string")
    text = value.strip()
    if not text:
        raise ValueError("empty")
    if text.endswith(("Z", "z")):
        text = text[:-1] + "+00:00"
    dt = datetime.fromisoformat(text)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def fmt_logical(dt):
    """Canonical UTC ISO string; omits fractional seconds when zero."""
    dt = dt.astimezone(timezone.utc)
    if dt.microsecond == 0:
        return dt.strftime("%Y-%m-%dT%H:%M:%SZ")
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def fmt_stamp(dt):
    """UTC ISO string with exactly three fractional digits (PRD §2.5)."""
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"
