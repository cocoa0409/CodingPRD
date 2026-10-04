"""Domain types: entity TypedDicts, status enums, role enum.

Field names match the PRD exactly. All business resources carry the common
system-managed property set (id, created_at, updated_at, version).
"""
from enum import Enum
from typing import Optional, TypedDict


class UserRole(str, Enum):
    PLATFORM_ADMIN = "PlatformAdmin"
    FRANCHISOR_OPS = "FranchisorOps"
    DEVELOPMENT_AGENT = "DevelopmentAgent"
    FRANCHISEE = "Franchisee"
    MEDIATOR = "Mediator"
    INSPECTOR = "Inspector"


class TerritoryStatus(str, Enum):
    UNASSIGNED = "UNASSIGNED"
    ASSIGNED = "ASSIGNED"
    REASSIGNMENT_PENDING = "REASSIGNMENT_PENDING"


class DevelopmentAgentStatus(str, Enum):
    ACTIVE = "ACTIVE"
    UNDER_REVIEW = "UNDER_REVIEW"
    UNDERPERFORMING = "UNDERPERFORMING"
    TERMINATED = "TERMINATED"


class FranchiseeStatus(str, Enum):
    PROSPECT = "PROSPECT"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    TERMINATED = "TERMINATED"


class StoreStatus(str, Enum):
    PIPELINE = "PIPELINE"
    OPEN = "OPEN"
    CLOSED_FOR_REMODEL = "CLOSED_FOR_REMODEL"
    PROBATION = "PROBATION"
    TERMINATION_PENDING = "TERMINATION_PENDING"
    TERMINATED = "TERMINATED"


class SiteApplicationStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    IMPACT_REVIEW = "IMPACT_REVIEW"
    REVISION_REQUESTED = "REVISION_REQUESTED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    WITHDRAWN = "WITHDRAWN"
    PROTESTED = "PROTESTED"
    SUSPENDED = "SUSPENDED"


class ImpactStudyStatus(str, Enum):
    PROVISIONAL = "PROVISIONAL"
    FINAL = "FINAL"
    VOID = "VOID"


class ProtestStatus(str, Enum):
    FILED = "FILED"
    UNDER_REVIEW = "UNDER_REVIEW"
    MEDIATION = "MEDIATION"
    MEDIATION_FAILED = "MEDIATION_FAILED"
    ESCALATED = "ESCALATED"
    RESOLVED_UPHELD = "RESOLVED_UPHELD"
    RESOLVED_REJECTED = "RESOLVED_REJECTED"


class ProtestResolution(str, Enum):
    UPHELD = "UPHELD"
    REJECTED = "REJECTED"


class TransferRequestStatus(str, Enum):
    PENDING = "PENDING"
    BUYER_TRAINING = "BUYER_TRAINING"
    PENDING_APPROVAL = "PENDING_APPROVAL"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class TrainingEnrollmentStatus(str, Enum):
    ENROLLED = "ENROLLED"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    EXPIRED = "EXPIRED"


class FinancingOption(str, Enum):
    SELF_FINANCED = "SELF_FINANCED"
    DA_LOAN = "DA_LOAN"
    FRANCHISOR_DEFERRAL = "FRANCHISOR_DEFERRAL"


class RemodelMandateStatus(str, Enum):
    ISSUED = "ISSUED"
    SCHEDULED = "SCHEDULED"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    OVERDUE = "OVERDUE"
    WAIVED = "WAIVED"


class InspectionStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    CONDUCTED = "CONDUCTED"
    FINALIZED = "FINALIZED"
    VOID = "VOID"


