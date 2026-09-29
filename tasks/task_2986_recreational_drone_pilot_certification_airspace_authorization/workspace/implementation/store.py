"""In-memory store.  Starts completely empty on every boot -- no seeding."""

import itertools
import uuid

from clockmod import clock

COLLECTIONS = (
    "pilots",
    "knowledge_tests",
    "certifications",
    "aircraft",
    "modules",
    "zones",
    "tfrs",
    "authorizations",
    "waivers",
    "safety_cases",
    "policies",
    "flights",
    "preflight_checks",
    "reports",
)


class Store:
    def __init__(self):
        self.data = {name: {} for name in COLLECTIONS}
        self._seq = itertools.count(1)
        self._certificate_seq = itertools.count(1)
        self._registration_seq = itertools.count(1)

    # -- creation -----------------------------------------------------------
    def insert(self, collection, fields, versioned=True):
        row = dict(fields)
        row["id"] = str(uuid.uuid4())
        row["created_at"] = clock.now()
        if versioned:
            row["updated_at"] = clock.now()
            row["version"] = 1
        row["_seq"] = next(self._seq)
        row["_kind"] = collection
        self.data[collection][row["id"]] = row
        return row

    def get(self, collection, row_id):
        if not isinstance(row_id, str):
            return None
        return self.data[collection].get(row_id)

    def all(self, collection):
        """Every row of a collection in created_at ascending order."""
        return sorted(self.data[collection].values(), key=order_key)

    def next_certificate_number(self):
        return "CERT-%06d" % next(self._certificate_seq)

    def next_registration_number(self):
        return "FA%08d" % next(self._registration_seq)


def order_key(row):
    return (row["created_at"], row["_seq"])


def touch(row):
    """Record a mutation of a row: bump updated_at and version (PRD 2.5)."""
    row["updated_at"] = clock.now()
    row["version"] = row["version"] + 1
    return row


store = Store()
