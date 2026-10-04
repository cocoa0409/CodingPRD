"""Recall scope computation (calculations.recall_scope) plus the adulterant
cascade / quarantine-release unwind shared by the lots and recall routes.

Scope rules:
- base suspect set = the suspect lot, or the suspect batch's genealogy_lot_ids.
- FINAL: affected = batches whose genealogy intersects the base set.
- PROVISIONAL: base widened by the supplier+spice_code+crop_year cohort over
  all RawLots in any status except REJECTED; affected = genealogy intersection
  with the widened set.
- affected_batch_ids sorted by batch created_at ascending;
  affected_quantity_kg = sum of quantity_kg.
"""
from state import DB


def compute_scope(case):
    """Return the list of affected FinishedBatches (sorted, created_at ASC)."""
    if case["suspect_lot_id"]:
        base = {case["suspect_lot_id"]}
    else:
        batch = DB.batches[case["suspect_batch_id"]]
        base = set(batch["genealogy_lot_ids"])
    pool = set(base)
    if case["scope_policy"] == "PROVISIONAL":
        for sid in base:
            s = DB.lots.get(sid)
            if s is None:
                continue
            for lot in DB.lots.values():
                if lot["status"] == "REJECTED":
                    continue
                if (lot["supplier_id"] == s["supplier_id"]
                        and lot["spice_code"] == s["spice_code"]
                        and lot["crop_year"] == s["crop_year"]):
                    pool.add(lot["id"])
    affected = [b for b in DB.batches.values()
                if pool.intersection(b["genealogy_lot_ids"])]
    affected.sort(key=lambda b: (b["created_at"], b["_seq"]))
    return affected


def batch_covered_by_initiated_recall(batch_id):
    return any(
        rc["status"] == "INITIATED" and batch_id in rc["affected_batch_ids"]
        for rc in DB.recall_cases.values()
    )


def adulterant_cascade(lot, new_entity, touch):
    """An ADULTERANT_SCREEN FAIL was just recorded on `lot` (already moved to
    QUARANTINED). Hold every CLEAR batch carrying the lot in its genealogy,
    and auto-create a standing DRAFT recall case when warranted."""
    from helpers import D  # local import to avoid a module cycle

    held = 0
    for b in DB.batches.values():
        if lot["id"] in b["genealogy_lot_ids"] and b["quality_status"] == "CLEAR":
            b["quality_status"] = "QUALITY_HOLD"
            b["quality_hold_cause"] = "LOT_QUARANTINE"
            b["quality_hold_lot_id"] = lot["id"]
            touch(b)
            held += 1
    if held > 0 and not any(
            rc["suspect_lot_id"] == lot["id"] and rc["status"] in ("DRAFT", "INITIATED")
            for rc in DB.recall_cases.values()):
        case = new_entity({
            "trigger_type": "LOT_SUSPECT",
            "suspect_lot_id": lot["id"],
            "suspect_batch_id": None,
            "scope_policy": "PROVISIONAL",
            "source": "AUTO_QUARANTINE",
            "affected_batch_ids": [],
            "affected_quantity_kg": D(0),
            "status": "DRAFT",
        })
        DB.recall_cases[case["id"]] = case


def release_cascade(lot, touch):
    """A QUARANTINED lot was released via ACCEPT. Clear batches held
    specifically because of this lot (unless an INITIATED recall owns them)
    and auto-close DRAFT AUTO_QUARANTINE recall cases naming this lot."""
    from helpers import D

    for b in DB.batches.values():
        # Only batches currently HELD because of this lot unwind; batches the
        # recall already moved to RECALLED/WITHDRAWN are terminal (PRD 3.7).
        if (b["quality_status"] == "QUALITY_HOLD"
                and b["quality_hold_cause"] == "LOT_QUARANTINE"
                and b["quality_hold_lot_id"] == lot["id"]
                and not batch_covered_by_initiated_recall(b["id"])):
            b["quality_status"] = "CLEAR"
            b["quality_hold_cause"] = "NONE"
            b["quality_hold_lot_id"] = None
            touch(b)
    for rc in DB.recall_cases.values():
        if (rc["source"] == "AUTO_QUARANTINE" and rc["status"] == "DRAFT"
                and rc["suspect_lot_id"] == lot["id"]):
            rc["status"] = "CLOSED"
            rc["affected_batch_ids"] = []
            rc["affected_quantity_kg"] = D(0)
            touch(rc)
