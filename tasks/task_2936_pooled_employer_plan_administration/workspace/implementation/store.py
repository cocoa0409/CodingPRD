"""In-memory data store.

The store starts completely empty on every boot: nothing is seeded, preloaded
or hardcoded. Every entity any caller needs is constructed through the declared
endpoints of PRD 4.
"""

import threading
import uuid

import clockcal

LOCK = threading.RLock()

COLLECTIONS = (
    "providers",
    "plans",
    "service_providers",
    "allocations",
    "employers",
    "elections",
    "batches",
    "deposits",
    "tests",
    "filings",
    "exits",
    "disclosures",
)

DB = {}


def reset():
    with LOCK:
        DB.clear()
        for name in COLLECTIONS:
            DB[name] = {}
        DB["_seq"] = 0
        DB["_approval_ordinal"] = 0
        clockcal.reset_clock()


reset()


def next_seq():
    DB["_seq"] += 1
    return DB["_seq"]


def new_id():
    return str(uuid.uuid4())


def insert(collection, record, versioned=True):
    """Insert a record, minting id/created_at (and updated_at/version)."""
    record["id"] = new_id()
    record["created_at"] = clockcal.stamp()
    if versioned:
        record["updated_at"] = record["created_at"]
        record["version"] = 1
    record["_seq"] = next_seq()
    DB[collection][record["id"]] = record
    return record


def get(collection, rid):
    if not isinstance(rid, str):
        return None
    return DB[collection].get(rid)


def all_rows(collection):
    """Every row of a collection in created_at ascending order.

    Ties on created_at (the logical clock can be stationary across many
    writes) fall back to insertion order. No ordering ever compares `id`.
    """
    return sorted(DB[collection].values(), key=lambda r: (r["created_at"], r["_seq"]))


def where(collection, **kwargs):
    out = []
    for row in all_rows(collection):
        if all(row.get(k) == v for k, v in kwargs.items()):
            out.append(row)
    return out


# --------------------------------------------------------------------------
# Version / updated_at bookkeeping (PRD 2.4)
#
# `version` increments by exactly one on every mutation, including cascaded
# ones. A single request may touch the same resource through several distinct
# side effects (a plan document, for instance, has its control totals and its
# derived gates recomputed by the same posting request); the resource is still
# mutated exactly once by that request, so the bump is idempotent within it.
# --------------------------------------------------------------------------


class Touch(object):
    """Per-request set of resources already bumped."""

    def __init__(self):
        self.seen = set()

    def bump(self, record):
        key = id(record)
        if key in self.seen:
            return record
        self.seen.add(key)
        record["updated_at"] = clockcal.stamp()
        record["version"] = record.get("version", 1) + 1
        return record


# --------------------------------------------------------------------------
# Cross-collection navigation helpers
# --------------------------------------------------------------------------


def plan_of_employer(employer):
    return get("plans", employer["plan_document_id"])


def plan_of_service_provider(sp):
    return get("plans", sp["plan_document_id"])


def employer_of_election(election):
    return get("employers", election["adopting_employer_id"])


def employer_of_batch(batch):
    return get("employers", batch["adopting_employer_id"])


def batch_of_deposit(deposit):
    return get("batches", deposit["payroll_batch_id"])


def employer_of_deposit(deposit):
    batch = batch_of_deposit(deposit)
    if batch is None:
        return None
    return employer_of_batch(batch)


def employer_of_exit(transfer):
    return get("employers", transfer["adopting_employer_id"])


def plan_of_election(election):
    emp = employer_of_election(election)
    return plan_of_employer(emp) if emp else None


def plan_of_batch(batch):
    emp = employer_of_batch(batch)
    return plan_of_employer(emp) if emp else None


def plan_of_deposit(deposit):
    emp = employer_of_deposit(deposit)
    return plan_of_employer(emp) if emp else None


def plan_of_exit(transfer):
    emp = employer_of_exit(transfer)
    return plan_of_employer(emp) if emp else None


def plan_of_allocation(alloc):
    return get("plans", alloc["plan_document_id"])


def plan_of_test(test):
    return get("plans", test["plan_document_id"])


def plan_of_filing(filing):
    return get("plans", filing["plan_document_id"])


def plan_of_disclosure(disc):
    return get("plans", disc["plan_document_id"])


def employers_of_plan(plan):
    return where("employers", plan_document_id=plan["id"])


def service_providers_of_plan(plan):
    return where("service_providers", plan_document_id=plan["id"])


def allocations_of_plan(plan):
    return where("allocations", plan_document_id=plan["id"])


def batches_of_employer(employer):
    return where("batches", adopting_employer_id=employer["id"])


def batches_of_plan(plan):
    out = []
    for emp in employers_of_plan(plan):
        out.extend(batches_of_employer(emp))
    return sorted(out, key=lambda r: (r["created_at"], r["_seq"]))


def deposits_of_batch(batch):
    return where("deposits", payroll_batch_id=batch["id"])


def deposits_of_employer(employer):
    out = []
    for batch in batches_of_employer(employer):
        out.extend(deposits_of_batch(batch))
    return sorted(out, key=lambda r: (r["created_at"], r["_seq"]))


def deposits_of_plan(plan):
    out = []
    for emp in employers_of_plan(plan):
        out.extend(deposits_of_employer(emp))
    return sorted(out, key=lambda r: (r["created_at"], r["_seq"]))


def elections_of_employer(employer):
    return where("elections", adopting_employer_id=employer["id"])


def approved_election(employer):
    for e in elections_of_employer(employer):
        if e["status"] == "APPROVED":
            return e
    return None


def exits_of_employer(employer):
    return where("exits", adopting_employer_id=employer["id"])


def exits_of_plan(plan):
    out = []
    for emp in employers_of_plan(plan):
        out.extend(exits_of_employer(emp))
    return sorted(out, key=lambda r: (r["created_at"], r["_seq"]))


def tests_of_plan(plan):
    return where("tests", plan_document_id=plan["id"])


def filings_of_plan(plan):
    return where("filings", plan_document_id=plan["id"])


def disclosures_of_plan(plan):
    return where("disclosures", plan_document_id=plan["id"])


def plans_of_provider(provider):
    return where("plans", pooled_plan_provider_id=provider["id"])
