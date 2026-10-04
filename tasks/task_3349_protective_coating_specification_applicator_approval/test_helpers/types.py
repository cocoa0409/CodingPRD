"""Domain types: status enumerations and entity shapes.

All fourteen resources are mutable records carrying the common quartet of
``id``, ``created_at``, ``updated_at`` and ``version`` (PRD §2.4); no resource
in this contract is append-only.
"""

from enum import Enum
from typing import List, Optional, TypedDict


# ── Input enumerations ───────────────────────────────────────────────────────

class SurfacePrepStandard(str, Enum):
    SSPC_SP10_NEAR_WHITE = "SSPC_SP10_NEAR_WHITE"
    SSPC_SP6_COMMERCIAL = "SSPC_SP6_COMMERCIAL"
    SSPC_SP11_POWER_TOOL = "SSPC_SP11_POWER_TOOL"
    SSPC_SP1_SOLVENT = "SSPC_SP1_SOLVENT"


class ApplicationMethod(str, Enum):
    SPRAY_AIRLESS = "SPRAY_AIRLESS"
    SPRAY_CONVENTIONAL = "SPRAY_CONVENTIONAL"
    BRUSH_ROLLER = "BRUSH_ROLLER"


class AssetType(str, Enum):
    BRIDGE = "BRIDGE"
    TANK_EXTERIOR = "TANK_EXTERIOR"
    TANK_INTERIOR = "TANK_INTERIOR"
    PIPELINE = "PIPELINE"
    STRUCTURAL_STEEL = "STRUCTURAL_STEEL"


class DefectMode(str, Enum):
    ADHESION_LOSS = "ADHESION_LOSS"
    CRACKING = "CRACKING"
    CORROSION_UNDERFILM = "CORROSION_UNDERFILM"
    DELAMINATION = "DELAMINATION"
    COLOR_GLOSS_DRIFT = "COLOR_GLOSS_DRIFT"


class OpenedBy(str, Enum):
    OWNER = "OWNER"
    MANUFACTURER = "MANUFACTURER"
    APPLICATOR = "APPLICATOR"


class AdjudicationOutcome(str, Enum):
    PRODUCT_DEFECT = "PRODUCT_DEFECT"
    APPLICATION_ERROR = "APPLICATION_ERROR"
    SHARED = "SHARED"
    NO_DEFECT = "NO_DEFECT"


# ── Status enumerations ─────────────────────────────────────────────────────

class CoatingSystemStatus(str, Enum):
    ACTIVE = "ACTIVE"
    OBSOLETE = "OBSOLETE"


class VocRegulationStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUPERSEDED = "SUPERSEDED"


class ApplicatorStatus(str, Enum):
    REGISTERED = "REGISTERED"
    ACTIVE = "ACTIVE"


class QualificationProgramStatus(str, Enum):
    ACTIVE = "ACTIVE"
    RETIRED = "RETIRED"


class QualificationStatus(str, Enum):
    CANDIDATE = "CANDIDATE"
    CERTIFIED = "CERTIFIED"
    SUSPENDED = "SUSPENDED"
    PROBATION = "PROBATION"
    REVOKED = "REVOKED"


class ProjectStatus(str, Enum):
    PLANNING = "PLANNING"
    SPECIFIED = "SPECIFIED"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class SpecificationStatus(str, Enum):
    DRAFT = "DRAFT"
    ISSUED = "ISSUED"
    SUPERSEDED = "SUPERSEDED"
    WITHDRAWN = "WITHDRAWN"


class SubstitutionRequestStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    UNDER_REVIEW = "UNDER_REVIEW"
    MORE_INFO_REQUESTED = "MORE_INFO_REQUESTED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


class WorkOrderStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    PREP_INSPECTION = "PREP_INSPECTION"
    PREP_APPROVED = "PREP_APPROVED"
    COATING_IN_PROGRESS = "COATING_IN_PROGRESS"
    ON_HOLD = "ON_HOLD"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class PrepResult(str, Enum):
    PASSED = "PASSED"
    FAILED = "FAILED"


class PrepFailureReason(str, Enum):
    PREP_STANDARD_MISMATCH = "PREP_STANDARD_MISMATCH"
    PROFILE_OUT_OF_RANGE = "PROFILE_OUT_OF_RANGE"
    SALT_EXCEEDED = "SALT_EXCEEDED"
    DEW_POINT_SPREAD_TOO_SMALL = "DEW_POINT_SPREAD_TOO_SMALL"


class CureState(str, Enum):
    WET = "WET"
    CURED = "CURED"
    INVALID = "INVALID"


class AcceptanceState(str, Enum):
    UNTESTED = "UNTESTED"
    TESTED = "TESTED"
    WAIVED = "WAIVED"


