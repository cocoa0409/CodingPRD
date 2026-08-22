"""Domain types for the Building Commissioning API: entity TypedDicts and enums.

Every stored resource in this system carries `id`, `created_at`, `updated_at`
and `version` (PRD section 2.4), so every entity TypedDict below lists all four.
"""

from enum import Enum
from typing import List, Optional, TypedDict


# --------------------------------------------------------------------------
# Roles
# --------------------------------------------------------------------------
class UserRole(str, Enum):
    PLATFORM_ADMIN = "PlatformAdmin"
    CX_AUTHORITY = "CxAuthority"
    CONTRACTOR = "Contractor"
    DESIGN_TEAM = "DesignTeam"
    OWNER_REPRESENTATIVE = "OwnerRepresentative"


# --------------------------------------------------------------------------
# Enumerations
# --------------------------------------------------------------------------
class ProjectType(str, Enum):
    NEW_CONSTRUCTION = "NEW_CONSTRUCTION"
    RETRO_COMMISSIONING = "RETRO_COMMISSIONING"


class CertificationTarget(str, Enum):
    NONE = "NONE"
    STANDARD = "STANDARD"
    ENHANCED = "ENHANCED"


class DeliveryPhase(str, Enum):
    PLANNING = "PLANNING"
    DESIGN = "DESIGN"
    CONSTRUCTION = "CONSTRUCTION"
    FUNCTIONAL_TESTING = "FUNCTIONAL_TESTING"
    ACCEPTANCE = "ACCEPTANCE"
    WARRANTY = "WARRANTY"
    CLOSED = "CLOSED"


class ReadinessPosture(str, Enum):
    OPEN = "OPEN"
    RESTRICTED = "RESTRICTED"
    FROZEN = "FROZEN"


class AcceptanceKind(str, Enum):
    SUBSTANTIAL = "SUBSTANTIAL"
    FINAL = "FINAL"


class Criticality(str, Enum):
    LIFE_SAFETY = "LIFE_SAFETY"
    CRITICAL = "CRITICAL"
    STANDARD = "STANDARD"


class RequirementStatus(str, Enum):
    DRAFT = "DRAFT"
    APPROVED = "APPROVED"
    SUPERSEDED = "SUPERSEDED"


class PlanStatus(str, Enum):
    DRAFT = "DRAFT"
    APPROVED = "APPROVED"
    SUPERSEDED = "SUPERSEDED"


class SubmittalKind(str, Enum):
    DESIGN_DOCUMENT = "DESIGN_DOCUMENT"
    PRODUCT_DATA = "PRODUCT_DATA"
    SHOP_DRAWING = "SHOP_DRAWING"
    OM_DATA = "OM_DATA"


class SubmittalStatus(str, Enum):
    RECEIVED = "RECEIVED"
    APPROVED = "APPROVED"
    APPROVED_AS_NOTED = "APPROVED_AS_NOTED"
    REVISE_AND_RESUBMIT = "REVISE_AND_RESUBMIT"


class SystemType(str, Enum):
    AHU = "AHU"
    CHILLER = "CHILLER"
    BOILER = "BOILER"
    LIGHTING = "LIGHTING"
    FIRE_ALARM = "FIRE_ALARM"
    ELEVATOR = "ELEVATOR"
    BAS = "BAS"


class InstallStatus(str, Enum):
    NOT_INSTALLED = "NOT_INSTALLED"
    INSTALLED = "INSTALLED"
    STARTED_UP = "STARTED_UP"
    REMOVED = "REMOVED"


class VerificationStatus(str, Enum):
    UNVERIFIED = "UNVERIFIED"
    PREFUNCTIONAL_VERIFIED = "PREFUNCTIONAL_VERIFIED"
    FUNCTIONAL_ACCEPTED = "FUNCTIONAL_ACCEPTED"
    CONDITIONALLY_ACCEPTED = "CONDITIONALLY_ACCEPTED"


class ChecklistStatus(str, Enum):
    DRAFT = "DRAFT"
    EXECUTED = "EXECUTED"
    VERIFIED = "VERIFIED"
    REWORK = "REWORK"


