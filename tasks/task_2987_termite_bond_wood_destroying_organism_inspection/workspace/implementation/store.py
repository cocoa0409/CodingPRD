"""In-memory data store.

Plain dicts keyed by id.  Nothing is persisted anywhere and NOTHING is seeded:
a fresh process starts completely empty and every row is built by the declared
API surface.
"""

import uuid

from clock import clock


class Store(object):
    def __init__(self):
        self.properties = {}
        self.inspectors = {}
        self.inspections = {}
        self.findings = {}
        self.plans = {}
        self.records = {}
        self.bonds = {}
        self.renewals = {}
        self.reports = {}
        self.stations = {}
        self.services = {}
        self.claims = {}
        self._seq = 0

    def next_seq(self):
        self._seq += 1
        return self._seq


db = Store()


def new_id():
    return str(uuid.uuid4())


def new_row(fields, versioned=True):
    """Build a row with the system-managed common fields of PRD 2.4."""
    now = clock.now()
    row = {"id": new_id(), "created_at": now, "_seq": db.next_seq()}
    if versioned:
        row["updated_at"] = now
        row["version"] = 1
    row.update(fields)
    return row


def touch(row):
    """Register a mutation: updated_at advances, version rises by exactly 1."""
    row["updated_at"] = clock.now()
    row["version"] = row.get("version", 1) + 1
    return row


def by_created(rows):
    """Ascending created_at order with sequence_no-style total tie-break."""
    return sorted(rows, key=lambda r: (r["created_at"], r["_seq"]))


def by_seq(rows):
    """Creation order for the three immutable record types."""
    return sorted(rows, key=lambda r: r["_seq"])


# --- typed collection lookups ---------------------------------------------

def findings_of(inspection_id):
    return by_seq([f for f in db.findings.values() if f["inspection_id"] == inspection_id])


def records_of(plan_id):
    return by_seq([r for r in db.records.values() if r["treatment_plan_id"] == plan_id])


def services_of(station_id):
    return by_seq([s for s in db.services.values() if s["bait_station_id"] == station_id])


def stations_of(plan_id):
    return sorted([s for s in db.stations.values() if s["treatment_plan_id"] == plan_id],
                  key=lambda s: s["station_index"])


def inspections_of(property_id):
    return by_created([i for i in db.inspections.values() if i["property_id"] == property_id])


def plans_of(property_id):
    return by_created([p for p in db.plans.values() if p["property_id"] == property_id])


def bonds_of(property_id):
    return by_created([b for b in db.bonds.values() if b["property_id"] == property_id])


def renewals_of(bond_id):
    return by_created([r for r in db.renewals.values() if r["bond_id"] == bond_id])


def reports_of(inspection_id):
    return by_created([r for r in db.reports.values() if r["inspection_id"] == inspection_id])


def claims_of(bond_id):
    return by_created([c for c in db.claims.values() if c["bond_id"] == bond_id])
