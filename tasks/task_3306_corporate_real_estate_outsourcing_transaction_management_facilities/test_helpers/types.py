"""Domain types: entity TypedDicts, status enums and the role enum.

Every entity in this system carries the full common field set (id, created_at,
updated_at, version); no entity is created in a reduced two-field form.
"""
from enum import Enum
from typing import TypedDict, Optional, List


# ─── Enumerations ─────────────────────────────────────

class AccountLifecycleState(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    OFFBOARDING = "OFFBOARDING"
    CLOSED_CONVERTED = "CLOSED_CONVERTED"
    CLOSED_TERMINATED = "CLOSED_TERMINATED"


class GovernancePosture(str, Enum):
    NORMAL = "NORMAL"
    ON_WATCH = "ON_WATCH"
    RESTRICTED = "RESTRICTED"


class ClientDataRights(str, Enum):
    BROKER_OWNED = "BROKER_OWNED"
    CLIENT_OWNED_EXCLUSIVE = "CLIENT_OWNED_EXCLUSIVE"
    CLIENT_OWNED_SHARED = "CLIENT_OWNED_SHARED"


class PlatformTier(str, Enum):
    BASIC = "BASIC"
    COMPLETE = "COMPLETE"
    ENTERPRISE = "ENTERPRISE"


class LeasePipelineState(str, Enum):
    PIPELINE = "PIPELINE"
    APPROVAL_PENDING = "APPROVAL_PENDING"
    BROKER_ASSIGNED = "BROKER_ASSIGNED"
    IN_MARKET = "IN_MARKET"
    NEGOTIATING = "NEGOTIATING"
    EXECUTED = "EXECUTED"
    REJECTED = "REJECTED"


class ExpirationBucket(str, Enum):
    UNASSIGNED = "UNASSIGNED"
    NEAR_TERM = "NEAR_TERM"
    MID_TERM = "MID_TERM"
    LONG_TERM = "LONG_TERM"


class TransactionRequestState(str, Enum):
    DRAFT = "DRAFT"
    PENDING_APPROVAL = "PENDING_APPROVAL"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    WITHDRAWN = "WITHDRAWN"
    EXECUTED = "EXECUTED"
    CANCELLED = "CANCELLED"


class ApprovalLevel(str, Enum):
    MANAGER = "MANAGER"
    DIRECTOR = "DIRECTOR"
    ACCOUNT_EXECUTIVE = "ACCOUNT_EXECUTIVE"


class RequestType(str, Enum):
    RENEWAL = "RENEWAL"
    NEW_LEASE = "NEW_LEASE"
    RESTRUCTURE = "RESTRUCTURE"
    DISPOSITION = "DISPOSITION"


class CommissionSource(str, Enum):
    THIRD_PARTY = "THIRD_PARTY"
    SELF_PERFORM = "SELF_PERFORM"


class BrokerClass(str, Enum):
    SENIOR = "SENIOR"
    STANDARD = "STANDARD"


class BrokerEngagementState(str, Enum):
    PENDING = "PENDING"
    ASSIGNED = "ASSIGNED"
    EXECUTED = "EXECUTED"
    TERMINATED = "TERMINATED"


class VendorState(str, Enum):
    SOURCING = "SOURCING"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    TERMINATED = "TERMINATED"


class VendorKpiTrack(str, Enum):
    LEVEL_A = "LEVEL_A"
    LEVEL_B = "LEVEL_B"
    LEVEL_C = "LEVEL_C"


class DeliveryModel(str, Enum):
    SELF_PERFORM = "SELF_PERFORM"
    SUBCONTRACTED = "SUBCONTRACTED"


class SourcingProgram(str, Enum):
    DIVERSITY = "DIVERSITY"
    LOCAL = "LOCAL"
    NATIONAL = "NATIONAL"


class ServiceLine(str, Enum):
    JANITORIAL = "JANITORIAL"
    SECURITY = "SECURITY"
    HVAC = "HVAC"
    LANDSCAPING = "LANDSCAPING"


class VacancyState(str, Enum):
    OCCUPIED = "OCCUPIED"
    VACATED = "VACATED"
    CONSOLIDATING = "CONSOLIDATING"
    DISPOSED = "DISPOSED"


class ConsolidationProjectState(str, Enum):
    PLANNED = "PLANNED"
    IN_REVIEW = "IN_REVIEW"
    APPROVED = "APPROVED"
    IN_EXECUTION = "IN_EXECUTION"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class ScorecardState(str, Enum):
    DRAFT = "DRAFT"
    PUBLISHED = "PUBLISHED"
    OVERRIDDEN = "OVERRIDDEN"


class Discipline(str, Enum):
    TRANSACTION = "TRANSACTION"
    FACILITIES = "FACILITIES"
    PROJECT = "PROJECT"


class AuditState(str, Enum):
    SCHEDULED = "SCHEDULED"
    IN_REVIEW = "IN_REVIEW"
    PASSED = "PASSED"
    FAILED = "FAILED"


class DataScope(str, Enum):
    AGGREGATE = "AGGREGATE"
    LINE_ITEM = "LINE_ITEM"


class DataLicenseState(str, Enum):
    REQUESTED = "REQUESTED"
    GRANTED = "GRANTED"
    REJECTED = "REJECTED"
    REVOKED = "REVOKED"


class TaskType(str, Enum):
    DATA_HANDOVER = "DATA_HANDOVER"
    RECORDS_TRANSFER = "RECORDS_TRANSFER"
    VENDOR_TERMINATION = "VENDOR_TERMINATION"
    FINAL_RECONCILIATION = "FINAL_RECONCILIATION"


class TaskState(str, Enum):
    PENDING = "PENDING"
    IN_PROGRESS = "IN_PROGRESS"
    DONE = "DONE"
    FAILED = "FAILED"


class KpiFamily(str, Enum):
    SERVICE_LEVEL = "SERVICE_LEVEL"
    SAVINGS = "SAVINGS"


class MeasurementUnit(str, Enum):
    BPS = "BPS"
    CENTS = "CENTS"


class MeasurementWindow(str, Enum):
    QUARTERLY = "QUARTERLY"
    ANNUAL = "ANNUAL"


class KpiEvaluationState(str, Enum):
    AWAITING_BASELINE = "AWAITING_BASELINE"
    EVALUATED = "EVALUATED"
    ESCALATED = "ESCALATED"


class EscalationStatus(str, Enum):
    NONE = "NONE"
    OPEN = "OPEN"
    RESOLVED = "RESOLVED"


class AccrualState(str, Enum):
    OPEN = "OPEN"
    CREDITED = "CREDITED"
    SETTLED = "SETTLED"


class AssignmentRole(str, Enum):
    ACCOUNT_EXECUTIVE = "ACCOUNT_EXECUTIVE"
    TRANSACTION_MANAGER = "TRANSACTION_MANAGER"
    FACILITIES_MANAGER = "FACILITIES_MANAGER"
    OCCUPANCY_PLANNER = "OCCUPANCY_PLANNER"
    GOVERNANCE_MANAGER = "GOVERNANCE_MANAGER"
    DATA_STEWARD = "DATA_STEWARD"
    TRANSITION_MANAGER = "TRANSITION_MANAGER"
    APPROVAL_AUTHORITY = "APPROVAL_AUTHORITY"


class UserRole(str, Enum):
    ACCOUNT_EXECUTIVE = "AccountExecutive"
    TRANSACTION_MANAGER = "TransactionManager"
    APPROVAL_AUTHORITY = "ApprovalAuthority"
    FACILITIES_MANAGER = "FacilitiesManager"
    OCCUPANCY_PLANNER = "OccupancyPlanner"
    GOVERNANCE_MANAGER = "GovernanceManager"
    DATA_STEWARD = "DataSteward"
    TRANSITION_MANAGER = "TransitionManager"


# ─── Entity shapes ────────────────────────────────────

class PortfolioAccount(TypedDict, total=False):
    id: str
    account_name: str
    client_name: str
    portfolio_sqft: int
    platform_tier: str
    client_data_rights: str
    governance_posture: str
    open_escalation_count: int
    lifecycle_state: str
    completion_pct_bps: int
    annual_net_fee_cents: float
    fee_ledger_credit_cents: float
    broker_pool_allocated_cents: float
    portfolio_leased_sqft: int
    created_at: str
    updated_at: str
    version: int


class Lease(TypedDict, total=False):
    id: str
    account_id: str
    property_address: str
    market_code: str
    leased_sqft: int
    base_rent_cents_per_year: int
    lease_start_date: str
    lease_end_date: str
    expiration_bucket: str
    pipeline_state: str
    revision_count: int
    created_at: str
    updated_at: str
    version: int


class TransactionRequest(TypedDict, total=False):
    id: str
    account_id: str
    lease_id: str
    request_type: str
    request_state: str
    required_approval_level: str
    prior_rent_cents_per_year: int
    proposed_rent_cents_per_year: int
    requested_term_months: int
    third_party_commission_cents: int
    has_commission_credit: bool
    savings_provisional_cents: int
    savings_final_cents: int
    created_at: str
    updated_at: str
    version: int


class CommissionRecord(TypedDict, total=False):
    id: str
    account_id: str
    commission_source: str
    base_rent_cents: int
    commission_pct: float
    accrual_date: str
    credit_amount_cents: float
    credited: bool
    created_at: str
    updated_at: str
    version: int


class BrokerEngagement(TypedDict, total=False):
    id: str
    account_id: str
    transaction_request_id: str
    market_code: str
    broker_name: str
    licensed_in_market: bool
    broker_class: str
    engagement_state: str
    deal_commission_cents: float
    broker_share_cents: float
    account_share_cents: float
    created_at: str
    updated_at: str
    version: int


class ServiceLevelKpi(TypedDict, total=False):
    id: str
    account_id: str
    kpi_code: str
    kpi_family: str
    measurement_unit: str
    measurement_window: str
    target_value: int
    actual_value: int
    evaluation_state: str
    escalation_status: str
    gainshare_cents: float
    penalty_cents: float
    net_adjustment_cents: float
    created_at: str
    updated_at: str
    version: int


class FacilitiesVendor(TypedDict, total=False):
    id: str
    account_id: str
    vendor_name: str
    service_line: str
    delivery_model: str
    sourcing_program: str
    kpi_track: str
    service_rate_cents_per_sqft: float
    sqft_reduction: int
    consolidation_window_start: Optional[str]
    consolidation_window_end: Optional[str]
    vendor_state: str
    created_at: str
    updated_at: str
    version: int


class FacilitySite(TypedDict, total=False):
    id: str
    account_id: str
    vendor_id: str
    site_name: str
    sqft: int
    vacancy_state: str
    consolidation_project_id: Optional[str]
    consolidation_window_start: Optional[str]
    consolidation_window_end: Optional[str]
    sqft_reduction: int
    created_at: str
    updated_at: str
    version: int


class ConsolidationProject(TypedDict, total=False):
    id: str
    account_id: str
    project_name: str
    project_state: str
    planned_sqft_reduction: int
    approved_sqft_reduction: int
    realized_sqft_reduction: int
    savings_estimate_cents: float
    savings_finalized_cents: float
    cost_inflation_factor: float
    per_site_rates: List[float]
    per_site_sqft_reductions: List[int]
    created_at: str
    updated_at: str
    version: int


class Scorecard(TypedDict, total=False):
    id: str
    account_id: str
    service_line: str
    quality_bps: int
    response_bps: int
    composite_bps: int
    adjustments_applied: int
    scorecard_state: str
    created_at: str
    updated_at: str
    version: int


class DisciplineAudit(TypedDict, total=False):
    id: str
    account_id: str
    discipline: str
    finding: str
    audit_state: str
    remediation_required: bool
    cooling_off_until: Optional[str]
    created_at: str
    updated_at: str
    version: int


class DataLicense(TypedDict, total=False):
    id: str
    account_id: str
    licensee_name: str
    platform_tier_at_issue: str
    data_scope: str
    requires_written_client_consent: bool
    license_state: str
    created_at: str
    updated_at: str
    version: int


class TransitionTask(TypedDict, total=False):
    id: str
    account_id: str
    task_name: str
    task_type: str
    sequence_no: int
    blocking: bool
    due_at: str
    task_state: str
    created_at: str
    updated_at: str
    version: int


class AccountFeeAccrual(TypedDict, total=False):
    id: str
    account_id: str
    period: str
    base_fee_cents: int
    applied_credit_cents: float
    credit_application_state: str
    settled_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class AccountAssignment(TypedDict, total=False):
    id: str
    account_id: str
    assignee_name: str
    assignment_role: str
    approval_level: str
    created_at: str
    updated_at: str
    version: int


class AuditReview(TypedDict, total=False):
    id: str
    discipline_audit_id: str
    reviewer_name: str
    round_notes: str
    review_round_no: int
    created_at: str
    updated_at: str
    version: int