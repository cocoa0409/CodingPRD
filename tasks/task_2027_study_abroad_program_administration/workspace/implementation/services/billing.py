"""Billing statement creation, payments, and voiding (billing_charge_calculation, refund_credit_memo)."""

import db
from db import new_id, now_iso

HOME_TUITION_PER_TERM_CENTS = 2400000
INSURANCE_PREMIUM_CENTS = 35000
APPLICATION_FEE_CENTS = 5000
AID_CAP_HOME_TUITION = 1.00
AID_CAP_PROGRAM_FEE = 0.60


def create_billing_statement(application, program, agreement):
    """Create a BillingStatement in ISSUED status per billing_charge_calculation."""
    if program["billing_model"] == "HOME_TUITION":
        base_cents = HOME_TUITION_PER_TERM_CENTS
        aid_cap_pct = AID_CAP_HOME_TUITION
    else:
        base_cents = program["program_fee_cents"]
        aid_cap_pct = AID_CAP_PROGRAM_FEE

    insurance_premium_cents = INSURANCE_PREMIUM_CENTS if agreement.get("insurance_required") else 0

    import math
    aid_cap_product = math.floor(aid_cap_pct * base_cents)
    aid_portable_cents = min(application["aid_award_cents_snapshot"], aid_cap_product)

    charge_cents = base_cents + insurance_premium_cents + APPLICATION_FEE_CENTS - aid_portable_cents
    amount_paid_cents = 0
    outstanding_cents = charge_cents - amount_paid_cents

    ts = now_iso()
    stmt = {
        "id": new_id(),
        "application_id": application["id"],
        "billing_model_snapshot": program["billing_model"],
        "base_cents": base_cents,
        "insurance_premium_cents": insurance_premium_cents,
        "application_fee_cents": APPLICATION_FEE_CENTS,
        "aid_portable_cents": aid_portable_cents,
        "charge_cents": charge_cents,
        "amount_paid_cents": amount_paid_cents,
        "credit_memo_cents": 0,
        "outstanding_cents": outstanding_cents,
        "status": "ISSUED",
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
    }
    db.billing_statements[stmt["id"]] = stmt
    return stmt


def void_statement(stmt):
    """Void a billing statement (refund_credit_memo)."""
    stmt["credit_memo_cents"] = stmt["amount_paid_cents"]
    stmt["outstanding_cents"] = 0
    stmt["status"] = "VOID"
    stmt["version"] += 1
    stmt["updated_at"] = now_iso()


def stmt_public(stmt):
    return dict(stmt)
