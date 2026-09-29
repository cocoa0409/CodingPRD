"""In-memory data store.

Storage is process-local Python dicts keyed by id. The store starts EMPTY on
every boot: no entity is ever seeded, preloaded or hardcoded. Tests build every
precondition through the declared API surface.
"""

import itertools
import uuid
from datetime import datetime

import clock

CARRIERS = {}
APPLICATIONS = {}
AUTHORITIES = {}
PROCESS_AGENTS = {}
DESIGNATIONS = {}
INSURERS = {}
FILINGS = {}
PROCEEDINGS = {}
AUDITS = {}
CONTRACTS = {}
SHIPMENTS = {}
LEDGER = {}

_seq = itertools.count(1)
_usdot_seq = itertools.count(1)
_docket_seq = itertools.count(1)


def new_id():
    return str(uuid.uuid4())


def next_usdot():
    return "USDOT-%07d" % next(_usdot_seq)


def next_docket():
    return "MC-%06d" % next(_docket_seq)


def base_record(mutable=True):
    """The system-managed common field set (PRD section 2.4)."""
    created = clock.now()
    rec = {"id": new_id(), "created_at": created}
    if mutable:
        rec["updated_at"] = created
        rec["version"] = 1
    return rec


def insert(collection, rec):
    rec["_seq"] = next(_seq)
    collection[rec["id"]] = rec
    return rec


def touch(rec):
    """A mutation -- refresh updated_at and increment version."""
    rec["updated_at"] = clock.now()
    rec["version"] = rec.get("version", 1) + 1
    return rec


def _sort_key(rec):
    return (rec["created_at"], rec["_seq"])


def ordered(records):
    """Every ordered walk in this system is created_at ascending."""
    return sorted(records, key=_sort_key)


def all_of(collection):
    return ordered(collection.values())


def where(collection, **filters):
    out = []
    for rec in collection.values():
        if all(rec.get(k) == v for k, v in filters.items()):
            out.append(rec)
    return ordered(out)


# ---------------------------------------------------------------- projections

def contracts_of_authority(authority_id):
    return where(CONTRACTS, authority_id=authority_id)


def shipments_of_contract(contract_id):
    return where(SHIPMENTS, contract_id=contract_id)


def designations_of_authority(authority_id):
    return where(DESIGNATIONS, authority_id=authority_id)


def filings_of_authority(authority_id):
    return where(FILINGS, authority_id=authority_id)


def proceedings_of_authority(authority_id):
    return where(PROCEEDINGS, authority_id=authority_id)


def authorities_of_carrier(carrier_id):
    return where(AUTHORITIES, carrier_id=carrier_id)


def audits_of_carrier(carrier_id):
    return where(AUDITS, carrier_id=carrier_id)


def ledger_of_carrier(carrier_id):
    return where(LEDGER, carrier_id=carrier_id)


# --------------------------------------------------------------- serialisation

_HIDDEN = ("_seq",)


def serialize(rec):
    out = {}
    for key, value in rec.items():
        if key in _HIDDEN:
            continue
        if isinstance(value, datetime):
            out[key] = clock.fmt(value)
        elif isinstance(value, list):
            out[key] = list(value)
        elif isinstance(value, dict):
            out[key] = dict(value)
        else:
            out[key] = value
    return out


def serialize_all(records):
    return [serialize(r) for r in records]
