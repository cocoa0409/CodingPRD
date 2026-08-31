"""Credit-ledger primitives (PRD 2.9)."""

import calc
import store


def post_note(customer_id, kind, amount_cents, core_unit_id=None,
              warranty_claim_id=None, memo=None):
    note = store.base_record()
    note.update({
        "customer_id": customer_id,
        "kind": kind,
        "amount_cents": int(amount_cents),
        "status": "POSTED",
        "core_unit_id": core_unit_id,
        "warranty_claim_id": warranty_claim_id,
        "memo": memo,
        "voided_at": None,
        "void_reason": None,
    })
    return store.insert("credit_notes", note)


def void_note(note, reason):
    note["status"] = "VOID"
    note["voided_at"] = store.logical_now_iso()
    note["void_reason"] = reason
    store.touch(note)
    return note


def posted_core_note(core_unit_id):
    """The core's POSTED CORE_EXCHANGE note; latest by created_at then version."""
    matches = [
        n for n in store.all_rows("credit_notes")
        if n["kind"] == "CORE_EXCHANGE"
        and n["status"] == "POSTED"
        and n.get("core_unit_id") == core_unit_id
    ]
    if not matches:
        return None
    return max(matches, key=lambda n: (n["created_at"], n.get("version", 0), n["_seq"]))


def settle(customer, reprice=False):
    """Recompute the four balances (bumping Customer.version), optionally repricing."""
    if customer is None:
        return
    calc.recompute_balances(customer)
    if reprice:
        calc.reprice_quoted_orders(customer["id"])


def void_core_note_and_settle(core, reason, reprice):
    customer = store.get("customers", core["customer_id"])
    note = posted_core_note(core["id"])
    if note is not None:
        void_note(note, reason)
    settle(customer, reprice=reprice)
