"""In-memory data store and the logical clock.

Storage is dicts keyed by id. The store starts empty on every boot — no
seeding. The logical clock defaults to exactly 2026-09-01T00:00:00Z and is
moved only by POST /_clock/set_current_utc; it never falls back to wall time.
All resource timestamps (created_at / updated_at) and the meta request
timestamp are taken from this logical clock so that storage-decay math and
delivery-window checks are deterministic.
"""

from constants import DEFAULT_CLOCK_ISO
from util import parse_dt


class Store:
    def __init__(self):
        self.growers = {}
        self.contracts = {}
        self.lots = {}
        self.facilities = {}
        self.lines = {}
        self.specs = {}
        self.chains = {}
        self.agreements = {}
        self.runs = {}
        self.batches = {}
        self.shipments = {}
        self.shortage_events = {}
        self.seq = 0
        self.clock = parse_dt(DEFAULT_CLOCK_ISO)


store = Store()


def next_seq():
    store.seq += 1
    return store.seq


def clock_now():
    return store.clock


def set_clock(dt):
    store.clock = dt
