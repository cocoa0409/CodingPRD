"""Domain types for the Audit Independence Monitoring API.

Status enums for every state axis the contract declares, plus one TypedDict per
top-level resource. Every resource in this API is created with the same four
system-managed fields (``id``, ``created_at``, ``updated_at`` and ``version``),
so every TypedDict below carries all four.
"""

from enum import Enum
from typing import List, Optional, TypedDict


# ─── Roles ─────────────────────────────────────────────────────────────────

class UserRole(str, Enum):
    """The six roles named in the contract, spelled exactly as declared."""

    PLATFORM_ADMIN = "PlatformAdmin"
    ENGAGEMENT_PARTNER = "EngagementPartner"
    CLIENT_ACCEPTANCE_COMMITTEE = "ClientAcceptanceCommittee"
    INDEPENDENCE_OFFICER = "IndependenceOfficer"
    AUDIT_COMMITTEE_LIAISON = "AuditCommitteeLiaison"
    QUALITY_REVIEWER = "QualityReviewer"


# ─── Vocabularies shared across resources ──────────────────────────────────

class IndustryCode(str, Enum):
    TECH = "TECH"
    FINANCIAL_SERVICES = "FINANCIAL_SERVICES"
    HEALTHCARE = "HEALTHCARE"
    MANUFACTURING = "MANUFACTURING"
    RETAIL = "RETAIL"
    ENERGY = "ENERGY"
    PUBLIC_SECTOR = "PUBLIC_SECTOR"


class IndependenceStatus(str, Enum):
    CLEAR = "CLEAR"
    RESTRICTED = "RESTRICTED"
    FROZEN = "FROZEN"


# ─── Client ────────────────────────────────────────────────────────────────

class ClientStatus(str, Enum):
    PROSPECT = "PROSPECT"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    TERMINATED = "TERMINATED"


class Client(TypedDict):
    id: str
    legal_name: str
    industry_code: str
    jurisdiction_country: str
    is_public_interest_entity: bool
    parent_client_id: Optional[str]
    status: str
    naf_annual_cap_cents: int
    naf_approved_fee_cents: int
    aggregate_independence_status: str
    open_finding_count: int
    created_at: str
    updated_at: str
    version: int


# ─── Engagement ────────────────────────────────────────────────────────────

class EngagementStatus(str, Enum):
    DRAFT = "DRAFT"
    ACCEPTANCE_PENDING = "ACCEPTANCE_PENDING"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    CLOSED = "CLOSED"


class EngagementType(str, Enum):
    STATUTORY_AUDIT = "STATUTORY_AUDIT"
    INTEGRATED_AUDIT = "INTEGRATED_AUDIT"
    REVIEW_ENGAGEMENT = "REVIEW_ENGAGEMENT"


class RiskTier(str, Enum):
    LOW = "LOW"
    MODERATE = "MODERATE"
    HIGH = "HIGH"
    SIGNIFICANT = "SIGNIFICANT"


class Engagement(TypedDict):
    id: str
    client_id: str
    engagement_type: str
    fiscal_year_end: str
    is_multinational: bool
    status: str
    independence_status: str
    risk_tier: str
    combined_risk_score: float
    assigned_workload_points: int
    lead_partner_id: Optional[str]
    concurring_partner_id: Optional[str]
    quality_review_required: bool
    created_at: str
    updated_at: str
    version: int


class IndependenceSummary(TypedDict):
    """Computed roll-up returned by the engagement independence summary read."""

    engagement_id: str
    independence_status: str
    critical_open_count: int
    high_open_count: int
    prohibited_service_count: int
    breached_attestation_count: int
    material_interest_count: int
    network_risk_points: int


# ─── Client acceptance ─────────────────────────────────────────────────────

class AcceptanceStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    CONDITIONAL = "CONDITIONAL"
    REJECTED = "REJECTED"
    WITHDRAWN = "WITHDRAWN"


class Decision(str, Enum):
    APPROVE = "APPROVE"
    CONDITIONAL = "CONDITIONAL"
    RETURN = "RETURN"
    REJECT = "REJECT"
    WITHDRAW = "WITHDRAW"


class ClientAcceptance(TypedDict):
    id: str
    client_id: str
    engagement_id: str
    proposed_by: str
    industry_expertise_required: str
    industry_expertise_confirmed: bool
    integrity_score: float
    risk_score: float
    combined_risk_score: float
    status: str
    decision_notes: Optional[str]
    decided_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


# ─── Integrity assessment ──────────────────────────────────────────────────

class SourceType(str, Enum):
    REGULATORY_ACTION = "REGULATORY_ACTION"
    LITIGATION = "LITIGATION"
    MEDIA_ADVERSE = "MEDIA_ADVERSE"
    PRIOR_AUDIT_FINDING = "PRIOR_AUDIT_FINDING"
    CREDIT_EVENT = "CREDIT_EVENT"


