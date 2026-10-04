"""Entity assertions and domain invariant checkers (PRD §2.5, §2.10, §3).

Field names are PRD-exact. Common-field checks follow PRD §2.5: every primary
resource carries id/created_at/updated_at/version; the append-only ledger
(FundingTransaction) carries ONLY id/created_at and must NOT carry
updated_at/version.
"""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

from .types import (
    AccountStatus,
    BlockStatus,
    CallStatus,
    CallType,
    CommissionBasis,
    ComplaintCategory,
    ComplaintStatus,
    CutoffReason,
    EscheatStatus,
    FacilityStatus,
    FundingModel,
    InmateStatus,
    LedgerEntryType,
    MessageStatus,
    PrivilegeStatus,
    RateScheduleStatus,
    RecordingStatus,
    RefundMethod,
    RefundSource,
    RefundStatus,
    RelationshipType,
    ContractStatus,
    VerificationStatus,
    VideoSessionStatus,
)


def _values(enum_cls):
    return [member.value for member in enum_cls]


def _assert_common_fields(data, label):
    assert is_valid_uuid(data.get("id", "")), f"{label}.id must be a valid UUID"
    assert is_iso8601_timestamp(
        data.get("created_at", "")
    ), f"{label}.created_at must be ISO 8601"
    assert is_iso8601_timestamp(
        data.get("updated_at", "")
    ), f"{label}.updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), f"{label}.version must be an int"


def _assert_optional_timestamp(data, field, label):
    value = data.get(field)
    assert value is None or is_iso8601_timestamp(
        value
    ), f"{label}.{field} must be null or ISO 8601"


def assert_facility(data: dict):
    _assert_common_fields(data, "Facility")
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["state_code"], str) and data["state_code"]
    assert isinstance(data["video_booth_count"], int)
    assert isinstance(data["video_turnover_minutes"], int)
    assert isinstance(data["max_session_minutes"], int)
    assert isinstance(data["visiting_open_minutes"], int)
    assert isinstance(data["visiting_close_minutes"], int)
    assert isinstance(data["daily_session_limit_per_inmate"], int)
    assert data["status"] in _values(FacilityStatus)


def assert_regulatory_cap(data: dict):
    _assert_common_fields(data, "RegulatoryCap")
    assert isinstance(data["state_code"], str) and data["state_code"]
    assert isinstance(data["max_per_minute_cents"], int)
    assert isinstance(data["max_connection_fee_cents"], int)
    assert isinstance(data["max_ancillary_fee_cents"], int)
    assert isinstance(data["max_deposit_fee_cents"], int)
    assert isinstance(data["max_commission_pct"], (int, float))
    assert data["refund_method"] in _values(RefundMethod)
    assert isinstance(data["dormancy_days"], int)
    assert isinstance(data["claim_window_days"], int)


def assert_contract(data: dict):
    _assert_common_fields(data, "FacilityContract")
    assert is_valid_uuid(data.get("facility_id", ""))
    assert isinstance(data["commission_pct"], (int, float))
    assert data["commission_basis"] in _values(CommissionBasis)
    assert isinstance(data["deposit_fee_cents"], int)
    assert isinstance(data["closure_fee_cents"], int)
    assert is_iso8601_timestamp(data["effective_from"])
    _assert_optional_timestamp(data, "effective_to", "FacilityContract")
    assert data["status"] in _values(ContractStatus)


def assert_rate_schedule(data: dict):
    _assert_common_fields(data, "RateSchedule")
    assert is_valid_uuid(data.get("contract_id", ""))
    for field in (
        "local_per_minute_cents",
        "intrastate_per_minute_cents",
        "interstate_per_minute_cents",
        "international_per_minute_cents",
        "connection_fee_cents",
        "message_price_cents",
        "video_session_fee_cents",
    ):
        assert isinstance(data[field], int), f"RateSchedule.{field} must be an int"
    assert data["status"] in _values(RateScheduleStatus)
    _assert_optional_timestamp(data, "activated_at", "RateSchedule")


def assert_inmate(data: dict):
    _assert_common_fields(data, "Inmate")
    assert is_valid_uuid(data.get("facility_id", ""))
    assert isinstance(data["booking_number"], str) and data["booking_number"]
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert data["status"] in _values(InmateStatus)
    _assert_optional_timestamp(data, "released_at", "Inmate")


