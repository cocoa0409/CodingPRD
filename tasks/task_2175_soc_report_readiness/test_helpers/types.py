"""Domain types for the SOC report readiness API: entity shapes, status enums, role enum."""

from enum import Enum
from typing import List, Optional, TypedDict


# --------------------------------------------------------------------------
# Roles
# --------------------------------------------------------------------------
class UserRole(str, Enum):
    COMPLIANCE_LEAD = "ComplianceLead"
    CONTROL_OWNER = "ControlOwner"
    EVIDENCE_REVIEWER = "EvidenceReviewer"
    AUDITOR = "Auditor"
    ACCOUNT_EXECUTIVE = "AccountExecutive"
    SUBSERVICE_CONTACT = "SubserviceContact"
    PLATFORM_ADMIN = "PlatformAdmin"


# --------------------------------------------------------------------------
# Enumerations
# --------------------------------------------------------------------------
class ReportType(str, Enum):
    SOC_1_TYPE_2 = "SOC_1_TYPE_2"
    SOC_2_TYPE_2 = "SOC_2_TYPE_2"


class CriteriaCategory(str, Enum):
    SECURITY = "SECURITY"
    AVAILABILITY = "AVAILABILITY"
    CONFIDENTIALITY = "CONFIDENTIALITY"
    PROCESSING_INTEGRITY = "PROCESSING_INTEGRITY"
    PRIVACY = "PRIVACY"


class EngagementStatus(str, Enum):
    SCOPING = "SCOPING"
    READINESS = "READINESS"
    OBSERVATION = "OBSERVATION"
    FIELDWORK = "FIELDWORK"
    REPORTING = "REPORTING"
    ISSUED = "ISSUED"
    ABANDONED = "ABANDONED"


class GapPosture(str, Enum):
    OPEN = "OPEN"
    RESTRICTED = "RESTRICTED"
    FROZEN = "FROZEN"


class SystemDescriptionStatus(str, Enum):
    DRAFT = "DRAFT"
    IN_REVIEW = "IN_REVIEW"
    APPROVED = "APPROVED"
    SUPERSEDED = "SUPERSEDED"
    WITHDRAWN = "WITHDRAWN"


class ComponentType(str, Enum):
    INFRASTRUCTURE = "INFRASTRUCTURE"
    SOFTWARE = "SOFTWARE"
    PEOPLE = "PEOPLE"
    PROCEDURES = "PROCEDURES"
    DATA = "DATA"


class ScopeStatus(str, Enum):
    IN_SCOPE = "IN_SCOPE"
    CARVED_OUT = "CARVED_OUT"
    EXCLUDED = "EXCLUDED"


class ControlFrequency(str, Enum):
    DAILY = "DAILY"
    WEEKLY = "WEEKLY"
    MONTHLY = "MONTHLY"
    QUARTERLY = "QUARTERLY"
    ANNUAL = "ANNUAL"
    ADHOC = "ADHOC"


class Automation(str, Enum):
    MANUAL = "MANUAL"
    AUTOMATED = "AUTOMATED"


class RiskRating(str, Enum):
    LOW = "LOW"
    MODERATE = "MODERATE"
    HIGH = "HIGH"


class DesignStatus(str, Enum):
    DESIGN_DRAFT = "DESIGN_DRAFT"
    DESIGN_MAPPED = "DESIGN_MAPPED"
    DESIGN_APPROVED = "DESIGN_APPROVED"
    DESIGN_DEFICIENT = "DESIGN_DEFICIENT"
    DESIGN_CARVED_OUT = "DESIGN_CARVED_OUT"


class OperatingStatus(str, Enum):
    NOT_TESTED = "NOT_TESTED"
    IN_OBSERVATION = "IN_OBSERVATION"
    TESTED_EFFECTIVE = "TESTED_EFFECTIVE"
    TESTED_EXCEPTION = "TESTED_EXCEPTION"
    TESTED_INEFFECTIVE = "TESTED_INEFFECTIVE"


class MappingType(str, Enum):
    PRIMARY = "PRIMARY"
    SECONDARY = "SECONDARY"


class MappingStatus(str, Enum):
    ACTIVE = "ACTIVE"
    RETIRED = "RETIRED"


class EvidenceStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    SUBMITTED = "SUBMITTED"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"
    MISSED = "MISSED"
    WAIVED = "WAIVED"


class GapSource(str, Enum):
    READINESS_ASSESSMENT = "READINESS_ASSESSMENT"
    EXCEPTION_CASCADE = "EXCEPTION_CASCADE"
    EVIDENCE_MISS = "EVIDENCE_MISS"
    COVERAGE_LOSS = "COVERAGE_LOSS"
    MANUAL = "MANUAL"


class GapSeverity(str, Enum):
    LOW = "LOW"
    MODERATE = "MODERATE"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class GapStatus(str, Enum):
    OPEN = "OPEN"
    PLANNED = "PLANNED"
    REMEDIATED = "REMEDIATED"
    VERIFIED = "VERIFIED"
    REOPENED = "REOPENED"
    WITHDRAWN = "WITHDRAWN"


class SampleStatus(str, Enum):
    DRAWN = "DRAWN"
    TESTING = "TESTING"
    CONCLUDED_CLEAN = "CONCLUDED_CLEAN"
    CONCLUDED_EXCEPTIONS = "CONCLUDED_EXCEPTIONS"
    VOIDED = "VOIDED"


class ItemOutcome(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"
    NOT_PROVIDED = "NOT_PROVIDED"


class ExceptionDisposition(str, Enum):
    UNEVALUATED = "UNEVALUATED"
    ISOLATED = "ISOLATED"
    PERVASIVE = "PERVASIVE"
    VOIDED = "VOIDED"


class SubserviceMethod(str, Enum):
    CARVE_OUT = "CARVE_OUT"
    INCLUSIVE = "INCLUSIVE"


class ArticulationStatus(str, Enum):
    DRAFT = "DRAFT"
    ARTICULATED = "ARTICULATED"
    RETIRED = "RETIRED"


class DistributionStatus(str, Enum):
    REQUESTED = "REQUESTED"
    NDA_PENDING = "NDA_PENDING"
    APPROVED = "APPROVED"
    DELIVERED = "DELIVERED"
    REVOKED = "REVOKED"
    DENIED = "DENIED"


class BridgeLetterStatus(str, Enum):
    DRAFT = "DRAFT"
    ISSUED = "ISSUED"
    EXPIRED = "EXPIRED"
    SUPERSEDED = "SUPERSEDED"


class QuestionnaireStatus(str, Enum):
    RECEIVED = "RECEIVED"
    DEFLECTED = "DEFLECTED"
    PARTIALLY_DEFLECTED = "PARTIALLY_DEFLECTED"
    MANUAL_RESPONSE = "MANUAL_RESPONSE"
    CLOSED = "CLOSED"


# --------------------------------------------------------------------------
# Entity shapes
# --------------------------------------------------------------------------
class Engagement(TypedDict):
    id: str
    client_name: str
    report_type: str
    observation_period_start: str
    observation_period_end: str
    required_criteria_categories: List[str]
    max_distribution_recipients: int
    status: str
    gap_posture: str
    gap_debt_points: float
    base_debt_points: int
    open_exception_count: int
    readiness_score: float
    criteria_in_scope_count: int
    covered_criteria_count_readiness: int
    covered_criteria_count_attestation: int
    criteria_coverage_pct_readiness: float
    criteria_coverage_pct_attestation: float
    boundary_locked: bool
    approved_system_description_id: Optional[str]
    observation_period_days: int
    readiness_assessed_at: Optional[str]
    calendar_epoch: int
    created_at: str
    updated_at: str
    version: int


class SystemDescription(TypedDict):
    id: str
    engagement_id: str
    version_label: str
    boundary_narrative: str
    authored_by_user_id: str
    status: str
    review_round: int
    boundary_locked: bool
    supersedes_system_description_id: Optional[str]
    in_scope_component_count: int
    carved_out_component_count: int
    approved_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class BoundaryComponent(TypedDict):
    id: str
    system_description_id: str
    component_type: str
    name: str
    scope_status: str
    subservice_organization_id: Optional[str]
    exclusion_rationale: Optional[str]
    created_at: str
    updated_at: str
    version: int


# TrustCriterion carries only id + created_at: catalog rows are never mutated,
# so they have neither updated_at nor version.
class TrustCriterion(TypedDict):
    id: str
    criterion_code: str
    category: str
    title: str
    min_primary_controls: int
    applies_to_report_types: List[str]
    created_at: str


class Control(TypedDict):
    id: str
    engagement_id: str
    control_ref: str
    title: str
    frequency: str
    automation: str
    risk_rating: str
    population_size: int
    owner_user_id: Optional[str]
    design_status: str
    operating_status: str
    in_scope: bool
    subservice_organization_id: Optional[str]
    primary_mapping_count: int
    active_mapping_count: int
    evidence_scheduled_count: int
    evidence_accepted_count: int
    evidence_missed_count: int
    tested_item_count: int
    open_gap_count: int
    created_at: str
    updated_at: str
    version: int


class CriteriaMapping(TypedDict):
    id: str
    control_id: str
    trust_criterion_id: str
    mapping_type: str
    rationale: Optional[str]
    status: str
    retired_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class EvidenceRequest(TypedDict):
    id: str
    control_id: str
    period_index: int
    period_start: str
    period_end: str
    due_date: str
    status: str
    submitted_by_user_id: Optional[str]
    submitted_at: Optional[str]
    reviewed_by_user_id: Optional[str]
    reviewed_at: Optional[str]
    rejection_round: int
    artifact_ref: Optional[str]
    late: bool
    created_at: str
    updated_at: str
    version: int


class Gap(TypedDict):
    id: str
    engagement_id: str
    control_id: Optional[str]
    trust_criterion_id: Optional[str]
    audit_exception_id: Optional[str]
    source: str
    severity: str
    status: str
    remediation_owner_user_id: Optional[str]
    remediation_due_date: Optional[str]
    reopen_count: int
    debt_points: int
    description: Optional[str]
    created_at: str
    updated_at: str
    version: int


class AuditSample(TypedDict):
    id: str
    control_id: str
    period_start: str
    period_end: str
    drawn_by_user_id: str
    drawn_at: str
    population_size_snapshot: int
    sample_size: int
    allowed_deviations: int
    items_recorded: int
    items_passed: int
    items_failed: int
    items_not_provided: int
    deviation_rate: float
    projected_failures: float
    status: str
    zero_population: bool
    supersedes_audit_sample_id: Optional[str]
    voided_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class AuditException(TypedDict):
    id: str
    audit_sample_id: str
    control_id: str
    item_ordinal: int
    failure_reason: Optional[str]
    disposition: str
    severity_assigned: Optional[str]
    projected_failures_upper: float
    pervasive_recommended: bool
    evaluated_by_user_id: Optional[str]
    evaluated_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class SubserviceOrganization(TypedDict):
    id: str
    engagement_id: str
    name: str
    services_provided: str
    method: str
    coverage_start: str
    coverage_end: str
    csoc_articulated: bool
    csoc_narrative: Optional[str]
    inclusive_control_count: int
    carved_out_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class CUEC(TypedDict):
    id: str
    engagement_id: str
    trust_criterion_id: str
    statement: str
    deflection_topic: str
    articulation_status: str
    articulated_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ReportDistribution(TypedDict):
    id: str
    engagement_id: str
    recipient_name: str
    recipient_email: str
    nda_reference: Optional[str]
    status: str
    delivered_at: Optional[str]
    revoked_at: Optional[str]
    report_period_start: Optional[str]
    report_period_end: Optional[str]
    created_at: str
    updated_at: str
    version: int


class BridgeLetter(TypedDict):
    id: str
    engagement_id: str
    coverage_start: str
    as_of_date: str
    status: str
    supersedes_bridge_letter_id: Optional[str]
    coverage_days: int
    issued_at: Optional[str]
    issued_by_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class CustomerQuestionnaire(TypedDict):
    id: str
    engagement_id: str
    report_distribution_id: str
    customer_name: str
    criteria_item_count: int
    post_period_item_count: int
    cuec_item_count: int
    item_count: int
    as_of_date: Optional[str]
    deflected_by_report_count: int
    deflected_by_bridge_count: int
    deflected_by_cuec_count: int
    manual_response_count: int
    deflection_ratio: float
    bridge_letter_id_used: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int
