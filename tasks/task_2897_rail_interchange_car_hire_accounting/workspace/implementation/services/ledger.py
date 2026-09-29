"""The append-only hire ledger (PRD section 3.9).

Entries are never edited or deleted; a reversal is another entry carrying the
opposite sign.  ``debit_road_id`` is the cycle payer, ``credit_road_id`` the
cycle payee, and ``amount_cents`` is signed from the payer's perspective.
"""
import db


def mint(
    entry_type,
    amount_cents,
    debit_road_id,
    credit_road_id,
    memo,
    settlement_cycle_id=None,
    movement_id=None,
    repair_bill_id=None,
    reclaim_claim_id=None,
    dispute_id=None,
):
    row = db.base_row(versioned=False)
    row.update(
        {
            "settlement_cycle_id": settlement_cycle_id,
            "movement_id": movement_id,
            "repair_bill_id": repair_bill_id,
            "reclaim_claim_id": reclaim_claim_id,
            "dispute_id": dispute_id,
            "entry_type": entry_type,
            "amount_cents": int(amount_cents),
            "debit_road_id": debit_road_id,
            "credit_road_id": credit_road_id,
            "effective_at": db.now(),
            "memo": memo,
        }
    )
    db.ledger[row["id"]] = row
    return row


def entries_for_cycle(cycle_id, entry_type=None):
    rows = [e for e in db.ledger.values() if e["settlement_cycle_id"] == cycle_id]
    if entry_type is not None:
        rows = [e for e in rows if e["entry_type"] == entry_type]
    rows.sort(key=lambda e: (e["effective_at"], e["_seq"]))
    return rows
