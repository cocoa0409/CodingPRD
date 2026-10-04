"""Entity assertions and domain invariant checkers (PRD §2.4, §3)."""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid


def _assert_common(data: dict):
    assert is_valid_uuid(data.get("id", "")), (
        f"id must be a valid UUID, got {data.get('id')!r}"
    )
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        "created_at must be ISO 8601"
    )
    assert is_iso8601_timestamp(data.get("updated_at", "")), (
        "updated_at must be ISO 8601"
    )
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        f"version must be a positive integer, got {data.get('version')!r}"
    )


def _assert_append_only(data: dict):
    """Append-only / line-level records carry only id + created_at."""
    assert is_valid_uuid(data.get("id", "")), (
        f"id must be a valid UUID, got {data.get('id')!r}"
    )
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        "created_at must be ISO 8601"
    )
    assert "updated_at" not in data, "append-only records carry no updated_at"
    assert "version" not in data, "append-only records carry no version"


def assert_store(data: dict):
    _assert_common(data)
    assert isinstance(data["store_code"], str) and data["store_code"]
    assert isinstance(data["submission_window_days"], int)
    assert isinstance(data["certificate_validity_months"], int)
    assert isinstance(data["expected_breakage_rate"], (int, float))
    assert 0 <= data["expected_breakage_rate"] <= 1
    assert isinstance(data["split_txn_window_hours"], int)
    assert isinstance(data["split_txn_min_receipts"], int)
    for f in ("outstanding_liability_cents", "net_liability_cents",
              "accrued_breakage_income_cents", "liability_epoch"):
        assert isinstance(data[f], int), f"{f} must be integer cents"
        assert data[f] >= 0, f"{f} must be non-negative"


def assert_program(data: dict):
    _assert_common(data)
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["week_start_date"], str)
    assert isinstance(data["week_end_date"], str)
    assert data["status"] in ["DRAFT", "ACTIVE", "CLOSED"]


def assert_program_item(data: dict):
    _assert_common(data)
    assert isinstance(data["program_id"], str) and data["program_id"]
    assert isinstance(data["sku"], str) and data["sku"]
    assert isinstance(data["rebate_pct"], (int, float))
    assert 0 < data["rebate_pct"] <= 1
    assert isinstance(data["excluded_categories"], list)
    assert isinstance(data["min_quantity"], int) and data["min_quantity"] >= 1
    cap = data.get("per_receipt_cap_cents")
    assert cap is None or (isinstance(cap, int) and cap > 0), (
        "per_receipt_cap_cents must be null or a positive integer"
    )


def assert_account(data: dict):
    _assert_common(data)
    assert isinstance(data["owner_name"], str) and data["owner_name"]
    assert data["account_type"] in ["RETAIL", "CONTRACTOR"]
    assert data["status"] in ["ACTIVE", "FROZEN", "CLOSED"]
    for f in ("credit_balance_cents", "pending_award_cents",
              "lifetime_rebate_cents"):
        assert isinstance(data[f], int), f"{f} must be integer cents"
        assert data[f] >= 0, f"{f} must be non-negative"


def assert_job_purchase(data: dict):
    _assert_common(data)
    assert isinstance(data["contractor_account_id"], str)
    assert isinstance(data["job_reference"], str) and data["job_reference"]
    assert data["status"] in ["OPEN", "SETTLED"]


def assert_receipt(data: dict):
    _assert_common(data)
    assert isinstance(data["store_id"], str) and data["store_id"]
    assert isinstance(data["receipt_number"], str) and data["receipt_number"]
    assert isinstance(data["account_id"], str) and data["account_id"]
    assert data.get("job_purchase_id") is None or isinstance(
        data["job_purchase_id"], str
    )
    assert isinstance(data["purchase_at"], str)
    assert data["status"] in ["OPEN", "PARTIALLY_RETURNED", "FULLY_RETURNED"]
    assert isinstance(data["total_cents"], int) and data["total_cents"] >= 0


def assert_receipt_line(data: dict):
    _assert_append_only(data)
    assert isinstance(data["receipt_id"], str) and data["receipt_id"]
    assert isinstance(data["line_number"], int) and data["line_number"] >= 1
    assert isinstance(data["sku"], str) and data["sku"]
    assert isinstance(data["category"], str)
    assert isinstance(data["quantity"], int) and data["quantity"] >= 1
    assert isinstance(data["unit_price_cents"], int) and data["unit_price_cents"] >= 0
    assert isinstance(data["returned_quantity"], int)
    assert 0 <= data["returned_quantity"] <= data["quantity"]
    assert isinstance(data["tender_splits"], list)
    assert isinstance(data["certificate_tendered_cents"], int)


