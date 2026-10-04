"""Domain types for the Product Certification Followup API.

Entity TypedDicts mirror the resources the API returns; the enums name the
states, roles and value sets the PRD declares. Every resource carries the four
system-managed properties of PRD section 2.4 (``id``, ``created_at``,
``updated_at``, ``version``), so every entity TypedDict includes them.
"""

from enum import Enum
from typing import List, Optional, TypedDict

__all__ = [
    "UserRole",
    "RevenueTier",
    "ManufacturerStatus",
    "ConformityRegime",
    "StandardStatus",
    "ReciprocityGroup",
    "ProjectStatus",
    "ProjectDecision",
    "SampleCondition",
    "SampleStatus",
    "TriageDecision",
    "TestOutcome",
    "ConstructionRecordStatus",
    "CertificationStatus",
    "SubstitutionRequestStatus",
    "SubstitutionDecision",
    "InspectionStatus",
    "InspectionResult",
    "FindingSeverity",
    "LabelType",
    "QuotaVariant",
    "MarkLicenseStatus",
    "LabelBatchStatus",
    "EvalStatus",
    "EvalOutcome",
    "AcceptanceStatus",
    "AcceptanceDecision",
    "WithdrawalReasonCode",
    "WithdrawalNoticeStatus",
    "ProtocolSpec",
    "TestResult",
    "ComponentEntry",
    "FindingEntry",
    "PermittedVariation",
    "Manufacturer",
    "Factory",
    "Standard",
    "Jurisdiction",
    "CertificationProject",
    "Sample",
    "ConstructionRecord",
    "Certification",
    "SubstitutionRequest",
    "FollowUpInspection",
    "MarkLicense",
    "LabelBatch",
    "FieldEvaluation",
    "WithdrawalNotice",
]


# ── Roles (PRD section 2.1) ────────────────────────────────────────────────

class UserRole(str, Enum):
    CERTIFICATION_BODY_ADMIN = "CertificationBodyAdmin"
    MANUFACTURER_REP = "ManufacturerRep"
    TEST_ENGINEER = "TestEngineer"
    CERTIFICATION_REVIEWER = "CertificationReviewer"
    FACTORY_INSPECTOR = "FactoryInspector"
    COMPLIANCE_OFFICER = "ComplianceOfficer"
    AHJ_AUTHORITY = "AHJAuthority"


# ── Value enums ────────────────────────────────────────────────────────────

class RevenueTier(str, Enum):
    MICRO = "MICRO"
    SMALL = "SMALL"
    STANDARD = "STANDARD"
    ENTERPRISE = "ENTERPRISE"


class ManufacturerStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class ConformityRegime(str, Enum):
    STANDARD = "STANDARD"
    PROBATION = "PROBATION"


class StandardStatus(str, Enum):
    UPCOMING = "UPCOMING"
    ACTIVE = "ACTIVE"
    RETIRED = "RETIRED"


class ReciprocityGroup(str, Enum):
    NONE = "NONE"
    NATIONAL = "NATIONAL"
    BILATERAL_EU = "BILATERAL_EU"
    CUSTOMS_UNION = "CUSTOMS_UNION"


class ProjectStatus(str, Enum):
    STANDARD_SELECTED = "STANDARD_SELECTED"
    TESTING = "TESTING"
    EVALUATION = "EVALUATION"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


class ProjectDecision(str, Enum):
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    RETEST = "RETEST"


class SampleCondition(str, Enum):
    INTACT = "INTACT"
    DAMAGED = "DAMAGED"


class SampleStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"
    TESTED = "TESTED"


class TriageDecision(str, Enum):
    ACCEPT = "ACCEPT"
    REJECT = "REJECT"


class TestOutcome(str, Enum):
    PASS = "PASS"
    CONDITIONAL = "CONDITIONAL"
    FAIL = "FAIL"


class ConstructionRecordStatus(str, Enum):
    FROZEN = "FROZEN"
    SUPERSEDED = "SUPERSEDED"


class CertificationStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    WITHDRAWN = "WITHDRAWN"
    EXPIRED = "EXPIRED"


class SubstitutionRequestStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    IMPLEMENTED = "IMPLEMENTED"


class SubstitutionDecision(str, Enum):
    APPROVE = "APPROVE"
    REJECT = "REJECT"


class InspectionStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    OVERDUE = "OVERDUE"
    COMPLETED = "COMPLETED"
    VOIDED = "VOIDED"


class InspectionResult(str, Enum):
    CONFORMING = "CONFORMING"
    MINOR_NC = "MINOR_NC"
    MAJOR_NC = "MAJOR_NC"
    CRITICAL_NC = "CRITICAL_NC"


class FindingSeverity(str, Enum):
    CRITICAL = "CRITICAL"
    MAJOR = "MAJOR"
    MINOR = "MINOR"


class LabelType(str, Enum):
    STANDARD = "STANDARD"
    HOLOGRAM = "HOLOGRAM"
    SECURED = "SECURED"


class QuotaVariant(str, Enum):
    STANDARD_QUOTA = "STANDARD_QUOTA"
    PROBATION_QUOTA = "PROBATION_QUOTA"


class MarkLicenseStatus(str, Enum):
    ACTIVE = "ACTIVE"
    EXHAUSTED = "EXHAUSTED"
    SUSPENDED = "SUSPENDED"
    REVOKED = "REVOKED"


class LabelBatchStatus(str, Enum):
    ISSUED = "ISSUED"
    VOIDED = "VOIDED"