class ItemResult(str, Enum):
    PENDING = "PENDING"
    PASS = "PASS"
    FAIL = "FAIL"
    NA = "NA"


class FunctionalTestStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    IN_PROGRESS = "IN_PROGRESS"
    PASSED = "PASSED"
    PASSED_WITH_EXCEPTIONS = "PASSED_WITH_EXCEPTIONS"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class IssueOrigin(str, Enum):
    DESIGN_REVIEW = "DESIGN_REVIEW"
    SUBMITTAL = "SUBMITTAL"
    PREFUNCTIONAL = "PREFUNCTIONAL"
    FUNCTIONAL = "FUNCTIONAL"
    SEASONAL = "SEASONAL"
    RETRO_CX = "RETRO_CX"


class IssueSeverity(str, Enum):
    S1 = "S1"
    S2 = "S2"
    S3 = "S3"
    S4 = "S4"


class IssueStatus(str, Enum):
    OPEN = "OPEN"
    IN_REVIEW = "IN_REVIEW"
    VERIFIED_CLOSED = "VERIFIED_CLOSED"
    DEFERRED = "DEFERRED"
    VOID = "VOID"


class Season(str, Enum):
    HEATING = "HEATING"
    COOLING = "COOLING"
    SHOULDER = "SHOULDER"


class DeferredTestStatus(str, Enum):
    PLANNED = "PLANNED"
    BLOCKED = "BLOCKED"
    EXECUTED_PASS = "EXECUTED_PASS"
    EXECUTED_FAIL = "EXECUTED_FAIL"
    MISSED = "MISSED"


class DeliverableKind(str, Enum):
    TRAINING_SESSION = "TRAINING_SESSION"
    SYSTEMS_MANUAL_SECTION = "SYSTEMS_MANUAL_SECTION"
    OM_DATA_PACKAGE = "OM_DATA_PACKAGE"


class DeliverableStatus(str, Enum):
    PLANNED = "PLANNED"
    DELIVERED = "DELIVERED"
    ACCEPTED = "ACCEPTED"
    RETURNED = "RETURNED"


class CreditStatus(str, Enum):
    NOT_STARTED = "NOT_STARTED"
    IN_PREPARATION = "IN_PREPARATION"
    SUBMITTED = "SUBMITTED"
    AWARDED = "AWARDED"
    DENIED = "DENIED"
    WITHDRAWN = "WITHDRAWN"


class CreditTier(str, Enum):
    NONE = "NONE"
    BRONZE = "BRONZE"
    SILVER = "SILVER"
    GOLD = "GOLD"


class EvidenceType(str, Enum):
    EQUIPMENT_VERIFICATION = "EQUIPMENT_VERIFICATION"
    FUNCTIONAL_TEST = "FUNCTIONAL_TEST"
    CHECKLIST = "CHECKLIST"
    TRAINING = "TRAINING"
    MANUAL_SECTION = "MANUAL_SECTION"
    ENERGY_BASELINE = "ENERGY_BASELINE"


class BaselineStatus(str, Enum):
    BASELINE_SET = "BASELINE_SET"
    POST_PERIOD_RECORDED = "POST_PERIOD_RECORDED"
    CERTIFIED = "CERTIFIED"


class SavingsVariant(str, Enum):
    DEEMED = "DEEMED"
    MEASURED = "MEASURED"


# --------------------------------------------------------------------------
# Entity shapes
# --------------------------------------------------------------------------
class CxProject(TypedDict):
    id: str
    name: str
    building_name: str
    project_type: str
    certification_target: str
    contract_value_cents: int
    witness_capacity: int
    delivery_phase: str
    readiness_posture: str
    issue_severity_index: float
    retainage_withheld_cents: int
    verified_prefunctional_units: int
    open_blocking_issue_count: int
    acceptance_completion_score: float
    final_acceptance_score: Optional[float]
    acceptance_kind: Optional[str]
    withdrawn_credit_count: int
    total_awarded_points: float
    created_at: str
    updated_at: str
    version: int


