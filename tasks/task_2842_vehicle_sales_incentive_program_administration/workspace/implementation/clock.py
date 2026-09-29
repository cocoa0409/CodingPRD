"""The logical clock (PRD 2.6).

Every system-stamped instant in the service reads from this clock. Its startup
default is exactly 2026-08-01T00:00:00.000Z and the server never falls back to
real wall-clock time under any circumstance.
"""

from datetime import datetime, timezone

import util

DEFAULT_UTC = "2026-08-01T00:00:00.000Z"

_current = DEFAULT_UTC


def now():
    """Current logical clock reading as a canonical instant string."""
    return _current


def now_dt():
    return util.to_dt(_current)


def set_now(canonical_iso):
    global _current
    _current = canonical_iso
    return _current


def reset():
    global _current
    _current = DEFAULT_UTC
