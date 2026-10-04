"""Entity assertions and domain invariant checkers.

Each ``assert_*`` helper validates the shape of one resource as the PRD
describes it: system-minted UUID id, ISO 8601 timestamps, declared enum
values, and the field set the resource carries. Append-only records
(DepositReturn, RepaymentAllocation, AbuseEvent, LedgerEntry) carry only
``id`` and ``created_at`` — asserting ``updated_at``/``version`` on them
would demand fields the PRD says they do not have.
"""

from typing import Any, Dict

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

from .types import (
    AdvanceOrigin,
    AdvanceStatus,
    AdjustmentDirection,
    AdjustmentStatus,
    AllocationMode,
    CaseStatus,
    DisputeType,
    EarlyPostingStatus,
    EvaluationMode,
    LedgerEntryStatus,
    LedgerEntryType,
    MemberStatus,
    OriginatorType,
    AccountType,
    ProfileStatus,
    ProvisionalStatus,
    RunStatus,
    DepositStatus,
    AbuseEventType,
    ReturnCode,
)


def _enum_values(enum_cls) -> list:
    return [e.value for e in enum_cls]


def _assert_primary_resource_shape(data: Dict[str, Any], label: str) -> None:
    assert is_valid_uuid(data.get("id", "")), f"{label}.id must be a UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"{label}.created_at must be an ISO 8601 timestamp"
    )
    assert is_iso8601_timestamp(data.get("updated_at", "")), (
        f"{label}.updated_at must be an ISO 8601 timestamp"
    )
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        f"{label}.version must be an integer starting at 1"
    )


def _assert_append_only_shape(data: Dict[str, Any], label: str) -> None:
    assert is_valid_uuid(data.get("id", "")), f"{label}.id must be a UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"{label}.created_at must be an ISO 8601 timestamp"
    )


def assert_member(data: Dict[str, Any]) -> None:
    _assert_primary_resource_shape(data, "Member")
    assert isinstance(data["external_ref"], str) and data["external_ref"]
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert is_iso8601_timestamp(data["enrolled_at"])
    assert data["status"] in _enum_values(MemberStatus)
    assert isinstance(data["tenure_days"], int) and data["tenure_days"] >= 0
    assert isinstance(data["current_limit_cents"], int) and data["current_limit_cents"] >= 0
    assert isinstance(data["consecutive_on_time_repayments"], int)
    assert isinstance(data["restricted_consecutive_repayments"], int)
    assert isinstance(data["abuse_event_count"], int) and data["abuse_event_count"] >= 0
    assert isinstance(data["abuse_events_90d"], int) and data["abuse_events_90d"] >= 0
    assert isinstance(data["deposit_reroute_flag"], bool)


def assert_deposit_account(data: Dict[str, Any]) -> None:
    _assert_primary_resource_shape(data, "DepositAccount")
    assert is_valid_uuid(data["member_id"])
    assert data["account_type"] in _enum_values(AccountType)
    assert data["currency"] == "USD"
    assert isinstance(data["sponsor_bank_code"], str) and data["sponsor_bank_code"]
    for field in (
        "posted_balance_cents",
        "provisional_early_cents",
        "holds_cents",
        "outstanding_cushion_cents",
        "usable_cushion_cents",
        "available_optimistic_cents",
        "available_conservative_cents",
    ):
        assert isinstance(data[field], int), f"DepositAccount.{field} must be integer cents"


def assert_direct_deposit(data: Dict[str, Any]) -> None:
    _assert_primary_resource_shape(data, "DirectDeposit")
    assert is_valid_uuid(data["account_id"])
    assert isinstance(data["originator_id"], str) and data["originator_id"]
    assert data["originator_type"] in _enum_values(OriginatorType)
    assert isinstance(data["amount_cents"], int) and data["amount_cents"] > 0
    assert is_iso8601_timestamp(data["settlement_date"])
    assert isinstance(data["trace_id"], str) and data["trace_id"]
    assert data["status"] in _enum_values(DepositStatus)
    assert isinstance(data["qualifying"], bool)
    assert isinstance(data["repaid_cents"], int) and data["repaid_cents"] >= 0


def assert_early_posting(data: Dict[str, Any]) -> None:
    _assert_primary_resource_shape(data, "EarlyPosting")
    assert is_valid_uuid(data["deposit_id"])
    assert isinstance(data["posted_amount_cents"], int) and data["posted_amount_cents"] > 0
    assert is_iso8601_timestamp(data["reversal_window_end"])
    assert data["status"] in _enum_values(EarlyPostingStatus)


def assert_deposit_return(data: Dict[str, Any]) -> None:
    _assert_append_only_shape(data, "DepositReturn")
    assert is_valid_uuid(data["deposit_id"])
    assert data["return_code"] in _enum_values(ReturnCode)
    assert isinstance(data["amount_cents"], int) and data["amount_cents"] > 0
    assert isinstance(data["shortfall_cents"], int) and data["shortfall_cents"] >= 0


