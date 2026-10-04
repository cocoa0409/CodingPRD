"""In-memory data store, logical clock, and entity base-field helpers.

The store starts empty on every boot — no seeding, no disk persistence. The
harness re-launches the server per test, so module-level state is per-test."""

import threading
from uuid import uuid4

from constants import CONSTANTS
from util import fmt_iso, parse_iso

LOCK = threading.RLock()


class Store:
    def __init__(self):
        self.seasons = {}
        self.categories = {}
        self.concepts = {}
        self.rounds = {}
        self.partners = {}
        self.variants = {}
        self.studies = {}
        self.media_tests = {}
        self.agreements = {}
        self.commitments = {}
        self.replenishments = {}
        self.cases = {}
        self.seq = 0
        # Logical clock: exactly CLOCK_DEFAULT_ISO until POST /_clock/set_current_utc.
        self.clock = parse_iso(CONSTANTS["CLOCK_DEFAULT_ISO"])


DB = Store()


def now():
    return DB.clock


def next_seq():
    DB.seq += 1
    return DB.seq


def touch(entity):
    entity["updated_at"] = fmt_iso(now())


def bump(entity):
    """Optimistic-concurrency/mutation counter: +1 exactly where the scaffold's
    endpoint side_effects say 'increments <Entity>.version by 1'."""
    entity["version"] += 1
    touch(entity)


def base_fields():
    ts = fmt_iso(now())
    return {
        "id": str(uuid4()),
        "created_at": ts,
        "created_dt": now(),
        "updated_at": ts,
        "version": 1,
        "seq": next_seq(),
    }
