"""Logical lapse-incident clock (PRD §3.9).

Starts at exactly 2026-09-01T00:00:00Z and never falls back to wall-clock time.
"""
from datetime import datetime, timedelta, timezone

DEFAULT_START = datetime(2026, 9, 1, 0, 0, 0, tzinfo=timezone.utc)


def parse_iso(value):
    if value is None:
        raise ValueError("missing timestamp")
    text = str(value).strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    dt = datetime.fromisoformat(text)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def iso(dt):
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.") + \
        "%03dZ" % (dt.microsecond // 1000)


class Clock:
    current = DEFAULT_START
    event_no = 0

    @classmethod
    def now(cls):
        return cls.current

    @classmethod
    def iso_now(cls):
        return iso(cls.current)

    @classmethod
    def reset(cls, start=DEFAULT_START):
        cls.current = start
        cls.event_no = 0

    @classmethod
    def advance_to(cls, target):
        """Monotonic: the target may never precede the current reading."""
        if target < cls.current:
            return None
        cls.current = target
        cls.event_no += 1
        return cls.event_no

    @classmethod
    def plus_hours(cls, hours):
        return cls.current + timedelta(hours=hours)

    @classmethod
    def iso_now_plus(cls, seconds):
        return iso(cls.current + timedelta(seconds=seconds))

    @classmethod
    def plus_seconds(cls, seconds):
        return cls.current + timedelta(seconds=seconds)