def assert_account(data: dict):
    _assert_common_fields(data, "Account")
    assert is_valid_uuid(data.get("facility_id", ""))
    assert is_valid_uuid(data.get("inmate_id", ""))
    assert data["funding_model"] in _values(FundingModel)
    assert isinstance(data["owner_name"], str) and data["owner_name"]
    assert isinstance(data["owner_contact"], str) and data["owner_contact"]
    assert data["status"] in _values(AccountStatus)
    assert data["escheat_status"] in _values(EscheatStatus)
    assert isinstance(data["balance_cents"], int)
    assert isinstance(data["retained_fees_cents"], int)
    assert isinstance(data["refunded_total_cents"], int)
    assert isinstance(data["escheated_total_cents"], int)
    assert isinstance(data["unclaimed_balance_cents"], int)
    _assert_optional_timestamp(data, "closed_at", "Account")
    _assert_optional_timestamp(data, "unclaimed_since", "Account")
    _assert_optional_timestamp(data, "escheat_notice_sent_at", "Account")
    for field in ("balance_at_closure_cents", "refundable_computed_cents"):
        value = data.get(field)
        assert value is None or isinstance(
            value, int
        ), f"Account.{field} must be null or an int"
    latest = data.get("latest_refund_request_id")
    assert latest is None or is_valid_uuid(
        latest
    ), "Account.latest_refund_request_id must be null or a UUID"


def assert_funding_transaction(data: dict):
    """Ledger rows are append-only: id + created_at only (PRD §2.5)."""
    assert is_valid_uuid(data.get("id", "")), "FundingTransaction.id must be a UUID"
    assert is_iso8601_timestamp(
        data.get("created_at", "")
    ), "FundingTransaction.created_at must be ISO 8601"
    assert (
        "updated_at" not in data
    ), "append-only ledger rows must not carry updated_at (PRD §2.5)"
    assert (
        "version" not in data
    ), "append-only ledger rows must not carry version (PRD §2.5)"
    assert is_valid_uuid(data.get("account_id", ""))
    assert data["type"] in _values(LedgerEntryType)
    assert isinstance(data["amount_cents"], int)
    reference = data.get("reference_id")
    assert reference is None or isinstance(reference, str)
    assert isinstance(data.get("note"), str)


def assert_recipient_number(data: dict):
    _assert_common_fields(data, "RecipientNumber")
    assert is_valid_uuid(data.get("account_id", ""))
    assert isinstance(data["e164_number"], str) and data["e164_number"]
    assert isinstance(data["label"], str) and data["label"]
    assert data["relationship_type"] in _values(RelationshipType)
    assert data["verification_status"] in _values(VerificationStatus)
    assert data["block_status"] in _values(BlockStatus)
    assert data["privilege_status"] in _values(PrivilegeStatus)
    assert isinstance(data["consent_to_recording"], bool)
    code = data.get("verification_code")
    assert code is None or (
        isinstance(code, str) and len(code) == 6 and code.isdigit()
    ), "verification_code must be a six-digit string when present"


def assert_call_record(data: dict):
    _assert_common_fields(data, "CallRecord")
    assert is_valid_uuid(data.get("account_id", ""))
    assert is_valid_uuid(data.get("inmate_id", ""))
    assert is_valid_uuid(data.get("facility_id", ""))
    assert is_valid_uuid(data.get("recipient_number_id", ""))
    assert is_valid_uuid(data.get("rate_schedule_id", ""))
    assert data["call_type"] in _values(CallType)
    assert data["status"] in _values(CallStatus)
    assert isinstance(data["applied_per_minute_cents"], int)
    assert isinstance(data["applied_connection_fee_cents"], int)
    assert is_iso8601_timestamp(data["connected_at"])
    assert data["cutoff_reason"] in _values(CutoffReason)
    assert data["recording_status"] in _values(RecordingStatus)
    _assert_optional_timestamp(data, "ended_at", "CallRecord")
    for field in ("billable_minutes", "total_charge_cents"):
        value = data.get(field)
        assert value is None or isinstance(
            value, int
        ), f"CallRecord.{field} must be null or an int"


def assert_video_session(data: dict):
    _assert_common_fields(data, "VideoSession")
    assert is_valid_uuid(data.get("facility_id", ""))
    assert is_valid_uuid(data.get("inmate_id", ""))
    assert is_valid_uuid(data.get("account_id", ""))
    assert isinstance(data["visitor_name"], str) and data["visitor_name"]
    assert is_iso8601_timestamp(data["scheduled_start"])
    assert is_iso8601_timestamp(data["scheduled_end"])
    assert isinstance(data["duration_minutes"], int) and data["duration_minutes"] > 0
    assert data["status"] in _values(VideoSessionStatus)
    charge = data.get("charge_cents")
    assert charge is None or isinstance(charge, int)
    for field in ("confirmed_at", "cancelled_at", "closed_out_at"):
        _assert_optional_timestamp(data, field, "VideoSession")


