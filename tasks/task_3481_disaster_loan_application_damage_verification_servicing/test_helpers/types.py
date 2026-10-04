"""Domain types: entity TypedDicts, status enums, role enum.

Field sets follow the PRD resource narratives (Sections 2 and 3). Three
record types are immutable ledgers — CreditReview, Payment and GrantAward —
and carry only ``id`` and ``created_at``; their TypedDicts deliberately omit
``updated_at`` and ``version``.
"""
from enum import Enum
from typing import List, Optional, TypedDict


class UserRole(str, Enum):
    ANONYMOUS = "Anonymous"
    APPLICANT = "Applicant"
    LOAN_OFFICER = "LoanOfficer"
    LOSS_VERIFIER = "LossVerifier"
    LOAN_APPROVER = "LoanApprover"
    SERVICING_AGENT = "ServicingAgent"
    GRANT_COORDINATOR = "GrantCoordinator"
    SYSTEM_ADMIN = "SystemAdmin"


class DisasterType(str, Enum):
    HURRICANE = "HURRICANE"
    FLOOD = "FLOOD"
    EARTHQUAKE = "EARTHQUAKE"
    TORNADO = "TORNADO"
    WILDFIRE = "WILDFIRE"


class LoanPurpose(str, Enum):
    PHYSICAL_DAMAGE = "PHYSICAL_DAMAGE"
    ECONOMIC_INJURY = "ECONOMIC_INJURY"


class ApplicantType(str, Enum):
    HOMEOWNER = "HOMEOWNER"
    RENTER = "RENTER"
    BUSINESS = "BUSINESS"


class DeclarationStatus(str, Enum):
    OPEN = "OPEN"
    PHYSICAL_CLOSED = "PHYSICAL_CLOSED"
    FULLY_CLOSED = "FULLY_CLOSED"


class ApplicationStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    VERIFICATION = "VERIFICATION"
    DECISION_PENDING = "DECISION_PENDING"
    APPROVED = "APPROVED"
    DECLINED = "DECLINED"


class DeclineReason(str, Enum):
    CREDIT_FAIL = "CREDIT_FAIL"
    DTI_EXCEEDED = "DTI_EXCEEDED"
    APPROVER_DECLINE = "APPROVER_DECLINE"


