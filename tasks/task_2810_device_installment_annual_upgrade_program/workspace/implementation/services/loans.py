"""Origination, the amortisation schedule, and loan closure (PRD 3.3, 3.7, 3.9)."""
import calc
import clock
import db
import serialize
from constants import (
    CLOSURE_PROGRAM_CANCELLATION, CLOSURE_UPGRADE_ROLLOVER, COVERAGE_ACTIVE,
    COVERAGE_TERMINATED, DQ_CURRENT, DU_LOCKED, DU_UNACTIVATED, DU_WITH_CUSTOMER,
    INST_PARTIALLY_PAID, INST_PAST_DUE, INST_SCHEDULED, INST_VOIDED, LOAN_ACTIVE,
    LOAN_PAID_OFF, LOAN_ROLLED_OVER, POSTING_PAYOFF, QUOTE_CONSUMED,
    UPGRADE_WINDOW_DAYS, VOID_REASON_LOAN_CLOSED,
)
from services import cascades


def imei_registered(imei):
    for unit in db.device_units.values():
        if unit["imei"] == imei:
            return True
    return False


def mint_loan(customer_id, credit_application_id, device_model_id, down_payment_cents,
              origination_fee_cents, rolled_over_balance_cents, principal_cents,
              term_months, monthly_premium_cents, imei, predecessor_loan_id,
              carrier_account_id=None):
    moment = clock.now()
    premium_total = monthly_premium_cents * term_months
    base = calc.base_principal_component(principal_cents, term_months)
    loan = db.insert(db.loans, {
        "customer_id": customer_id,
        "credit_application_id": credit_application_id,
        "device_model_id": device_model_id,
        "predecessor_loan_id": predecessor_loan_id,
        "down_payment_cents": down_payment_cents,
        "origination_fee_cents": origination_fee_cents,
        "rolled_over_balance_cents": rolled_over_balance_cents,
        "principal_cents": principal_cents,
        "term_months": term_months,
        "monthly_protection_premium_cents": monthly_premium_cents,
        "premium_total_cents": premium_total,
        "monthly_installment_cents": base + monthly_premium_cents,
        "paid_principal_cents": 0,
        "paid_premium_cents": 0,
        "outstanding_late_fee_cents": 0,
        "paid_installment_count": 0,
        "status": LOAN_ACTIVE,
        "closure_reason": None,
        "delinquency_state": DQ_CURRENT,
        "days_past_due": 0,
        "protection_coverage_status": COVERAGE_ACTIVE,
        "upgrade_hold_flag": False,
        "origination_date": clock.format_iso8601(moment),
        "upgrade_window_opens_at": clock.format_iso8601(
            clock.add_days(moment, UPGRADE_WINDOW_DAYS)),
    })
    for row in calc.schedule_rows(principal_cents, term_months, monthly_premium_cents, moment):
        db.insert(db.installments, {
            "loan_id": loan["id"],
            "installment_number": row["installment_number"],
            "due_date": clock.format_iso8601(row["due_date"]),
            "principal_component_cents": row["principal_component_cents"],
            "premium_component_cents": row["premium_component_cents"],
            "amount_due_cents": row["amount_due_cents"],
            "paid_principal_cents": 0,
            "paid_premium_cents": 0,
            "paid_amount_cents": 0,
            "late_fee_cents": 0,
            "late_fee_paid_cents": 0,
            "late_fee_assessed": False,
            "status": INST_SCHEDULED,
            "paid_at": None,
            "void_reason": None,
        })
    db.insert(db.device_units, {
        "loan_id": loan["id"],
        "device_model_id": device_model_id,
        "carrier_account_id": carrier_account_id,
        "imei": imei,
        "activation_status": DU_UNACTIVATED,
        "unlock_status": DU_LOCKED,
        "possession_status": DU_WITH_CUSTOMER,
        "activated_at": None,
        "unlock_requested_at": None,
        "unlocked_at": None,
        "returned_at": None,
    })
    return loan


def void_open_installments(loan):
    for installment in serialize.loan_installments(loan["id"]):
        if installment["status"] in (INST_SCHEDULED, INST_PAST_DUE, INST_PARTIALLY_PAID):
            installment["status"] = INST_VOIDED
            installment["void_reason"] = VOID_REASON_LOAN_CLOSED
            db.touch(installment)


def close_as_paid_off(loan, quote, payment_amount_cents):
    """Early cancellation settles the quote and closes the loan (PRD 3.7)."""
    cleared_late_fee = loan["outstanding_late_fee_cents"]
    cleared_principal = loan["principal_cents"] - loan["paid_principal_cents"]
    loan["status"] = LOAN_PAID_OFF
    loan["closure_reason"] = CLOSURE_PROGRAM_CANCELLATION
    loan["paid_principal_cents"] = loan["principal_cents"]
    loan["outstanding_late_fee_cents"] = 0
    loan["protection_coverage_status"] = COVERAGE_TERMINATED
    void_open_installments(loan)
    db.touch(loan)

    posting = db.insert(db.payment_postings, {
        "loan_id": loan["id"],
        "posting_type": POSTING_PAYOFF,
        "reverses_posting_id": None,
        "amount_cents": payment_amount_cents,
        "allocated_late_fee_cents": cleared_late_fee,
        "allocated_premium_cents": 0,
        "allocated_principal_cents": cleared_principal,
        "installments_satisfied_count": 0,
        "overpayment_cents": 0,
        "obligation_balance_after_cents": serialize.loan_obligation_balance(loan),
        "posted_at": clock.now_iso(),
        "_allocations": [],
    }, append_only=True)

    quote["status"] = QUOTE_CONSUMED
    quote["consumed_at"] = clock.now_iso()
    db.touch(quote)
    cascades.supersede_standing_quotes(loan, keep_id=quote["id"])
    cascades.unlock_device_on_closure(loan)
    return posting


def close_as_rolled_over(loan):
    """The predecessor loan of a completed upgrade (PRD 3.9)."""
    loan["status"] = LOAN_ROLLED_OVER
    loan["closure_reason"] = CLOSURE_UPGRADE_ROLLOVER
    loan["paid_principal_cents"] = loan["principal_cents"]
    loan["protection_coverage_status"] = COVERAGE_TERMINATED
    loan["upgrade_hold_flag"] = False
    void_open_installments(loan)
    db.touch(loan)
    cascades.supersede_standing_quotes(loan)
