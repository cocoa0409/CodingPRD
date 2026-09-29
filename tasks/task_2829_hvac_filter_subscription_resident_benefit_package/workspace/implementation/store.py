"""In-memory store. Starts completely empty on every boot: no seeding, no
preloading, no persistence of any kind."""
import uuid

import clock


class Store:
    def __init__(self):
        self.properties = {}
        self.units = {}
        self.skus = {}
        self.residents = {}
        self.subscriptions = {}
        self.shipments = {}
        self.readings = {}
        self.surveys = {}
        self.cases = {}
        self.claims = {}
        self.entitlements = {}
        self.ledger = {}
        self.transfers = {}
        self._seq = 0

    def next_seq(self):
        self._seq += 1
        return self._seq


db = Store()


def new_id():
    return str(uuid.uuid4())


def base_record(with_version=True):
    """Common auditing fields (PRD 2.4). `_seq` is an internal, never-serialized
    insertion ordinal used as the final deterministic tie-break, because the
    logical clock does not advance on its own and many rows therefore share the
    same created_at value."""
    rec = {"id": new_id()}
    rec["_seq"] = db.next_seq()
    rec["created_at"] = clock.now_iso()
    if with_version:
        rec["updated_at"] = rec["created_at"]
        rec["version"] = 1
    return rec


def touch(rec):
    """Every mutation refreshes updated_at and increments version by exactly 1."""
    rec["updated_at"] = clock.now_iso()
    rec["version"] = rec["version"] + 1


def sorted_rows(rows):
    """List order: created_at ascending, then insertion order."""
    return sorted(rows, key=lambda r: (r["created_at"], r["_seq"]))


def public(rec, extra=None):
    out = {k: v for k, v in rec.items() if not k.startswith("_")}
    if extra:
        out.update(extra)
    return out
