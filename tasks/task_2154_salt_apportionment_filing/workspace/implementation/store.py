"""In-memory data store and the server's logical compliance clock.

The store starts completely empty on every boot: no entity is ever seeded,
preloaded or hardcoded here.  Tests construct every precondition through the
declared API surface.
"""
import itertools
import threading
import uuid
from datetime import datetime, timezone

# Section 2.5 - before the clock has ever been set it reads exactly this instant
# and it never falls back to wall-clock time.
DEFAULT_CLOCK_UTC = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)

LOCK = threading.RLock()


class Store(object):
    def __init__(self):
        self.reset()

    def reset(self):
        self.groups = {}
        self.legal_entities = {}
        self.registrations = {}
        self.activity_records = {}
        self.elections = {}
        self.filings = {}
        self.factors = {}
        self.modifications = {}
        self.credit_claims = {}
        self.payments = {}
        self.extensions = {}
        self.notices = {}
        self.vdas = {}
        self.clock = DEFAULT_CLOCK_UTC
        self._counter = itertools.count(1)

    def next_seq(self):
        return next(self._counter)


db = Store()


def new_id():
    return str(uuid.uuid4())


def now_wall():
    return datetime.now(timezone.utc)
