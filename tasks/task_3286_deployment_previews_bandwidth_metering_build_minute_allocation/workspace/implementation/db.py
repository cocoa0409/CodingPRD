"""In-memory store, logical clock, ids, timestamps."""

import uuid
import threading
from datetime import datetime, timezone

_store_lock = threading.RLock()


def lock():
    return _store_lock


def new_id():
    return str(uuid.uuid4())


class Store:
    def __init__(self):
        self.reset()

    def reset(self):
        self.plans = {}        # id -> plan
        self.plan_by_tier = {} # tier -> plan
        self.teams = {}
        self.members = {}
        self.projects = {}
        self.deployments = {}
        self.env_vars = {}
        self.domains = {}
        self.certificates = {}
        self.redirects = {}
        self.usage_periods = {}
        self.usage_events = {}
        self.alert_rules = {}
        self.spend_caps = {}
        self.clock = datetime(2026, 9, 1, 0, 0, 0, tzinfo=timezone.utc)


db = Store()


def now_iso():
    return format_ts(db.clock)


def format_ts(dt):
    if dt is None:
        return None
    s = dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")
    ms = dt.microsecond // 1000
    return f"{s}.{ms:03d}Z"


def parse_ts(s):
    if not isinstance(s, str):
        raise ValueError("not a string")
    t = s.strip()
    if t.endswith("Z"):
        t = t[:-1] + "+00:00"
    dt = datetime.fromisoformat(t)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def touch(entity):
    """Refresh updated_at and bump version on mutation."""
    entity["updated_at"] = now_iso()
    entity["version"] = entity.get("version", 0) + 1
