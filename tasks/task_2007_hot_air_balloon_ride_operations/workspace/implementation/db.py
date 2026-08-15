"""In-memory data store. Fresh on every process boot (per-test-server isolation).

No entity is seeded at startup: every record is created through the declared API
surface. `_seq` is a monotonic insertion counter used only as a deterministic
tie-breaker for created_at-equal rows; it is never serialized.
"""

COLLECTIONS = [
    "launch_sites",
    "balloons",
    "pilots",
    "customers",
    "flights",
    "reservations",
    "passengers",
    "weather_briefings",
    "chase_assignments",
    "refunds",
    "photo_packages",
]

db = {name: {} for name in COLLECTIONS}

_seq_counter = [0]


def next_seq() -> int:
    _seq_counter[0] += 1
    return _seq_counter[0]
