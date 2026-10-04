"""In-memory data store and logical clock.

The store starts completely empty on every boot. No seeding, ever.
"""
from datetime import datetime, timezone

# Logical clock: server startup default is exactly 2026-09-01T00:00:00Z.
# The server never falls back to wall-clock time for business rules.
_logical_clock = datetime(2026, 9, 1, 0, 0, 0, tzinfo=timezone.utc)


def get_clock():
    return _logical_clock


def set_clock(dt):
    global _logical_clock
    _logical_clock = dt


# Entity tables: name -> { id: entity-dict }
stores = {
    "market_centers": {},
    "agents": {},
    "sponsorship_edges": {},
    "onboarding_documents": {},
    "disputes": {},
    "commission_events": {},
    "periods": {},
    "ledger_entries": {},
    "distributions": {},
    "transfer_requests": {},
    "vesting_schedules": {},
    "resolutions": {},
}
