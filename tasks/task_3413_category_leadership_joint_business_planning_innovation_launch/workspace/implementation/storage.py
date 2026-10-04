"""In-memory stores, id/sequence issuance, and common-field stamping.

The store starts empty on every boot; every entity is created via API calls.
Records are plain dicts; keys prefixed with "_" are internal (parsed
datetimes, creation sequence) and are stripped from API output.
"""

import itertools
import uuid

import clock
from timeutil import fmt_stamp

STORE = {
    "retailers": {},
    "categories": {},
    "plans": {},
    "events": {},
    "analyses": {},
    "shelf_recs": {},
    "launches": {},
    "phases": {},
    "funds": {},
    "deductions": {},
    "forecasts": {},
    "ppds": {},
    "reviews": {},
}

_seq = itertools.count(1)


def new_id():
    return str(uuid.uuid4())


def stamp_new(record):
    """Populate common system fields on a freshly created record (PRD §2.5)."""
    record["created_at"] = fmt_stamp(clock.now())
    record["updated_at"] = record["created_at"]
    record["version"] = 1
    record["_created_logical"] = clock.now()
    record["_seq"] = next(_seq)
    return record


def touch(record):
    """Register one mutation: version += 1 and updated_at refreshed."""
    record["version"] += 1
    record["updated_at"] = fmt_stamp(clock.now())
    return record


def public(record):
    """The API-facing view: every non-internal field."""
    return {k: v for k, v in record.items() if not k.startswith("_")}


def by_seq(records):
    """List order: creation timestamp ascending; the sequence breaks ties in
    creation order when several records share one logical instant."""
    return sorted(records, key=lambda r: r["_seq"])