class CreditVerdict(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"


class VerificationMethod(str, Enum):
    INSPECTION = "INSPECTION"
    ESTIMATION = "ESTIMATION"


class ValuationBasis(str, Enum):
    REPLACEMENT_COST = "REPLACEMENT_COST"
    ACTUAL_CASH_VALUE = "ACTUAL_CASH_VALUE"


class VerificationStatus(str, Enum):
    REQUESTED = "REQUESTED"
    COMPLETED = "COMPLETED"
    DISPUTED = "DISPUTED"


class LoanLifecycleStatus(str, Enum):
    PENDING_ACCEPTANCE = "PENDING_ACCEPTANCE"
    ACTIVE = "ACTIVE"
    PAID_IN_FULL = "PAID_IN_FULL"
    CHARGED_OFF = "CHARGED_OFF"


class ServicingStatus(str, Enum):
    CURRENT = "CURRENT"
    DEFERRED = "DEFERRED"
    HARDSHIP = "HARDSHIP"
    DELINQUENT = "DELINQUENT"
    DEFAULT = "DEFAULT"


class TrancheStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    ELIGIBLE = "ELIGIBLE"
    RELEASED = "RELEASED"
    CANCELLED = "CANCELLED"


class MilestoneStatus(str, Enum):
    REPORTED = "REPORTED"
    VERIFIED = "VERIFIED"
    REJECTED = "REJECTED"


class MilestoneDecision(str, Enum):
    VERIFIED = "VERIFIED"
    REJECTED = "REJECTED"


class ModificationStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    DENIED = "DENIED"


class ApplicationDecision(str, Enum):
    APPROVED = "APPROVED"
    DECLINED = "DECLINED"


class SettlementStatus(str, Enum):
    REPORTED = "REPORTED"
    APPLIED = "APPLIED"
    VOIDED = "VOIDED"


class ReceivableStatus(str, Enum):
    OPEN = "OPEN"
    PARTIALLY_PAID = "PARTIALLY_PAID"
    PAID = "PAID"
    ESCALATED = "ESCALATED"


class ServicingActionType(str, Enum):
    DEFERMENT = "DEFERMENT"
    HARDSHIP = "HARDSHIP"


class ServicingActionStatus(str, Enum):
    REQUESTED = "REQUESTED"
    APPROVED = "APPROVED"
    ACTIVE = "ACTIVE"
    EXPIRED = "EXPIRED"
    DENIED = "DENIED"


class ServicingActionDecision(str, Enum):
    APPROVED = "APPROVED"
    DENIED = "DENIED"


class PaymentStatus(str, Enum):
    POSTED = "POSTED"
    REVERSED = "REVERSED"


class CountyEntry(TypedDict):
    county_fips: str
    eligible_purposes: List[str]


class DisasterDeclaration(TypedDict):
    id: str
    declaration_number: str
    disaster_type: str
    incident_start_date: str
    incident_end_date: str
    declared_date: str
    counties: List[CountyEntry]
    physical_filing_deadline: str
    economic_injury_filing_deadline: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Applicant(TypedDict):
    id: str
    full_name: str
    email: str
    applicant_type: str
    annual_income_cents: int
    monthly_debt_cents: int
    created_at: str
    updated_at: str
    version: int


class LoanApplication(TypedDict):
    id: str
    declaration_id: str
    applicant_id: str
    county_fips: str
    loan_purpose: str
    requested_amount_cents: int
    status: str
    reconsideration_count: int
    submitted_at: Optional[str]
    decline_reason: Optional[str]
    loan_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class CreditReview(TypedDict):
    """Immutable ledger record: id + created_at only (no updated_at/version)."""
    id: str
    application_id: str
    reviewer_user_id: str
    credit_score: int
    verified_monthly_debt_cents: int
    proposed_payment_cents: int
    dti_pass: bool
    score_pass: bool
    verdict: str
    created_at: str


class DamageVerification(TypedDict):
    id: str
    application_id: str
    method: str
    valuation_basis: str
    depreciation_pct: Optional[float]
    assessed_loss_cents: int
    insurance_proceeds_cents: int
    verified_loss_cents: int
    net_verified_loss_cents: int
    status: str
    verifier_user_id: Optional[str]
    completed_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Loan(TypedDict):
    id: str
    application_id: str
    applicant_id: str
    loan_purpose: str
    approved_amount_cents: int
    interest_rate: float
    term_months: int
    deferral_months: int
    monthly_payment_cents: int
    collateral_required: bool
    collateral_description: Optional[str]
    collateral_value_cents: Optional[int]
    commitment_amount_cents: int
    disbursed_total_cents: int
    outstanding_balance_cents: int
    accrued_interest_balance_cents: int
    last_accrual_date: Optional[str]
    late_fee_balance_cents: int
    total_principal_paid_cents: int
    total_interest_paid_cents: int
    next_due_date: Optional[str]
    days_past_due: int
    lifecycle_status: str
    servicing_status: str
    created_at: str
    updated_at: str
    version: int


class DisbursementTranche(TypedDict):
    id: str
    loan_id: str
    stage_number: int
    amount_cents: int
    status: str
    released_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class RepairMilestone(TypedDict):
    id: str
    loan_id: str
    description: str
    claimed_cost_cents: int
    verified_cost_cents: Optional[int]
    status: str
    verifier_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ModificationRequest(TypedDict):
    id: str
    loan_id: str
    requested_amount_cents: int
    reason: str
    status: str
    decided_by: Optional[str]
    created_at: str
    updated_at: str
    version: int


class InsuranceSettlement(TypedDict):
    id: str
    loan_id: str
    settlement_amount_cents: int
    received_date: str
    status: str
    clawback_commitment_delta_cents: Optional[int]
    excess_due_cents: Optional[int]
    created_at: str
    updated_at: str
    version: int


class ExcessFundsReceivable(TypedDict):
    id: str
    loan_id: str
    amount_due_cents: int
    amount_paid_cents: int
    due_date: str
    status: str
    created_at: str
    updated_at: str
    version: int


class ServicingAction(TypedDict):
    id: str
    loan_id: str
    action_type: str
    start_date: str
    end_date: str
    status: str
    decided_by: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Payment(TypedDict):
    """Immutable ledger record: id + created_at only (no updated_at/version)."""
    id: str
    loan_id: str
    amount_cents: int
    fee_portion_cents: int
    interest_portion_cents: int
    principal_portion_cents: int
    status: str
    created_at: str


class GrantAward(TypedDict):
    """Immutable ledger record: id + created_at only (no updated_at/version)."""
    id: str
    application_id: str
    program_name: str
    award_amount_cents: int
    purpose_category: str
    created_at: str
