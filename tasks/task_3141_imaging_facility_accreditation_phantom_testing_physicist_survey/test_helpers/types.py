"""Domain types: entity TypedDicts, status enums and role enum.

Every entity declared by the API carries the full common property set
(`id`, `created_at`, `updated_at`, `version`), so each TypedDict below
includes all four.
"""
from enum import Enum
from typing import Optional, TypedDict


# ─── Status / enum vocabularies ────────────────────────────────────────────

class FacilityStatus(str, Enum):
    PENDING = "PENDING"
    ENROLLED = "ENROLLED"
    DEFERRED = "DEFERRED"
    SUSPENDED = "SUSPENDED"


class AccreditationCurrency(str, Enum):
    PROVISIONAL = "PROVISIONAL"
    CURRENT = "CURRENT"
    LAPSED = "LAPSED"
    SUSPENDED = "SUSPENDED"


class PayerParticipationStatus(str, Enum):
    ACTIVE = "ACTIVE"
    AT_RISK = "AT_RISK"
    REVOKED = "REVOKED"


class RosterDisposition(str, Enum):
    CLEAR = "CLEAR"
    HOLD = "HOLD"
    HALT = "HALT"


class FacilityType(str, Enum):
    HOSPITAL = "HOSPITAL"
    IMAGING_CENTER = "IMAGING_CENTER"
    MOBILE_UNIT = "MOBILE_UNIT"


class ModalityCode(str, Enum):
    MRI = "MRI"
    CT = "CT"
    MAMM = "MAMM"
    PET = "PET"
    US = "US"


class UnitStatus(str, Enum):
    ENROLLED = "ENROLLED"
    DEFERRED = "DEFERRED"
    WITHDRAWN = "WITHDRAWN"


class EquipmentStatus(str, Enum):
    ACTIVE = "ACTIVE"
    OUT_OF_SERVICE = "OUT_OF_SERVICE"
    RETIRED = "RETIRED"


