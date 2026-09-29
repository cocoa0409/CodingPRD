"""Payment posting: allocation, distribution and the downstream reaches
(PRD 3.5, 3.9).  Shared by the payments endpoint and employer remittances.
"""
import db
import util
from services import cascade, interest, ledger


def advance_offer(case, offer):
    """Move a compromise offer along its installment track."""
    if offer is None or offer["status"] not in ("ACCEPTED", "ACTIVE"):
        return
    count = offer["compliance_payment_count"]
    is_final = (count + 1) == offer["installment_count"]
    offer["compliance_payment_count"] = count + 1
    if offer["next_installment_due_date"] is not None:
        offer["next_installment_due_date"] = util.add_months_date(
            offer["next_installment_due_date"], 1)
    if is_final:
        offer["status"] = "COMPLETED"
        offer["completed_at"] = db.now()
        offer["next_installment_due_date"] = None
        case["enforcement_posture"] = "NORMAL"
        for charge in db.case_charges(case["id"]):
            if charge["status"] == "OPEN":
                charge["unpaid_balance_cents"] = 0
                charge["status"] = "SATISFIED"
    elif offer["status"] == "ACCEPTED":
        offer["status"] = "ACTIVE"
    db.touch(offer)


def required_installment_cents(offer):
    """The floor amount this installment must cover."""
    if (offer["compliance_payment_count"] + 1) == offer["installment_count"]:
        return offer["final_installment_cents"]
    return offer["monthly_installment_cents"]


def post(case, source, amount_cents, iwo_id=None, offer=None):
    """Create the payment, run the waterfall and settle every consequence."""
    received_at = db.now()
    applied = ledger.allocate(case, amount_cents, received_at)
    disbursed, retained = ledger.distribute(case, amount_cents, applied)
    ledger.post_to_case(case, applied)

    row = db.stamp_new_immutable({
        "case_id": case["id"],
        "iwo_id": iwo_id,
        "compromise_offer_id": offer["id"] if offer is not None else None,
        "source": source,
        "amount_cents": amount_cents,
        "received_at": received_at,
        "applied_current_cents": applied["applied_current_cents"],
        "applied_medical_cents": applied["applied_medical_cents"],
        "applied_arrears_cents": applied["applied_arrears_cents"],
        "applied_interest_cents": applied["applied_interest_cents"],
        "applied_genetic_cost_cents": applied["applied_genetic_cost_cents"],
        "unapplied_credit_cents": applied["unapplied_credit_cents"],
        "retained_by_state_cents": retained,
        "disbursed_to_cp_cents": disbursed,
    })
    db.payments[row["id"]] = row

    if source == "COMPROMISE_INSTALLMENT":
        advance_offer(case, offer)

    if source == "TAX_REFUND_INTERCEPT" and interest.arrears_principal(case["id"]) == 0:
        for action in db.case_actions(case["id"]):
            if action["status"] == "ACTIVE" \
                    and action["action_type"] == "TAX_REFUND_INTERCEPT":
                cascade.release_action(action, case, "ARREARS_SATISFIED")

    db.touch(case)
    return row
