"""Domain types: entity TypedDicts, status enums, role enum.

Every primary resource carries the common system fields id / created_at /
updated_at / version (PRD §2.5).
"""
from enum import Enum
from typing import List, Optional, TypedDict


class OrgType(str, Enum):
    HOSPITAL = "HOSPITAL"
    PHYSICIAN_GROUP = "PHYSICIAN_GROUP"
    DEBT_BUYER = "DEBT_BUYER"


class SourceOrgStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class PolicyStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    RETIRED = "RETIRED"


class PortfolioStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    SCREENING = "SCREENING"
    PRICED = "PRICED"
    CONTRACTED = "CONTRACTED"
    SETTLED = "SETTLED"
    ABOLISHING = "ABOLISHING"
    CLOSED = "CLOSED"
    CANCELLED = "CANCELLED"


class EligibilityStatus(str, Enum):
    UNSCREENED = "UNSCREENED"
    ELIGIBLE = "ELIGIBLE"
    INELIGIBLE = "INELIGIBLE"
    NEEDS_REVIEW = "NEEDS_REVIEW"


class LifecycleStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    PURCHASED = "PURCHASED"
    ABOLISHED = "ABOLISHED"
    EXCLUDED = "EXCLUDED"


class BureauName(str, Enum):
    EQUIFAX = "EQUIFAX"
    EXPERIAN = "EXPERIAN"
    TRANSUNION = "TRANSUNION"


class BureauStatus(str, Enum):
    NOT_REPORTED = "NOT_REPORTED"
    REPORTED = "REPORTED"
    DELETION_REQUESTED = "DELETION_REQUESTED"
    DELETED = "DELETED"
    DELETION_FAILED = "DELETION_FAILED"


class ScreeningRunStatus(str, Enum):
    PENDING = "PENDING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


class ContractStatus(str, Enum):
    DRAFT = "DRAFT"
    EXECUTED = "EXECUTED"
    SETTLED = "SETTLED"
    TERMINATED = "TERMINATED"


class EarmarkType(str, Enum):
    GEOGRAPHY = "GEOGRAPHY"
    HOSPITAL = "HOSPITAL"
    GENERAL = "GENERAL"


class CampaignStatus(str, Enum):
    OPEN = "OPEN"
    FUNDED = "FUNDED"
    CLOSED = "CLOSED"


class DonationStatus(str, Enum):
    PLEDGED = "PLEDGED"
    RECEIVED = "RECEIVED"
    REFUNDED = "REFUNDED"


class BatchStatus(str, Enum):
    STAGING = "STAGING"
    COMMITTED = "COMMITTED"
    FINALIZED = "FINALIZED"
    REVERSED = "REVERSED"


class LetterChannel(str, Enum):
    MAIL = "MAIL"
    EMAIL = "EMAIL"


class LetterStatus(str, Enum):
    QUEUED = "QUEUED"
    SENT = "SENT"
    DELIVERED = "DELIVERED"
    BOUNCED = "BOUNCED"
    UNDELIVERABLE = "UNDELIVERABLE"
    CANCELLED = "CANCELLED"


class CdrStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    REJECTED = "REJECTED"
    ACKNOWLEDGED = "ACKNOWLEDGED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class TaxRecordStatus(str, Enum):
    PENDING = "PENDING"
    ASSESSED = "ASSESSED"
    EXEMPT = "EXEMPT"
    FILED = "FILED"
    CANCELLED = "CANCELLED"


class PartnershipStatus(str, Enum):
    PROPOSED = "PROPOSED"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    COMPLETED = "COMPLETED"


class MilestoneStatus(str, Enum):
    PENDING = "PENDING"
    MET = "MET"
    MISSED = "MISSED"
    WAIVED = "WAIVED"


class ReportScope(str, Enum):
    GLOBAL = "GLOBAL"
    GEOGRAPHY = "GEOGRAPHY"
    HOSPITAL = "HOSPITAL"


class CountingVariant(str, Enum):
    PER_ACCOUNT = "PER_ACCOUNT"
    DEDUPED_HOUSEHOLD = "DEDUPED_HOUSEHOLD"


class ReportStatus(str, Enum):
    DRAFT = "DRAFT"
    PUBLISHED = "PUBLISHED"


