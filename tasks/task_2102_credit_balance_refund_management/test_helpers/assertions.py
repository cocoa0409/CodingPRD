"""Entity assertions and domain invariant checkers."""
from datetime import datetime, timezone

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid


# --- Instant helpers ---------------------------------------------------------

def parse_instant(value: str) -> datetime:
    """Parse an ISO 8601 UTC instant, tolerating both 'Z' and '+00:00' spellings."""
    assert isinstance(value, str) and value, f"expected an ISO 8601 instant, got {value!r}"
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    parsed = datetime.fromisoformat(text)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def assert_instant_equals(actual, expected_iso: str, label: str = "instant"):
    """Assert that `actual` names the same UTC instant as `expected_iso`."""
    assert actual is not None, f"{label} must not be null (expected {expected_iso})"
    assert parse_instant(actual) == parse_instant(expected_iso), (
        f"Expected {label} == {expected_iso}, got {actual}"
    )


def assert_common_fields(data: dict, label: str = "resource"):
    """id + created_at + updated_at + version, per PRD section 2.4."""
    assert is_valid_uuid(data.get("id", "")), f"{label}.id must be a UUID: {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"{label}.created_at must be an ISO 8601 timestamp: {data.get('created_at')!r}"
    )
    assert is_iso8601_timestamp(data.get("updated_at", "")), (
        f"{label}.updated_at must be an ISO 8601 timestamp: {data.get('updated_at')!r}"
    )
    assert isinstance(data.get("version"), int), f"{label}.version must be an integer"
    assert data["version"] >= 1, f"{label}.version starts at 1"


def assert_audit_record_fields(data: dict, label: str = "audit record"):
    """Immutable audit records carry only id and created_at."""
    assert is_valid_uuid(data.get("id", "")), f"{label}.id must be a UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"{label}.created_at must be an ISO 8601 timestamp"
    )
    assert "version" not in data, f"{label} must not expose a version field"
    assert "updated_at" not in data, f"{label} must not expose an updated_at field"


# --- Per-entity assertions ---------------------------------------------------

def assert_payer(data: dict):
    assert_common_fields(data, "Payer")
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["payer_code"], str) and 2 <= len(data["payer_code"]) <= 16
    assert data["payer_type"] in (
        "MEDICARE", "MEDICAID", "COMMERCIAL", "TRICARE", "SELF_PAY"
    )
    assert isinstance(data["take_back_allowed"], bool)
    assert isinstance(data["refund_remit_days"], int)


def assert_patient_account(data: dict):
    assert_common_fields(data, "PatientAccount")
    assert isinstance(data["account_number"], str) and data["account_number"]
    assert isinstance(data["mrn"], str)
    assert isinstance(data["patient_name"], str)
    assert data["guarantor_state_code"] in ("CA", "TX", "NY", "FL")
    assert is_valid_uuid(data.get("primary_payer_id", ""))
    assert data["financial_class"] in ("INPATIENT", "OUTPATIENT", "EMERGENCY")
    assert isinstance(data["balance_cents"], int)
    assert isinstance(data["credit_balance_cents"], int)
    assert data["status"] in ("OPEN", "CLOSED", "BAD_DEBT")


def assert_account_transaction(data: dict):
    assert_audit_record_fields(data, "AccountTransaction")
    assert is_valid_uuid(data.get("account_id", ""))
    assert data["txn_type"] in (
        "CHARGE", "PAYMENT", "CONTRACTUAL_ADJUSTMENT", "REFUND_DISBURSEMENT",
        "TAKE_BACK_OFFSET", "ESCHEAT_REMITTANCE", "REVERSAL",
    )
    assert isinstance(data["amount_cents"], int)
    assert data["source"] in ("PATIENT", "PAYER", "SYSTEM")
    assert is_iso8601_timestamp(data.get("posted_at", ""))
    assert isinstance(data["is_reversed"], bool)


def assert_credit_balance(data: dict):
    assert_common_fields(data, "CreditBalance")
    assert is_valid_uuid(data.get("account_id", ""))
    assert is_valid_uuid(data.get("payer_id", ""))
    assert isinstance(data["credit_amount_cents"], int) and data["credit_amount_cents"] > 0
    assert is_iso8601_timestamp(data.get("identified_at", ""))
    assert data.get("attribution_method") in (None, "PROPORTIONAL", "REVERSE_CHRONOLOGICAL")
    assert data.get("attribution") in (None, "PATIENT", "PAYER", "SPLIT", "UNDETERMINED")
    for field in (
        "patient_portion_cents", "payer_portion_cents", "refunded_cents",
        "offset_cents", "outstanding_cents", "aging_days",
    ):
        assert isinstance(data[field], int), f"CreditBalance.{field} must be an integer"
    assert data["aging_bucket"] in ("D0_30", "D31_60", "D61_90", "D91_180", "OVER_180")
    assert isinstance(data["root_cause_confirmed"], bool)
    assert data["status"] in (
        "IDENTIFIED", "UNDER_REVIEW", "ATTRIBUTED", "REFUND_PENDING", "REFUNDED",
        "RESOLVED_BY_OFFSET", "ESCHEATED", "WRITTEN_OFF",
    )


