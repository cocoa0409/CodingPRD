"""Logical-clock arithmetic and ISO 8601 UTC timestamp helpers.

All timestamps in this system are ISO 8601 in UTC with three fractional
digits (PRD §2.2, §2.4). Every time-gated rule resolves against the logical
clock, never against wall-clock time (PRD §2.5).
"""

from datetime import datetime, timedelta, timezone

from store import store

# Instant after which the demand-window cut-over switches from the open
# interval to the half-open interval (SCAFFOLD §1.3 demand_30d).
DEMAND_HALF_OPEN_FROM = datetime(2026, 9, 10, 0, 0, 0, tzinfo=timezone.utc)


def parse_iso(value):
    """Parse an ISO 8601 instant into an aware UTC datetime; None on failure."""
    if value is None or not isinstance(value, str):
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
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def now():
    """The current instant of the logical clock."""
    parsed = parse_iso(store.current_utc)
    if parsed is None:
        parsed = parse_iso("2026-09-01T00:00:00Z")
    return parsed


def now_iso():
    """The logical clock rendered in the canonical wire format."""
    return to_iso(now())


def to_iso(moment):
    """Render a datetime as ISO 8601 UTC with three fractional digits."""
    if moment is None:
        return None
    text = moment.astimezone(timezone.utc).isoformat(timespec="milliseconds")
    if text.endswith("+00:00"):
        text = text[:-6] + "Z"
    return text


def add_days(moment, days):
    return moment + timedelta(days=days)


def day(moment):
    """The calendar day an instant falls on, as a plain date."""
    if moment is None:
        return None
    return moment.astimezone(timezone.utc).date()


def parse_iso_or(value, fallback):
    """Parse an operator-supplied instant, falling back when unusable."""
    parsed = parse_iso(value)
    return fallback if parsed is None else parsed