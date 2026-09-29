"""Cross-domain side effects shared by several workflows."""

import calc
from derive import (
    dam_deficiencies, dam_eap_required, dam_escalated_deficiency_count,
    next_ledger_sequence_no, owner_is_delinquent,
)
from store import db, insert, touch

SYSTEM_USER_ID = "SYSTEM"


# ---------------------------------------------------------------------------
# Fee ledger (append-only journal; the balance is a replay, never a stored field)
# ---------------------------------------------------------------------------

def post_ledger_entry(owner_id, entry_type, amount_cents, posted_by_user_id,
                      source_ref=None, memo=None):
    return insert(db.ledger, {
        "owner_id": owner_id,
        "sequence_no": next_ledger_sequence_no(owner_id),
        "entry_type": entry_type,
        "amount_cents": int(amount_cents),
        "source_ref": source_ref,
        "memo": memo,
        "posted_by_user_id": posted_by_user_id,
    }, versioned=False)


def ledger_sign_agrees(entry_type, amount_cents):
    if entry_type in calc.POSITIVE_LEDGER_TYPES:
        return amount_cents > 0
    return amount_cents < 0


# ---------------------------------------------------------------------------
# System-opened deficiencies
# ---------------------------------------------------------------------------

def has_unclosed_category(dam_id, category):
    for row in dam_deficiencies(dam_id):
        if row["category"] == category and row["status"] != "CLOSED_VERIFIED":
            return True
    return False


def open_system_deficiency(dam_id, source, category, severity, description):
    """Opens a system deficiency unless one of the same category is already
    unclosed on the dam. Returns the new row, or None when suppressed."""
    if has_unclosed_category(dam_id, category):
        return None
    return insert(db.deficiencies, {
        "dam_id": dam_id,
        "inspection_id": None,
        "source": source,
        "category": category,
        "severity": severity,
        "description": description,
        "status": "OPEN",
        "remediation_due_at": None,
        "closed_at": None,
    })


def open_eap_missing_deficiency(dam):
    """PRD Section 3.2 link 4 / Section 3.9: fires only for a dam that requires a plan."""
    if not dam_eap_required(dam):
        return None
    return open_system_deficiency(
        dam["id"], "SYSTEM_EAP", "EAP_MISSING", "SERIOUS",
        "Dam requires an approved emergency action plan but has none in force.")


# ---------------------------------------------------------------------------
# Drawdown cancellation cascade
# ---------------------------------------------------------------------------

def cancel_drawdown(order, reason):
    """Cancels a non-terminal drawdown order, releasing whatever it had
    committed. Returns True when the order had held reach/reservoir commitments."""
    held_commitment = order["status"] in ("COORDINATED", "ACTIVE")
    order["status"] = "CANCELLED"
    order["cancelled_at"] = db.clock
    order["cancel_reason"] = reason
    touch(order)
    return held_commitment


# ---------------------------------------------------------------------------
# Enforcement posture
# ---------------------------------------------------------------------------

def move_under_enforcement(dam):
    if dam["regulatory_status"] == "REGISTERED":
        dam["regulatory_status"] = "UNDER_ENFORCEMENT"
        touch(dam)
        return True
    return False


def maybe_release_enforcement(dam):
    """PRD Section 3.4: once no escalated deficiency remains and the owner is no
    longer delinquent, the dam returns UNDER_ENFORCEMENT -> REGISTERED."""
    if dam["regulatory_status"] != "UNDER_ENFORCEMENT":
        return False
    if dam_escalated_deficiency_count(dam["id"]) > 0:
        return False
    if owner_is_delinquent(dam["owner_id"]):
        return False
    dam["regulatory_status"] = "REGISTERED"
    touch(dam)
    return True
