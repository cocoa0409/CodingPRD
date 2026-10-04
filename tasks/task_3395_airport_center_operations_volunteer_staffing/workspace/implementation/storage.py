"""In-memory data store and the single logical clock.

No seeding: every collection starts empty; the clock starts at the PRD
default (2026-09-01T00:00:00Z) and only moves via POST /_clock/set_current_utc.
"""

import threading
from datetime import datetime, timezone

from constants import CLOCK_DEFAULT_UTC


def _parse_initial_clock():
    return datetime(2026, 9, 1, 0, 0, 0, tzinfo=timezone.utc)


class Store:
    def __init__(self):
        self.centers = {}
        self.agreements = {}
        self.volunteers = {}
        self.screenings = {}
        self.shifts = {}
        self.assignments = {}
        self.guests = {}
        self.checkins = {}
        self.bookings = {}
        self.lots = {}
        self.events = {}
        self.grants = {}
        self.seq = 0
        self.lock = threading.RLock()
        self.clock = _parse_initial_clock()

    def now(self):
        """Current logical clock time (timezone-aware UTC)."""
        return self.clock

    def set_clock(self, dt):
        self.clock = dt

    def next_seq(self):
        self.seq += 1
        return self.seq


STORE = Store()
