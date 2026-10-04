"""In-memory data store and logical clock.

The store starts completely empty on every boot. No seeding, ever.
"""
from datetime import datetime, timezone

# Logical clock: server startup default is exactly 2026-09-01T00:00:00Z.
_logical_clock = datetime(2026, 9, 1, 0, 0, 0, tzinfo=timezone.utc)


def get_clock():
    return _logical_clock


def set_clock(dt):
    global _logical_clock
    _logical_clock = dt


# Entity tables: name -> { id: entity-dict }
stores = {
    "yards": {},
    "sellers": {},
    "members": {},
    "licenses": {},
    "vehicles": {},
    "titles": {},
    "auctions": {},
    "auction_items": {},
    "bids": {},
    "sales": {},
    "gate_passes": {},
    "settlements": {},
    "export_documents": {},
}
