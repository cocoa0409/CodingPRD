"""Entity serializers.  Field lists follow SCAFFOLD.yaml section 1.1 exactly.

Computed fields are derived at read time so they can never drift from the rows
they aggregate.  Money is always emitted as a JSON integer number of cents.
"""
import db
from constants import (
    INST_PAID, INST_VOIDED, LOAN_ACTIVE, UR_COMPLETED, UR_RESERVING_STATUSES,
    EV_DEFAULT_DECLARED,
)

COMMON = ("id", "created_at", "updated_at", "version")
APPEND_ONLY_COMMON = ("id", "created_at")


def _pick(record, fields, common):
    out = {}
    for field in fields:
        out[field] = record.get(field)
    for field in common:
        out[field] = record.get(field)
    return out


# --- derived aggregates ---

def customer_loans(customer_id):
    return [loan for loan in db.values(db.loans) if loan["customer_id"] == customer_id]


def customer_outstanding_principal(customer_id):
    return sum(loan["principal_cents"] - loan["paid_principal_cents"]
               for loan in customer_loans(customer_id) if loan["status"] == LOAN_ACTIVE)


def customer_open_loan_count(customer_id):
    return sum(1 for loan in customer_loans(customer_id) if loan["status"] == LOAN_ACTIVE)


def customer_completed_upgrades(customer_id):
    return [req for req in db.values(db.upgrade_requests)
            if req["customer_id"] == customer_id and req["status"] == UR_COMPLETED]


def customer_default_strikes(customer_id):
    loan_ids = {loan["id"] for loan in customer_loans(customer_id)}
    return sum(1 for event in db.values(db.delinquency_events)
               if event["loan_id"] in loan_ids and event["event_type"] == EV_DEFAULT_DECLARED)


def model_reserved_slot_count(model_id):
    return sum(1 for req in db.values(db.upgrade_requests)
               if req["target_device_model_id"] == model_id
               and req["status"] in UR_RESERVING_STATUSES)


def loan_installments(loan_id):
    return sorted((i for i in db.installments.values() if i["loan_id"] == loan_id),
                  key=lambda i: i["installment_number"])


def loan_obligation_balance(loan):
    return ((loan["principal_cents"] - loan["paid_principal_cents"])
            + (loan["premium_total_cents"] - loan["paid_premium_cents"])
            + loan["outstanding_late_fee_cents"])


def recompute_loan_ledger(loan):
    """Roll the loan's money columns up from its installments (PRD 3.5)."""
    rows = loan_installments(loan["id"])
    loan["paid_principal_cents"] = sum(r["paid_principal_cents"] for r in rows)
    loan["paid_premium_cents"] = sum(r["paid_premium_cents"] for r in rows)
    loan["paid_installment_count"] = sum(1 for r in rows if r["status"] == INST_PAID)
    loan["outstanding_late_fee_cents"] = sum(
        r["late_fee_cents"] - r["late_fee_paid_cents"]
        for r in rows if r["status"] != INST_VOIDED)
    return loan


# --- serializers ---

CUSTOMER_FIELDS = ("full_name", "email", "mobile_number", "status",
                   "financing_lock_reason", "financing_locked_at", "credit_score_band",
                   "credit_limit_cents", "outstanding_principal_cents", "open_loan_count",
                   "completed_upgrade_count", "last_upgrade_completed_at",
                   "default_strike_count")


def customer(record):
    out = _pick(record, CUSTOMER_FIELDS, COMMON)
    out["outstanding_principal_cents"] = customer_outstanding_principal(record["id"])
    out["open_loan_count"] = customer_open_loan_count(record["id"])
    completed = customer_completed_upgrades(record["id"])
    out["completed_upgrade_count"] = len(completed)
    if completed:
        latest = max(completed, key=lambda r: (r["completed_at"], r["_seq"]))
        out["last_upgrade_completed_at"] = latest["completed_at"]
    else:
        out["last_upgrade_completed_at"] = None
    out["default_strike_count"] = customer_default_strikes(record["id"])
    return out


DEVICE_MODEL_FIELDS = ("sku", "display_name", "retail_price_cents",
                       "monthly_protection_premium_cents", "trade_in_base_credit_cents",
                       "concurrent_reservation_capacity", "reserved_slot_count",
                       "generation_year", "active")


def device_model(record):
    out = _pick(record, DEVICE_MODEL_FIELDS, COMMON)
    out["reserved_slot_count"] = model_reserved_slot_count(record["id"])
    return out


CARRIER_ACCOUNT_FIELDS = ("customer_id", "carrier_code", "account_number",
                          "unlock_policy_days", "activation_state", "activated_at",
                          "port_freeze_flag", "active_device_imei")


def carrier_account(record):
    return _pick(record, CARRIER_ACCOUNT_FIELDS, COMMON)


