"""Logical clock: starts at 2026-09-01T00:00:00Z, advances only via the
clock endpoint. Never falls back to wall-clock."""
from datetime import datetime, timezone

_INITIAL = datetime(2026, 9, 1, 0, 0, 0, tzinfo=timezone.utc)

_now = _INITIAL


def now():
    return _now


def set_now(dt):
    global _now
    _now = dt


def _fmt_z(dt):
    """Whole-second ISO8601 Z form — the canonical representation of the
    logical clock's instants (PRD §2.8 writes the clock start as
    2026-09-01T00:00:00Z and business fields are stamped from the clock)."""
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def _fmt_ms(dt):
    """ISO8601 UTC with three fractional digits — required by PRD for
    created_at/updated_at and api_request_timestamp only."""
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def iso_now():
    """Current logical time as whole-second ISO8601 Z string."""
    return _fmt_z(_now)


def iso_now_ms():
    """Current logical time with three fractional digits (updated_at)."""
    return _fmt_ms(_now)


def parse_iso(s):
    """Parse an ISO8601 string into an aware datetime (UTC)."""
    if not isinstance(s, str):
        raise ValueError("not a string")
    txt = s.strip()
    if txt.endswith("Z"):
        txt = txt[:-1] + "+00:00"
    dt = datetime.fromisoformat(txt)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def iso(dt):
    if dt is None:
        return None
    return _fmt_z(dt)


def iso_ms(dt):
    if dt is None:
        return None
    return _fmt_ms(dt)
