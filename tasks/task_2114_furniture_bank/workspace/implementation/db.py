"""In-memory data store.

Every collection is a plain dict keyed by id and lives only in this process:
restarting the server wipes every byte of state. Nothing is ever seeded here -
tests build all preconditions through the declared API surface.
"""

from datetime import datetime
from decimal import Decimal

from flask import g

from core import clock, new_id


class Store(object):
    def __init__(self):
        self.reset()

    def reset(self):
        self.agencies = {}
        self.clients = {}
        self.referrals = {}
        self.vouchers = {}
        self.voucher_lines = {}
        self.donation_offers = {}
        self.donation_items = {}
        self.inventory_items = {}
        self.trucks = {}
        self.delivery_runs = {}
        self.delivery_stops = {}
        self.volunteers = {}
        self.crew_assignments = {}
        self.waitlist_entries = {}
        self._seq = 0

    def next_seq(self):
        self._seq += 1
        return self._seq


db = Store()


# --------------------------------------------------------------------------
# Common resource properties (PRD 2.4)
# --------------------------------------------------------------------------
def new_entity(**fields):
    now = clock.now()
    entity = {
        "id": new_id(),
        "created_at": now,
        "updated_at": now,
        "version": 1,
        "_seq": db.next_seq(),
    }
    entity.update(fields)
    return entity


def _touched_set():
    try:
        touched = getattr(g, "_touched_entities", None)
    except RuntimeError:
        return None
    if touched is None:
        touched = set()
        g._touched_entities = touched
    return touched


def touch(entity):
    """Refresh `updated_at` and increase `version` by exactly 1.

    A row mutated several times inside one request still moves by exactly one
    version - `version` is the observable evidence that the operation touched
    the row, not a counter of individual field writes.
    """
    entity["updated_at"] = clock.now()
    touched = _touched_set()
    key = entity["id"]
    if touched is not None:
        if key in touched:
            return entity
        touched.add(key)
    entity["version"] += 1
    return entity


# --------------------------------------------------------------------------
# Serialisation
# --------------------------------------------------------------------------
def _plain(value):
    if isinstance(value, datetime):
        from core import iso
        return iso(value)
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, list):
        return [_plain(v) for v in value]
    if isinstance(value, dict):
        return dict((k, _plain(v)) for k, v in value.items())
    return value


def serialize(entity):
    out = {}
    for key, value in entity.items():
        if key.startswith("_"):
            continue
        out[key] = _plain(value)
    return out


def serialize_many(entities):
    return [serialize(e) for e in entities]


# --------------------------------------------------------------------------
# Ordering helpers - list results are sorted by created_at ascending (PRD 2.3);
# rows minted inside one request share the logical instant, so the insertion
# sequence keeps the order in which they were supplied.
# --------------------------------------------------------------------------
def creation_key(entity):
    return (entity["created_at"], entity["_seq"])


def sorted_by_creation(entities):
    return sorted(entities, key=creation_key)


# --------------------------------------------------------------------------
# Reverse-reachability helpers
# --------------------------------------------------------------------------
def lines_of_voucher(voucher_id):
    return sorted_by_creation(
        [l for l in db.voucher_lines.values() if l["voucher_id"] == voucher_id]
    )


def line_ids_of_voucher(voucher_id):
    return set(l["id"] for l in db.voucher_lines.values() if l["voucher_id"] == voucher_id)


def units_of_voucher(voucher_id, statuses=None):
    line_ids = line_ids_of_voucher(voucher_id)
    out = []
    for unit in db.inventory_items.values():
        if unit["reserved_for_voucher_line_id"] in line_ids:
            if statuses is None or unit["status"] in statuses:
                out.append(unit)
    return sorted_by_creation(out)


def units_of_line(line_id, statuses=None):
    out = []
    for unit in db.inventory_items.values():
        if unit["reserved_for_voucher_line_id"] == line_id:
            if statuses is None or unit["status"] in statuses:
                out.append(unit)
    return sorted_by_creation(out)


def items_of_offer(offer_id):
    return sorted_by_creation(
        [i for i in db.donation_items.values() if i["offer_id"] == offer_id]
    )


def stops_of_run(run_id, statuses=None):
    out = [s for s in db.delivery_stops.values() if s["run_id"] == run_id]
    if statuses is not None:
        out = [s for s in out if s["status"] in statuses]
    return sorted_by_creation(out)


def stops_of_voucher(voucher_id, statuses=None):
    out = [s for s in db.delivery_stops.values() if s["voucher_id"] == voucher_id]
    if statuses is not None:
        out = [s for s in out if s["status"] in statuses]
    return sorted_by_creation(out)


def crew_of_run(run_id, statuses=None):
    out = [c for c in db.crew_assignments.values() if c["run_id"] == run_id]
    if statuses is not None:
        out = [c for c in out if c["status"] in statuses]
    return sorted_by_creation(out)


def crew_of_volunteer(volunteer_id, statuses=None):
    out = [c for c in db.crew_assignments.values() if c["volunteer_id"] == volunteer_id]
    if statuses is not None:
        out = [c for c in out if c["status"] in statuses]
    return sorted_by_creation(out)


def waitlist_of_line(line_id, statuses=None):
    out = [w for w in db.waitlist_entries.values() if w["voucher_line_id"] == line_id]
    if statuses is not None:
        out = [w for w in out if w["status"] in statuses]
    return sorted_by_creation(out)


def waitlist_of_client(client_id, statuses=None):
    out = [w for w in db.waitlist_entries.values() if w["client_id"] == client_id]
    if statuses is not None:
        out = [w for w in out if w["status"] in statuses]
    return sorted_by_creation(out)


def voucher_of_referral(referral_id):
    for voucher in db.vouchers.values():
        if voucher["referral_id"] == referral_id:
            return voucher
    return None


def referrals_of_client(client_id, statuses=None):
    out = [r for r in db.referrals.values() if r["client_id"] == client_id]
    if statuses is not None:
        out = [r for r in out if r["status"] in statuses]
    return sorted_by_creation(out)


# --------------------------------------------------------------------------
# Chain walks: voucher -> referral -> client / agency
# --------------------------------------------------------------------------
def referral_of_voucher(voucher):
    return db.referrals.get(voucher["referral_id"])


def client_of_voucher(voucher):
    referral = referral_of_voucher(voucher)
    return db.clients.get(referral["client_id"]) if referral else None


def agency_of_voucher(voucher):
    referral = referral_of_voucher(voucher)
    return db.agencies.get(referral["agency_id"]) if referral else None


def voucher_of_line(line):
    return db.vouchers.get(line["voucher_id"])
