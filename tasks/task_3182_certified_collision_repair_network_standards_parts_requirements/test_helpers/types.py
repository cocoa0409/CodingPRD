"""Domain types: entity TypedDicts, status enums, role enum.

All entities in this domain carry the full common field set
(id, created_at, updated_at, version) per the PRD's Common Resource
Properties section.
"""
from enum import Enum
from typing import TypedDict, Optional, List


class ShopStatus(str, Enum):
    APPLICANT = "APPLICANT"
    CERTIFIED = "CERTIFIED"
    PROBATION = "PROBATION"
    SUSPENDED = "SUSPENDED"
    EXPIRED = "EXPIRED"
    DECERTIFIED = "DECERTIFIED"


class RequirementCategory(str, Enum):
    EQUIPMENT = "EQUIPMENT"
    TRAINING = "TRAINING"
    TOOLING = "TOOLING"
    STRUCTURAL = "STRUCTURAL"


class RequirementStatus(str, Enum):
    DRAFT = "DRAFT"
    PUBLISHED = "PUBLISHED"
    SUPERSEDED = "SUPERSEDED"
    RETIRED = "RETIRED"


class CycleStatus(str, Enum):
    OPEN = "OPEN"
    AUDIT_SCHEDULED = "AUDIT_SCHEDULED"
    UNDER_AUDIT = "UNDER_AUDIT"
    CORRECTIVE_ACTION = "CORRECTIVE_ACTION"
    CLOSED_PASS = "CLOSED_PASS"
    CLOSED_FAIL = "CLOSED_FAIL"


class AttestationStatus(str, Enum):
    ACTIVE = "ACTIVE"
    LAPSED = "LAPSED"
    UNDER_CORRECTION = "UNDER_CORRECTION"
    SUPERSEDED = "SUPERSEDED"


class AuditStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    IN_PROGRESS = "IN_PROGRESS"
    FINDINGS_ISSUED = "FINDINGS_ISSUED"
    VERIFICATION = "VERIFICATION"
    PASSED = "PASSED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class AuditGrade(str, Enum):
    A = "A"
    B = "B"
    C = "C"
    F = "F"


class CorrectiveActionStatus(str, Enum):
    OPEN = "OPEN"
    SUBMITTED = "SUBMITTED"
    VERIFIED = "VERIFIED"
    REJECTED = "REJECTED"


class TechnicianStatus(str, Enum):
    PROVISIONAL = "PROVISIONAL"
    CURRENT = "CURRENT"
    LAPSED = "LAPSED"
    INACTIVE = "INACTIVE"


class TechRole(str, Enum):
    STRUCTURAL = "STRUCTURAL"
    NON_STRUCTURAL = "NON_STRUCTURAL"
    ESTIMATOR = "ESTIMATOR"
    REFINISH = "REFINISH"
    ADAS_SPECIALIST = "ADAS_SPECIALIST"


class CompletionStatus(str, Enum):
    CURRENT = "CURRENT"
    EXPIRED = "EXPIRED"


class RepairOrderStatus(str, Enum):
    ESTIMATE = "ESTIMATE"
    APPROVED = "APPROVED"
    IN_REPAIR = "IN_REPAIR"
    QC = "QC"
    REWORK = "REWORK"
    CALIBRATION = "CALIBRATION"
    COMPLETE = "COMPLETE"
    WARRANTY_ACTIVE = "WARRANTY_ACTIVE"
    CLOSED = "CLOSED"
    VOIDED = "VOIDED"


class StepType(str, Enum):
    PRE_SCAN = "PRE_SCAN"
    STRUCTURAL_MEASURE = "STRUCTURAL_MEASURE"
    WELD_BOND = "WELD_BOND"
    POST_SCAN = "POST_SCAN"
    ADAS_CALIBRATION_STATIC = "ADAS_CALIBRATION_STATIC"
    ADAS_CALIBRATION_DYNAMIC = "ADAS_CALIBRATION_DYNAMIC"


