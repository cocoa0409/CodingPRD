"""The logical clock (PRD 2.4). Startup default is exactly 2026-09-01T00:00:00Z;
the server never falls back to wall-clock time for entity timestamps."""

from datetime import datetime, timezone

_state = {"current": datetime(2026, 9, 1, 0, 0, 0, tzinfo=timezone.utc)}


def get_current():
    return _state["current"]


def set_current(dt):
    _state["current"] = dt
