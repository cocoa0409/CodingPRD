"""In-memory data store. Fresh on every process boot (per-test-server isolation).

The store starts EMPTY on every boot: no seeding, no preloading. Every entity a
test needs is built through the declared API surface.
"""

COLLECTIONS = [
    "districts",
    "guideline_sets",
    "owners",
    "properties",
    "applications",
    "meetings",
    "hearings",
    "comments",
    "appeals",
    "violations",
    "demolition_delays",
    "hardship_reviews",
    "certificates",
]

db = {name: {} for name in COLLECTIONS}

# Global monotonic creation sequence: stable tiebreaker for the
# created_at-ascending list sort when two records share a wall-clock millisecond.
_seq_counter = [0]


def next_seq() -> int:
    _seq_counter[0] += 1
    return _seq_counter[0]
