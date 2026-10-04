"""In-memory store, logical clock, id minting, and mutation stamping.

The store starts empty on every boot; nothing is seeded. All time-dependent
behavior reads the single logical clock, which starts at exactly
2026-09-01T00:00:00Z and only moves via POST /stb/_clock/set_current_utc.
"""
import uuid
from datetime import datetime, timezone

DEFAULT_CLOCK_DT = datetime(2026, 9, 1, 0, 0, 0, tzinfo=timezone.utc)

db = {
    'carriers': {},
    'findings': {},
    'rate_complaints': {},
    'evidence': {},
    'service_complaints': {},
    'esos': {},
    'mergers': {},
    'plans': {},
    'abandonments': {},
    'petitions': {},
}

_clock_dt = DEFAULT_CLOCK_DT
_clock_frac = 0  # fractional digits the clock string carries (default: none)
_seq = 0         # global monotonic counter: creation order + verify order


def clock_now():
    return _clock_dt


def clock_frac_digits():
    return _clock_frac


def set_clock(dt, frac_digits):
    global _clock_dt, _clock_frac
    _clock_dt = dt
    _clock_frac = frac_digits


def next_seq():
    global _seq
    _seq += 1
    return _seq


def new_id():
    # Server-minted dashed UUID, no type prefix.
    return str(uuid.uuid4())


def touch(entity):
    """Every mutation bumps version by exactly 1 and refreshes updated_at."""
    entity['version'] += 1
    entity['updated_at'] = _clock_dt


def stamp_new(entity):
    """Initialize the common identity block on a freshly created entity."""
    entity['created_at'] = _clock_dt
    entity['updated_at'] = _clock_dt
    entity['version'] = 1
    entity['_seq'] = next_seq()
    return entity
