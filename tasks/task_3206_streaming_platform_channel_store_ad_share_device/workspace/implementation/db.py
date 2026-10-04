"""In-memory data store. Starts empty on every boot; never seeded."""

import uuid
from datetime import datetime, timezone


def new_id():
    return str(uuid.uuid4())


def new_request_id():
    return "req_" + uuid.uuid4().hex[:20]


def iso_now_wallclock():
    """ISO8601 UTC timestamp with 3 fractional digits (for meta / created_at)."""
    dt = datetime.now(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


class Store:
    def __init__(self):
        self.publishers = {}
        self.channels = {}
        self.channel_versions = {}
        self.viewer_accounts = {}
        self.subscriptions = {}
        self.ad_slot_grants = {}
        self.campaigns = {}
        self.placement_bookings = {}
        self.manufacturers = {}
        self.device_models = {}
        self.lab_bookings = {}
        self.os_updates = {}
        self.device_units = {}
        self.statements = {}
        self.disputes = {}
        # Logical clock: exactly 2026-09-01T00:00:00Z before any clock call;
        # must never fall back to wall-clock time.
        self.clock = datetime(2026, 9, 1, 0, 0, 0, tzinfo=timezone.utc)
        # Monotonic ordering counter so list endpoints sort stably by
        # creation order (created_at uses wall clock and can tie).
        self.seq = 0

    def next_seq(self):
        self.seq += 1
        return self.seq

    def new_entity(self):
        """Return the base system-managed fields for a new resource."""
        ts = iso_now_wallclock()
        return {
            "id": new_id(),
            "created_at": ts,
            "updated_at": ts,
            "version": 1,
            "_seq": self.next_seq(),
        }

    def touch(self, entity):
        """Refresh updated_at and bump version on mutation."""
        entity["updated_at"] = iso_now_wallclock()
        entity["version"] = int(entity.get("version", 1)) + 1


store = Store()