class Severity(str, Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class IntegrityAssessment(TypedDict):
    id: str
    acceptance_id: str
    source_type: str
    severity: str
    score_impact: int
    assessed_on: str
    resolved: bool
    created_at: str
    updated_at: str
    version: int


# ─── Professional ──────────────────────────────────────────────────────────

class Grade(str, Enum):
    PARTNER = "PARTNER"
    DIRECTOR = "DIRECTOR"
    SENIOR_MANAGER = "SENIOR_MANAGER"
    MANAGER = "MANAGER"


class RotationRoleClass(str, Enum):
    LEAD_PARTNER = "LEAD_PARTNER"
    CONCURRING_PARTNER = "CONCURRING_PARTNER"
    EQ_REVIEWER = "EQ_REVIEWER"
    NONE = "NONE"


class Availability(str, Enum):
    AVAILABLE = "AVAILABLE"
    IN_TIME_OFF = "IN_TIME_OFF"
    OVERLOADED = "OVERLOADED"


class Professional(TypedDict):
    id: str
    full_name: str
    grade: str
    home_affiliate_id: str
    rotation_role_class: str
    availability: str
    max_workload_points: int
    active_workload_points: int
    rotation_exposure_months: int
    created_at: str
    updated_at: str
    version: int


# ─── Engagement role assignment ────────────────────────────────────────────

class AssignmentRole(str, Enum):
    LEAD_PARTNER = "LEAD_PARTNER"
    CONCURRING_PARTNER = "CONCURRING_PARTNER"
    EQ_REVIEWER = "EQ_REVIEWER"
    ENGAGEMENT_MANAGER = "ENGAGEMENT_MANAGER"


class AssignmentStatus(str, Enum):
    ACTIVE = "ACTIVE"
    ENDED = "ENDED"


class RotationStatus(str, Enum):
    ON_SERVICE = "ON_SERVICE"
    ROTATION_DUE = "ROTATION_DUE"
    IN_TIME_OFF = "IN_TIME_OFF"
    ELIGIBLE = "ELIGIBLE"


class EngagementRoleAssignment(TypedDict):
    id: str
    engagement_id: str
    professional_id: str
    role: str
    started_on: str
    scheduled_end_on: str
    ended_on: Optional[str]
    status: str
    consecutive_service_months: int
    time_off_months_required: Optional[int]
    eligible_return_on: Optional[str]
    rotation_status: str
    workload_points: int
    created_at: str
    updated_at: str
    version: int


# ─── Independence finding ──────────────────────────────────────────────────

class FindingStatus(str, Enum):
    OPEN = "OPEN"
    REMEDIATION = "REMEDIATION"
    RE_TEST = "RE_TEST"
    CLOSED = "CLOSED"
    REOPENED = "REOPENED"


class FindingOrigin(str, Enum):
    DECLARATION = "DECLARATION"
    FINANCIAL_INTEREST = "FINANCIAL_INTEREST"
    EMPLOYMENT_RELATIONSHIP = "EMPLOYMENT_RELATIONSHIP"
    PROHIBITED_SERVICE = "PROHIBITED_SERVICE"
    AFFILIATE_BREACH = "AFFILIATE_BREACH"
    WORKLOAD_LIMIT = "WORKLOAD_LIMIT"
    INSPECTION = "INSPECTION"


class FindingType(str, Enum):
    FINANCIAL_INTEREST = "FINANCIAL_INTEREST"
    EMPLOYMENT_RELATIONSHIP = "EMPLOYMENT_RELATIONSHIP"
    PROHIBITED_SERVICE = "PROHIBITED_SERVICE"
    AFFILIATE_OBLIGATION = "AFFILIATE_OBLIGATION"
    WORKLOAD_LIMIT = "WORKLOAD_LIMIT"


#: Statuses in which a finding keeps the engagement's posture elevated.
LIVE_FINDING_STATUSES = ("OPEN", "REMEDIATION", "RE_TEST", "REOPENED")


class IndependenceFinding(TypedDict):
    id: str
    professional_id: str
    engagement_id: str
    origin: str
    origin_ref_id: str
    finding_type: str
    severity: str
    status: str
    discovered_on: str
    remediation_due_on: Optional[str]
    closed_on: Optional[str]
    remediation_attempts: int
    created_at: str
    updated_at: str
    version: int


# ─── Independence threat ───────────────────────────────────────────────────

class ThreatType(str, Enum):
    FINANCIAL_INTEREST = "FINANCIAL_INTEREST"
    EMPLOYMENT_RELATIONSHIP = "EMPLOYMENT_RELATIONSHIP"


class InstrumentType(str, Enum):
    EQUITY = "EQUITY"
    DEBT = "DEBT"
    MUTUAL_FUND = "MUTUAL_FUND"
    DERIVATIVE = "DERIVATIVE"
    TRUST = "TRUST"


class RelationshipType(str, Enum):
    IMMEDIATE_FAMILY_EMPLOYED_BY_CLIENT = "IMMEDIATE_FAMILY_EMPLOYED_BY_CLIENT"
    FORMER_FIRM_PROFESSIONAL_JOINED_CLIENT = "FORMER_FIRM_PROFESSIONAL_JOINED_CLIENT"
    PROFESSIONAL_PRIOR_CLIENT_EMPLOYEE = "PROFESSIONAL_PRIOR_CLIENT_EMPLOYEE"
    CLIENT_BOARD_MEMBERSHIP = "CLIENT_BOARD_MEMBERSHIP"


class ThreatStatus(str, Enum):
    DECLARED = "DECLARED"
    IN_COOLING_OFF = "IN_COOLING_OFF"
    MITIGATED = "MITIGATED"
    DIVESTED = "DIVESTED"
    CLEARED = "CLEARED"


class IndependenceThreat(TypedDict):
    id: str
    professional_id: str
    client_id: str
    threat_type: str
    instrument_type: Optional[str]
    relationship_type: Optional[str]
    value_cents: int
    effective_on: str
    is_material: bool
    cooling_off_end_on: Optional[str]
    status: str
    cleared_on: Optional[str]
    created_at: str
    updated_at: str
    version: int


# ─── Non-audit service ─────────────────────────────────────────────────────

class ServiceCategory(str, Enum):
    BOOKKEEPING = "BOOKKEEPING"
    INTERNAL_AUDIT_OUTSOURCING = "INTERNAL_AUDIT_OUTSOURCING"
    VALUATION = "VALUATION"
    TAX_PREPARATION = "TAX_PREPARATION"
    TAX_ADVISORY = "TAX_ADVISORY"
    IT_SYSTEMS_DESIGN = "IT_SYSTEMS_DESIGN"
    ACTUARIAL = "ACTUARIAL"
    MANAGEMENT_FUNCTION = "MANAGEMENT_FUNCTION"
    LEGAL = "LEGAL"
    OTHER = "OTHER"


class ServiceStatus(str, Enum):
    DRAFT = "DRAFT"
    PENDING_APPROVAL = "PENDING_APPROVAL"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    REVOKED = "REVOKED"


class NonAuditService(TypedDict):
    id: str
    client_id: str
    engagement_id: Optional[str]
    service_category: str
    fee_cents: int
    is_prohibited_for_pie: bool
    committee_resolution_ref: Optional[str]
    approval_expires_on: Optional[str]
    approved_fee_cents: Optional[int]
    approved_on: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


# ─── Affiliate ─────────────────────────────────────────────────────────────

class NetworkTier(str, Enum):
    MEMBER_FIRM = "MEMBER_FIRM"
    CORRESPONDENT = "CORRESPONDENT"
    ALLIANCE = "ALLIANCE"


class IndependenceFramework(str, Enum):
    SEC_RESTRICTED = "SEC_RESTRICTED"
    EU_LOCAL = "EU_LOCAL"
    IFAC_BASELINE = "IFAC_BASELINE"


class AffiliateStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class Affiliate(TypedDict):
    id: str
    firm_name: str
    country_code: str
    network_tier: str
    independence_framework: str
    status: str
    open_breach_count: int
    created_at: str
    updated_at: str
    version: int


# ─── Affiliate attestation ─────────────────────────────────────────────────

class AttestationStatus(str, Enum):
    PENDING = "PENDING"
    ATTESTED = "ATTESTED"
    BREACHED = "BREACHED"
    WAIVED = "WAIVED"


class AffiliateAttestation(TypedDict):
    id: str
    affiliate_id: str
    engagement_id: str
    attestation_status: str
    attested_on: Optional[str]
    breach_count: int
    created_at: str
    updated_at: str
    version: int


# ─── Quality review ────────────────────────────────────────────────────────

class ReviewType(str, Enum):
    ENGAGEMENT_QUALITY_REVIEW = "ENGAGEMENT_QUALITY_REVIEW"
    INSPECTION_READINESS = "INSPECTION_READINESS"
    REGULATORY_INSPECTION = "REGULATORY_INSPECTION"


class InspectionBody(str, Enum):
    PCAOB = "PCAOB"
    SEC = "SEC"
    LOCAL_REGULATOR = "LOCAL_REGULATOR"
    INTERNAL_QC = "INTERNAL_QC"


class ReviewStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    IN_PROGRESS = "IN_PROGRESS"
    PASSED = "PASSED"
    DEFICIENT = "DEFICIENT"
    REMEDIATED = "REMEDIATED"


class QualityReview(TypedDict):
    id: str
    engagement_id: str
    reviewer_id: str
    review_type: str
    inspection_body: Optional[str]
    received_on: str
    due_on: str
    response_due_on: Optional[str]
    deficiency_count: int
    remediation_plan_ref: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


#: Every entity type name, for parametrized helpers that need to name one.
ENTITY_TYPES: List[str] = [
    "Client",
    "Engagement",
    "ClientAcceptance",
    "IntegrityAssessment",
    "Professional",
    "EngagementRoleAssignment",
    "IndependenceFinding",
    "IndependenceThreat",
    "NonAuditService",
    "Affiliate",
    "AffiliateAttestation",
    "QualityReview",
]
