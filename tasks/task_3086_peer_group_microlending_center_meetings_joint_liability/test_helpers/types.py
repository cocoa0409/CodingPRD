"""Domain types: entity TypedDicts, status enums, role enum for the microlending PRD."""
from enum import Enum
from typing import List, Optional, TypedDict


class UserRole(str, Enum):
    PROGRAM_ADMIN = "ProgramAdmin"
    BRANCH_MANAGER = "BranchManager"
    CENTER_MANAGER = "CenterManager"
    FIELD_OFFICER = "FieldOfficer"
    MEMBER = "Member"


class BranchTier(str, Enum):
    SMALL = "SMALL"
    MEDIUM = "MEDIUM"
    LARGE = "LARGE"


class PeerGroupStatus(str, Enum):
    FORMING = "FORMING"
    TRAINING = "TRAINING"
    ACTIVE = "ACTIVE"
    RESTRICTED = "RESTRICTED"
    DISSOLVED = "DISSOLVED"


class MemberStatus(str, Enum):
    RECRUITED = "RECRUITED"
    IN_TRAINING = "IN_TRAINING"
    ELIGIBLE = "ELIGIBLE"
    ACTIVE_BORROWER = "ACTIVE_BORROWER"
    DELINQUENT = "DELINQUENT"
    BLACKLISTED = "BLACKLISTED"


class TrainingSessionStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class LoanApplicationStatus(str, Enum):
    DRAFT = "DRAFT"
    VOTING = "VOTING"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    EXPIRED = "EXPIRED"
    DISBURSED = "DISBURSED"


class VoteDecision(str, Enum):
    APPROVE = "APPROVE"
    REJECT = "REJECT"


class LoanStatus(str, Enum):
    ACTIVE = "ACTIVE"
    DELINQUENT = "DELINQUENT"
    DEFAULTED = "DEFAULTED"
    PAID_OFF = "PAID_OFF"


class LoanRestructureStatus(str, Enum):
    PROPOSED = "PROPOSED"
    ACTIVE = "ACTIVE"
    SUPERSEDED = "SUPERSEDED"


class CenterMeetingStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    OPEN = "OPEN"
    CLOSED = "CLOSED"
    CANCELLED = "CANCELLED"


class SettlementStatus(str, Enum):
    PENDING = "PENDING"
    POSTED = "POSTED"
    RECONCILED = "RECONCILED"
    DISPUTED = "DISPUTED"


class TransactionStatus(str, Enum):
    POSTED = "POSTED"
    VOIDED = "VOIDED"


class SavingsAccountStatus(str, Enum):
    OPEN = "OPEN"
    FROZEN = "FROZEN"
    CLOSED = "CLOSED"


class ReportType(str, Enum):
    PROVISIONAL = "PROVISIONAL"
    FINAL = "FINAL"


class PlanStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


class PlanDecision(str, Enum):
    APPROVE = "APPROVE"
    REJECT = "REJECT"


# ---------------------------------------------------------------------------
# Entities carrying the standard system-managed field set
# ---------------------------------------------------------------------------

class Branch(TypedDict, total=False):
    id: str
    name: str
    tier: str
    active_member_count: int
    total_manager_caseload: int
    created_at: str
    updated_at: str
    version: int


class CenterManager(TypedDict, total=False):
    id: str
    branch_id: str
    full_name: str
    hired_on: str
    current_caseload: int
    center_cap: int
    member_cap: int
    created_at: str
    updated_at: str
    version: int


class Center(TypedDict, total=False):
    id: str
    branch_id: str
    center_manager_id: str
    name: str
    meeting_day_of_week: int
    created_at: str
    updated_at: str
    version: int


class PeerGroup(TypedDict, total=False):
    id: str
    center_id: str
    name: str
    status: str
    member_count: int
    completed_training_sessions: int
    delinquent_loan_count: int
    created_at: str
    updated_at: str
    version: int


class Member(TypedDict, total=False):
    id: str
    branch_id: str
    full_name: str
    national_id: str
    peer_group_id: Optional[str]
    status: str
    cycle_level: int
    cured_delinquency_count: int
    consecutive_absence_streak: int
    attendance_strikes: int
    credit_score: int
    created_at: str
    updated_at: str
    version: int


class GroupTrainingSession(TypedDict, total=False):
    id: str
    peer_group_id: str
    center_manager_id: str
    start_time: str
    end_time: str
    status: str
    created_at: str
    updated_at: str
    version: int


class LoanApplication(TypedDict, total=False):
    id: str
    peer_group_id: str
    member_id: str
    requested_amount_cents: int
    status: str
    voting_deadline: Optional[str]
    applied_ceiling_cents: Optional[int]
    created_at: str
    updated_at: str
    version: int


class Loan(TypedDict, total=False):
    id: str
    member_id: str
    loan_application_id: str
    cycle_level: int
    principal_cents: int
    term_weeks: int
    weekly_installment_cents: int
    savings_required_cents: int
    principal_outstanding_cents: int
    next_due_date: str
    installments_on_time: int
    installments_missed: int
    status: str
    created_at: str
    updated_at: str
    version: int


class LoanRestructure(TypedDict, total=False):
    id: str
    loan_id: str
    new_term_weeks: int
    status: str
    created_at: str
    updated_at: str
    version: int


class CenterMeeting(TypedDict, total=False):
    id: str
    center_id: str
    scheduled_start: str
    scheduled_end: str
    status: str
    settlement_status: str
    declared_cash_cents: Optional[int]
    closer_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class RepaymentTransaction(TypedDict, total=False):
    id: str
    center_meeting_id: str
    loan_id: str
    member_id: str
    amount_cents: int
    savings_applied_cents: int
    installment_applied_cents: int
    principal_applied_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class SavingsAccount(TypedDict, total=False):
    id: str
    member_id: str
    balance_cents: int
    locked_cents: int
    withdrawable_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class ExpansionFeasibility(TypedDict, total=False):
    required_member_capacity: int
    available_member_capacity: int
    required_center_slots: int
    available_center_slots: int
    feasible: bool


class BranchExpansionPlan(TypedDict, total=False):
    id: str
    branch_id: str
    new_centers: int
    new_managers_hired: int
    target_new_members: int
    feasibility: ExpansionFeasibility
    status: str
    created_at: str
    updated_at: str
    version: int


# ---------------------------------------------------------------------------
# Append-only audit records: id and created_at only (no updated_at / version)
# ---------------------------------------------------------------------------

class ConsensusVote(TypedDict, total=False):
    id: str
    loan_application_id: str
    voter_member_id: str
    decision: str
    created_at: str


class MeetingAttendance(TypedDict, total=False):
    id: str
    center_meeting_id: str
    member_id: str
    present: bool
    created_at: str


class CreditBureauReport(TypedDict, total=False):
    id: str
    member_id: str
    loan_id: str
    report_type: str
    score_reported: int
    created_at: str
