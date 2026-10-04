"""Domain types: entity TypedDicts, status enums, role enum."""
from enum import Enum
from typing import Any, Optional, TypedDict


class ProjectStatus(str, Enum):
    PROSPECT = "PROSPECT"
    SITE_SECURED = "SITE_SECURED"
    DEVELOPMENT = "DEVELOPMENT"
    READY_FOR_CONSTRUCTION = "READY_FOR_CONSTRUCTION"
    UNDER_CONSTRUCTION = "UNDER_CONSTRUCTION"
    COMMISSIONING = "COMMISSIONING"
    COMMERCIAL_OPERATION = "COMMERCIAL_OPERATION"
    OPERATIONAL = "OPERATIONAL"
    ABANDONED = "ABANDONED"


class SiteControlStatus(str, Enum):
    DRAFT = "DRAFT"
    EXECUTED = "EXECUTED"
    EXERCISED = "EXERCISED"
    RECORDED = "RECORDED"
    EXPIRED = "EXPIRED"
    TERMINATED = "TERMINATED"


class InterconnectionRequestStatus(str, Enum):
    QUEUED = "QUEUED"
    FEASIBILITY_STUDY = "FEASIBILITY_STUDY"
    SYSTEM_IMPACT_STUDY = "SYSTEM_IMPACT_STUDY"
    FACILITIES_STUDY = "FACILITIES_STUDY"
    AGREEMENT_EXECUTED = "AGREEMENT_EXECUTED"
    IN_SERVICE = "IN_SERVICE"
    WITHDRAWN = "WITHDRAWN"


class StudyPhase(str, Enum):
    FEASIBILITY = "FEASIBILITY"
    SYSTEM_IMPACT = "SYSTEM_IMPACT"
    FACILITIES = "FACILITIES"


class StudyStatus(str, Enum):
    SCOPED = "SCOPED"
    IN_PROGRESS = "IN_PROGRESS"
    DELIVERED = "DELIVERED"
    ACCEPTED = "ACCEPTED"
    DEFICIENT = "DEFICIENT"


class OfftakeStatus(str, Enum):
    NEGOTIATING = "NEGOTIATING"
    COUNTERED = "COUNTERED"
    EXECUTED = "EXECUTED"
    EFFECTIVE = "EFFECTIVE"
    EXPIRED = "EXPIRED"
    TERMINATED = "TERMINATED"


class SupplyAgreementStatus(str, Enum):
    DRAFT = "DRAFT"
    EXECUTED = "EXECUTED"
    AMENDMENT_PENDING = "AMENDMENT_PENDING"
    DELIVERING = "DELIVERING"
    FULFILLED = "FULFILLED"
    TERMINATED = "TERMINATED"


class SafeHarborMethod(str, Enum):
    FIVE_PERCENT_COST = "FIVE_PERCENT_COST"
    PHYSICAL_WORK = "PHYSICAL_WORK"


class ProcurementOrderStatus(str, Enum):
    PLACED = "PLACED"
    DEPOSIT_PAID = "DEPOSIT_PAID"
    SAFE_HARBOR_QUALIFIED = "SAFE_HARBOR_QUALIFIED"
    DELIVERED = "DELIVERED"
    ACCEPTED = "ACCEPTED"
    CANCELLED = "CANCELLED"


class MilestoneType(str, Enum):
    FOUNDATION = "FOUNDATION"
    ERECTION = "ERECTION"
    ENERGIZATION = "ENERGIZATION"
    SUBSTANTIAL_COMPLETION = "SUBSTANTIAL_COMPLETION"
    COMMERCIAL_OPERATION = "COMMERCIAL_OPERATION"
    CONTINUOUS_WORK = "CONTINUOUS_WORK"


class MilestoneStatus(str, Enum):
    PLANNED = "PLANNED"
    EVIDENCE_SUBMITTED = "EVIDENCE_SUBMITTED"
    CERTIFIED = "CERTIFIED"
    REJECTED = "REJECTED"


class QualificationStatus(str, Enum):
    NOT_ELIGIBLE = "NOT_ELIGIBLE"
    SAFE_HARBOR_ESTABLISHED = "SAFE_HARBOR_ESTABLISHED"
    CONTINUITY_MAINTAINED = "CONTINUITY_MAINTAINED"
    CONTINUITY_LAPSED = "CONTINUITY_LAPSED"
    CURED = "CURED"
    QUALIFIED = "QUALIFIED"
    DISQUALIFIED = "DISQUALIFIED"


class ContinuityVariant(str, Enum):
    FOUR_YEAR_SAFE_HARBOR = "FOUR_YEAR_SAFE_HARBOR"
    FACTS_AND_CIRCUMSTANCES = "FACTS_AND_CIRCUMSTANCES"


class PartnershipStatus(str, Enum):
    STRUCTURING = "STRUCTURING"
    COMMITMENT_EXECUTED = "COMMITMENT_EXECUTED"
    FUNDING = "FUNDING"
    FULLY_FUNDED = "FULLY_FUNDED"
    PRE_FLIP_OPERATING = "PRE_FLIP_OPERATING"
    FLIPPED = "FLIPPED"
    DISSOLVED = "DISSOLVED"


