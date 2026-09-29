"""Entity serialization. Field names and sets follow the scaffold entity tables."""

from calc import account_age_months, num
from responses import iso_ms, iso_seconds
from store import store

COMMON = ("id", "created_at", "updated_at", "version")
LEDGER_COMMON = ("id", "created_at")

_UTC_FIELDS = (
    "computed_from_clock_utc", "closed_at_utc", "guarantee_start_utc", "guarantee_end_utc",
    "replacement_deadline_utc", "holdback_release_utc", "scheduled_holdback_release_utc",
    "settled_at_utc",
)
_RATIO_FIELDS = (
    "verification_variance", "collection_rate", "attrition_pct", "base_multiple",
    "age_adjustment", "effective_multiple", "effective_multiple_at_close",
)


def _emit(record, fields, ledger=False):
    out = {}
    for key in (LEDGER_COMMON if ledger else COMMON):
        value = record.get(key)
        out[key] = iso_ms(value) if key in ("created_at", "updated_at") else value
    for key in fields:
        value = record.get(key)
        if key in _UTC_FIELDS:
            out[key] = iso_seconds(value)
        elif key in _RATIO_FIELDS:
            out[key] = num(value)
        else:
            out[key] = value
    return out


PROFILE_FIELDS = ("state_code", "required_permit_types", "reciprocity_states",
                  "transfer_processing_days", "cooling_off_days", "provisional_operation_allowed")

SELLER_FIELDS = ("legal_name", "state_code", "license_number", "status", "suspension_reason_code")

BUYER_FIELDS = ("legal_name", "state_code", "license_status", "prequalified_amount_cents",
                "qualification_status", "qualified_on")

LISTING_FIELDS = ("seller_id", "region_code", "state_code", "asking_price_cents",
                  "listed_mrr_cents", "listed_account_count", "exclusive_start_date",
                  "exclusive_end_date", "status", "claimed_recurring_mrr_cents",
                  "claimed_repair_mrr_cents", "claimed_account_count",
                  "verified_recurring_mrr_cents", "verified_repair_mrr_cents",
                  "verified_account_count", "verification_posture",
                  "introductions_completed_count", "withdrawal_reason_code")

ACCOUNT_FIELDS = ("listing_id", "deal_id", "replaced_account_id", "customer_ref",
                  "service_start_date", "route_day", "monthly_service_fee_cents",
                  "avg_monthly_chemical_cents", "avg_monthly_repair_cents",
                  "chemical_billing_method", "billing_frequency",
                  "claimed_recurring_mrr_cents", "verified_recurring_mrr_cents",
                  "verified_repair_mrr_cents", "verification_variance",
                  "verification_status", "transfer_status", "account_age_months",
                  "introduction_sequence_no", "introduced_on", "current_mrr_cents",
                  "exclusion_reason_code", "verified_by_user_id")

BILLING_FIELDS = ("account_id", "period_month", "billed_service_cents", "billed_chemical_cents",
                  "billed_repair_cents", "collected_cents", "source", "collection_rate",
                  "recurring_collected_cents", "repair_collected_cents")

VALUATION_FIELDS = ("listing_id", "basis", "recurring_mrr_cents", "repair_mrr_cents",
                    "account_count", "weighted_avg_account_age_months", "base_multiple",
                    "age_adjustment", "effective_multiple", "recurring_component_cents",
                    "repair_component_cents", "valuation_cents", "is_superseded",
                    "computed_from_clock_utc")

DEAL_FIELDS = ("listing_id", "buyer_id", "offer_round", "current_offer_price_cents",
               "financing_type", "down_payment_cents", "note_principal_cents", "lender_name",
               "approved_amount_cents", "retention_guarantee_days", "status", "clawback_status",
               "accepted_on", "closed_at_utc", "guarantee_start_utc", "guarantee_end_utc",
               "replacement_deadline_utc", "holdback_release_utc", "effective_multiple_at_close",
               "commission_cents", "holdback_cents", "escrow_target_amount_cents",
               "clawback_cap_cents", "guaranteed_mrr_cents", "attrited_mrr_cents",
               "retained_mrr_cents", "replacement_mrr_cents", "net_attrition_mrr_cents",
               "allowance_mrr_cents", "attrition_pct", "non_solicitation_executed_on",
               "non_solicitation_end_date", "repricing_reason_code", "termination_reason_code")

ESCROW_FIELDS = ("deal_id", "target_amount_cents", "funded_amount_cents", "holdback_amount_cents",
                 "holdback_balance_cents", "undisbursed_balance_cents", "disbursed_to_broker_cents",
                 "disbursed_to_seller_cents", "disbursed_to_buyer_cents", "status",
                 "funded_by_user_id", "deposits_blocked", "holdback_release_blocked",
                 "scheduled_holdback_release_utc")

TRANSFER_FIELDS = ("deal_id", "state_profile_id", "permit_type", "status", "applied_on",
                   "processing_window_end", "decided_on", "denial_reason_code", "attempt_count",
                   "waiver_basis")

EVENT_FIELDS = ("deal_id", "account_id", "event_type", "effective_date", "mrr_delta_cents",
                "attributed_to", "recorded_by_role")

SETTLEMENT_FIELDS = ("deal_id", "escrow_id", "remedy_basis", "status", "computed_from_clock_utc",
                     "guaranteed_mrr_cents", "lost_natural_mrr_cents", "lost_solicited_mrr_cents",
                     "lost_buyer_fault_mrr_cents", "recovered_mrr_cents",
                     "replacement_credit_cap_cents", "replacement_credit_mrr_cents",
                     "allowance_mrr_cents", "compensable_natural_mrr_cents",
                     "compensable_solicited_mrr_cents", "raw_adjustment_cents",
                     "adjustment_cents", "from_holdback_cents", "from_note_principal_cents",
                     "seller_direct_due_cents", "holdback_release_to_seller_cents",
                     "dispute_reason_code", "settled_at_utc")


def profile_json(record):
    return _emit(record, PROFILE_FIELDS)


def seller_json(record):
    return _emit(record, SELLER_FIELDS)


def buyer_json(record):
    return _emit(record, BUYER_FIELDS)


def listing_json(record):
    return _emit(record, LISTING_FIELDS)


def account_json(record):
    out = _emit(record, ACCOUNT_FIELDS)
    # account_age_months is evaluated lazily against the logical clock.
    out["account_age_months"] = account_age_months(store.clock, record["service_start_date"])
    return out


def billing_json(record):
    return _emit(record, BILLING_FIELDS, ledger=True)


def valuation_json(record):
    return _emit(record, VALUATION_FIELDS)


def deal_json(record):
    return _emit(record, DEAL_FIELDS)


def escrow_json(record):
    return _emit(record, ESCROW_FIELDS)


def transfer_json(record):
    return _emit(record, TRANSFER_FIELDS)


def event_json(record):
    return _emit(record, EVENT_FIELDS, ledger=True)


def settlement_json(record):
    return _emit(record, SETTLEMENT_FIELDS)
