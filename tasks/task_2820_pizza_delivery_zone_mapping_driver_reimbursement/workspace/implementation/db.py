"""In-memory data store.

Plain dicts keyed by id. The store starts EMPTY on every boot: nothing is
seeded, preloaded or hardcoded -- every entity is built through the declared
endpoints.
"""
import itertools
import uuid

import clock

_counter = itertools.count(1)

stores = {}
zone_versions = {}
service_addresses = {}
disputes = {}
drivers = {}
cost_models = {}
mvr_checks = {}
insurance_verifications = {}
orders = {}
dispatches = {}
stops = {}
lines = {}
safe_drops = {}
complaints = {}
# PRD 4 lists "signing a qualification decision" among the action endpoints that
# "create a record as their principal effect" and answer 201 with "that new
# resource in the data field". The record has no path variable, no not-found
# identifier and no read endpoint, so it lives outside COLLECTIONS.
qualification_decisions = {}

COLLECTIONS = {
    "store": stores,
    "zone_version": zone_versions,
    "service_address": service_addresses,
    "address_dispute": disputes,
    "driver": drivers,
    "vehicle_cost_model": cost_models,
    "mvr_check": mvr_checks,
    "insurance_verification": insurance_verifications,
    "order": orders,
    "dispatch": dispatches,
    "dispatch_stop": stops,
    "reimbursement_line": lines,
    "safe_drop": safe_drops,
    "complaint": complaints,
}

NOT_FOUND = {
    "store": "ERR_STORE_NOT_FOUND",
    "zone_version": "ERR_ZONE_VERSION_NOT_FOUND",
    "service_address": "ERR_SERVICE_ADDRESS_NOT_FOUND",
    "address_dispute": "ERR_ADDRESS_DISPUTE_NOT_FOUND",
    "driver": "ERR_DRIVER_NOT_FOUND",
    "vehicle_cost_model": "ERR_VEHICLE_COST_MODEL_NOT_FOUND",
    "mvr_check": "ERR_MVR_CHECK_NOT_FOUND",
    "insurance_verification": "ERR_INSURANCE_VERIFICATION_NOT_FOUND",
    "order": "ERR_ORDER_NOT_FOUND",
    "dispatch": "ERR_DISPATCH_NOT_FOUND",
    "dispatch_stop": "ERR_DISPATCH_STOP_NOT_FOUND",
    "reimbursement_line": "ERR_REIMBURSEMENT_LINE_NOT_FOUND",
    "safe_drop": "ERR_SAFE_DROP_NOT_FOUND",
    "complaint": "ERR_COMPLAINT_NOT_FOUND",
}


def new_id():
    return str(uuid.uuid4())


def next_seq():
    return next(_counter)


def insert(collection, record, common=True, versioned=True):
    """Register a record, stamping the common resource properties."""
    record["id"] = new_id()
    record["_seq"] = next_seq()
    record["created_at"] = clock.now()
    if common:
        if versioned:
            record["updated_at"] = clock.now()
            record["version"] = 1
    collection[record["id"]] = record
    return record


def touch(record):
    """A mutation: refresh updated_at to the logical clock, bump version by 1."""
    if record is None:
        return record
    if "version" in record:
        record["version"] = record["version"] + 1
    if "updated_at" in record:
        record["updated_at"] = clock.now()
    return record


def sort_key(record):
    return (record["created_at"], record["_seq"])


def ordered(records, descending=False):
    return sorted(records, key=sort_key, reverse=descending)


def lookup(kind, ident):
    if not isinstance(ident, str):
        return None
    return COLLECTIONS[kind].get(ident)


def reset():
    for coll in COLLECTIONS.values():
        coll.clear()
    qualification_decisions.clear()
