"""Domain types: entity TypedDicts, status enums, role enum.

Every one of the fourteen primary resources in this API carries the same
system-managed fields (id / created_at / updated_at / version), so each
TypedDict below lists all four.
"""
from enum import Enum
from typing import TypedDict, Optional, List


# ─── Enumerations ─────────────────────────────────────

class UserRole(str, Enum):
    PLATFORM_ADMIN = "PlatformAdmin"
    ADVISOR_OPS = "AdvisorOps"
    BRANCH_MANAGER = "BranchManager"
    COMPLIANCE_OFFICER = "ComplianceOfficer"


class AffiliationModel(str, Enum):
    IC = "IC"
    EMPLOYEE = "EMPLOYEE"
    HYBRID = "HYBRID"
    INSTITUTIONAL = "INSTITUTIONAL"


class AdvisorStatus(str, Enum):
    PROSPECT = "PROSPECT"
    ONBOARDING = "ONBOARDING"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    DEPARTING = "DEPARTING"
    DEPARTED = "DEPARTED"


class RetentionStatus(str, Enum):
    NOT_AT_RISK = "NOT_AT_RISK"
    CONTESTED = "CONTESTED"
    RETAINED = "RETAINED"
    DEPARTED_CONFIRMED = "DEPARTED_CONFIRMED"


class EoCoverageLevel(str, Enum):
    STANDARD = "STANDARD"
    PREMIUM = "PREMIUM"
    LIMITED = "LIMITED"


class BranchState(str, Enum):
    SUPERVISED = "SUPERVISED"
    UNSUPERVISED = "UNSUPERVISED"


class BranchStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"


class EnrollmentStatus(str, Enum):
    REQUESTED = "REQUESTED"
    ENROLLED = "ENROLLED"
    REVOKED = "REVOKED"


class LinkStatus(str, Enum):
    ASSIGNED = "ASSIGNED"
    INACTIVE = "INACTIVE"


class AssignmentType(str, Enum):
    PRIMARY = "PRIMARY"
    SECONDARY = "SECONDARY"


class AccountType(str, Enum):
    ADVISORY = "ADVISORY"
    BROKERAGE = "BROKERAGE"


class AccountStatus(str, Enum):
    OPEN = "OPEN"
    FROZEN = "FROZEN"
    PENDING_TRANSFER = "PENDING_TRANSFER"
    TRANSFERRED_OUT = "TRANSFERRED_OUT"
    RETENTION_CONTESTED = "RETENTION_CONTESTED"
    RETAINED = "RETAINED"


class ProductType(str, Enum):
    EQUITY = "EQUITY"
    MUTUAL_FUND = "MUTUAL_FUND"
    ANNUITY = "ANNUITY"
    BROKERAGE_TRAIL = "BROKERAGE_TRAIL"
    ADVISORY = "ADVISORY"


class RevenueEntryStatus(str, Enum):
    DRAFT = "DRAFT"
    RELEASED = "RELEASED"
    TRUE_UP_APPLIED = "TRUE_UP_APPLIED"
    VOID = "VOID"


class PayoutPeriodState(str, Enum):
    OPEN = "OPEN"
    CLOSED = "CLOSED"
    PAID = "PAID"
    REOPENED = "REOPENED"
    VOID = "VOID"


class PayoutLineStatus(str, Enum):
    DRAFT = "DRAFT"
    RELEASED = "RELEASED"
    TRUE_UP_APPLIED = "TRUE_UP_APPLIED"
    VOID = "VOID"


class PayoutLoanStatus(str, Enum):
    REQUESTED = "REQUESTED"
    ACTIVE = "ACTIVE"
    AMORTIZING = "AMORTIZING"
    REPAID = "REPAID"
    FORGIVEN = "FORGIVEN"
    DISCHARGED = "DISCHARGED"


class AmortizationEntryStatus(str, Enum):
    POSTED = "POSTED"
    VOID = "VOID"


class PassThroughCategory(str, Enum):
    TECHNOLOGY = "TECHNOLOGY"
    CLEARING = "CLEARING"
    E_AND_O = "E_AND_O"
    REGULATORY = "REGULATORY"


class BillingModel(str, Enum):
    FLAT_MONTHLY = "FLAT_MONTHLY"
    PCT_OF_GROSS = "PCT_OF_GROSS"


