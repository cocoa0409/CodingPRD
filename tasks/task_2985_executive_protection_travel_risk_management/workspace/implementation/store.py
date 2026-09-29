"""In-memory store.

Every byte of state lives in the dictionaries below and vanishes with the
process.  Nothing is seeded at import time or at startup: every row any caller
observes was created through a declared endpoint.
"""

from flask import g

from util import CLOCK_DEFAULT, new_id


class Store(object):
    def __init__(self):
        # PRD 2.5: the logical clock, initialised to its fixed startup default.
        self.clock = CLOCK_DEFAULT
        self._seq = 0
        self.executives = {}
        self.staff = {}
        self.signals = {}
        self.assessments = {}
        self.ratings = {}
        self.policies = {}
        self.trips = {}
        self.legs = {}
        self.assignments = {}
        self.vendors = {}
        self.engagements = {}
        self.incidents = {}
        self.checkins = {}

    def next_seq(self):
        self._seq += 1
        return self._seq

    def now(self):
        return self.clock


store = Store()


def audit_row(extra=None):
    """A row carrying the full audit triple (PRD 2.4)."""
    now = store.now()
    row = {
        "id": new_id(),
        "created_at": now,
        "updated_at": now,
        "version": 1,
        "_seq": store.next_seq(),
    }
    if extra:
        row.update(extra)
    return row


def event_row(extra=None):
    """An append-only event record: id and created_at only (PRD 2.4)."""
    row = {
        "id": new_id(),
        "created_at": store.now(),
        "_seq": store.next_seq(),
    }
    if extra:
        row.update(extra)
    return row


def touch(row):
    """Refresh updated_at and bump version exactly once per row per operation.

    PRD 2.4: "Whenever a rule in this document says that some entity's version
    is incremented, it means exactly one increment per mutated row per
    operation."  Event rows carry neither field and are left alone.
    """
    if row is None or "version" not in row:
        return
    row["updated_at"] = store.now()
    seen = getattr(g, "_touched_rows", None)
    if seen is None:
        seen = set()
        g._touched_rows = seen
    key = id(row)
    if key not in seen:
        seen.add(key)
        row["version"] += 1


def rating_for_country(country_code):
    for rating in store.ratings.values():
        if rating["country_code"] == country_code:
            return rating
    return None


def legs_of_trip(trip_id):
    rows = [l for l in store.legs.values() if l["trip_id"] == trip_id]
    rows.sort(key=lambda r: (r["sequence_no"], r["_seq"]))
    return rows


def assignments_of_leg(leg_id):
    rows = [a for a in store.assignments.values() if a["trip_leg_id"] == leg_id]
    rows.sort(key=lambda r: (r["created_at"], r["_seq"]))
    return rows


def assignments_of_trip(trip_id):
    leg_ids = {l["id"] for l in store.legs.values() if l["trip_id"] == trip_id}
    rows = [a for a in store.assignments.values() if a["trip_leg_id"] in leg_ids]
    rows.sort(key=lambda r: (r["created_at"], r["_seq"]))
    return rows


def engagements_of_trip(trip_id):
    leg_ids = {l["id"] for l in store.legs.values() if l["trip_id"] == trip_id}
    rows = [e for e in store.engagements.values() if e["trip_leg_id"] in leg_ids]
    rows.sort(key=lambda r: (r["created_at"], r["_seq"]))
    return rows


def engagements_of_vendor(vendor_id):
    rows = [e for e in store.engagements.values() if e["vendor_id"] == vendor_id]
    rows.sort(key=lambda r: (r["created_at"], r["_seq"]))
    return rows


def engagements_of_incident(incident_id):
    rows = [e for e in store.engagements.values() if e["incident_id"] == incident_id]
    rows.sort(key=lambda r: (r["created_at"], r["_seq"]))
    return rows


def incidents_of_trip(trip_id):
    rows = [i for i in store.incidents.values() if i["trip_id"] == trip_id]
    rows.sort(key=lambda r: (r["created_at"], r["_seq"]))
    return rows


def checkins_of_trip(trip_id):
    rows = [c for c in store.checkins.values() if c["trip_id"] == trip_id]
    rows.sort(key=lambda r: (r["created_at"], r["_seq"]))
    return rows


def signals_of_executive(executive_id):
    rows = [s for s in store.signals.values() if s["executive_id"] == executive_id]
    rows.sort(key=lambda r: (r["created_at"], r["_seq"]))
    return rows


def policies_of_executive(executive_id):
    rows = [p for p in store.policies.values() if p["executive_id"] == executive_id]
    rows.sort(key=lambda r: (r["created_at"], r["_seq"]))
    return rows


def trip_of_leg(leg):
    return store.trips.get(leg["trip_id"])


def executive_of_trip(trip):
    return store.executives.get(trip["executive_id"])
