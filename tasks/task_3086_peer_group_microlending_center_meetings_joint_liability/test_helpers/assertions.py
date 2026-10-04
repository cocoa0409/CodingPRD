"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

from .types import (
    CenterMeetingStatus,
    LoanApplicationStatus,
    LoanRestructureStatus,
    LoanStatus,
    MemberStatus,
    PeerGroupStatus,
    PlanStatus,
    ReportType,
    SavingsAccountStatus,
    SettlementStatus,
    TrainingSessionStatus,
    TransactionStatus,
)


def _assert_common_fields(data, label):
    assert is_valid_uuid(data.get("id", "")), f"{label}.id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"{label}.created_at must be an ISO 8601 timestamp"
    )
    assert is_iso8601_timestamp(data.get("updated_at", "")), (
        f"{label}.updated_at must be an ISO 8601 timestamp"
    )
    assert isinstance(data.get("version"), int), f"{label}.version must be an integer"


def _assert_append_only_fields(data, label):
    assert is_valid_uuid(data.get("id", "")), f"{label}.id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"{label}.created_at must be an ISO 8601 timestamp"
    )
    assert "updated_at" not in data, f"{label} is append-only and must not carry updated_at"
    assert "version" not in data, f"{label} is append-only and must not carry version"


def assert_branch(data: dict):
    _assert_common_fields(data, "Branch")
    assert isinstance(data.get("name"), str) and data["name"], "Branch.name required"
    assert data.get("tier") in ("SMALL", "MEDIUM", "LARGE"), "Branch.tier enum"
    assert isinstance(data.get("active_member_count"), int)
    assert isinstance(data.get("total_manager_caseload"), int)


def assert_center_manager(data: dict):
    _assert_common_fields(data, "CenterManager")
    assert isinstance(data.get("branch_id"), str)
    assert isinstance(data.get("full_name"), str) and data["full_name"]
    assert isinstance(data.get("current_caseload"), int)
    assert isinstance(data.get("center_cap"), int)
    assert isinstance(data.get("member_cap"), int)


def assert_center(data: dict):
    _assert_common_fields(data, "Center")
    assert isinstance(data.get("branch_id"), str)
    assert isinstance(data.get("center_manager_id"), str)
    assert isinstance(data.get("name"), str) and data["name"]
    assert isinstance(data.get("meeting_day_of_week"), int)
    assert 0 <= data["meeting_day_of_week"] <= 6


def assert_peer_group(data: dict):
    _assert_common_fields(data, "PeerGroup")
    assert data.get("status") in [s.value for s in PeerGroupStatus]
    assert isinstance(data.get("member_count"), int)
    assert isinstance(data.get("completed_training_sessions"), int)
    assert isinstance(data.get("delinquent_loan_count"), int)


def assert_member(data: dict):
    _assert_common_fields(data, "Member")
    assert data.get("status") in [s.value for s in MemberStatus]
    assert isinstance(data.get("full_name"), str) and data["full_name"]
    assert isinstance(data.get("national_id"), str) and data["national_id"]
    assert isinstance(data.get("cycle_level"), int)
    assert isinstance(data.get("cured_delinquency_count"), int)
    assert isinstance(data.get("consecutive_absence_streak"), int)
    assert isinstance(data.get("attendance_strikes"), int)
    assert isinstance(data.get("credit_score"), int)


def assert_training_session(data: dict):
    _assert_common_fields(data, "GroupTrainingSession")
    assert data.get("status") in [s.value for s in TrainingSessionStatus]
    assert isinstance(data.get("peer_group_id"), str)
    assert isinstance(data.get("center_manager_id"), str)
    assert is_iso8601_timestamp(data.get("start_time", ""))
    assert is_iso8601_timestamp(data.get("end_time", ""))


def assert_loan_application(data: dict):
    _assert_common_fields(data, "LoanApplication")
    assert data.get("status") in [s.value for s in LoanApplicationStatus]
    assert isinstance(data.get("member_id"), str)
    assert isinstance(data.get("requested_amount_cents"), int)


def assert_loan(data: dict):
    _assert_common_fields(data, "Loan")
    assert data.get("status") in [s.value for s in LoanStatus]
    assert isinstance(data.get("member_id"), str)
    assert isinstance(data.get("principal_cents"), int)
    assert isinstance(data.get("weekly_installment_cents"), int)
    assert isinstance(data.get("savings_required_cents"), int)
    assert isinstance(data.get("principal_outstanding_cents"), int)
    assert isinstance(data.get("term_weeks"), int)
    assert isinstance(data.get("installments_on_time"), int)
    assert isinstance(data.get("installments_missed"), int)


def assert_loan_restructure(data: dict):
    _assert_common_fields(data, "LoanRestructure")
    assert data.get("status") in [s.value for s in LoanRestructureStatus]
    assert isinstance(data.get("loan_id"), str)
    assert isinstance(data.get("new_term_weeks"), int)


def assert_center_meeting(data: dict):
    _assert_common_fields(data, "CenterMeeting")
    assert data.get("status") in [s.value for s in CenterMeetingStatus]
    assert data.get("settlement_status") in [s.value for s in SettlementStatus]
    assert isinstance(data.get("center_id"), str)
    assert is_iso8601_timestamp(data.get("scheduled_start", ""))
    assert is_iso8601_timestamp(data.get("scheduled_end", ""))


def assert_repayment_transaction(data: dict):
    _assert_common_fields(data, "RepaymentTransaction")
    assert data.get("status") in [s.value for s in TransactionStatus]
    assert isinstance(data.get("amount_cents"), int)
    assert isinstance(data.get("savings_applied_cents"), int)
    assert isinstance(data.get("installment_applied_cents"), int)
    assert isinstance(data.get("principal_applied_cents"), int)


def assert_savings_account(data: dict):
    _assert_common_fields(data, "SavingsAccount")
    assert data.get("status") in [s.value for s in SavingsAccountStatus]
    assert isinstance(data.get("member_id"), str)
    assert isinstance(data.get("balance_cents"), int)
    assert isinstance(data.get("locked_cents"), int)
    assert isinstance(data.get("withdrawable_cents"), int)


def assert_expansion_plan(data: dict):
    _assert_common_fields(data, "BranchExpansionPlan")
    assert data.get("status") in [s.value for s in PlanStatus]
    assert isinstance(data.get("new_centers"), int)
    assert isinstance(data.get("new_managers_hired"), int)
    assert isinstance(data.get("target_new_members"), int)


def assert_consensus_vote(data: dict):
    _assert_append_only_fields(data, "ConsensusVote")
    assert isinstance(data.get("loan_application_id"), str)
    assert isinstance(data.get("voter_member_id"), str)
    assert data.get("decision") in ("APPROVE", "REJECT")


def assert_meeting_attendance(data: dict):
    _assert_append_only_fields(data, "MeetingAttendance")
    assert isinstance(data.get("center_meeting_id"), str)
    assert isinstance(data.get("member_id"), str)
    assert isinstance(data.get("present"), bool)


def assert_bureau_report(data: dict):
    _assert_append_only_fields(data, "CreditBureauReport")
    assert data.get("report_type") in [s.value for s in ReportType]
    assert isinstance(data.get("member_id"), str)
    assert isinstance(data.get("loan_id"), str)
    assert isinstance(data.get("score_reported"), int)
