"""In-memory data store + server-held logical clock.

Storage is in-memory only (Python dicts keyed by id). No seeding, no
persistence: every start.sh re-invocation boots a byte-fresh store.
"""
from datetime import datetime, timezone

# One dict per top-level resource; insertion order preserved (py3.7+).
STORES = {
    'products': {},
    'lots': {},
    'batches': {},
    'facilities': {},
    'programs': {},      # ConversionProgram
    'trays': {},
    'agreements': {},
    'orders': {},
    'claims': {},
    'disruptions': {},
    'inventory': {},
}

# PRD 2.4: before any call has set it, the logical clock reads exactly
# 2026-09-01T00:00:00Z and never falls back to wall-clock time.
DEFAULT_CLOCK_ISO = '2026-09-01T00:00:00Z'
_clock = {'dt': datetime(2026, 9, 1, 0, 0, 0, tzinfo=timezone.utc)}


def get_clock():
    return _clock['dt']


def set_clock(dt):
    _clock['dt'] = dt


def fmt_iso(dt):
    """Normalize a tz-aware datetime to an ISO8601 UTC string with Z suffix."""
    dt = dt.astimezone(timezone.utc)
    if dt.microsecond:
        return dt.strftime('%Y-%m-%dT%H:%M:%S.') + '{:06d}Z'.format(dt.microsecond)
    return dt.strftime('%Y-%m-%dT%H:%M:%SZ')


def clock_iso():
    """Current logical clock as a normalized ISO8601 string."""
    return fmt_iso(get_clock())
