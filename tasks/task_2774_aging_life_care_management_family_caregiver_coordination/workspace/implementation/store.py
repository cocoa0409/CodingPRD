"""In-memory data store.  Nothing is seeded: the store starts empty on every
boot and every record is created through the declared API surface."""
import uuid

import clock


class Store:
    def __init__(self):
        self.clients = {}
        self.care_managers = {}
        self.vendors = {}
        self.contacts = {}
        self.assessments = {}
        self.care_plans = {}
        self.authorizations = {}
        self.conferences = {}
        self.decisions = {}
        self.episodes = {}
        self.time_entries = {}
        self.invoices = {}
        self.deposits = []
        self._seq = 0

    def next_seq(self):
        self._seq += 1
        return self._seq


db = Store()


def new_id():
    return str(uuid.uuid4())


def new_record(fields):
    """Create a record carrying the four housekeeping properties."""
    ts = clock.now()
    rec = {
        "id": new_id(),
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
        "_seq": db.next_seq(),
    }
    rec.update(fields)
    return rec


def touch(rec):
    """Register a mutation: refresh updated_at and advance version by one."""
    rec["updated_at"] = clock.now()
    rec["version"] = rec["version"] + 1
    return rec


def ordered(records, descending=False):
    """Collections are returned in ascending created_at order (oldest first);
    the client roster is the one deliberate exception and is newest first."""
    if descending:
        return sorted(records, key=lambda r: (r["created_at"], r["_seq"]),
                      reverse=True)
    return sorted(records, key=lambda r: (r["created_at"], r["_seq"]))


def rank_desc(records, key):
    """Rank by `key` descending with ties broken by created_at ascending
    (never by id)."""
    items = sorted(records, key=lambda r: (r["created_at"], r["_seq"]))
    return sorted(items, key=lambda r: r[key], reverse=True)
