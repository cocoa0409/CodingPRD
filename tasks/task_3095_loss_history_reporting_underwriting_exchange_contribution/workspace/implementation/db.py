"""In-memory data store. Starts empty on every boot — no seeding."""
import uuid
from datetime import datetime, timezone

from util import parse_iso, DEFAULT_CLOCK


class Store:
    def __init__(self):
        self.clock = parse_iso(DEFAULT_CLOCK)
        self.seq = 0  # global monotonic insertion counter
        self.carriers = {}
        self.consumers = {}
        self.batches = {}
        self.claims = {}
        self.inquiries = {}
        self.reports = {}
        self.entries = {}
        self.disputes = {}
        self.notices = {}
        self.audit_events = {}
        self.exchange_rule = None  # singleton dict or None

    def next_seq(self):
        self.seq += 1
        return self.seq

    def new_id(self):
        return str(uuid.uuid4())

    def now(self):
        return self.clock

    def set_clock(self, dt):
        self.clock = dt


db = Store()