class StepResult(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"
    NOT_APPLICABLE = "NOT_APPLICABLE"


class StepStatus(str, Enum):
    RECORDED = "RECORDED"
    VOIDED = "VOIDED"


class PartClass(str, Enum):
    OE = "OE"
    OE_SURPLUS = "OE_SURPLUS"
    AFTERMARKET = "AFTERMARKET"
    RECYCLED = "RECYCLED"
    REMANUFACTURED = "REMANUFACTURED"


class LineStatus(str, Enum):
    ACTIVE = "ACTIVE"
    REMOVED = "REMOVED"


class DefectCategory(str, Enum):
    WORKMANSHIP = "WORKMANSHIP"
    PART_DEFECT = "PART_DEFECT"
    CORROSION = "CORROSION"
    PAINT_ADHESION = "PAINT_ADHESION"
    CALIBRATION_DRIFT = "CALIBRATION_DRIFT"


class ClaimStatus(str, Enum):
    FILED = "FILED"
    UNDER_REVIEW = "UNDER_REVIEW"
    ESCALATED = "ESCALATED"
    RESOLVED_ACCEPTED = "RESOLVED_ACCEPTED"
    RESOLVED_DENIED = "RESOLVED_DENIED"
    CLOSED = "CLOSED"


class RelationStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    TERMINATED = "TERMINATED"


class ReferralStatus(str, Enum):
    UNROUTED = "UNROUTED"
    ROUTED = "ROUTED"
    ACCEPTED = "ACCEPTED"
    DECLINED = "DECLINED"
    EXPIRED = "EXPIRED"


class SourceType(str, Enum):
    DEALER = "DEALER"
    INSURER = "INSURER"
    CONSUMER_DIRECT = "CONSUMER_DIRECT"


class UserRole(str, Enum):
    ANONYMOUS = "Anonymous"
    NETWORK_ADMIN = "NetworkAdmin"
    NETWORK_AUDITOR = "NetworkAuditor"
    SHOP_MANAGER = "ShopManager"
    DEALER_REP = "DealerRep"
    INSURER_REP = "InsurerRep"


class Shop(TypedDict, total=False):
    id: str
    legal_name: str
    state_code: str
    zip_code: str
    latitude: float
    longitude: float
    certification_status: str
    locator_hidden: bool
    structural_capability: bool
    lifetime_repair_count: int
    pending_referral_count: int
    warranty_reserve_cents: int
    live_compliance_score: float
    created_at: str
    updated_at: str
    version: int


class Requirement(TypedDict, total=False):
    id: str
    requirement_code: str
    category: str
    requirement_version: int
    supersedes_requirement_id: Optional[str]
    description: str
    severity_if_failed: str
    status: str
    effective_from: str
    created_at: str
    updated_at: str
    version: int


class CertificationCycle(TypedDict, total=False):
    id: str
    shop_id: str
    cycle_index: int
    window_start: str
    window_end: str
    status: str
    audit_snapshot_score: Optional[float]
    created_at: str
    updated_at: str
    version: int


class ShopAttestation(TypedDict, total=False):
    id: str
    shop_id: str
    requirement_id: str
    evidence_uri: str
    attested_at: str
    status: str
    lapse_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Audit(TypedDict, total=False):
    id: str
    cycle_id: str
    auditor_user_id: str
    scheduled_start: str
    scheduled_end: str
    round_number: int
    status: str
    severity_points: int
    grade: Optional[str]
    created_at: str
    updated_at: str
    version: int


class CorrectiveAction(TypedDict, total=False):
    id: str
    audit_id: str
    attestation_id: str
    finding_severity: str
    due_at: str
    status: str
    issued_by_user_id: str
    verified_by_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Technician(TypedDict, total=False):
    id: str
    shop_id: str
    full_name: str
    tech_role: str
    status: str
    curriculum_progress_pct: float
    created_at: str
    updated_at: str
    version: int


class TrainingCourse(TypedDict, total=False):
    id: str
    course_code: str
    title: str
    required_for_roles: List[str]
    validity_months: int
    credit_hours: int
    active: bool
    created_at: str
    updated_at: str
    version: int


class CourseCompletion(TypedDict, total=False):
    id: str
    technician_id: str
    course_id: str
    completed_at: str
    proof_uri: str
    status: str
    created_at: str
    updated_at: str
    version: int


class RepairOrder(TypedDict, total=False):
    id: str
    shop_id: str
    referral_id: Optional[str]
    vin: str
    vehicle_model_year: int
    adas_equipped: Optional[bool]
    is_structural: bool
    insurer_relation_id: Optional[str]
    assigned_technician_id: str
    status: str
    estimate_total_cents: int
    oe_parts_ratio_by_cost: float
    oe_parts_ratio_by_count: float
    rework_count: int
    completed_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ProcedureStep(TypedDict, total=False):
    id: str
    repair_order_id: str
    step_type: str
    performed_by_technician_id: str
    performed_at: str
    result: str
    scan_report_uri: Optional[str]
    sequence_index: int
    status: str
    created_at: str
    updated_at: str
    version: int


class PartLineItem(TypedDict, total=False):
    id: str
    repair_order_id: str
    part_number: str
    part_class: str
    unit_cost_cents: int
    quantity: int
    is_safety_critical: bool
    alternative_justification: Optional[str]
    line_status: str
    created_at: str
    updated_at: str
    version: int


class WarrantyClaim(TypedDict, total=False):
    id: str
    repair_order_id: str
    claimant_contact: str
    defect_category: str
    claim_amount_cents: int
    filed_at: str
    status: str
    filed_by_role: str
    reviewed_by_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class InsurerRelation(TypedDict, total=False):
    id: str
    shop_id: str
    insurer_code: str
    steering_enabled: bool
    discount_pct_bps: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Referral(TypedDict, total=False):
    id: str
    consumer_zip: str
    source_type: str
    source_reference: str
    insurer_code: Optional[str]
    vin: str
    routed_shop_id: Optional[str]
    status: str
    routed_at: Optional[str]
    created_at: str
    updated_at: str
    version: int