class OwnerRequirement(TypedDict):
    id: str
    project_id: str
    supersedes_requirement_id: Optional[str]
    metric_key: str
    target_value: float
    tolerance_pct: float
    criticality: str
    revision: int
    status: str
    created_at: str
    updated_at: str
    version: int


class CxPlan(TypedDict):
    id: str
    project_id: str
    title: str
    status: str
    pinned_requirement_ids: List[str]
    pinned_requirement_count: int
    pin_stale: bool
    approved_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Submittal(TypedDict):
    id: str
    project_id: str
    equipment_id: Optional[str]
    title: str
    submittal_kind: str
    status: str
    review_round: int
    last_decision: Optional[str]
    review_comment: Optional[str]
    escalation_issue_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class EquipmentUnit(TypedDict):
    id: str
    project_id: str
    tag: str
    system_type: str
    criticality: str
    contract_value_cents: int
    weight_units: int
    install_status: str
    verification_status: str
    blocking_issue_count: int
    created_at: str
    updated_at: str
    version: int


class ChecklistItem(TypedDict):
    item_code: str
    description: str
    is_safety_critical: bool
    result: str
    recorded_by_user_id: Optional[str]
    recorded_at: Optional[str]


class PrefunctionalChecklist(TypedDict):
    id: str
    equipment_id: str
    template_code: str
    status: str
    items: List[ChecklistItem]
    item_count: int
    passed_item_count: int
    failed_item_count: int
    executed_by_user_id: Optional[str]
    verified_by_user_id: Optional[str]
    rework_cycle_count: int
    created_at: str
    updated_at: str
    version: int


class FunctionalTest(TypedDict):
    id: str
    equipment_id: str
    requirement_id: str
    retest_of_test_id: Optional[str]
    script_code: str
    scheduled_start: str
    scheduled_end: str
    status: str
    measured_value: Optional[float]
    outcome_deviation_pct: Optional[float]
    witness_user_id: Optional[str]
    started_at: Optional[str]
    completed_at: Optional[str]
    generated_issue_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Issue(TypedDict):
    id: str
    project_id: str
    equipment_id: Optional[str]
    closure_retest_id: Optional[str]
    origin: str
    source_ref_id: Optional[str]
    severity: str
    description: str
    status: str
    blocks_acceptance: bool
    opened_at: str
    opened_by_user_id: str
    proposed_by_user_id: Optional[str]
    proposed_resolution: Optional[str]
    retainage_hold_cents: int
    reopen_count: int
    created_at: str
    updated_at: str
    version: int


class DeferredTest(TypedDict):
    id: str
    equipment_id: str
    requirement_id: str
    issue_id: Optional[str]
    season: str
    window_start: str
    window_end: str
    status: str
    executed_at: Optional[str]
    measured_value: Optional[float]
    created_at: str
    updated_at: str
    version: int


class CloseoutDeliverable(TypedDict):
    id: str
    project_id: str
    equipment_id: Optional[str]
    deliverable_kind: str
    title: str
    required_attendee_count: int
    attendee_count: int
    duration_minutes: int
    session_start: Optional[str]
    status: str
    delivered_by_user_id: Optional[str]
    accepted_by_user_id: Optional[str]
    coverage_ratio: float
    created_at: str
    updated_at: str
    version: int


class CertificationCredit(TypedDict):
    id: str
    project_id: str
    credit_code: str
    required_evidence_count: int
    max_points: float
    status: str
    evidence_count: int
    fresh_evidence_count: int
    stale_evidence_count: int
    completeness_ratio: float
    provisional_tier: str
    documentation_score: float
    final_tier: str
    awarded_points: float
    submitted_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class CreditEvidence(TypedDict):
    id: str
    credit_id: str
    evidence_type: str
    evidence_ref_id: str
    is_stale: bool
    staled_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class EnergyBaseline(TypedDict):
    id: str
    project_id: str
    measure_code: str
    baseline_kwh: float
    baseline_hdd: float
    stipulated_kwh_per_hour: float
    operating_hours: float
    post_kwh: Optional[float]
    post_hdd: Optional[float]
    deemed_savings_kwh: Optional[float]
    measured_savings_kwh: Optional[float]
    certified_savings_kwh: Optional[float]
    certified_variant: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int
