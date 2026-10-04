"""In-memory data store (PRD: storage dies with the process; nothing is
seeded at startup), the logical clock, and shared entity helpers."""
import itertools
import uuid
from datetime import datetime, timezone

import timeutil


class Store:
    def __init__(self):
        # Entity tables: dicts keyed by id. Everything starts empty (PRD §2.5;
        # the test harness constructs all entities via the API).
        self.issuers = {}
        self.underwriters = {}
        self.engagements = {}
        self.scorecards = {}
        self.criteria_versions = {}
        self.sessions = {}
        self.votes = {}
        self.ratings = {}
        self.appeals = {}
        self.bond_sales = {}
        self.obligations = {}
        self.review_items = {}
        self.notifications = {}
        # Global insertion sequence for deterministic created_at tie-breaks.
        self.seq = itertools.count(1)
        # The single logical clock (PRD §2.4). Never falls back to wall clock.
        self.clock = timeutil.clock_start()

    def next_seq(self):
        return next(self.seq)

    def now(self):
        return self.clock

    def set_clock(self, dt):
        self.clock = dt


db = Store()


def _base_entity(has_version=True):
    """Common resource boilerplate (PRD §2.5): id (bare UUID), created_at,
    updated_at, version. CommitteeVote and IssuerNotification omit the last
    two."""
    now = db.now()
    ent = {
        "id": str(uuid.uuid4()),
        "created_at": now,
        "_seq": db.next_seq(),
    }
    if has_version:
        ent["updated_at"] = now
        ent["version"] = 1
    return ent


def new_entity(has_version=True):
    return _base_entity(has_version)


def touch(entity):
    """Refresh updated_at and bump version on every mutation (PRD §2.5)."""
    entity["updated_at"] = db.now()
    entity["version"] = entity.get("version", 0) + 1


def touch_no_version(entity):
    """Refresh updated_at without a version bump (sweep-driven rating
    withdrawal explicitly carries no version increment, PRD §3.5)."""
    entity["updated_at"] = db.now()


def notify(issuer_id, event_type, reference_id, message):
    """Append an IssuerNotification (PRD §2.11); entries are never updated."""
    ent = _base_entity(has_version=False)
    ent.update(
        issuer_id=issuer_id,
        event_type=event_type,
        reference_id=reference_id,
        message=message,
    )
    db.notifications[ent["id"]] = ent
    return ent
