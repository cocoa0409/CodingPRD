"""In-memory data store and logical clock. Store starts empty on every boot."""
from datetime import datetime, timezone

DEFAULT_CLOCK = datetime(2026, 9, 1, 0, 0, 0, tzinfo=timezone.utc)

contracts = {}
baselines = {}
bundles = {}
measures = {}
facilities = {}
draws = {}
phases = {}
disruptions = {}
reports = {}
adjustments = {}
disputes = {}
owner_reps = {}
engineers = {}

_clock = {"now": DEFAULT_CLOCK}


def logical_now():
    return _clock["now"]


def set_logical_now(dt):
    _clock["now"] = dt
