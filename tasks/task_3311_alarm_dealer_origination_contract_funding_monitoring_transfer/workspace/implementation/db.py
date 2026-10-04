"""In-memory data store. Python dicts keyed by id, wiped on every boot.

The store starts EMPTY. Nothing here seeds, preloads or hardcodes entity data:
every row a test needs is created through a declared endpoint.
"""

from datetime import timezone

from util import LOGICAL_CLOCK_START, parse_ts

# PRD §2.4 — the logical clock is fixed at boot and never falls back to real time.
START_INSTANT = parse_ts(LOGICAL_CLOCK_START)


class Store(object):
    def __init__(self):
        self.reset()

    def reset(self):
        self.dealers = {}
        self.dealer_packages = {}
        self.contracts = {}
        self.customers = {}
        self.sites = {}
        self.installations = {}
        self.monitoring_accounts = {}
        self.alarm_events = {}
        self.dispatch_requests = {}
        self.alarm_reduction_actions = {}
        self.attrition_sweeps = {}
        self.attrition_flags = {}
        self.service_visits = {}
        self.contract_owners = {}
        self.assumption_requests = {}
        self.rescission_requests = {}
        self.clock = START_INSTANT

    # --- generic accessors -------------------------------------------------
    def table(self, name):
        return getattr(self, name)

    def insert(self, name, row):
        self.table(name)[row["id"]] = row
        return row

    def get(self, name, row_id):
        if row_id is None:
            return None
        return self.table(name).get(row_id)

    def all(self, name):
        return list(self.table(name).values())


state = Store()


def now():
    """The current logical instant."""
    return state.clock


def set_clock(dt):
    state.clock = dt.astimezone(timezone.utc)


def bump(row, moments=1):
    """PRD §2.5 — any write that mutates a row advances that row's version."""
    row["version"] = row.get("version", 1) + moments
    row["updated_at"] = now()


def touch(row):
    """Refresh updated_at only (no version bump)."""
    row["updated_at"] = now()