def assert_tablet_message(data: dict):
    _assert_common_fields(data, "TabletMessage")
    assert is_valid_uuid(data.get("account_id", ""))
    assert is_valid_uuid(data.get("inmate_id", ""))
    assert is_valid_uuid(data.get("facility_id", ""))
    assert isinstance(data["body_text"], str)
    assert len(data["body_text"]) <= 1000
    assert isinstance(data["price_cents"], int)
    assert data["status"] in _values(MessageStatus)
    _assert_optional_timestamp(data, "reviewed_at", "TabletMessage")


def assert_refund_request(data: dict):
    _assert_common_fields(data, "RefundRequest")
    assert is_valid_uuid(data.get("account_id", ""))
    assert data["source"] in _values(RefundSource)
    assert data["status"] in _values(RefundStatus)
    assert isinstance(data["requested_amount_cents"], int)
    payout = data.get("computed_payout_cents")
    assert payout is None or isinstance(payout, int)
    method = data.get("refund_method_applied")
    assert method is None or method in _values(RefundMethod)
    assert isinstance(data.get("requested_by_user_id"), str)
    assert isinstance(data.get("requested_by_role"), str)
    _assert_optional_timestamp(data, "paid_at", "RefundRequest")


def assert_complaint(data: dict):
    _assert_common_fields(data, "Complaint")
    assert is_valid_uuid(data.get("facility_id", ""))
    assert data["category"] in _values(ComplaintCategory)
    assert isinstance(data["description"], str) and data["description"]
    assert data["status"] in _values(ComplaintStatus)
    assert isinstance(data.get("filed_by_user_id"), str)
    assert isinstance(data.get("filed_by_role"), str)
    _assert_optional_timestamp(data, "resolved_at", "Complaint")
    _assert_optional_timestamp(data, "escalated_at", "Complaint")


# ---------------------------------------------------------------------------
# Domain invariant checkers
# ---------------------------------------------------------------------------


def assert_account_balance_invariant(account: dict):
    """PRD §2.5: a PREPAID or DEBIT balance never falls below zero; a COLLECT
    balance never falls below the negative of its collect_credit_limit_cents."""
    balance = account["balance_cents"]
    if account["funding_model"] in (FundingModel.PREPAID.value, FundingModel.DEBIT.value):
        assert balance >= 0, f"PREPAID/DEBIT balance went negative: {balance}"
    elif account["funding_model"] == FundingModel.COLLECT.value:
        limit = account.get("collect_credit_limit_cents") or 0
        assert balance >= -limit, (
            f"COLLECT balance {balance} breached credit limit {limit}"
        )


def assert_closure_balance_partition(account: dict, remaining_frozen_cents: int):
    """PRD §2.10 closure balance partition: the closure snapshot is always the
    sum of refunded + escheated + retained + frozen remainder + unclaimed."""
    snapshot = account.get("balance_at_closure_cents")
    assert snapshot is not None, "account must be CLOSED for the partition check"
    total = (
        account["refunded_total_cents"]
        + account["escheated_total_cents"]
        + account["retained_fees_cents"]
        + remaining_frozen_cents
        + account["unclaimed_balance_cents"]
    )
    assert total == snapshot, (
        f"closure partition drift: {account['refunded_total_cents']} refunded + "
        f"{account['escheated_total_cents']} escheated + "
        f"{account['retained_fees_cents']} retained + {remaining_frozen_cents} "
        f"frozen + {account['unclaimed_balance_cents']} unclaimed != {snapshot}"
    )


def assert_ledger_balance(account: dict, ledger_rows: list):
    """PRD §2.5: balance_cents is the sum of signed ledger amounts."""
    recomputed = sum(row["amount_cents"] for row in ledger_rows)
    assert recomputed == account["balance_cents"], (
        f"ledger sum {recomputed} != balance_cents {account['balance_cents']}"
    )


__all__ = [
    "assert_facility",
    "assert_regulatory_cap",
    "assert_contract",
    "assert_rate_schedule",
    "assert_inmate",
    "assert_account",
    "assert_funding_transaction",
    "assert_recipient_number",
    "assert_call_record",
    "assert_video_session",
    "assert_tablet_message",
    "assert_refund_request",
    "assert_complaint",
    "assert_account_balance_invariant",
    "assert_closure_balance_partition",
    "assert_ledger_balance",
]
