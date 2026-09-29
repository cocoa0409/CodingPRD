"""The payment waterfall and its compensating reversal (PRD 3.5)."""
import calc
import clock
import db
import serialize
from constants import (
    INST_PAID, INST_PARTIALLY_PAID, INST_PAST_DUE, INST_SCHEDULED, INST_VOIDED,
    POSTING_REVERSAL,
)
from services import servicing


def refresh_installment_status(installment, moment):
    """Re-derive the installment's status from its own figures (PRD 3.5, 3.6)."""
    if installment["status"] == INST_VOIDED:
        return installment
    fully_funded = (installment["paid_amount_cents"] >= installment["amount_due_cents"]
                    and installment["late_fee_paid_cents"] >= installment["late_fee_cents"])
    if fully_funded:
        if installment["status"] != INST_PAID:
            installment["paid_at"] = clock.now_iso()
        installment["status"] = INST_PAID
    else:
        installment["paid_at"] = None
        if installment["paid_amount_cents"] > 0:
            installment["status"] = INST_PARTIALLY_PAID
        elif clock.parse_iso8601(installment["due_date"]) <= moment:
            installment["status"] = INST_PAST_DUE
        else:
            installment["status"] = INST_SCHEDULED
    return installment


def has_allocatable_installment(loan):
    for installment in serialize.loan_installments(loan["id"]):
        if installment["status"] in (INST_SCHEDULED, INST_PARTIALLY_PAID, INST_PAST_DUE):
            return True
    return False


def _entry(allocations, installment):
    return allocations.setdefault(installment["id"], {
        "installment_id": installment["id"],
        "installment_number": installment["installment_number"],
        "late_fee_cents": 0,
        "principal_cents": 0,
        "premium_cents": 0,
        "amount_cents": 0,
    })


def run_waterfall(loan, amount_cents, moment):
    """Assessed late fees, then arrears, then future installments (PRD 3.5)."""
    rows = serialize.loan_installments(loan["id"])
    bucket_1 = [r for r in rows if r["status"] == INST_PAST_DUE and r["late_fee_assessed"]]
    bucket_2 = [r for r in rows if r["status"] in (INST_PAST_DUE, INST_PARTIALLY_PAID)]
    bucket_3 = [r for r in rows if r["status"] in (INST_SCHEDULED, INST_PARTIALLY_PAID)]

    remaining = amount_cents
    allocations = {}
    for index, bucket in enumerate((bucket_1, bucket_2, bucket_3)):
        for installment in bucket:
            if remaining == 0:
                break
            if index == 0:
                need = installment["late_fee_cents"] - installment["late_fee_paid_cents"]
            else:
                need = installment["amount_due_cents"] - installment["paid_amount_cents"]
            if need <= 0:
                continue
            taken = min(remaining, need)
            entry = _entry(allocations, installment)
            if index == 0:
                installment["late_fee_paid_cents"] += taken
                entry["late_fee_cents"] += taken
            else:
                principal_share = calc.round_half_up(
                    taken * installment["principal_component_cents"],
                    installment["amount_due_cents"])
                premium_share = taken - principal_share
                installment["paid_principal_cents"] += principal_share
                installment["paid_premium_cents"] += premium_share
                installment["paid_amount_cents"] += taken
                entry["principal_cents"] += principal_share
                entry["premium_cents"] += premium_share
                entry["amount_cents"] += taken
            remaining -= taken

    satisfied = 0
    for entry in allocations.values():
        installment = db.installments[entry["installment_id"]]
        was_paid = installment["status"] == INST_PAID
        refresh_installment_status(installment, moment)
        db.touch(installment)
        if installment["status"] == INST_PAID and not was_paid:
            satisfied += 1

    return {
        "allocated_late_fee_cents": sum(e["late_fee_cents"] for e in allocations.values()),
        "allocated_principal_cents": sum(e["principal_cents"] for e in allocations.values()),
        "allocated_premium_cents": sum(e["premium_cents"] for e in allocations.values()),
        "installments_satisfied_count": satisfied,
        "overpayment_cents": remaining,
        "_allocations": list(allocations.values()),
    }


def run_reversal(loan, target, moment):
    """Walk the target's allocations in descending installment_number and
    subtract exactly what it credited (PRD 3.5)."""
    removed_late_fee = 0
    removed_principal = 0
    removed_premium = 0
    entries = sorted(target.get("_allocations", []),
                     key=lambda e: e["installment_number"], reverse=True)
    for entry in entries:
        installment = db.installments.get(entry["installment_id"])
        if installment is None:
            continue
        installment["late_fee_paid_cents"] -= entry["late_fee_cents"]
        installment["paid_principal_cents"] -= entry["principal_cents"]
        installment["paid_premium_cents"] -= entry["premium_cents"]
        installment["paid_amount_cents"] -= entry["amount_cents"]
        refresh_installment_status(installment, moment)
        db.touch(installment)
        removed_late_fee += entry["late_fee_cents"]
        removed_principal += entry["principal_cents"]
        removed_premium += entry["premium_cents"]
    return {
        "allocated_late_fee_cents": removed_late_fee,
        "allocated_principal_cents": removed_principal,
        "allocated_premium_cents": removed_premium,
        "installments_satisfied_count": 0,
        "overpayment_cents": 0,
        "_allocations": [],
    }


def already_reversed(posting_id):
    for posting in db.payment_postings.values():
        if posting["reverses_posting_id"] == posting_id:
            return True
    return False


def record_posting(loan, posting_type, amount_cents, reverses_posting_id, figures, moment):
    record = {
        "loan_id": loan["id"],
        "posting_type": posting_type,
        "reverses_posting_id": reverses_posting_id,
        "amount_cents": amount_cents,
        "allocated_late_fee_cents": figures["allocated_late_fee_cents"],
        "allocated_premium_cents": figures["allocated_premium_cents"],
        "allocated_principal_cents": figures["allocated_principal_cents"],
        "installments_satisfied_count": figures["installments_satisfied_count"],
        "overpayment_cents": figures["overpayment_cents"],
        "obligation_balance_after_cents": serialize.loan_obligation_balance(loan),
        "posted_at": clock.now_iso(),
        "_allocations": figures.get("_allocations", []),
    }
    return db.insert(db.payment_postings, record, append_only=True)


def post_money(loan, posting_type, amount_cents, target_posting, moment):
    """Apply one posting end to end and return the stored PaymentPosting."""
    if posting_type == POSTING_REVERSAL:
        figures = run_reversal(loan, target_posting, moment)
    else:
        figures = run_waterfall(loan, amount_cents, moment)
    serialize.recompute_loan_ledger(loan)
    if posting_type == POSTING_REVERSAL:
        servicing.recompute_after_reversal(loan, moment)
    else:
        servicing.recompute_after_payment(loan, moment)
    db.touch(loan)
    reverses = target_posting["id"] if target_posting is not None else None
    return record_posting(loan, posting_type, amount_cents, reverses, figures, moment)
