"""Shared cascades. Every cascade is immediate, complete and synchronous (PRD 2.6)."""

import calc
import store

LOOKBACK_QUARANTINE_REASON = "LOOKBACK_OPEN"


def reopen_request(req):
    """ALLOCATED -> OPEN with the priority recomputed against the clock as it stands."""
    req["status"] = "OPEN"
    calc.apply_priority(req)
    store.touch(req)


def live_allocation_for_request(request_id):
    for allocation in store.by_created(
        [a for a in store.DB["allocations"].values() if a["request_id"] == request_id]
    ):
        if allocation["status"] in ("RESERVED", "CONFIRMED"):
            return allocation
    return None


def reserved_allocation_for_tissue(tissue_id):
    for allocation in store.by_created(
        [a for a in store.DB["allocations"].values() if a["tissue_id"] == tissue_id]
    ):
        if allocation["status"] == "RESERVED":
            return allocation
    return None


def confirmed_allocation_for_tissue(tissue_id):
    for allocation in store.by_created(
        [a for a in store.DB["allocations"].values() if a["tissue_id"] == tissue_id]
    ):
        if allocation["status"] in ("CONFIRMED", "CONSUMED"):
            return allocation
    return None


def cancel_reserved_allocation(allocation, reason, reopen=True):
    """A RESERVED allocation never entered a money sum, so no money moves."""
    allocation["status"] = "CANCELLED"
    allocation["cancel_reason"] = reason
    store.touch(allocation)
    req = store.DB["requests"].get(allocation["request_id"])
    if req is not None and reopen and req["status"] == "ALLOCATED":
        reopen_request(req)


def release_allocation(allocation, reason):
    """CONFIRMED -> RELEASED: credits the surgeon and reopens the request."""
    allocation["status"] = "RELEASED"
    allocation["cancel_reason"] = reason
    store.touch(allocation)
    req = store.DB["requests"].get(allocation["request_id"])
    surgeon = None
    if req is not None:
        if req["status"] == "ALLOCATED":
            reopen_request(req)
        surgeon = store.DB["surgeons"].get(req["surgeon_id"])
    if surgeon is not None:
        calc.recompute_fee_ledger(surgeon)
        store.touch(surgeon)
    return surgeon


def quarantine_tissue(tissue, reason):
    """Dimension A only; custody_status is never touched here."""
    was_reserved = tissue["disposition_status"] == "RESERVED"
    tissue["disposition_status"] = "QUARANTINED"
    tissue["quarantine_reason"] = reason
    store.touch(tissue)
    if was_reserved:
        allocation = reserved_allocation_for_tissue(tissue["id"])
        if allocation is not None:
            cancel_reserved_allocation(allocation, "TISSUE_QUARANTINED")


# ----------------------------------------------------------------- lookback


def open_lookback_investigation(donor, trigger_reason, source_report_id=None):
    """The open cascade of PRD 3.9. Returns the created investigation."""
    row = store.base_row()
    row.update(
        {
            "donor_id": donor["id"],
            "source_report_id": source_report_id,
            "trigger_reason": trigger_reason,
            "status": "OPEN",
            "opened_at": store.now(),
            "notified_at": None,
            "closed_at": None,
            "impacted_tissue_count": 0,
            "quarantined_count": 0,
            "notified_recipient_count": None,
            "closure_note": None,
            "_quarantined_tissue_ids": [],
        }
    )

    donor["lookback_flag"] = True
    store.touch(donor)

    tissues = calc.donor_tissues(donor["id"])
    row["impacted_tissue_count"] = len(tissues)
    quarantined = []
    for tissue in tissues:
        if tissue["disposition_status"] in calc.LOOKBACK_QUARANTINABLE:
            quarantine_tissue(tissue, LOOKBACK_QUARANTINE_REASON)
            quarantined.append(tissue["id"])
    row["quarantined_count"] = len(quarantined)
    row["_quarantined_tissue_ids"] = quarantined

    store.DB["investigations"][row["id"]] = row
    return row


def donor_has_live_investigation(donor_id):
    for row in store.DB["investigations"].values():
        if row["donor_id"] == donor_id and row["status"] in ("OPEN", "NOTIFIED"):
            return True
    return False


def close_lookback_sweep(investigation, resolution):
    ids = set(investigation.get("_quarantined_tissue_ids") or [])
    affected = [
        store.DB["tissues"][tid]
        for tid in ids
        if tid in store.DB["tissues"]
        and store.DB["tissues"][tid]["disposition_status"] == "QUARANTINED"
    ]
    for tissue in store.by_created(affected):
        if resolution == "NO_ACTION":
            tissue["disposition_status"] = "ELIGIBLE"
            tissue["quarantine_reason"] = None
        else:
            tissue["disposition_status"] = "DISCARDED"
            tissue["disposal_method"] = "INCINERATION"
            tissue["custody_status"] = "DESTROYED"
        store.touch(tissue)
