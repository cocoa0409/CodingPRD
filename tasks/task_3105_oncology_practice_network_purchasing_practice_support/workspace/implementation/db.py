"""In-memory data store.

Storage is process-local dicts keyed by id. Nothing is persisted: the store
starts empty on every boot and the implementation never seeds an entity.
"""

from utils import fmt_ts, new_id, utc_now_dt

COLLECTIONS = (
    "networks",
    "practices",
    "providers",
    "drug_products",
    "pricing_agreements",
    "purchase_orders",
    "inventory_lots",
    "lot_consumptions",
    "treatments",
    "claims",
    "rebate_programs",
    "rebate_qualifications",
    "pathway_protocols",
    "management_agreements",
    "research_participations",
    "drug_shortages",
    "shortage_allocations",
    "affiliation_contracts",
    "idempotency",
)

_DATA = {}
_SEQ = [0]


def reset():
    _DATA.clear()
    for name in COLLECTIONS:
        _DATA[name] = {}
    _SEQ[0] = 0


reset()


def next_seq():
    _SEQ[0] += 1
    return _SEQ[0]


def create(collection, fields, created_at=None):
    """Create a record with the common system-managed fields."""
    now = created_at or utc_now_dt()
    rec = dict(fields)
    rec["id"] = new_id()
    rec["created_at"] = fmt_ts(now)
    rec["updated_at"] = rec["created_at"]
    rec["version"] = 1
    rec["_seq"] = next_seq()
    _DATA[collection][rec["id"]] = rec
    return rec


def touch(rec):
    """Mark a mutation: refresh updated_at and advance version."""
    rec["updated_at"] = fmt_ts(utc_now_dt())
    rec["version"] = rec.get("version", 1) + 1
    return rec


def get(collection, rec_id):
    if rec_id is None:
        return None
    return _DATA[collection].get(rec_id)


def all_records(collection):
    return list(_DATA[collection].values())


def where(collection, **criteria):
    out = []
    for rec in _DATA[collection].values():
        ok = True
        for key, want in criteria.items():
            if rec.get(key) != want:
                ok = False
                break
        if ok:
            out.append(rec)
    return out


def creation_order(records):
    """Order by creation timestamp ascending, ties by creation sequence."""
    return sorted(records, key=lambda r: (r.get("created_at") or "", r.get("_seq", 0)))


def public(rec):
    """Serialization view. Private bookkeeping keys (leading underscore) never
    leave the process."""
    if rec is None:
        return None
    return {k: v for k, v in rec.items() if not k.startswith("_")}


def set_idempotent(key, record):
    _DATA["idempotency"][key] = record


def get_idempotent(key):
    return _DATA["idempotency"].get(key)