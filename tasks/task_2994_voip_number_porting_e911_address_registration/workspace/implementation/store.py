"""Pure in-memory storage plus the server-side logical clock.

Every collection starts empty on every boot: no seeding, no preloading, no
persistence of any kind.  `start.sh` re-invocation therefore wipes all state.
"""
from datetime import datetime, timezone

# Before the clock has ever been set it reads exactly 2026-08-01T00:00:00Z and
# never falls back to real wall-clock time.
CLOCK_EPOCH = datetime(2026, 8, 1, 0, 0, 0, 0, tzinfo=timezone.utc)

accounts = {}
carriers = {}
jurisdictions = {}
number_blocks = {}
phone_numbers = {}
number_reservations = {}
port_requests = {}
csr_snapshots = {}
cutover_slots = {}
temporary_bridges = {}
devices = {}
e911_registrations = {}
call_attempts = {}
fee_assessments = {}

_state = {"clock": CLOCK_EPOCH, "seq": 0}


def now():
    """The current logical-clock reading."""
    return _state["clock"]


def set_clock(instant):
    previous = _state["clock"]
    _state["clock"] = instant
    return previous


def next_seq():
    """Monotonic insertion counter used for the documented tie-breaks."""
    _state["seq"] += 1
    return _state["seq"]


def all_of(collection):
    """Rows of a collection in insertion order."""
    return sorted(collection.values(), key=lambda r: r["_seq"])