class UserRole(str, Enum):
    PLATFORM_ADMIN = "PlatformAdmin"
    PORTFOLIO_ANALYST = "PortfolioAnalyst"
    ELIGIBILITY_OFFICER = "EligibilityOfficer"
    CONTRACT_MANAGER = "ContractManager"
    FINANCE_OFFICER = "FinanceOfficer"
    DONOR_RELATIONS_OFFICER = "DonorRelationsOfficer"
    COMPLIANCE_AUDITOR = "ComplianceAuditor"
    HOSPITAL_PARTNER = "HospitalPartner"


class SourceOrganization(TypedDict):
    id: str
    name: str
    org_type: str
    state_code: str
    contact_email: str
    status: str
    created_at: str
    updated_at: str
    version: int


class EligibilityPolicy(TypedDict):
    id: str
    name: str
    state_code: str
    fpl_multiplier: float
    insolvency_qualifies: bool
    effective_from: str
    effective_to: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Portfolio(TypedDict):
    id: str
    source_org_id: str
    label: str
    face_value_cents: int
    asking_price_cents: int
    status: str
    eligible_face_value_cents: int
    eligible_account_count: int
    quoted_price_cents: Optional[int]
    purchased_price_cents: Optional[int]
    abolished_face_value_cents: int
    created_at: str
    updated_at: str
    version: int


class DebtAccount(TypedDict):
    id: str
    portfolio_id: str
    external_ref: str
    debtor_household_key: str
    debtor_zip: str
    debtor_state: str
    household_size: Optional[int]
    annual_income_cents: Optional[int]
    is_insolvent: bool
    balance_cents: int
    accrued_adjustment_cents: int
    reported_to_bureau: bool
    bureau_name: Optional[str]
    mailing_address: Optional[str]
    eligibility_status: str
    lifecycle_status: str
    bureau_status: str
    abolished_amount_cents: Optional[int]
    abolished_at: Optional[str]
    abolished_batch_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ScreeningRun(TypedDict):
    id: str
    portfolio_id: str
    policy_id: str
    status: str
    eligible_count: int
    ineligible_count: int
    needs_review_count: int
    executed_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class PurchaseContract(TypedDict):
    id: str
    portfolio_id: str
    contract_price_cents: int
    collection_prohibition: bool
    no_resale: bool
    status: str
    executed_by: Optional[str]
    settled_by: Optional[str]
    terminated_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class DonorCampaign(TypedDict):
    id: str
    name: str
    earmark_type: str
    earmark_state_code: Optional[str]
    earmark_source_org_id: Optional[str]
    goal_cents: int
    raised_cents: int
    committed_cents: int
    spent_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Donation(TypedDict):
    id: str
    campaign_id: str
    donor_name: str
    donor_email: str
    gross_cents: int
    fee_cents: int
    net_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class FundingAllocation(TypedDict):
    campaign_id: str
    amount_cents: int


class AbolishmentBatch(TypedDict):
    id: str
    portfolio_id: str
    account_ids: List[str]
    account_count: int
    total_abolished_cents: int
    funding_allocations: List[FundingAllocation]
    status: str
    reversed_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class NotificationLetter(TypedDict):
    id: str
    account_id: str
    batch_id: str
    channel: str
    mailing_address: Optional[str]
    status: str
    attempt_count: int
    sent_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class CreditDeletionRequest(TypedDict):
    id: str
    account_id: str
    batch_id: Optional[str]
    bureau: str
    status: str
    resubmission_count: int
    rejection_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class TaxReliefRecord(TypedDict):
    id: str
    account_id: str
    relief_amount_cents: int
    insolvency_exclusion_cents: Optional[int]
    reportable_amount_cents: Optional[int]
    status: str
    created_at: str
    updated_at: str
    version: int


class HospitalPartnership(TypedDict):
    id: str
    source_org_id: str
    fap_baseline_score: int
    fap_target_score: int
    fap_current_score: int
    status: str
    created_at: str
    updated_at: str
    version: int


class PartnershipMilestone(TypedDict):
    id: str
    partnership_id: str
    code: str
    description: str
    weight: int
    due_date: str
    status: str
    created_at: str
    updated_at: str
    version: int


class ImpactReport(TypedDict):
    id: str
    scope: str
    scope_state_code: Optional[str]
    scope_source_org_id: Optional[str]
    period_start: str
    period_end: str
    counting_variant: str
    households_relieved: int
    dollars_abolished_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int
