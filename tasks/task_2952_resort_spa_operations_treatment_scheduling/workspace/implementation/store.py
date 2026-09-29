"""In-memory data store and the logical clock (PRD §2.4).

Storage is plain Python dicts held in a module-level singleton. Nothing is
persisted and nothing is seeded: a fresh process starts completely empty and the
logical clock reads exactly 2026-08-01T00:00:00Z until it is driven forward.
"""

import uuid
from datetime import datetime, timezone

CLOCK_EPOCH = datetime(2026, 8, 1, 0, 0, 0, 0, tzinfo=timezone.utc)


class Store(object):
    def __init__(self):
        self.reset()

    def reset(self):
        self.clock = CLOCK_EPOCH
        self._seq = 0
        self.treatment_types = {}
        self.rooms = {}
        self.therapists = {}
        self.licenses = {}
        self.ce_records = {}
        self.certifications = {}
        self.shift_blocks = {}
        self.guests = {}
        self.intake_forms = {}
        self.appointments = {}
        self.retail_attachments = {}
        self.settlements = {}
        self.folio_charges = {}

    def next_seq(self):
        self._seq += 1
        return self._seq


db = Store()


def new_id():
    return str(uuid.uuid4())


def now():
    return db.clock


def stamp_common(entity, versioned=True):
    """Attach id/created_at (+updated_at/version) using the logical clock."""
    entity["id"] = new_id()
    entity["_seq"] = db.next_seq()
    entity["created_at"] = db.clock
    if versioned:
        entity["updated_at"] = db.clock
        entity["version"] = 1
    return entity


def touch(entity):
    """Register a mutation: refresh updated_at and increment version by one."""
    entity["updated_at"] = db.clock
    entity["version"] = entity.get("version", 1) + 1
    return entity


def by_created(rows):
    return sorted(rows, key=lambda r: (r["created_at"], r["_seq"]))


def by_created_desc(rows):
    return sorted(rows, key=lambda r: (r["created_at"], r["_seq"]), reverse=True)
