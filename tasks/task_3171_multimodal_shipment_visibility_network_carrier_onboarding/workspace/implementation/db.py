"""In-memory data store + logical clock.

The store starts EMPTY on every boot — no seeding. All entities are built
by tests through the declared API surface.
"""
from datetime import datetime, timezone

# Logical clock — starts at exactly 2026-09-01T00:00:00Z; never wall-clock.
_clock = datetime(2026, 9, 1, 0, 0, 0, tzinfo=timezone.utc)


def get_clock():
    return _clock


def set_clock(dt):
    global _clock
    _clock = dt


# Entity stores (keyed by id, insertion-ordered)
carriers = {}
shippers = {}
consignees = {}
connections = {}
purchase_orders = {}
facilities = {}
shipments = {}
tracking_events = {}        # keyed by event id
identity_links = {}
alerts = {}
appointments = {}
data_share_grants = {}
heartbeat_records = {}
ops_runs = {}                # keyed by run_index

# Last completed ops-run timestamp (None until first checkpoint)
last_run_at = None