class PerformanceVerdict(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"
    PENDING = "PENDING"


class ImageType(str, Enum):
    CLINICAL = "CLINICAL"
    PHANTOM_REFERENCE = "PHANTOM_REFERENCE"


class ReviewStatus(str, Enum):
    PENDING_REVIEW = "PENDING_REVIEW"
    ACCEPTED = "ACCEPTED"
    DEFICIENCY = "DEFICIENCY"
    FAILED = "FAILED"
    RESUBMITTED = "RESUBMITTED"


class ReviewOutcome(str, Enum):
    ACCEPT = "ACCEPT"
    ACCEPT_WITH_DEFICIENCY = "ACCEPT_WITH_DEFICIENCY"
    FAIL = "FAIL"


class DeficiencyCode(str, Enum):
    NONE = "NONE"
    IMAGE_QUALITY = "IMAGE_QUALITY"
    POSITIONING = "POSITIONING"
    ARTIFACT = "ARTIFACT"
    DOSE = "DOSE"


class PhantomResultStatus(str, Enum):
    ACQUIRED = "ACQUIRED"
    SCORED = "SCORED"
    PASS = "PASS"
    FAIL = "FAIL"
    VOIDED = "VOIDED"


class SurveyType(str, Enum):
    ANNUAL = "ANNUAL"
    INITIAL = "INITIAL"
    POST_REPAIR = "POST_REPAIR"


class SurveyStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    SUBMITTED = "SUBMITTED"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"
    CORRECTIVE_REQUIRED = "CORRECTIVE_REQUIRED"
    RESUBMITTED = "RESUBMITTED"


class RejectionCode(str, Enum):
    NONE = "NONE"
    CREDENTIAL_LAPSED = "CREDENTIAL_LAPSED"
    DOSE_OUT_OF_RANGE = "DOSE_OUT_OF_RANGE"
    SHIELDING_FAILED = "SHIELDING_FAILED"
    DOCUMENTATION_INCOMPLETE = "DOCUMENTATION_INCOMPLETE"


class PersonnelRole(str, Enum):
    INTERPRETING_PHYSICIAN = "INTERPRETING_PHYSICIAN"
    TECHNOLOGIST = "TECHNOLOGIST"
    MEDICAL_PHYSICIST = "MEDICAL_PHYSICIST"


class CredentialStatus(str, Enum):
    PENDING = "PENDING"
    VERIFIED = "VERIFIED"
    LAPSED = "LAPSED"
    REVOKED = "REVOKED"


class PlanStatus(str, Enum):
    OPEN = "OPEN"
    SUBMITTED = "SUBMITTED"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"
    EXPIRED = "EXPIRED"


class DeadlineStatus(str, Enum):
    ON_TRACK = "ON_TRACK"
    DUE_SOON = "DUE_SOON"
    OVERDUE = "OVERDUE"


class CycleStatus(str, Enum):
    PENDING = "PENDING"
    ACTIVE = "ACTIVE"
    RENEWAL_DUE = "RENEWAL_DUE"
    RENEWED = "RENEWED"
    LAPSED = "LAPSED"


class AuditSelectionStatus(str, Enum):
    NOT_APPLICABLE = "NOT_APPLICABLE"
    SELECTED = "SELECTED"
    WAIVED = "WAIVED"


class AuditOutcome(str, Enum):
    PENDING = "PENDING"
    PASS = "PASS"
    FAIL = "FAIL"


class BenchmarkSubmissionStatus(str, Enum):
    NOT_STARTED = "NOT_STARTED"
    PARTIAL = "PARTIAL"
    COMPLETE = "COMPLETE"
    OVERDUE = "OVERDUE"


class BenchmarkStatus(str, Enum):
    NOT_EVALUATED = "NOT_EVALUATED"
    WITHIN_BENCHMARK = "WITHIN_BENCHMARK"
    ABOVE_BENCHMARK = "ABOVE_BENCHMARK"
    CRITICAL = "CRITICAL"


class DoseSubmissionStatus(str, Enum):
    STAGED = "STAGED"
    SUBMITTED = "SUBMITTED"
    REJECTED = "REJECTED"


class ExamCategoryCode(str, Enum):
    CT_HEAD = "CT_HEAD"
    CT_ABDOMEN = "CT_ABDOMEN"
    MAMM_SCREEN = "MAMM_SCREEN"
    PET_TORSO = "PET_TORSO"


class ShieldingVerdict(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"


class UserRole(str, Enum):
    FACILITY_ADMIN = "FacilityAdmin"
    MEDICAL_PHYSICIST = "MedicalPhysicist"
    ACCREDITATION_BODY = "AccreditationBody"
    ANY = "Any"
    ANONYMOUS = "Anonymous"


# ─── Entity TypedDicts (all carry full common properties) ─────────────────

class Facility(TypedDict):
    id: str
    name: str
    state_code: str
    facility_type: str
    facility_status: str
    accreditation_currency: str
    payer_participation_status: str
    registry_credit_cents: int
    enrolled_unit_count: int
    deferred_unit_count: int
    current_cycle_index: int
    rejected_survey_count: int
    roster_disposition: str
    created_at: str
    updated_at: str
    version: int


class ModalityUnit(TypedDict):
    id: str
    facility_id: str
    modality_code: str
    unit_label: str
    unit_status: str
    clinical_deadline_at: Optional[str]
    testing_deadline_at: Optional[str]
    phantom_attempt_count: int
    phantom_failure_count: int
    deficiency_open_count: int
    last_phantom_score: Optional[float]
    last_survey_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class EquipmentItem(TypedDict):
    id: str
    unit_id: str
    manufacturer: str
    model_number: str
    serial_number: str
    modality_code: str
    installed_on: str
    equipment_status: str
    performance_verdict: str
    created_at: str
    updated_at: str
    version: int


class ClinicalImageSubmission(TypedDict):
    id: str
    unit_id: str
    image_type: str
    submitted_at: str
    reviewer_note_code: str
    required_view_count: int
    accepted_view_count: int
    resubmission_of_submission_id: Optional[str]
    review_status: str
    deficiency_code: str
    review_outcome_score: Optional[float]
    deficiency_issued_at: Optional[str]
    deficiency_deadline_at: Optional[str]
    resubmission_round: int
    corrective_action_plan_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class PhantomTest(TypedDict):
    id: str
    unit_id: str
    phantom_serial_code: str
    acquired_at: str
    duration_minutes: int
    spatial_resolution_score: Optional[int]
    contrast_score: Optional[int]
    artifact_score: Optional[int]
    phantom_total_score: Optional[float]
    result_status: str
    scored_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class PhysicistSurvey(TypedDict):
    id: str
    facility_id: str
    physicist_qualification_id: str
    survey_type: str
    scheduled_at: str
    performed_at: Optional[str]
    reference_entrance_dose_mgy: float
    measured_entrance_dose_mgy: Optional[float]
    shielding_verdict: Optional[str]
    dose_deviation_pct: Optional[float]
    survey_status: str
    rejection_code: str
    unit_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class PersonnelQualification(TypedDict):
    id: str
    facility_id: str
    person_name: str
    personnel_role: str
    credential_number: str
    ce_credit_hours: float
    required_ce_hours: float
    credential_expires_on: str
    credential_status: str
    qualification_verified_at: Optional[str]
    survey_count: int
    created_at: str
    updated_at: str
    version: int


class CorrectiveActionPlan(TypedDict):
    id: str
    facility_id: str
    source_submission_id: str
    deficiency_code: str
    plan_status: str
    deadline_status: str
    due_at: str
    resubmission_deadline_at: str
    resubmission_attempts: int
    created_at: str
    updated_at: str
    version: int


class AccreditationCycle(TypedDict):
    id: str
    facility_id: str
    cycle_index: int
    cycle_started_at: str
    cycle_status: str
    cycle_expires_at: str
    prior_cycle_id: Optional[str]
    benchmark_submission_status: str
    audit_selection_status: str
    audit_outcome: str
    unit_count_at_start: Optional[int]
    created_at: str
    updated_at: str
    version: int


class DoseRegistryRecord(TypedDict):
    id: str
    unit_id: str
    exam_category_code: str
    exam_month: str
    dose_index_value: float
    benchmark_status: str
    submission_status: str
    submitted_at: Optional[str]
    benchmark_comparison_value: Optional[float]
    dose_benchmark_average: Optional[float]
    registry_fee_cents: int
    created_at: str
    updated_at: str
    version: int