class InspectionOutcome(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"
    FAIL_CRITICAL = "FAIL_CRITICAL"


class PromotionStatus(str, Enum):
    PROPOSED = "PROPOSED"
    VOTING = "VOTING"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    ACTIVE = "ACTIVE"
    CLOSED = "CLOSED"


class Ballot(str, Enum):
    FOR = "FOR"
    AGAINST = "AGAINST"
    ABSTAIN = "ABSTAIN"


class FundingDisputeStatus(str, Enum):
    OPEN = "OPEN"
    RESOLVED_DA_ABSORBS = "RESOLVED_DA_ABSORBS"
    RESOLVED_FRANCHISEE_PAYS = "RESOLVED_FRANCHISEE_PAYS"
    RESOLVED_FRANCHISOR_ABSORBS = "RESOLVED_FRANCHISOR_ABSORBS"


class DisputeResolution(str, Enum):
    DA_ABSORBS = "DA_ABSORBS"
    FRANCHISEE_PAYS = "FRANCHISEE_PAYS"
    FRANCHISOR_ABSORBS = "FRANCHISOR_ABSORBS"


class FeeStatementStatus(str, Enum):
    PROVISIONAL = "PROVISIONAL"
    FINALIZED = "FINALIZED"
    SETTLED = "SETTLED"


class FeeStatementVariant(str, Enum):
    PROVISIONAL_ESTIMATE = "PROVISIONAL_ESTIMATE"
    FINAL_RECONCILIATION = "FINAL_RECONCILIATION"


class Territory(TypedDict, total=False):
    id: str
    code: str
    region: str
    royalty_rate_pct: float
    development_quota_stores: int
    assigned_agent_id: Optional[str]
    status: str
    open_store_count: int
    created_at: str
    updated_at: str
    version: int


class DevelopmentAgent(TypedDict, total=False):
    id: str
    legal_name: str
    contact_email: str
    agreement_start: str
    agreement_end: str
    status: str
    underperformance_strikes: int
    performance_score: float
    created_at: str
    updated_at: str
    version: int


class Franchisee(TypedDict, total=False):
    id: str
    legal_name: str
    contact_email: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Store(TypedDict, total=False):
    id: str
    store_number: str
    territory_id: str
    franchisee_id: str
    address: str
    geo_lat: float
    geo_lng: float
    opened_on: str
    estimated_weekly_sales_cents: int
    actual_avg_weekly_sales_cents: int
    status: str
    consecutive_failed_inspections: int
    source_site_application_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class SiteApplication(TypedDict, total=False):
    id: str
    territory_id: str
    applicant_franchisee_id: str
    proposed_address: str
    proposed_lat: float
    proposed_lng: float
    proposed_open_date: str
    store_id: Optional[str]
    status: str
    revision_count: int
    approved_on: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ImpactStudy(TypedDict, total=False):
    id: str
    site_application_id: str
    radius_miles: float
    affected_store_count: int
    provisional_impact_cents: float
    final_impact_cents: Optional[float]
    status: str
    created_at: str
    updated_at: str
    version: int


class Protest(TypedDict, total=False):
    id: str
    site_application_id: str
    protesting_store_id: str
    protesting_franchisee_id: str
    grounds: str
    filed_on: str
    mediator_ref: Optional[str]
    mediation_deadline: Optional[str]
    resolution: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class TransferRequest(TypedDict, total=False):
    id: str
    store_id: str
    seller_franchisee_id: str
    buyer_franchisee_id: str
    sale_price_cents: int
    transfer_fee_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class TrainingEnrollment(TypedDict, total=False):
    id: str
    franchisee_id: str
    program_code: str
    expires_on: str
    score: Optional[float]
    completed_on: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class RemodelMandate(TypedDict, total=False):
    id: str
    store_id: str
    due_by: str
    financing_option: str
    estimated_cost_cents: int
    closure_start: Optional[str]
    closure_end: Optional[str]
    downtime_days: Optional[int]
    downtime_charge_cents: Optional[int]
    status: str
    created_at: str
    updated_at: str
    version: int


class Inspection(TypedDict, total=False):
    id: str
    store_id: str
    inspector_ref: str
    scheduled_on: str
    food_safety_score: Optional[float]
    cleanliness_score: Optional[float]
    operations_score: Optional[float]
    critical_violations: Optional[int]
    final_score: Optional[float]
    outcome: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class Promotion(TypedDict, total=False):
    id: str
    name: str
    voting_open: str
    voting_close: str
    active_start: str
    active_end: str
    base_cost_per_store_cents: int
    eligible_voter_count: int
    votes_for: int
    votes_against: int
    votes_abstain: int
    participating_store_count: Optional[int]
    store_share_cents: Optional[int]
    total_pool_cents: Optional[int]
    status: str
    created_at: str
    updated_at: str
    version: int


class PromotionVote(TypedDict, total=False):
    id: str
    promotion_id: str
    store_id: str
    franchisee_id: str
    ballot: str
    retracted: bool
    created_at: str
    updated_at: str
    version: int


class FundingDispute(TypedDict, total=False):
    id: str
    promotion_id: str
    store_id: str
    disputed_amount_cents: int
    reason: str
    resolution: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class FeeStatement(TypedDict, total=False):
    id: str
    development_agent_id: str
    territory_id: str
    period_start: str
    period_end: str
    gross_fees_cents: int
    da_share_cents: int
    franchisor_share_cents: int
    variant: str
    status: str
    created_at: str
    updated_at: str
    version: int
