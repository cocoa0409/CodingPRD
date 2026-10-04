"""In-memory data store.

Every byte of state lives in process memory, keyed by id.  Nothing is written
to disk and nothing is seeded: the store starts empty on every boot, and every
entity a caller observes was created through a declared endpoint.
"""

import uuid

from clock import Clock, fmt_dt, parse_dt


def new_id():
    return str(uuid.uuid4())


COLLECTIONS = (
    "employer_accounts",
    "bundle_entitlements",
    "care_advocates",
    "members",
    "clinics",
    "clinic_contracts",
    "treatment_plans",
    "preauthorizations",
    "treatment_cycles",
    "medication_orders",
    "pathway_requests",
    "claims",
    "outcome_records",
    "surrender_routes",
)


class Store:
    """All entity tables plus the logical clock."""

    def __init__(self):
        for name in COLLECTIONS:
            setattr(self, name, {})
        self.clock = Clock()

    # -- common fields ----------------------------------------------------
    def common(self):
        return {
            "id": new_id(),
            "created_at": fmt_dt(self.clock.now),
            "updated_at": fmt_dt(self.clock.now),
            "version": 1,
        }

    def touch(self, row):
        """Advance version and updated_at when at least one field changed."""
        row["version"] = row.get("version", 1) + 1
        row["updated_at"] = fmt_dt(self.clock.now)

    # -- generic access ---------------------------------------------------
    def find(self, collection, row_id):
        return getattr(self, collection).get(row_id)

    def all(self, collection):
        return list(getattr(self, collection).values())

    def now(self):
        return self.clock.now

    def created_key(self, row):
        dt = parse_dt(row.get("created_at"))
        return dt if dt is not None else self.clock.now

    def sorted_by_created(self, rows):
        """Ascending created_at, with insertion-stable tie-breaking."""
        return sorted(rows, key=lambda r: (self.created_key(r), r.get("id", "")))

    def add(self, row):
        collection = row["_collection"]
        getattr(self, collection)[row["id"]] = row
        return row


# Process-global store.  A fresh process starts it empty.
db = Store()


def reset_store():
    """Re-create the store with no entities (used when the module is reloaded)."""
    global db
    db = Store()
    return db