class SubVerdict(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"


class OverallVerdict(str, Enum):
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"


class WarrantyStatus(str, Enum):
    ACTIVE = "ACTIVE"
    CLAIMED = "CLAIMED"
    RESOLVED = "RESOLVED"
    DENIED = "DENIED"
    VOIDED = "VOIDED"


class InvestigationStatus(str, Enum):
    OPENED = "OPENED"
    EVIDENCE_GATHERING = "EVIDENCE_GATHERING"
    ADJUDICATED_PRODUCT_DEFECT = "ADJUDICATED_PRODUCT_DEFECT"
    ADJUDICATED_APPLICATION_ERROR = "ADJUDICATED_APPLICATION_ERROR"
    ADJUDICATED_SHARED = "ADJUDICATED_SHARED"
    CLOSED_NO_DEFECT = "CLOSED_NO_DEFECT"


# ── Entity shapes (every resource carries the common quartet) ───────────────

class CoatingSystem(TypedDict, total=False):
    id: str
    system_code: str
    manufacturer_name: str
    is_competitor_system: bool
    spec_revision: int
    surface_prep_standard: str
    min_surface_profile_mils: float
    max_surface_profile_mils: float
    coat_count: int
    total_dft_min_mils: float
    total_dft_max_mils: float
    base_voc_gpl: float
    thinner_voc_gpl: float
    max_thinner_pct: float
    adhesion_min_psi: int
    status: str
    created_at: str
    updated_at: str
    version: int


class VocRegulation(TypedDict, total=False):
    id: str
    jurisdiction_code: str
    application_method: str
    voc_limit_gpl: int
    effective_from: str
    effective_to: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Applicator(TypedDict, total=False):
    id: str
    company_name: str
    contact_email: str
    quality_history_score: int
    consecutive_passed_inspections: int
    status: str
    created_at: str
    updated_at: str
    version: int


class QualificationProgram(TypedDict, total=False):
    id: str
    program_code: str
    coating_system_id: str
    min_quality_history_score: int
    min_consecutive_passed_inspections: int
    requires_training: bool
    requires_equipment_audit: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class ApplicatorQualification(TypedDict, total=False):
    id: str
    applicator_id: str
    program_id: str
    training_completed_at: Optional[str]
    equipment_audit_passed: bool
    suspension_count: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Project(TypedDict, total=False):
    id: str
    project_name: str
    owner_name: str
    jurisdiction_code: str
    asset_type: str
    warranty_budget_cents: int
    committed_warranty_exposure_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class ProjectSpecification(TypedDict, total=False):
    id: str
    project_id: str
    coating_system_id: str
    pinned_spec_revision: int
    supersedes_specification_id: Optional[str]
    pinned_voc_regulation_id: str
    application_method: str
    voc_at_issuance_gpl: float
    status: str
    created_at: str
    updated_at: str
    version: int


class SubstitutionRequest(TypedDict, total=False):
    id: str
    specification_id: str
    proposed_coating_system_id: str
    rationale: str
    review_round: int
    max_review_rounds: int
    decision_reason: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class WorkOrder(TypedDict, total=False):
    id: str
    project_id: str
    specification_id: str
    applicator_id: str
    asset_zone: str
    window_start: str
    window_end: str
    hold_point_prep_released: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class SurfacePreparationInspection(TypedDict, total=False):
    id: str
    work_order_id: str
    inspector_id: str
    observed_prep_standard: str
    measured_profile_mils: float
    soluble_salt_ug_cm2: float
    ambient_dew_point_spread_c: float
    result: str
    failure_reasons: List[str]
    created_at: str
    updated_at: str
    version: int


class CoatingApplication(TypedDict, total=False):
    id: str
    work_order_id: str
    coat_number: int
    applied_at: str
    thinner_pct_used: float
    applied_voc_gpl: float
    voc_compliant: bool
    cure_state: str
    acceptance_state: str
    created_at: str
    updated_at: str
    version: int


class InspectionReport(TypedDict, total=False):
    id: str
    coating_application_id: str
    inspector_id: str
    spot_dft_readings_mils: List[float]
    adhesion_readings_psi: List[float]
    holiday_count: int
    tested_area_m2: float
    dft_verdict: str
    adhesion_verdict: str
    holiday_verdict: str
    overall_verdict: str
    created_at: str
    updated_at: str
    version: int


class Warranty(TypedDict, total=False):
    id: str
    project_id: str
    work_order_id: str
    term_years: int
    exposure_cents: int
    material_share_cents: int
    application_share_cents: int
    manufacturer_fault_pct: int
    status: str
    created_at: str
    updated_at: str
    version: int


class FailureInvestigation(TypedDict, total=False):
    id: str
    warranty_id: str
    opened_by: str
    defect_mode: str
    evidence_notes: str
    adjudicated_fault_pct: Optional[int]
    status: str
    created_at: str
    updated_at: str
    version: int
