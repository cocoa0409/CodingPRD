"""Entity -> JSON projections.

Field sets follow SCAFFOLD.yaml `entities` exactly.  Non-monetary numerics
(rebate_pct, expected_breakage_rate) are emitted as JSON numbers preserving
caller precision (PRD 2.5); money is always integer cents.

PRD 2.4: ReceiptLine, SubmissionLine and CreditLedgerEntry carry only `id`
and `created_at` (no updated_at / version).
"""

from decimal import Decimal

STORE_FIELDS = [
    "id", "store_code", "submission_window_days", "certificate_validity_months",
    "expected_breakage_rate", "split_txn_window_hours", "split_txn_min_receipts",
    "outstanding_liability_cents", "net_liability_cents",
    "accrued_breakage_income_cents", "liability_epoch",
    "created_at", "updated_at", "version",
]

PROGRAM_FIELDS = [
    "id", "store_id", "name", "week_start_date", "week_end_date", "status",
    "created_at", "updated_at", "version",
]

PROGRAM_ITEM_FIELDS = [
    "id", "program_id", "store_id", "sku", "rebate_pct", "excluded_categories",
    "min_quantity", "per_receipt_cap_cents",
    "created_at", "updated_at", "version",
]

ACCOUNT_FIELDS = [
    "id", "store_id", "owner_name", "account_type", "status",
    "credit_balance_cents", "pending_award_cents", "lifetime_rebate_cents",
    "created_at", "updated_at", "version",
]

JOB_FIELDS = [
    "id", "store_id", "contractor_account_id", "job_reference", "status",
    "created_at", "updated_at", "version",
]

RECEIPT_FIELDS = [
    "id", "store_id", "receipt_number", "account_id", "job_purchase_id",
    "purchase_at", "status", "total_cents",
    "created_at", "updated_at", "version",
]

RECEIPT_LINE_FIELDS = [
    "id", "receipt_id", "store_id", "line_number", "sku", "category",
    "quantity", "unit_price_cents", "returned_quantity", "tender_splits",
    "certificate_tendered_cents",
    "created_at",
]

RETURN_FIELDS = [
    "id", "store_id", "receipt_id", "lines", "processed_at",
    "reversal_entry_ids",
    "created_at", "updated_at", "version",
]

SUBMISSION_FIELDS = [
    "id", "store_id", "account_id", "receipt_id", "status",
    "provisional_award_cents", "award_cents", "rejection_reason",
    "submitted_at", "resubmit_count",
    "created_at", "updated_at", "version",
]

SUBMISSION_LINE_FIELDS = [
    "id", "submission_id", "store_id", "receipt_line_id", "program_item_id",
    "eligible_base_cents", "awarded_cents", "exclusion_reason",
    "created_at",
]

CERTIFICATE_FIELDS = [
    "id", "store_id", "account_id", "submission_id", "issued_amount_cents",
    "remaining_balance_cents", "status", "fraud_hold", "issued_at",
    "expires_at", "reissued_from_id",
    "created_at", "updated_at", "version",
]

LEDGER_ENTRY_FIELDS = [
    "id", "store_id", "account_id", "certificate_id", "entry_type",
    "amount_cents", "liability_epoch", "created_note",
    "created_at",
]

FLAG_FIELDS = [
    "id", "store_id", "account_id", "flag_type", "status", "receipt_ids",
    "detail",
    "created_at", "updated_at", "version",
]

BREAKAGE_RUN_FIELDS = [
    "id", "store_id", "status", "run_at", "expired_count",
    "breakage_recognized_cents", "epoch",
    "created_at", "updated_at", "version",
]


def _jsonable(value):
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, list):
        return [_jsonable(v) for v in value]
    if isinstance(value, dict):
        return {k: _jsonable(v) for k, v in value.items()}
    return value


def _project(rec, fields):
    return {name: _jsonable(rec.get(name)) for name in fields}


def store_out(rec):
    return _project(rec, STORE_FIELDS)


def program_out(rec):
    return _project(rec, PROGRAM_FIELDS)


def program_item_out(rec):
    return _project(rec, PROGRAM_ITEM_FIELDS)


def account_out(rec):
    return _project(rec, ACCOUNT_FIELDS)


def job_out(rec):
    return _project(rec, JOB_FIELDS)


def receipt_out(rec):
    return _project(rec, RECEIPT_FIELDS)


def receipt_line_out(rec):
    return _project(rec, RECEIPT_LINE_FIELDS)


def return_out(rec):
    return _project(rec, RETURN_FIELDS)


def submission_out(rec):
    return _project(rec, SUBMISSION_FIELDS)


def submission_line_out(rec):
    return _project(rec, SUBMISSION_LINE_FIELDS)


def certificate_out(rec):
    return _project(rec, CERTIFICATE_FIELDS)


def ledger_entry_out(rec):
    return _project(rec, LEDGER_ENTRY_FIELDS)


def flag_out(rec):
    return _project(rec, FLAG_FIELDS)


def breakage_run_out(rec):
    return _project(rec, BREAKAGE_RUN_FIELDS)