class LedgerEntryType(str, Enum):
    CONTRIBUTION = "CONTRIBUTION"
    DISTRIBUTION_INVESTOR = "DISTRIBUTION_INVESTOR"
    DISTRIBUTION_DEVELOPER = "DISTRIBUTION_DEVELOPER"
    CREDIT_ALLOCATION_INVESTOR = "CREDIT_ALLOCATION_INVESTOR"
    CREDIT_ALLOCATION_DEVELOPER = "CREDIT_ALLOCATION_DEVELOPER"


class DebtFacilityStatus(str, Enum):
    COMMITMENT = "COMMITMENT"
    CONSTRUCTION_DRAWING = "CONSTRUCTION_DRAWING"
    CONVERSION_PENDING = "CONVERSION_PENDING"
    TERM_REPAYMENT = "TERM_REPAYMENT"
    RETIRED = "RETIRED"
    DEFAULTED = "DEFAULTED"


class UserRole(str, Enum):
    DEVELOPER_ADMIN = "DeveloperAdmin"
    ORIGINATION_MANAGER = "OriginationManager"
    PROCUREMENT_LEAD = "ProcurementLead"
    CONSTRUCTION_MANAGER = "ConstructionManager"
    TAX_COUNSEL = "TaxCounsel"
    INVESTOR_MANAGER = "InvestorManager"
    LENDER_AGENT = "LenderAgent"
    AUDITOR = "Auditor"
    PLATFORM_ADMIN = "PlatformAdmin"


class Project(TypedDict, total=False):
    id: str
    name: str
    technology: str
    target_capacity_mw: float
    resource_class: str
    energy_community_eligible: bool
    domestic_content_certified: bool
    availability_guarantee_pct: float
    status: str
    cod_date: Optional[str]
    measured_availability_pct: Optional[float]
    availability_ld_usd: Optional[float]
    tax_credit_anchored: bool
    total_itc_credits_usd: float
    created_at: str
    updated_at: str
    version: int


class SiteControlInstrument(TypedDict, total=False):
    id: str
    project_id: str
    parcel_id: str
    instrument_type: str
    start_date: str
    end_date: str
    exercise_price_usd: float
    status: str
    created_at: str
    updated_at: str
    version: int


class InterconnectionRequest(TypedDict, total=False):
    id: str
    project_id: str
    cluster_id: str
    requested_capacity_mw: float
    queue_position: int
    status: str
    upgrade_allocated: bool
    upgrade_cost_share_usd: Optional[float]
    last_upgrade_total_usd: float
    created_at: str
    updated_at: str
    version: int


class InterconnectionStudy(TypedDict, total=False):
    id: str
    request_id: str
    phase: str
    window_start: str
    window_end: str
    status: str
    rework_count: int
    created_at: str
    updated_at: str
    version: int


class OfftakeAgreement(TypedDict, total=False):
    id: str
    project_id: str
    buyer_type: str
    base_price_usd_mwh: float
    escalator_pct: float
    term_years: int
    delivery_start_date: str
    status: str
    counter_count: int
    created_at: str
    updated_at: str
    version: int


class SupplyAgreement(TypedDict, total=False):
    id: str
    project_id: str
    equipment_type: str
    supplier_name: str
    total_contract_usd: float
    domestic_content_certified: bool
    status: str
    amendment_count: int
    created_at: str
    updated_at: str
    version: int


class ProcurementOrder(TypedDict, total=False):
    id: str
    supply_agreement_id: str
    order_amount_usd: float
    safe_harbor_method: str
    eligible_cost_basis_usd: float
    deposit_paid_usd: float
    safe_harbor_qualified: bool
    physical_work_evidence_uri: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class ConstructionMilestone(TypedDict, total=False):
    id: str
    project_id: str
    milestone_type: str
    sequence_no: int
    planned_date: str
    evidence_uri: Optional[str]
    work_date: Optional[str]
    submitted_by_user_id: Optional[str]
    certified_by_user_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class TaxCreditQualification(TypedDict, total=False):
    id: str
    project_id: str
    status: str
    continuity_variant: Optional[str]
    safe_harbor_established_date: Optional[str]
    lapse_date: Optional[str]
    lapse_count: int
    credit_rate_pct: Optional[float]
    qualified_credit_usd: Optional[float]
    created_at: str
    updated_at: str
    version: int


class TaxEquityPartnership(TypedDict, total=False):
    id: str
    project_id: str
    investor_name: str
    commitment_usd: float
    target_irr_pct: float
    investor_pre_flip_share_pct: float
    investor_post_flip_share_pct: float
    flip_date: Optional[str]
    investor_irr_pct: float
    contributed_usd: float
    retained_cash_usd: float
    status: str
    created_at: str
    updated_at: str
    version: int


# Append-only ledger entry: id + created_at only; NO updated_at, NO version.
class PartnershipLedgerEntry(TypedDict, total=False):
    id: str
    partnership_id: str
    entry_type: str
    amount_usd: float
    period_end_date: str
    created_at: str


class DebtFacility(TypedDict, total=False):
    id: str
    project_id: str
    commitment_usd: float
    drawn_usd: float
    interest_rate_pct: float
    projected_cfads_usd: float
    min_dscr: float
    term_debt_usd: Optional[float]
    status: str
    created_at: str
    updated_at: str
    version: int
