"""In-memory store and logical clock. No seeding: all dicts start empty."""
import itertools
import uuid
from datetime import datetime, timezone

LOGICAL_CLOCK_DEFAULT_UTC = datetime(2026, 9, 1, 0, 0, 0, tzinfo=timezone.utc)


class Store:
    def __init__(self):
        self.contracts = {}
        self.programs = {}
        self.retailers = {}
        self.items = {}
        self.cases = {}
        self.purses = {}
        self.entries = {}
        self.postings = {}
        self.cards = {}
        self.txns = {}
        self.claims = {}
        self.batches = {}
        self.disputes = {}
        self.deliveries = {}
        self.seq = itertools.count(1)


DB = Store()

_clock = {"now": LOGICAL_CLOCK_DEFAULT_UTC}


def clock_now():
    return _clock["now"]


def clock_set(dt):
    _clock["now"] = dt


def new_id():
    return str(uuid.uuid4())


def next_seq():
    return next(DB.seq)
