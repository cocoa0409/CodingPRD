"""Domain types: entity TypedDicts, status enums, role enum (PRD §2.1, §2.4, §3)."""
from enum import Enum
from typing import Any, List, Optional, TypedDict


class UserRole(str, Enum):
    FRANCHISOR_OPS = "FranchisorOps"
    FRANCHISEE_ADMIN = "FranchiseeAdmin"
    BRAND_AUDITOR = "BrandAuditor"


class BrandStatus(str, Enum):
    ACTIVE = "ACTIVE"
    RETIRED = "RETIRED"


class BrokerageStatus(str, Enum):
    PROSPECT = "PROSPECT"
    FRANCHISED = "FRANCHISED"
    TERMINATED = "TERMINATED"


class AgreementStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    EXPIRED = "EXPIRED"
    TERMINATED = "TERMINATED"
    DEIDENTIFYING = "DEIDENTIFYING"
    CLOSED = "CLOSED"


class AgentStatus(str, Enum):
    ACTIVE = "ACTIVE"
    INACTIVE = "INACTIVE"


class RoyaltyPeriodStatus(str, Enum):
    ASSESSED = "ASSESSED"
    SETTLED = "SETTLED"
    WAIVED = "WAIVED"


class DefaultCaseStatus(str, Enum):
    OPEN = "OPEN"
    CURING = "CURING"
    RESOLVED = "RESOLVED"
    ESCALATED = "ESCALATED"


class DefaultReasonCode(str, Enum):
    PAYMENT = "PAYMENT"
    BRAND_STANDARDS = "BRAND_STANDARDS"
    REPORTING = "REPORTING"
    TERRITORY = "TERRITORY"


class ProposalStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    EXECUTED = "EXECUTED"


class AuditStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class AuditType(str, Enum):
    SIGNAGE = "SIGNAGE"
    MARKETING = "MARKETING"
    TECH_ADOPTION = "TECH_ADOPTION"
    AGENT_ONBOARDING = "AGENT_ONBOARDING"


class AuditFinding(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"


class DeidentificationTaskStatus(str, Enum):
    PENDING = "PENDING"
    COMPLETED = "COMPLETED"
    VERIFIED = "VERIFIED"


class DeidentificationCategory(str, Enum):
    SIGNAGE_REMOVAL = "SIGNAGE_REMOVAL"
    MARKETING_WITHDRAWAL = "MARKETING_WITHDRAWAL"
    DATA_PURGE = "DATA_PURGE"
    DOMAIN_RELEASE = "DOMAIN_RELEASE"
    DIRECTORY_REMOVAL = "DIRECTORY_REMOVAL"


class LedgerEntryType(str, Enum):
    COLLECT = "COLLECT"
    SPEND = "SPEND"


class Vote(str, Enum):
    APPROVE = "APPROVE"
    REJECT = "REJECT"


# --- Entity TypedDicts (PRD §2.4: primary resources carry id/created_at/updated_at/version) ---

class Brand(TypedDict, total=False):
    id: str
    brand_code: str
    display_name: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Market(TypedDict, total=False):
    id: str
    market_code: str
    name: str
    created_at: str
    updated_at: str
    version: int


class Brokerage(TypedDict, total=False):
    id: str
    legal_name: str
    home_market_id: str
    principal_email: str
    status: str
    created_at: str
    updated_at: str
    version: int


class FranchiseAgreement(TypedDict, total=False):
    id: str
    brokerage_id: str
    brand_id: str
    market_id: str
    term_start: str
    term_end: str
    base_royalty_rate_bps: int
    annual_royalty_cap_cents: int
    volume_incentive_threshold_cents: int
    volume_incentive_rate_bps: int
    ad_fund_rate_bps: int
    status: str
    activated_at: Optional[str]
    renewed_from_id: Optional[str]
    cumulative_billed_royalty_cents: int
    cumulative_gci_cents: int
    open_cure_count: int
    created_at: str
    updated_at: str
    version: int


class ConversionPlan(TypedDict, total=False):
    id: str
    agreement_id: str
    milestones: List[dict]
    milestones_done: int
    ready: bool
    created_at: str
    updated_at: str
    version: int


class Agent(TypedDict, total=False):
    id: str
    brokerage_id: str
    full_name: str
    license_no: str
    affiliated_on: str
    status: str
    created_at: str
    updated_at: str
    version: int


# Append-only (PRD §2.4): only id + created_at; no updated_at, no version.
class AgentCountReport(TypedDict, total=False):
    id: str
    agreement_id: str
    period_month: str
    active_agent_count: int
    reported_at: str
    created_at: str


class GCIReport(TypedDict, total=False):
    id: str
    agreement_id: str
    period_month: str
    gci_cents: int
    reported_at: str
    reported_by_role: str
    created_at: str


class RoyaltyPeriod(TypedDict, total=False):
    id: str
    agreement_id: str
    period_month: str
    gci_cents: int
    royalty_due_cents: int
    provisional_royalty_cents: int
    ad_fund_due_cents: int
    status: str
    settled_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class DefaultCase(TypedDict, total=False):
    id: str
    agreement_id: str
    reason_code: str
    status: str
    opened_at: str
    cure_deadline: str
    escalated_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class AdFundLedgerEntry(TypedDict, total=False):
    id: str
    brand_id: str
    agreement_id: Optional[str]
    period_id: Optional[str]
    entry_type: str
    amount_cents: int
    created_at: str


class AdvisoryCouncil(TypedDict, total=False):
    id: str
    brand_id: str
    seat_count: int
    member_brokerage_ids: List[str]
    quorum_votes: int
    created_at: str
    updated_at: str
    version: int


class AdFundSpendProposal(TypedDict, total=False):
    id: str
    brand_id: str
    council_id: str
    title: str
    amount_cents: int
    status: str
    approvals: int
    rejections: int
    approver_ids: List[str]
    rejecter_ids: List[str]
    created_at: str
    updated_at: str
    version: int


class ComplianceAudit(TypedDict, total=False):
    id: str
    agreement_id: str
    audit_type: str
    started_at: Optional[str]
    finding: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class DeidentificationTask(TypedDict, total=False):
    id: str
    agreement_id: str
    category: str
    status: str
    due_at: str
    created_at: str
    updated_at: str
    version: int