def assert_refund_request(data: dict):
    assert_common_fields(data, "RefundRequest")
    assert is_valid_uuid(data.get("credit_balance_id", ""))
    assert isinstance(data["requested_amount_cents"], int)
    assert isinstance(data["approved_amount_cents"], int)
    assert data["payee_type"] in ("PATIENT", "PAYER")
    assert data["payee_state_code"] in ("CA", "TX", "NY", "FL")
    assert isinstance(data["prepared_by_user_id"], str) and data["prepared_by_user_id"]
    assert data["required_approval_tier"] in (1, 2, 3)
    assert data["required_approval_count"] in (1, 2)
    assert isinstance(data["approvals_received"], int)
    assert isinstance(data["revision_count"], int)
    assert data["approval_state"] in (
        "DRAFT", "SUBMITTED", "APPROVED", "REJECTED", "RETURNED_FOR_REVISION", "CANCELLED"
    )
    assert data["disbursement_state"] in (
        "NOT_SCHEDULED", "BATCHED", "ISSUED", "CLEARED", "REISSUE_PENDING", "VOID_CLOSED"
    )


def assert_refund_approval(data: dict):
    assert_audit_record_fields(data, "RefundApproval")
    assert is_valid_uuid(data.get("refund_request_id", ""))
    assert isinstance(data["approver_user_id"], str) and data["approver_user_id"]
    assert data["approver_tier"] in (1, 2, 3)
    assert data["decision"] in ("APPROVED", "REJECTED", "RETURNED")
    assert is_iso8601_timestamp(data.get("decided_at", ""))


def assert_refund_batch(data: dict):
    assert_common_fields(data, "RefundBatch")
    assert isinstance(data["batch_number"], str) and data["batch_number"]
    assert data["bank_account_code"] in ("OPERATING", "TRUST", "ESCROW")
    assert is_iso8601_timestamp(data.get("cutoff_at", ""))
    assert is_iso8601_timestamp(data.get("scheduled_run_at", ""))
    for field in ("item_count", "total_gross_cents", "total_fee_cents", "total_net_cents"):
        assert isinstance(data[field], int)
    assert data["state"] in ("OPEN", "LOCKED", "ISSUED", "CLOSED")


def assert_check_disbursement(data: dict):
    assert_common_fields(data, "CheckDisbursement")
    assert is_valid_uuid(data.get("refund_request_id", ""))
    assert is_valid_uuid(data.get("refund_batch_id", ""))
    for field in ("gross_amount_cents", "processing_fee_cents", "net_check_amount_cents"):
        assert isinstance(data[field], int)
    assert data["net_check_amount_cents"] == (
        data["gross_amount_cents"] - data["processing_fee_cents"]
    ), "net_check_amount_cents is gross_amount_cents minus processing_fee_cents"
    assert data["payee_state_code"] in ("CA", "TX", "NY", "FL")
    assert data["state"] in (
        "PENDING", "ISSUED", "CLEARED", "VOIDED", "STALE", "REISSUED", "ESCHEATED"
    )


def assert_take_back_notice(data: dict):
    assert_common_fields(data, "TakeBackNotice")
    assert is_valid_uuid(data.get("payer_id", ""))
    assert isinstance(data["notice_number"], str) and data["notice_number"]
    for field in (
        "total_recoup_cents", "admin_fee_cents", "applied_cents",
        "remaining_unapplied_cents",
    ):
        assert isinstance(data[field], int)
    assert is_iso8601_timestamp(data.get("received_at", ""))
    assert is_iso8601_timestamp(data.get("dispute_deadline_at", ""))
    assert data["state"] in (
        "RECEIVED", "PARTIALLY_APPLIED", "FULLY_APPLIED", "DISPUTED", "WITHDRAWN"
    )


