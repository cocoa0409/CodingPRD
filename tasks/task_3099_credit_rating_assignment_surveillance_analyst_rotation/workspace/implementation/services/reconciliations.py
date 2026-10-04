"""Appearance reconciliations: the appeal-admissibility gate.

SCAFFOLD state_machines -> AppearanceReconciliation, PRD section 3.6.
"""

from db import base_row, db, now, touch
from errors import fail


def create(analyst_id, rating_decision_id, stated_role, evidence_reference):
    if len(evidence_reference or "") < 10:
        fail("ERR_INVALID_STATE", "evidence_reference must be at least 10 characters.")
    row = base_row()
    row.update(
        {
            "analyst_id": analyst_id,
            "rating_decision_id": rating_decision_id,
            "stated_role": stated_role,
            "evidence_reference": evidence_reference,
            "confirmed_at": None,
            "reconciliation_status": "PENDING",
        }
    )
    db.appearance_reconciliations[row["id"]] = row
    return row


def clear(row):
    if row["reconciliation_status"] not in ("PENDING", "APPEAL_PENDING"):
        fail("ERR_RECONCILIATION_ALREADY_CLEARED")
    row["reconciliation_status"] = "CLEARED"
    return touch(row)


def confirm_breach(row):
    if row["reconciliation_status"] not in ("PENDING", "APPEAL_PENDING"):
        fail("ERR_RECONCILIATION_ALREADY_CLEARED")
    row["reconciliation_status"] = "BREACH_CONFIRMED"
    row["confirmed_at"] = now()
    return touch(row)


def appeal(row):
    if row["reconciliation_status"] != "BREACH_CONFIRMED":
        fail("ERR_RECONCILIATION_NOT_BREACHED")
    row["reconciliation_status"] = "APPEAL_PENDING"
    return touch(row)