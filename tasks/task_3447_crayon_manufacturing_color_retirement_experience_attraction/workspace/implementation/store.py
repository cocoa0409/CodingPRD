"""In-memory store and logical clock.

The store starts EMPTY on every boot (per-test-server isolation wipes the
process). No seeding. All entities are plain dicts; internal bookkeeping fields
are prefixed with "_" and stripped by serializers.
"""
from datetime import datetime, timezone

from constants import CLOCK_START


def parse_dt(value):
    """Parse an ISO-8601 string into an aware UTC datetime. Raises ValueError."""
    if not isinstance(value, str):
        raise ValueError("not a string")
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    dt = datetime.fromisoformat(text)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def fmt_dt(dt, with_millis=True):
    """Format an aware datetime as ISO-8601 UTC."""
    if with_millis:
        return dt.isoformat(timespec="milliseconds").replace("+00:00", "Z")
    return dt.isoformat(timespec="seconds").replace("+00:00", "Z")


def fmt_like(dt, sample):
    """Format dt matching the fractional-seconds style of the sample string."""
    return fmt_dt(dt, with_millis=("." in sample))


class Store:
    def __init__(self):
        # Entity tables keyed by id.
        self.colors = {}
        self.batches = {}
        self.formulas = {}
        self.campaigns = {}
        self.safety_tests = {}
        self.specs = {}
        self.runs = {}
        self.lots = {}
        self.allocations = {}
        self.lines = {}
        self.sessions = {}
        self.tickets = {}
        self.recall_cases = {}
        # Monotonic sequences.
        self.global_seq = 0          # universal creation-order tie-breaker
        self.run_seq = 0             # global per ProductionRun
        self.epoch_index = 0
        self.test_seq = {}           # formula_id -> last test_seq
        self.lot_seq = {}            # spec_id -> last lot_seq
        self.request_seq = {}        # spec_id -> last request_seq
        self.waitlist_seq = {}       # session_id -> last waitlist_seq
        # Logical clock: boots at exactly CLOCK_START, never wall clock.
        self.clock_raw = CLOCK_START
        self.clock_dt = parse_dt(CLOCK_START)

    def next_global(self):
        self.global_seq += 1
        return self.global_seq

    def next_run_seq(self):
        self.run_seq += 1
        return self.run_seq

    def next_scoped(self, table, key):
        table[key] = table.get(key, 0) + 1
        return table[key]

    def now_ts(self):
        """Entity timestamp (always three fractional digits, logical clock)."""
        return fmt_dt(self.clock_dt, with_millis=True)

    def set_clock(self, raw):
        self.clock_raw = raw
        self.clock_dt = parse_dt(raw)


STORE = Store()
