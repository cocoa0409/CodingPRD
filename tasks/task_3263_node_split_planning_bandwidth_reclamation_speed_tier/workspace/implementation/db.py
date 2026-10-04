"""In-memory data store and logical clock. State resets on every process boot."""

import threading
import uuid
from datetime import datetime, timezone, timedelta

LOCK = threading.RLock()

# Logical clock: starts at 2026-09-01T00:00:00Z; never falls back to wall clock.
_clock_utc = datetime(2026, 9, 1, 0, 0, 0, tzinfo=timezone.utc)


def clock_now():
    return _clock_utc


def set_clock(dt):
    global _clock_utc
    _clock_utc = dt


def now_iso():
    """Wall-clock timestamp for meta/created_at/updated_at (ISO8601, 3 fractional digits, Z)."""
    dt = datetime.now(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def parse_dt(value):
    """Parse an ISO8601 datetime string into an aware datetime. Raises ValueError."""
    if not isinstance(value, str):
        raise ValueError("not a string")
    s = value.strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def new_id():
    return str(uuid.uuid4())


# Stores: dict id -> record (records are plain dicts)
franchise_areas = {}
optical_nodes = {}
spectrum_blocks = {}
service_groups = {}
utilization_samples = {}
capacity_actions = {}
node_split_projects = {}
migration_waves = {}
customer_premises = {}
customer_equipment = {}
speed_tiers = {}
provisioning_requests = {}
refresh_campaigns = {}
congestion_complaints = {}


def stamp_new(record, with_version=True):
    ts = now_iso()
    record["created_at"] = ts
    if with_version:
        record["updated_at"] = ts
        record["version"] = 1
    return record


def touch(record):
    """Mutate bookkeeping: refresh updated_at and bump version."""
    record["updated_at"] = now_iso()
    record["version"] = record.get("version", 1) + 1


def get_or_404(store, rid):
    from errors import raise_err
    rec = store.get(rid)
    if rec is None:
        raise_err("ERR_NOT_FOUND", f"Resource {rid} not found")
    return rec
