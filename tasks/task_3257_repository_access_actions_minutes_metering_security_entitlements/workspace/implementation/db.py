"""In-memory data store. Empty on every boot."""
import threading
from datetime import datetime, timezone, timedelta

DEFAULT_CLOCK_ISO = "2026-09-01T00:00:00Z"


class Store:
    def __init__(self):
        self.lock = threading.RLock()
        self.enterprises = {}
        self.organizations = {}
        self.users = {}
        self.commit_events = {}
        self.teams = {}
        self.memberships = {}
        self.repositories = {}
        self.collaborators = {}
        self.runners = {}
        self.workflow_runs = {}
        self.artifacts = {}
        self.entitlements = {}
        self.tokens = {}
        self.audit_events = {}
        self.app_installations = {}
        self.clock = parse_iso(DEFAULT_CLOCK_ISO)


def parse_iso(s):
    if s is None:
        raise ValueError("missing datetime")
    if not isinstance(s, str):
        raise ValueError("datetime must be string")
    t = s.strip()
    if t.endswith("Z"):
        t = t[:-1] + "+00:00"
    dt = datetime.fromisoformat(t)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def iso_out(dt):
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.") + \
        f"{dt.microsecond // 1000:03d}Z"


db = Store()