def assert_overdraft_advance(data: Dict[str, Any]) -> None:
    _assert_primary_resource_shape(data, "OverdraftAdvance")
    assert is_valid_uuid(data["account_id"])
    assert data["origin"] in _enum_values(AdvanceOrigin)
    assert isinstance(data["principal_cents"], int) and data["principal_cents"] > 0
    assert isinstance(data["outstanding_cents"], int) and data["outstanding_cents"] >= 0
    assert data["status"] in _enum_values(AdvanceStatus)


def assert_repayment_allocation(data: Dict[str, Any]) -> None:
    _assert_append_only_shape(data, "RepaymentAllocation")
    assert is_valid_uuid(data["advance_id"])
    assert is_valid_uuid(data["deposit_id"])
    assert isinstance(data["amount_cents"], int) and data["amount_cents"] > 0
    assert data["allocation_mode"] in _enum_values(AllocationMode)


def assert_eligibility_profile(data: Dict[str, Any]) -> None:
    _assert_primary_resource_shape(data, "EligibilityProfile")
    assert is_valid_uuid(data["member_id"])
    assert data["evaluation_mode"] in _enum_values(EvaluationMode)
    assert isinstance(data["score"], int) and 0 <= data["score"] <= 1000
    for field in ("regularity_points", "tenure_points", "repayment_points", "abuse_penalty"):
        assert isinstance(data[field], int) and data[field] >= 0
    assert isinstance(data["computed_limit_cents"], int)
    assert isinstance(data["delta_vs_current_cents"], int)
    assert data["status"] in _enum_values(ProfileStatus)


def assert_cushion_limit_adjustment(data: Dict[str, Any]) -> None:
    _assert_primary_resource_shape(data, "CushionLimitAdjustment")
    assert is_valid_uuid(data["member_id"])
    assert isinstance(data["old_limit_cents"], int)
    assert isinstance(data["new_limit_cents"], int)
    assert data["direction"] in _enum_values(AdjustmentDirection)
    assert data["status"] in _enum_values(AdjustmentStatus)
    assert is_iso8601_timestamp(data["effective_at"])


def assert_abuse_event(data: Dict[str, Any]) -> None:
    _assert_append_only_shape(data, "AbuseEvent")
    assert is_valid_uuid(data["member_id"])
    assert data["event_type"] in _enum_values(AbuseEventType)


def assert_ledger_entry(data: Dict[str, Any]) -> None:
    _assert_append_only_shape(data, "LedgerEntry")
    assert is_valid_uuid(data["account_id"])
    assert data["entry_type"] in _enum_values(LedgerEntryType)
    assert isinstance(data["program_leg_cents"], int)
    assert isinstance(data["bank_leg_cents"], int)
    assert data["status"] in _enum_values(LedgerEntryStatus)
    assert is_iso8601_timestamp(data["posted_at"])
    assert_leg_parity(data)


def assert_leg_parity(entry: Dict[str, Any]) -> None:
    """The two legs of every ledger entry must sum to zero."""
    assert entry["program_leg_cents"] + entry["bank_leg_cents"] == 0, (
        f"ledger parity violated: {entry['program_leg_cents']} + {entry['bank_leg_cents']} != 0"
    )


def assert_reconciliation_run(data: Dict[str, Any]) -> None:
    _assert_primary_resource_shape(data, "ReconciliationRun")
    assert isinstance(data["sponsor_bank_code"], str) and data["sponsor_bank_code"]
    assert is_iso8601_timestamp(data["period_start"])
    assert is_iso8601_timestamp(data["period_end"])
    assert isinstance(data["bank_reported_net_cents"], int)
    assert isinstance(data["program_net_cents"], int)
    assert isinstance(data["bank_net_cents"], int)
    assert isinstance(data["discrepancy_cents"], int)
    assert data["status"] in _enum_values(RunStatus)


def assert_dispute(data: Dict[str, Any]) -> None:
    _assert_primary_resource_shape(data, "Dispute")
    assert is_valid_uuid(data["member_id"])
    assert is_valid_uuid(data["deposit_id"])
    assert data["dispute_type"] in _enum_values(DisputeType)
    assert isinstance(data["amount_cents"], int) and data["amount_cents"] > 0
    assert isinstance(data["statement"], str) and data["statement"]
    assert data["case_status"] in _enum_values(CaseStatus)
    assert data["provisional_status"] in _enum_values(ProvisionalStatus)
    assert is_iso8601_timestamp(data["provisional_due_at"])
    assert is_iso8601_timestamp(data["resolution_due_at"])
    assert isinstance(data["provisional_overdue"], bool)