class PassThroughStatus(str, Enum):
    PENDING = "PENDING"
    POSTED = "POSTED"
    WAIVED = "WAIVED"


class AdvisorySplitStatus(str, Enum):
    PENDING = "PENDING"
    POSTED = "POSTED"
    VOID = "VOID"


class TransitionStatus(str, Enum):
    PENDING = "PENDING"
    CONTESTED = "CONTESTED"
    SETTLED = "SETTLED"


class RetentionRowStatus(str, Enum):
    PENDING = "PENDING"
    POSTED = "POSTED"
    RETAINED = "RETAINED"
    LOST = "LOST"
    VOID = "VOID"


# ─── Entity TypedDicts ────────────────────────────────

class Branch(TypedDict):
    id: str
    branch_code: str
    name: str
    transmittal_account: str
    osj_name: str
    osj_enabled: bool
    state: str
    status: str
    supervising_advisor_count: int
    current_payout_period_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Advisor(TypedDict):
    id: str
    advisor_code: str
    crd_number: str
    full_name: str
    affiliation_model: str
    primary_branch_code: str
    ingested_book_total_cents: int
    book_transferred_cents: int
    book_portability_pct: int
    protocol_eligible: bool
    t12_production_cents: int
    ytd_payout_earned_cents: int
    ytd_payout_paid_cents: int
    outstanding_loan_balance_cents: int
    eo_coverage_level: str
    eo_charge_locked_cents: int
    pass_through_locked_cents: int
    annual_payout_cap_hit: bool
    retention_status: str
    status: str
    created_at: str
    updated_at: str
    version: int


class BranchSupervisorEnrollment(TypedDict):
    id: str
    branch_code: str
    advisor_code: str
    effective_date: str
    status: str
    created_at: str
    updated_at: str
    version: int


class AdvisorBranchLink(TypedDict):
    id: str
    advisor_code: str
    branch_code: str
    is_supervisor: bool
    assignment_type: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Account(TypedDict):
    id: str
    advisor_code: str
    account_number: str
    account_type: str
    balance_cents: int
    annual_fee_cents: int
    base_annual_fee_cents: Optional[int]
    rafee_effective_bps: Optional[int]
    held_away: bool
    fee_levelized: bool
    pending_transfer_at: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class RevenueEntry(TypedDict):
    id: str
    advisor_code: str
    account_id: str
    product_type: str
    gross_commission_cents: int
    production_date: str
    status: str
    created_at: str
    updated_at: str
    version: int


class PayoutPeriod(TypedDict):
    id: str
    branch_code: str
    year: int
    month: int
    period_index: int
    state: str
    status: str
    period_gross_cents: int
    period_payout_cents: int
    true_up_amount_cents: int
    created_at: str
    updated_at: str
    version: int


class AdvisorPayoutLine(TypedDict):
    id: str
    payout_period_id: str
    advisor_code: str
    period_gross_cents: int
    projected_annual_production_cents: int
    provisional_base_rate_bps: int
    release_amount_cents: int
    true_up_amount_cents: int
    net_settlement_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class PayoutLoan(TypedDict):
    id: str
    advisor_code: str
    principal_cents: int
    amortization_rate_bps: int
    forgiveness_milestone_pct: int
    remaining_balance_cents: int
    milestone_progress_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class LoanAmortizationEntry(TypedDict):
    id: str
    payout_loan_id: str
    payout_period_id: str
    amortization_amount_cents: int
    forgiveness_amount_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class ExpensePassThrough(TypedDict):
    id: str
    advisor_code: str
    payout_period_id: str
    category: str
    billing_model: str
    amount_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class AdvisoryRevenueSplit(TypedDict):
    id: str
    account_id: str
    payout_period_id: str
    advisory_fee_cents: int
    brokerage_revenue_cents: int
    advisory_revenue_cents: int
    levelization_delta_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class TransitionRecord(TypedDict):
    id: str
    advisor_code: str
    payout_period_id: str
    retention_credit_cents: int
    accounts_in_contest_count: int
    accounts_retained_count: int
    settled_amount_cents: int
    retention_ratio_bps: int
    status: str
    created_at: str
    updated_at: str
    version: int


class AccountRetention(TypedDict):
    id: str
    transition_record_id: str
    account_id: str
    retention_rate_bps: int
    credit_amount_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int