def assert_offset_application(data: dict):
    assert_common_fields(data, "OffsetApplication")
    assert is_valid_uuid(data.get("take_back_notice_id", ""))
    assert is_valid_uuid(data.get("account_id", ""))
    assert is_valid_uuid(data.get("credit_balance_id", ""))
    for field in ("applied_cents", "admin_fee_share_cents", "sequence"):
        assert isinstance(data[field], int)
    assert data["applied_cents"] > 0, "no zero-cent offset rows are ever written"
    assert data["sequence"] >= 1
    assert data["state"] in ("APPLIED", "REVERSED")


def assert_medicare_obligation(data: dict):
    assert_common_fields(data, "MedicareRepaymentObligation")
    assert is_valid_uuid(data.get("credit_balance_id", ""))
    assert is_valid_uuid(data.get("payer_id", ""))
    assert is_iso8601_timestamp(data.get("identified_at", ""))
    assert is_iso8601_timestamp(data.get("due_at", ""))
    for field in ("reportable_amount_cents", "days_elapsed", "days_late", "penalty_cents"):
        assert isinstance(data[field], int)
    assert data["state"] in (
        "OPEN", "LATE", "REPORTED", "REPORTED_LATE", "SATISFIED", "SATISFIED_LATE",
        "SATISFIED_BY_OFFSET",
    )
    assert data.get("satisfaction_mode") in (None, "REFUND_CHECK", "OFFSET", "WRITE_OFF")


def assert_escheatment_record(data: dict):
    assert_common_fields(data, "EscheatmentRecord")
    assert is_valid_uuid(data.get("check_disbursement_id", ""))
    assert data["basis"] in ("ISSUE_DATE", "LAST_CONTACT")
    assert data["state_code"] in ("CA", "TX", "NY", "FL")
    assert isinstance(data["dormancy_days"], int)
    assert is_iso8601_timestamp(data.get("dormancy_start_at", ""))
    assert is_iso8601_timestamp(data.get("escheat_due_at", ""))
    assert is_iso8601_timestamp(data.get("due_diligence_open_at", ""))
    assert isinstance(data["remitted_amount_cents"], int)
    assert data["state"] in (
        "DORMANT", "DUE_DILIGENCE_SENT", "CLAIMED", "REMITTED", "EXEMPT"
    )


def assert_compliance_report(data: dict):
    assert_common_fields(data, "ComplianceReport")
    assert data["report_type"] in (
        "CREDIT_BALANCE_LIABILITY", "MEDICARE_CBR", "ESCHEAT_HOLDER_REPORT"
    )
    assert isinstance(data["scope_code"], str) and data["scope_code"]
    for field in (
        "total_liability_cents", "patient_liability_cents", "payer_liability_cents",
        "medicare_at_risk_cents", "over_180_count", "line_count",
    ):
        assert isinstance(data[field], int)
    assert data["state"] in ("DRAFT", "FINALIZED")


# --- Domain invariants -------------------------------------------------------

def assert_credit_liability_invariant(credit_balance: dict):
    """credit_amount_cents == refunded_cents + offset_cents + outstanding_cents."""
    total = (
        credit_balance["refunded_cents"]
        + credit_balance["offset_cents"]
        + credit_balance["outstanding_cents"]
    )
    assert credit_balance["credit_amount_cents"] == total, (
        "credit_amount_cents must equal refunded_cents + offset_cents + "
        f"outstanding_cents, got {credit_balance['credit_amount_cents']} != {total}"
    )


def assert_recoupment_invariant(notice: dict):
    """total_recoup_cents == applied_cents + remaining_unapplied_cents."""
    total = notice["applied_cents"] + notice["remaining_unapplied_cents"]
    assert notice["total_recoup_cents"] == total, (
        "total_recoup_cents must equal applied_cents + remaining_unapplied_cents, "
        f"got {notice['total_recoup_cents']} != {total}"
    )


def assert_ledger_invariant(account: dict, transactions: list):
    """balance_cents is the plain sum of amount_cents over every row on the account."""
    total = sum(txn["amount_cents"] for txn in transactions)
    assert account["balance_cents"] == total, (
        f"balance_cents must equal the sum of every posting ({total}), "
        f"got {account['balance_cents']}"
    )


def assert_attribution_portions_sum(credit_balance: dict):
    """patient_portion_cents + payer_portion_cents == credit_amount_cents."""
    total = credit_balance["patient_portion_cents"] + credit_balance["payer_portion_cents"]
    assert total == credit_balance["credit_amount_cents"], (
        "the two portions always sum exactly to credit_amount_cents, got "
        f"{total} != {credit_balance['credit_amount_cents']}"
    )
