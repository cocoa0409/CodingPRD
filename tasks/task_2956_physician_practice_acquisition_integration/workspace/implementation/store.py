"""In-memory data store.

Plain Python dicts keyed by id.  Nothing is seeded, preloaded or hardcoded:
the store starts completely empty on every boot and every row is created
through a declared endpoint.
"""

import threading
import uuid

from flask import g

import clock
from errors import ApiError

KINDS = (
    "acquisitions",
    "physicians",
    "valuation_opinions",
    "compensation_plans",
    "payer_contracts",
    "credentialing_packages",
    "ehr_migration_batches",
    "staff_transition_offers",
    "billing_conversions",
    "readiness_tasks",
    "liability_items",
    "performance_reports",
)

# Human readable entity names for the ERR_RESOURCE_NOT_FOUND message.
KIND_LABEL = {
    "acquisitions": "Acquisition",
    "physicians": "Physician",
    "valuation_opinions": "ValuationOpinion",
    "compensation_plans": "CompensationPlan",
    "payer_contracts": "PayerContract",
    "credentialing_packages": "CredentialingPackage",
    "ehr_migration_batches": "EhrMigrationBatch",
    "staff_transition_offers": "StaffTransitionOffer",
    "billing_conversions": "BillingConversion",
    "readiness_tasks": "ReadinessTask",
    "liability_items": "LiabilityItem",
    "performance_reports": "PerformanceReport",
}

_LOCK = threading.RLock()

TABLES = {kind: {} for kind in KINDS}
_SEQ = [0]


def next_seq():
    with _LOCK:
        _SEQ[0] += 1
        return _SEQ[0]


def new_id():
    return str(uuid.uuid4())


def insert(kind, row, versioned=True):
    """Insert a freshly built row.  version starts at 1; created_at == updated_at."""
    row["id"] = new_id()
    row["_kind"] = kind
    row["_seq"] = next_seq()
    stamp = clock.CLOCK.instant_str()
    row["created_at"] = stamp
    if versioned:
        row["updated_at"] = stamp
        row["version"] = 1
    fresh = getattr(g, "_fresh", None)
    if fresh is None:
        fresh = set()
        g._fresh = fresh
    fresh.add(row["id"])
    TABLES[kind][row["id"]] = row
    return row


def get(kind, row_id):
    if not isinstance(row_id, str):
        return None
    return TABLES[kind].get(row_id)


def require(kind, row_id):
    row = get(kind, row_id)
    if row is None:
        raise ApiError(
            "ERR_RESOURCE_NOT_FOUND",
            "%s '%s' was not found." % (KIND_LABEL[kind], row_id),
        )
    return row


def all_rows(kind):
    return list(TABLES[kind].values())


def where(kind, **criteria):
    out = []
    for row in TABLES[kind].values():
        ok = True
        for key, value in criteria.items():
            if row.get(key) != value:
                ok = False
                break
        if ok:
            out.append(row)
    return out


def ordered(rows):
    """created_at ascending, stable within a response via the insertion sequence."""
    return sorted(rows, key=lambda r: (r["created_at"], r["_seq"]))


# ---------------------------------------------------------------------------
# Mutation bookkeeping.  Every row that actually changes during a request gets
# exactly one version bump and one updated_at refresh at commit time, whether
# the change was requested directly or arrived as a cascade (PRD section 2.4).
# ---------------------------------------------------------------------------

def mark(row):
    dirty = getattr(g, "_dirty", None)
    if dirty is None:
        dirty = {}
        g._dirty = dirty
    dirty[row["id"]] = row


def set_field(row, name, value):
    if row.get(name) != value or name not in row:
        row[name] = value
        mark(row)


def commit():
    dirty = getattr(g, "_dirty", None) or {}
    fresh = getattr(g, "_fresh", None) or set()
    stamp = clock.CLOCK.instant_str()
    for row_id, row in dirty.items():
        if row_id in fresh:
            continue
        if "version" not in row:
            continue
        row["version"] += 1
        row["updated_at"] = stamp
    g._dirty = {}
