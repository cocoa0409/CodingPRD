"""The agency logical clock.

No rule in this API reads real wall-clock time: every temporal judgement and
every stamp is derived from the single logical clock, which starts at
2026-09-01T00:00:00Z and is moved only by POST /api/_clock/set_current_utc.
"""

from datetime import datetime, timedelta, timezone

DEFAULT_CLOCK_ISO = "2026-09-01T00:00:00Z"
DAY = timedelta(days=1)

_clock = {"now": None}


def _parse(value):
    text = str(value).strip()
    if text.endswith("Z") or text.endswith("z"):
        text = text[:-1] + "+00:00"
    dt = datetime.fromisoformat(text)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def now():
    if _clock["now"] is None:
        _clock["now"] = _parse(DEFAULT_CLOCK_ISO)
    return _clock["now"]


def set_clock(value):
    _clock["now"] = _parse(value)
    return _clock["now"]


def reset():
    _clock["now"] = _parse(DEFAULT_CLOCK_ISO)


def iso(dt):
    """ISO 8601 UTC with exactly three fractional digits: 2025-05-24T10:30:00.123Z"""
    if dt is None:
        return None
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (dt.microsecond // 1000)


def now_iso():
    return iso(now())


def parse(value):
    return _parse(value)


def parse_or_none(value):
    if value is None:
        return None
    try:
        return _parse(value)
    except (ValueError, TypeError):
        return None


def clock_day(dt):
    """The logical-clock calendar day (UTC) of an instant."""
    return dt.astimezone(timezone.utc).date()
