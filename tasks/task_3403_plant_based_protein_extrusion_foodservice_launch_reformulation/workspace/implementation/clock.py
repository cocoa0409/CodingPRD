# Logical clock (PRD 2.4) — single controllable time source; never wall-clock
# for domain decisions. Default at boot: exactly 2026-09-01T00:00:00Z.
from datetime import datetime, timezone

import constants


def parse_dt(value):
    """Parse an ISO-8601 string into an aware UTC datetime. Returns None if invalid."""
    if not isinstance(value, str):
        return None
    text = value.strip()
    if not text:
        return None
    if text.endswith(("Z", "z")):
        text = text[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def fmt_ms(dt):
    """ISO 8601 UTC with exactly three fractional digits (PRD 2.5 format)."""
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (dt.microsecond // 1000)


def fmt_canonical(dt):
    """Canonical instant format: no fraction when the value lands on a whole
    second (matches the PRD's clock literal style), else three fractional digits."""
    if dt.microsecond == 0:
        return dt.strftime("%Y-%m-%dT%H:%M:%SZ")
    return fmt_ms(dt)


_state = {"now": parse_dt(constants.DEFAULT_CLOCK_START_ISO)}


def now():
    return _state["now"]


def set_now(dt):
    _state["now"] = dt


def now_ms():
    """Current logical clock formatted with three fractional digits."""
    return fmt_ms(_state["now"])


def now_canonical():
    """Current logical clock in canonical format (for clock-stamped fields)."""
    return fmt_canonical(_state["now"])
