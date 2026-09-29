"""In-memory store.  Every collection starts empty on every boot; no seeding."""

import uuid

import util

institutions = {}
national_rate_caps = {}
brokers = {}
broker_agreements = {}
exceptions = {}
programs = {}
classifications = {}
placements = {}
rate_cap_checks = {}
concentration_limits = {}
contingency_plans = {}
call_report_filings = {}

ALL_STORES = (
    institutions, national_rate_caps, brokers, broker_agreements, exceptions,
    programs, classifications, placements, rate_cap_checks,
    concentration_limits, contingency_plans, call_report_filings,
)


def new_id():
    return str(uuid.uuid4())


def stamp_new(record, versioned=True):
    """Attach identity fields.  `_seq` is the internal ordering tie-break."""
    record["id"] = new_id()
    record["created_at"] = util.now_iso()
    if versioned:
        record["updated_at"] = record["created_at"]
        record["version"] = 1
    record["_seq"] = util.next_seq()
    return record


def touch(record):
    record["updated_at"] = util.now_iso()


def bump(record):
    record["updated_at"] = util.now_iso()
    record["version"] = record.get("version", 1) + 1


def public(record):
    """Serialise a record, dropping internal keys."""
    return {k: v for k, v in record.items() if not k.startswith("_")}


def public_list(records):
    return [public(r) for r in records]


def by_created(records):
    return sorted(records, key=lambda r: (r["created_at"], r["_seq"]))


def reset_all():
    for store in ALL_STORES:
        store.clear()
    util.reset_clock()
