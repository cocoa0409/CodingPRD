"""In-memory data store.

The store starts empty on every boot: nothing is seeded, preloaded or
hardcoded. Every record any client needs is built through the declared API.
"""
import itertools
import uuid

from flask import g

import clock

_seq = itertools.count(1)

COLLECTIONS = (
    "desk_policies",
    "approval_tiers",
    "products",
    "volume_tiers",
    "bundle_rules",
    "accounts",
    "quotes",
    "quote_lines",
    "nonstandard_terms",
    "competitive_exceptions",
    "revrec_assessments",
    "approval_requests",
    "approval_steps",
    "delegation_grants",
    "order_forms",
)

store = {name: {} for name in COLLECTIONS}


def reset():
    for name in COLLECTIONS:
        store[name] = {}
    clock.reset()


def new_id():
    return str(uuid.uuid4())


def next_seq():
    return next(_seq)


def insert(collection, record, versioned=True):
    """Insert a record, minting id/created_at (and updated_at/version)."""
    record["id"] = record.get("id") or new_id()
    created_at = clock.now()
    record["created_at"] = created_at
    if versioned:
        record["updated_at"] = created_at
        record["version"] = 1
    record["_seq"] = next_seq()
    store[collection][record["id"]] = record
    return record


def get(collection, record_id):
    if not isinstance(record_id, str):
        return None
    return store[collection].get(record_id)


def all_records(collection):
    return list(store[collection].values())


def sort_key(record):
    """created_at ASC with insertion order as the deterministic tie-break."""
    return (record["created_at"], record["_seq"])


def sorted_records(records):
    return sorted(records, key=sort_key)


def mark_fresh(record):
    """Exempt a record created in this request from a same-request bump.

    A freshly created record carries version 1; the repricing that runs in the
    same request must not carry it to 2.
    """
    try:
        touched = g._touched_records
    except (AttributeError, RuntimeError):
        touched = None
    if touched is None:
        touched = set()
        try:
            g._touched_records = touched
        except RuntimeError:
            return record
    touched.add(record["id"])
    return record


def touch(record):
    """Refresh updated_at and increment version (PRD 2.4 / 2.8).

    A record mutated more than once while serving a single HTTP request is
    counted once: every explicit statement in the PRD describes a write as
    incrementing the counter "by one".
    """
    record["updated_at"] = clock.now()
    if "version" not in record:
        return record
    try:
        touched = g._touched_records
    except (AttributeError, RuntimeError):
        touched = None
    if touched is None:
        touched = set()
        try:
            g._touched_records = touched
        except RuntimeError:
            pass
    key = record["id"]
    if key not in touched:
        record["version"] = record.get("version", 0) + 1
        touched.add(key)
    return record


# ---- typed accessors -------------------------------------------------------

def policy(record_id):
    return get("desk_policies", record_id)


def product(record_id):
    return get("products", record_id)


def account(record_id):
    return get("accounts", record_id)


def quote(record_id):
    return get("quotes", record_id)


def tiers_of_policy(policy_id):
    rows = [r for r in all_records("approval_tiers") if r["desk_policy_id"] == policy_id]
    return sorted(rows, key=lambda r: (r["tier_level"], r["_seq"]))


def tier_at_level(policy_id, level):
    for row in tiers_of_policy(policy_id):
        if row["tier_level"] == level:
            return row
    return None


def bands_of_product(product_id):
    rows = [r for r in all_records("volume_tiers") if r["product_id"] == product_id]
    return sorted(rows, key=lambda r: (r["min_quantity"], r["_seq"]))


def bundle_rules_attached_to(product_id):
    rows = [r for r in all_records("bundle_rules") if r["attached_product_id"] == product_id]
    return sorted_records(rows)


def lines_of_quote(quote_id):
    rows = [r for r in all_records("quote_lines") if r["quote_id"] == quote_id]
    return sorted_records(rows)


def terms_of_quote(quote_id):
    rows = [r for r in all_records("nonstandard_terms") if r["quote_id"] == quote_id]
    return sorted_records(rows)


def exceptions_of_quote(quote_id):
    rows = [r for r in all_records("competitive_exceptions") if r["quote_id"] == quote_id]
    return sorted_records(rows)


def assessments_of_quote(quote_id):
    rows = [r for r in all_records("revrec_assessments") if r["quote_id"] == quote_id]
    return sorted_records(rows)


def requests_of_quote(quote_id):
    rows = [r for r in all_records("approval_requests") if r["quote_id"] == quote_id]
    return sorted_records(rows)


def steps_of_request(request_id):
    rows = [r for r in all_records("approval_steps") if r["approval_request_id"] == request_id]
    return sorted_records(rows)


def order_forms_of_quote(quote_id):
    rows = [r for r in all_records("order_forms") if r["quote_id"] == quote_id]
    return sorted_records(rows)


def active_policy():
    for row in sorted_records(all_records("desk_policies")):
        if row["status"] == "ACTIVE":
            return row
    return None


def open_request_of_quote(quote_id):
    """The newest approval request of a quote (one per submit cycle)."""
    rows = requests_of_quote(quote_id)
    return rows[-1] if rows else None
