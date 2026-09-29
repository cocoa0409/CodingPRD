"""Path resolution, ownership and list-response helpers (PRD 2.8 rungs 3-5, 2.9)."""

import envelope
import store
from errors import ApiError
from validation import filter_arg, paginate


# ---- rung 3: path existence, resolved strictly left to right (PRD 2.9)

def need_carrier(carrier_id):
    rec = store.CARRIERS.get(carrier_id)
    if rec is None:
        raise ApiError("ERR_CARRIER_NOT_FOUND")
    return rec


def need_application(application_id):
    rec = store.APPLICATIONS.get(application_id)
    if rec is None:
        raise ApiError("ERR_APPLICATION_NOT_FOUND")
    return rec


def need_authority(authority_id):
    rec = store.AUTHORITIES.get(authority_id)
    if rec is None:
        raise ApiError("ERR_AUTHORITY_NOT_FOUND")
    return rec


def need_filing(filing_id):
    rec = store.FILINGS.get(filing_id)
    if rec is None:
        raise ApiError("ERR_FILING_NOT_FOUND")
    return rec


def need_ref(collection, record_id):
    rec = collection.get(record_id)
    if rec is None:
        raise ApiError("ERR_REFERENCE_NOT_FOUND")
    return rec


def resolve_body_ref(collection, value):
    """Rung 6: a foreign key supplied in the body must resolve."""
    rec = collection.get(value) if isinstance(value, str) else None
    if rec is None:
        raise ApiError("ERR_REFERENCE_NOT_FOUND")
    return rec


# ---- rung 4: carrier ownership

def require_carrier_owner(role, user_id, carrier_id):
    if role != "CarrierRep":
        return
    if carrier_id is None or user_id != carrier_id:
        raise ApiError("ERR_NOT_CARRIER_OWNER")


# ---- rung 5: insurer identity

def require_filing_party(role, user_id, insurer_id):
    if role != "InsuranceFiler":
        return
    if insurer_id is None or user_id != insurer_id:
        raise ApiError("ERR_INSURER_NOT_FILING_PARTY")


# ---- list responses

def listing(records, filters=None):
    """Apply exact-match query filters, then paginate, then serialise."""
    rows = records
    if filters:
        for field, param in filters.items():
            raw = filter_arg(param)
            if raw is None:
                continue
            rows = [r for r in rows if str(r.get(field)) == raw]
    window, meta = paginate(rows)
    return envelope.array(store.serialize_all(window), meta)


def one(record, status=200):
    return envelope.obj(store.serialize(record), status)
