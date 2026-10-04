"""In-memory data store and the server-held logical clock.

Storage is in-memory only: plain dicts keyed by resource id. The store starts
empty on every boot; nothing is seeded. Every byte of state arrives via API
calls. The logical clock starts at exactly 2026-09-01T00:00:00Z and is only
ever moved by POST /_clock/set_current_utc -- never by wall-clock time.
"""

import uuid
from datetime import datetime, timezone

# entity name -> {id: record}
STORE = {
    "programs": {},
    "lots": {},
    "methods": {},
    "certificates": {},
    "customers": {},
    "sales_orders": {},
    "services": {},
    "calibration_orders": {},
    "traceability_links": {},
    "pt_rounds": {},
    "pt_results": {},
}

# Monotonic insertion sequence: deterministic tie-break for created_at ties.
_seq = [0]


def next_seq():
    _seq[0] += 1
    return _seq[0]


def new_id():
    # Dashed canonical UUID (validators expect the dashed form).
    return str(uuid.uuid4())


CLOCK_START = datetime(2026, 9, 1, 0, 0, 0, tzinfo=timezone.utc)
_clock = [CLOCK_START]


def get_clock():
    return _clock[0]


def set_clock(dt):
    _clock[0] = dt