class EvalStatus(str, Enum):
    REQUESTED = "REQUESTED"
    EVALUATED_PASS = "EVALUATED_PASS"
    EVALUATED_FAIL = "EVALUATED_FAIL"


class EvalOutcome(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"


class AcceptanceStatus(str, Enum):
    PENDING = "PENDING"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"


class AcceptanceDecision(str, Enum):
    ACCEPT = "ACCEPT"
    REJECT = "REJECT"


class WithdrawalReasonCode(str, Enum):
    SAFETY = "SAFETY"
    NONCONFORMITY = "NONCONFORMITY"
    VOLUNTARY = "VOLUNTARY"
    MISUSE_OF_MARK = "MISUSE_OF_MARK"


class WithdrawalNoticeStatus(str, Enum):
    DRAFT = "DRAFT"
    PUBLISHED = "PUBLISHED"
    EFFECTIVE = "EFFECTIVE"


# ── Nested shapes ──────────────────────────────────────────────────────────

class ProtocolSpec(TypedDict):
    protocol_code: str
    name: str
    mandatory: bool
    safety_critical: bool
    pass_threshold: float
    base_fee_cents: int


class TestResult(TypedDict):
    protocol_code: str
    measured_value: float
    outcome: str
    margin: float
    recorded_by: str
    recorded_at: str


class ComponentEntry(TypedDict):
    slot: str
    component_name: str
    material: str
    part_number: str
    rating: str


class FindingEntry(TypedDict, total=False):
    finding_ref: str
    certification_id: Optional[str]
    severity: str
    description: str


class PermittedVariation(TypedDict):
    slot: str
    allowed_alternates: List[str]


# ── Entities ───────────────────────────────────────────────────────────────
# Every resource carries the common system-managed properties (PRD 2.4):
# id, created_at, updated_at, version.

class Manufacturer(TypedDict):
    id: str
    legal_name: str
    home_jurisdiction_code: str
    annual_revenue_tier: str
    status: str
    suspension_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Factory(TypedDict):
    id: str
    manufacturer_id: str
    site_code: str
    country_code: str
    jurisdiction_code: str
    conformity_regime: str
    conformity_score: float
    open_critical_findings: int
    last_inspection_completed_on: Optional[str]
    next_inspection_due_on: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Standard(TypedDict):
    id: str
    category_code: str
    standard_code: str
    edition_label: str
    effective_from: str
    effective_to: Optional[str]
    construction_requirements: List[str]
    test_protocols: List[ProtocolSpec]
    status: str
    created_at: str
    updated_at: str
    version: int


class Jurisdiction(TypedDict):
    id: str
    jurisdiction_code: str
    name: str
    accepts_field_labels: bool
    accepts_reciprocity: bool
    reciprocity_sources: List[str]
    reciprocity_group: str
    created_at: str
    updated_at: str
    version: int


class CertificationProject(TypedDict):
    id: str
    manufacturer_id: str
    factory_id: str
    category_code: str
    standard_id: str
    product_model: str
    retest_count: int
    fee_snapshot_cents: Optional[int]
    status: str
    decided_by: Optional[str]
    decided_on: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Sample(TypedDict):
    id: str
    project_id: str
    serial_no: str
    condition: str
    status: str
    triaged_by: Optional[str]
    results: List[TestResult]
    created_at: str
    updated_at: str
    version: int


class ConstructionRecord(TypedDict):
    id: str
    project_id: str
    revision_no: int
    components: List[ComponentEntry]
    status: str
    created_at: str
    updated_at: str
    version: int


class Certification(TypedDict):
    id: str
    project_id: str
    manufacturer_id: str
    factory_id: str
    standard_id: str
    construction_record_id: str
    construction_record_revision: int
    listing_number: str
    permitted_variations: List[PermittedVariation]
    issued_on: str
    expires_on: Optional[str]
    status: str
    suspension_causes: List[str]
    created_at: str
    updated_at: str
    version: int


class SubstitutionRequest(TypedDict):
    id: str
    certification_id: str
    slot: str
    proposed_component: ComponentEntry
    rationale: str
    status: str
    decided_by: Optional[str]
    decided_on: Optional[str]
    created_at: str
    updated_at: str
    version: int


class FollowUpInspection(TypedDict):
    id: str
    factory_id: str
    scheduled_for: str
    inspector_ref: str
    completed_on: Optional[str]
    result: Optional[str]
    findings: List[FindingEntry]
    status: str
    created_at: str
    updated_at: str
    version: int


class MarkLicense(TypedDict):
    id: str
    certification_id: str
    label_type: str
    declared_annual_volume: int
    quota_variant: str
    authorized_quantity: int
    used_quantity: int
    next_serial: int
    serial_prefix: str
    status: str
    created_at: str
    updated_at: str
    version: int


class LabelBatch(TypedDict):
    id: str
    license_id: str
    quantity: int
    serial_start: int
    serial_end: int
    status: str
    created_at: str
    updated_at: str
    version: int


class FieldEvaluation(TypedDict):
    id: str
    manufacturer_id: str
    standard_id: str
    evaluating_jurisdiction_id: str
    site_jurisdiction_id: str
    equipment_description: str
    site_address: str
    eval_status: str
    acceptance_status: str
    evaluated_by: Optional[str]
    ahj_decided_by: Optional[str]
    label_issued_on: Optional[str]
    created_at: str
    updated_at: str
    version: int


class WithdrawalNotice(TypedDict):
    id: str
    certification_id: str
    reason_code: str
    public_text: str
    published_on: Optional[str]
    effective_on: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int