CREDIT_APPLICATION_FIELDS = ("customer_id", "device_model_id", "requested_term_months",
                             "declared_down_payment_cents", "requested_principal_cents",
                             "credit_score_band", "credit_limit_cents",
                             "exposure_at_decision_cents", "approved_principal_cents",
                             "conditional_down_payment_required_cents", "status",
                             "decision_reason", "underwriter_user_id", "decided_at")


def credit_application(record):
    return _pick(record, CREDIT_APPLICATION_FIELDS, COMMON)


LOAN_FIELDS = ("customer_id", "credit_application_id", "device_model_id",
               "predecessor_loan_id", "down_payment_cents", "origination_fee_cents",
               "rolled_over_balance_cents", "principal_cents", "term_months",
               "monthly_protection_premium_cents", "premium_total_cents",
               "monthly_installment_cents", "paid_principal_cents", "paid_premium_cents",
               "outstanding_late_fee_cents", "paid_installment_count",
               "obligation_balance_cents", "status", "closure_reason", "delinquency_state",
               "days_past_due", "protection_coverage_status", "upgrade_hold_flag",
               "origination_date", "upgrade_window_opens_at")


def loan(record):
    out = _pick(record, LOAN_FIELDS, COMMON)
    out["obligation_balance_cents"] = loan_obligation_balance(record)
    return out


INSTALLMENT_FIELDS = ("loan_id", "installment_number", "due_date",
                      "principal_component_cents", "premium_component_cents",
                      "amount_due_cents", "paid_principal_cents", "paid_premium_cents",
                      "paid_amount_cents", "late_fee_cents", "late_fee_paid_cents",
                      "late_fee_assessed", "status", "paid_at", "void_reason")


def installment(record):
    return _pick(record, INSTALLMENT_FIELDS, COMMON)


PAYMENT_POSTING_FIELDS = ("loan_id", "posting_type", "reverses_posting_id", "amount_cents",
                          "allocated_late_fee_cents", "allocated_premium_cents",
                          "allocated_principal_cents", "installments_satisfied_count",
                          "overpayment_cents", "obligation_balance_after_cents", "posted_at")


def payment_posting(record):
    return _pick(record, PAYMENT_POSTING_FIELDS, APPEND_ONLY_COMMON)


DEVICE_UNIT_FIELDS = ("loan_id", "device_model_id", "carrier_account_id", "imei",
                      "activation_status", "unlock_status", "possession_status",
                      "activated_at", "unlock_requested_at", "unlocked_at", "returned_at")


def device_unit(record):
    return _pick(record, DEVICE_UNIT_FIELDS, COMMON)


UPGRADE_REQUEST_FIELDS = ("loan_id", "customer_id", "target_device_model_id", "new_loan_id",
                          "payoff_quote_id", "fulfillment_window_start",
                          "fulfillment_window_end", "paid_installment_count_at_request",
                          "eligibility_ratio_bps", "trade_in_credit_projection_cents",
                          "projected_rollover_balance_cents", "credit_shortfall_cents",
                          "funding_flag", "status", "additional_down_payment_cents",
                          "expiry_reason", "completed_at")


def upgrade_request(record):
    return _pick(record, UPGRADE_REQUEST_FIELDS, COMMON)


TRADE_IN_FIELDS = ("upgrade_request_id", "device_unit_id", "declared_condition",
                   "credit_estimate_cents", "graded_condition", "credit_final_cents",
                   "diagnostic_result", "latest_report_sequence_no", "credit_variance_cents",
                   "dispute_count", "dispute_reason", "status", "received_at", "graded_at",
                   "settled_at")


def trade_in(record):
    return _pick(record, TRADE_IN_FIELDS, COMMON)


DIAGNOSTIC_REPORT_FIELDS = ("trade_in_id", "sequence_no", "report_type",
                            "technician_user_id", "screen_grade", "battery_health_pct",
                            "water_damage_flag", "functional_pass", "derived_condition",
                            "condition_multiplier_bps", "battery_deduction_cents",
                            "screen_deduction_cents", "computed_credit_cents",
                            "diagnostic_result", "override_reason")


def diagnostic_report(record):
    return _pick(record, DIAGNOSTIC_REPORT_FIELDS, APPEND_ONLY_COMMON)


PAYOFF_QUOTE_FIELDS = ("loan_id", "quote_type", "remaining_principal_cents",
                       "outstanding_late_fee_cents", "unearned_premium_cents",
                       "premium_rebate_cents", "admin_fee_cents", "total_payoff_cents",
                       "past_due_amount_cents", "paid_installment_count_at_quote",
                       "issued_at", "expires_at", "status", "consumed_at")


def payoff_quote(record):
    return _pick(record, PAYOFF_QUOTE_FIELDS, COMMON)


DELINQUENCY_EVENT_FIELDS = ("loan_id", "event_type", "from_state", "to_state",
                            "days_past_due_at_event", "amount_cents", "occurred_at")


def delinquency_event(record):
    return _pick(record, DELINQUENCY_EVENT_FIELDS, APPEND_ONLY_COMMON)
