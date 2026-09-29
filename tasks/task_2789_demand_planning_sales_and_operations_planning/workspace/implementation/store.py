"""In-memory store. Starts completely empty on every boot -- nothing is seeded."""
from util import clock, new_id


class Store(object):
    COLLECTIONS = (
        "families", "items", "customers", "capacity_blocks", "promotions",
        "cycles", "forecasts", "adjustments", "supply_plans", "allocations",
        "scenarios", "accuracy_records",
    )

    def __init__(self):
        for name in self.COLLECTIONS:
            setattr(self, name, {})
        self._seq = 0

    def next_seq(self):
        self._seq += 1
        return self._seq


store = Store()


def new_row(with_common=True):
    """Fresh row skeleton: id, created_at and (unless suppressed) updated_at/version."""
    now = clock.now_iso()
    row = {"id": new_id(), "created_at": now, "_seq": store.next_seq()}
    if with_common:
        row["updated_at"] = now
        row["version"] = 1
    return row


def touch(row):
    """A mutation: refresh updated_at and bump version by exactly 1."""
    row["updated_at"] = clock.now_iso()
    row["version"] = row.get("version", 1) + 1


def ordered(rows):
    """Default list ordering: created_at ascending (creation sequence breaks ties)."""
    return sorted(rows, key=lambda r: (r["created_at"], r["_seq"]))


def public(row):
    """Serialise a row: every field except the internal underscore-prefixed keys."""
    return dict((k, v) for k, v in row.items() if not k.startswith("_"))


def public_all(rows):
    return [public(r) for r in rows]
