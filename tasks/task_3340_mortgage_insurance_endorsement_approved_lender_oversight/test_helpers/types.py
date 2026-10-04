"""Domain types: entity TypedDicts, status enums, role enum."""
from enum import Enum
from typing import Any, Dict, List, Optional, TypedDict


# ---------------------------------------------------------------------------
# Role enum
# ---------------------------------------------------------------------------
class UserRole(str, Enum):
    PLATFORM_ADMIN = "PlatformAdmin"
    LENDER_OFFICER = "LenderOfficer"
    SERVICER_OFFICER = "ServicerOfficer"
    FHA_REVIEWER = "FhaReviewer"
    FHA_APPROVER = "FhaApprover"
    CLAIMS_EXAMINER = "ClaimsExaminer"


# ---------------------------------------------------------------------------
# Status enums
# ---------------------------------------------------------------------------
class LenderStatus(str, Enum):
    DESK_REVIEW = "DESK_REVIEW"
    FIELD_REVIEW = "FIELD_REVIEW"
    RETURNED = "RETURNED"
    APPROVED = "APPROVED"
    SUSPENDED = "SUSPENDED"
    TERMINATED = "TERMINATED"


class InstitutionType(str, Enum):
    MORTGAGEE_SUPERVISED = "MORTGAGEE_SUPERVISED"
    MORTGAGEE_NONSUPERVISED = "MORTGAGEE_NONSUPERVISED"
    MORTGAGEE_INVESTING = "MORTGAGEE_INVESTING"


class NetWorthVariant(str, Enum):
    SMALL_LENDER = "SMALL_LENDER"
    STANDARD = "STANDARD"


class FilingStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"
    SUPERSEDED = "SUPERSEDED"


class LoanCaseStatus(str, Enum):
    CASE_NUMBER_ASSIGNED = "CASE_NUMBER_ASSIGNED"
    UNDERWRITE_SUBMITTED = "UNDERWRITE_SUBMITTED"
    DEFICIENT = "DEFICIENT"
    BLOCKED = "BLOCKED"
    ENDORSED = "ENDORSED"
    IN_DEFAULT = "IN_DEFAULT"
    CLAIM_FILED = "CLAIM_FILED"
    VOIDED = "VOIDED"
    CLAIM_PAID = "CLAIM_PAID"
    CLAIM_DENIED = "CLAIM_DENIED"


class MipVintage(str, Enum):
    PRE_CUTOFF = "PRE_CUTOFF"
    POST_CUTOFF = "POST_CUTOFF"


class EndorsementIntegrity(str, Enum):
    SOUND = "SOUND"
    IMPAIRED = "IMPAIRED"


class AppraisalStatus(str, Enum):
    DELIVERED = "DELIVERED"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"
    EXPIRED = "EXPIRED"
    TRANSFERRED = "TRANSFERRED"


class EscrowStatus(str, Enum):
    OPEN = "OPEN"
    FROZEN = "FROZEN"
    DISBURSED = "DISBURSED"
    EXPIRED = "EXPIRED"
    FORFEITED = "FORFEITED"


class FreezeOrigin(str, Enum):
    SUSPENSION = "SUSPENSION"
    IMPAIRMENT = "IMPAIRMENT"


class MipEntryType(str, Enum):
    UPFRONT = "UPFRONT"
    ANNUAL = "ANNUAL"
    REFUND = "REFUND"


class MipEntryStatus(str, Enum):
    BILLED = "BILLED"
    CANCELLED = "CANCELLED"


class ReviewStatus(str, Enum):
    INITIATED = "INITIATED"
    FINDINGS_RECORDED = "FINDINGS_RECORDED"
    CLOSURE_PENDING = "CLOSURE_PENDING"
    CLOSED = "CLOSED"


class DefectCode(str, Enum):
    INCOME_MISCALC = "INCOME_MISCALC"
    APPRAISAL_INFLATED = "APPRAISAL_INFLATED"
    ASSET_VERIFICATION_MISSING = "ASSET_VERIFICATION_MISSING"
    QC_PLAN_VIOLATION = "QC_PLAN_VIOLATION"
    ELIGIBILITY_CRITERIA_UNMET = "ELIGIBILITY_CRITERIA_UNMET"


class DefectStatus(str, Enum):
    OPEN = "OPEN"
    CONFIRMED = "CONFIRMED"
    REMEDIATED = "REMEDIATED"
    DISMISSED = "DISMISSED"


class SeverityTier(str, Enum):
    TIER_1 = "TIER_1"
    TIER_2 = "TIER_2"
    TIER_3 = "TIER_3"


class AgreementStatus(str, Enum):
    DRAFT = "DRAFT"
    EXECUTED = "EXECUTED"
    SATISFIED = "SATISFIED"


