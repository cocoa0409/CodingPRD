"""In-memory data store. Empty on every boot — no seeding."""
from datetime import datetime, timezone

# Logical clock: default 2026-09-01T00:00:00Z, advanced only via /api/_clock/set_current_utc
_clock = datetime(2026, 9, 1, 0, 0, 0, tzinfo=timezone.utc)


def get_clock():
    return _clock


def set_clock(dt):
    global _clock
    _clock = dt


# Stores keyed by id
customers = {}
spas = {}
trains = {}
adps = {}
cargo_slots = {}
berths = {}
vessel_calls = {}
laytime_statements = {}
pipelines = {}
day_schedules = {}
nominations = {}
cancellations = {}
resales = {}
turnarounds = {}
