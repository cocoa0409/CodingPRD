"""In-memory data store and logical clock.

The store starts completely empty on every boot — the test harness rebuilds
all state through the declared API surface. The logical clock defaults to
exactly 2026-09-01T00:00:00Z and is only advanced via
POST /mfc/_clock/set_current_utc.
"""

import threading
import uuid
from datetime import datetime, timezone

_LOCK = threading.RLock()

# Logical clock: fixed default, never wall-clock.
_clock = datetime(2026, 9, 1, 0, 0, 0, tzinfo=timezone.utc)

# Entity tables: id -> dict
sites = {}
products = {}
balances = {}          # InventoryBalance
lots = {}              # StockLot
customers = {}
memberships = {}
replenish_orders = {}
orders = {}
pick_batches = {}
pickers = {}
drivers = {}
delivery_bags = {}


def lock():
    return _LOCK


def new_id():
    return str(uuid.uuid4())


def now():
    """Current logical time (aware datetime, UTC)."""
    with _LOCK:
        return _clock


def set_now(dt):
    global _clock
    with _LOCK:
        _clock = dt


def fmt_ts(dt):
    """ISO 8601 UTC with three fractional digits, e.g. 2026-09-01T00:00:00.000Z."""
    if dt is None:
        return None
    ms = int(round(dt.microsecond / 1000.0))
    if ms >= 1000:
        from datetime import timedelta
        dt = dt + timedelta(seconds=1)
        ms = 0
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{ms:03d}Z"


def touch(resource):
    """Refresh updated_at and increment version on a common-field resource."""
    resource["updated_at"] = now()
    resource["version"] = resource.get("version", 1) + 1


def new_common(resource):
    ts = now()
    resource.setdefault("created_at", ts)
    resource.setdefault("updated_at", ts)
    resource.setdefault("version", 1)
    return resource