class LossMitigationActionType(str, Enum):
    REPAYMENT_PLAN = "REPAYMENT_PLAN"
    SPECIAL_FORBEARANCE = "SPECIAL_FORBEARANCE"
    LOAN_MODIFICATION = "LOAN_MODIFICATION"
    PARTIAL_CLAIM = "PARTIAL_CLAIM"
    PRE_FORECLOSURE_SALE = "PRE_FORECLOSURE_SALE"
    DEED_IN_LIEU = "DEED_IN_LIEU"


class LossMitigationStatus(str, Enum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    FAILED = "FAILED"
    INFEASIBLE = "INFEASIBLE"


class ClaimType(str, Enum):
    CONVEYANCE = "CONVEYANCE"
    WITHOUT_CONVEYANCE = "WITHOUT_CONVEYANCE"


class ClaimStatus(str, Enum):
    UNDER_REVIEW = "UNDER_REVIEW"
    PAID = "PAID"
    DENIED = "DENIED"


class DenialReason(str, Enum):
    EXAMINER_DENIAL = "EXAMINER_DENIAL"
    INDEMNIFIED_DEFECT = "INDEMNIFIED_DEFECT"


# ---------------------------------------------------------------------------
# Entity TypedDicts (all entities carry the common resource properties)
# ---------------------------------------------------------------------------
class Lender(TypedDict, total=False):
    id: str
    legal_name: str
    institution_type: str
    home_state: str
    qc_plan_on_file: bool
    status: str
    advanced_by_user_id: Optional[str]
    approved_by_user_id: Optional[str]
    endorsed_volume_cents: int
    net_worth_variant: str
    required_net_worth_cents: int
    last_accepted_filing_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class FinancialFiling(TypedDict, total=False):
    id: str
    lender_id: str
    fiscal_year_end: str
    total_assets_cents: int
    total_liabilities_cents: int
    liquid_assets_cents: int
    adjusted_net_worth_cents: int
    status: str
    decided_by_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class LoanCase(TypedDict, total=False):
    id: str
    lender_id: str
    borrower_reference: str
    base_loan_amount_cents: int
    appraised_value_cents: int
    term_months: int
    note_rate_bps: int
    current_monthly_payment_cents: int
    refinance_of_case_id: Optional[str]
    status: str
    ltv_bps: int
    mip_vintage: str
    endorsement_date: Optional[str]
    endorsement_reviewer_id: Optional[str]
    endorsement_integrity: str
    default_date: Optional[str]
    mip_cancelled: bool
    mip_retained_cents: int
    forfeited_escrow_total_cents: int
    deficiency_codes: List[str]
    created_at: str
    updated_at: str
    version: int


class Appraisal(TypedDict, total=False):
    id: str
    loan_case_id: str
    appraised_value_cents: int
    effective_date: str
    expiry_date: str
    mps_deficiency_codes: List[str]
    status: str
    transferred_from_case_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class RepairEscrow(TypedDict, total=False):
    id: str
    loan_case_id: str
    amount_cents: int
    start_date: str
    end_date: str
    status: str
    freeze_origin: Optional[str]
    remaining_amount_cents: int
    disbursed_amount_cents: int
    created_at: str
    updated_at: str
    version: int


class MipLedgerEntry(TypedDict, total=False):
    id: str
    loan_case_id: str
    entry_type: str
    period_index: int
    amount_cents: int
    credit_cents: int
    rate_bps: int
    status: str
    created_at: str
    updated_at: str
    version: int


class PostEndorsementReview(TypedDict, total=False):
    id: str
    loan_case_id: str
    reviewer_user_id: str
    scope_codes: List[str]
    status: str
    closed_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Defect(TypedDict, total=False):
    id: str
    review_id: str
    defect_code: str
    detail: Optional[str]
    severity_score: int
    severity_tier: str
    status: str
    created_by_user_id: str
    confirmed_by_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class IndemnificationAgreement(TypedDict, total=False):
    id: str
    loan_case_id: str
    coverage_cap_cents: int
    status: str
    recovered_total_cents: int
    created_by_user_id: str
    created_at: str
    updated_at: str
    version: int


class LossMitigationAction(TypedDict, total=False):
    id: str
    loan_case_id: str
    action_type: str
    tier: int
    status: str
    new_upb_cents: Optional[int]
    new_payment_cents: Optional[int]
    reduction_bps: Optional[int]
    evaluated_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class InsuranceClaim(TypedDict, total=False):
    id: str
    loan_case_id: str
    claim_type: str
    unpaid_principal_balance_cents: int
    expense_items: List[Dict[str, Any]]
    principal_component_cents: int
    expense_component_cents: int
    forfeited_escrow_offset_cents: int
    total_claim_cents: int
    status: str
    denial_reason: Optional[str]
    decided_by_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int