def assert_return(data: dict):
    _assert_common(data)
    assert isinstance(data["receipt_id"], str) and data["receipt_id"]
    assert isinstance(data["lines"], list) and data["lines"]
    assert isinstance(data["processed_at"], str)
    assert isinstance(data["reversal_entry_ids"], list)


def assert_submission(data: dict):
    _assert_common(data)
    assert isinstance(data["account_id"], str) and data["account_id"]
    assert isinstance(data["receipt_id"], str) and data["receipt_id"]
    assert data["status"] in [
        "SUBMITTED", "UNDER_REVIEW", "APPROVED", "REJECTED", "REVERSED",
    ]
    assert isinstance(data["provisional_award_cents"], int)
    assert data.get("award_cents") is None or isinstance(data["award_cents"], int)
    assert data.get("rejection_reason") is None or isinstance(
        data["rejection_reason"], str
    )
    assert isinstance(data["submitted_at"], str)
    assert isinstance(data["resubmit_count"], int) and data["resubmit_count"] >= 0


def assert_submission_line(data: dict):
    _assert_append_only(data)
    assert isinstance(data["submission_id"], str) and data["submission_id"]
    assert isinstance(data["receipt_line_id"], str) and data["receipt_line_id"]
    assert data.get("program_item_id") is None or isinstance(
        data["program_item_id"], str
    )
    assert isinstance(data["eligible_base_cents"], int)
    assert isinstance(data["awarded_cents"], int) and data["awarded_cents"] >= 0
    assert data.get("exclusion_reason") in [
        None, "NO_PROGRAM_ITEM", "EXCLUDED_CATEGORY", "BELOW_MIN_QUANTITY",
        "FULLY_CERTIFICATE_TENDERED", "FULLY_RETURNED",
    ]


def assert_certificate(data: dict):
    _assert_common(data)
    assert isinstance(data["account_id"], str) and data["account_id"]
    assert isinstance(data["store_id"], str) and data["store_id"]
    assert isinstance(data["issued_amount_cents"], int)
    assert isinstance(data["remaining_balance_cents"], int)
    assert 0 <= data["remaining_balance_cents"] <= data["issued_amount_cents"]
    assert data["status"] in [
        "ACTIVE", "PARTIALLY_REDEEMED", "FULLY_REDEEMED", "EXPIRED",
        "REISSUED", "VOIDED",
    ]
    assert data["fraud_hold"] in ["NONE", "HELD", "RELEASED"]
    assert isinstance(data["issued_at"], str)
    assert isinstance(data["expires_at"], str)
    assert data.get("reissued_from_id") is None or isinstance(
        data["reissued_from_id"], str
    )


def assert_ledger_entry(data: dict):
    _assert_append_only(data)
    assert isinstance(data["account_id"], str) and data["account_id"]
    assert isinstance(data["certificate_id"], str) and data["certificate_id"]
    assert data["entry_type"] in [
        "ISSUANCE_ACCRUAL", "REDEMPTION", "REVERSAL_DEBIT",
        "BREAKAGE_EXPIRY", "REISSUE_CREDIT",
    ]
    assert isinstance(data["amount_cents"], int)
    assert isinstance(data["liability_epoch"], int)
    assert isinstance(data["created_note"], str)


def assert_fraud_flag(data: dict):
    _assert_common(data)
    assert isinstance(data["account_id"], str) and data["account_id"]
    assert data["flag_type"] in ["SPLIT_TRANSACTION", "DUPLICATE_RECEIPT"]
    assert data["status"] in ["OPEN", "CONFIRMED", "CLEARED"]
    assert isinstance(data["receipt_ids"], list)
    assert isinstance(data["detail"], str)


def assert_breakage_run(data: dict):
    _assert_common(data)
    assert isinstance(data["store_id"], str) and data["store_id"]
    assert data["status"] in ["RUNNING", "COMPLETED"]
    assert isinstance(data["run_at"], str)
    assert isinstance(data["expired_count"], int) and data["expired_count"] >= 0
    assert isinstance(data["breakage_recognized_cents"], int)
    assert data["breakage_recognized_cents"] >= 0
    assert isinstance(data["epoch"], int) and data["epoch"] >= 1


def assert_account_invariants(data: dict):
    """Domain invariants on an account after any operation."""
    assert data["credit_balance_cents"] >= 0
    assert data["pending_award_cents"] >= 0
    assert data["lifetime_rebate_cents"] >= 0


def assert_store_liability_invariants(data: dict):
    """Domain invariants on a store after any operation: the net variant never
    exceeds the gross variant, and breakage income is non-negative."""
    assert data["outstanding_liability_cents"] >= 0
    assert data["net_liability_cents"] >= 0
    assert data["net_liability_cents"] <= data["outstanding_liability_cents"]
    assert data["accrued_breakage_income_cents"] >= 0
    assert data["liability_epoch"] >= 0
