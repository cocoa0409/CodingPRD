"""Domain types: entity TypedDicts, status enums, role enum.

Field names mirror the identifiers declared in the product requirements exactly.
Every resource in this API carries id / created_at / updated_at / version.
"""

from enum import Enum
from typing import List, Optional, TypedDict


class UserRole(str, Enum):
    RATING_ADMIN = "RatingAdmin"
    HOSPITAL_RESPONDENT = "HospitalRespondent"
    VERIFICATION_ANALYST = "VerificationAnalyst"
    RATING_ENGINE = "RatingEngine"
    PURCHASER_ADMIN = "PurchaserAdmin"
    ANY_AUTHENTICATED = "AnyAuthenticated"


class HospitalStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class DisclosureStatus(str, Enum):
    NEVER_SUBMITTED = "NEVER_SUBMITTED"
    SUBMITTED = "SUBMITTED"
    UNVERIFIED = "UNVERIFIED"


class TeachingStatus(str, Enum):
    TEACHING = "TEACHING"
    NON_TEACHING = "NON_TEACHING"


class SurveyAfStatus(str, Enum):
    AWAITING_SUBMISSION = "AWAITING_SUBMISSION"
    SUBMITTED = "SUBMITTED"
    VERIFIED = "VERIFIED"
    DISCREPANCY_OPEN = "DISCREPANCY_OPEN"
    DISCREPANCY_RESOLVED = "DISCREPANCY_RESOLVED"


class SurveyCertificationLevel(str, Enum):
    UNCERTIFIED = "UNCERTIFIED"
    CERTIFIED = "CERTIFIED"
    CERTIFICATION_WITHDRAWN = "CERTIFICATION_WITHDRAWN"


class VerificationResponse(str, Enum):
    ACCEPT = "ACCEPT"
    DISCREPANCY_REQUEST = "DISCREPANCY_REQUEST"


class MethodologyStatus(str, Enum):
    DRAFT = "DRAFT"
    PUBLISHED = "PUBLISHED"


class MeasureStatus(str, Enum):
    REPORTED = "REPORTED"
    UNREPORTED_EXCLUDED = "UNREPORTED_EXCLUDED"
    PUBLIC_SOURCE_SUBSTITUTED = "PUBLIC_SOURCE_SUBSTITUTED"


class Domain(str, Enum):
    PATIENT_SAFETY = "PATIENT_SAFETY"
    INFECTION_PREVENTION = "INFECTION_PREVENTION"
    CPOE = "CPOE"
    STAFFING = "STAFFING"
    SURGICAL_VOLUME = "SURGICAL_VOLUME"


class DerivationRule(str, Enum):
    NONE = "NONE"
    RATE_TO_COUNT_FLOOR = "RATE_TO_COUNT_FLOOR"
    INVERSE_BOUNDED = "INVERSE_BOUNDED"
    PER_100_BEDS_FLOOR = "PER_100_BEDS_FLOOR"


class ReadinessState(str, Enum):
    INCOMPLETE = "INCOMPLETE"
    OMITTED_FROM_CYCLE = "OMITTED_FROM_CYCLE"
    READY = "READY"


class ScoreState(str, Enum):
    RUNNING = "RUNNING"
    SCORED = "SCORED"
    CHAR_EXEMPT = "CHAR_EXEMPT"
    REANALYSIS_PENDING = "REANALYSIS_PENDING"


class GradeStatus(str, Enum):
    SCORED = "SCORED"
    CHAR_EXEMPT = "CHAR_EXEMPT"
    CORRECTED = "CORRECTED"
    WITHHELD = "WITHHELD"


class ReleaseCycleState(str, Enum):
    DRAFT = "DRAFT"
    OPEN_REVIEW = "OPEN_REVIEW"
    CORRECTION_CLOSED = "CORRECTION_CLOSED"
    EMBARGOED = "EMBARGOED"
    PUBLISHED = "PUBLISHED"


class HospitalReviewStatus(str, Enum):
    PENDING = "PENDING"
    ACCEPTED = "ACCEPTED"
    CORRECTION_REQUESTED = "CORRECTION_REQUESTED"


class CorrectionType(str, Enum):
    MEASURE_VALUE_ERROR = "MEASURE_VALUE_ERROR"
    MEASURE_OMISSION = "MEASURE_OMISSION"
    SOURCE_PROGRAM_MISMATCH = "SOURCE_PROGRAM_MISMATCH"


class CorrectionStatus(str, Enum):
    PENDING = "PENDING"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"
    EXPIRED = "EXPIRED"


class ReanalysisStatus(str, Enum):
    PENDING = "PENDING"
    UNDER_REVIEW = "UNDER_REVIEW"
    GRANTED = "GRANTED"
    REFUTED = "REFUTED"
    WITHDRAWN = "WITHDRAWN"


class PendingMethodologyChangeStatus(str, Enum):
    PENDING = "PENDING"
    APPLIED = "APPLIED"
    REJECTED_NOT_COMPARABLE = "REJECTED_NOT_COMPARABLE"
    WITHDRAWN = "WITHDRAWN"


class PurchaserType(str, Enum):
    SELF_INSURED_EMPLOYER = "SELF_INSURED_EMPLOYER"
    COALITION = "COALITION"
    HEALTH_PLAN = "HEALTH_PLAN"


class Hospital(TypedDict, total=False):
    id: str
    name: str
    ccn: str
    state_code: str
    bed_count: int
    teaching_status: str
    annual_discharges: int
    survey_contact_email: str
    active_methodology_version_id: Optional[str]
    worst_grade_ever: Optional[str]
    disclosure_status: str
    submitted_source_document_count: int
    status: str
    created_at: str
    updated_at: str
    version: int


class MeasureDefinition(TypedDict, total=False):
    measure_code: str
    domain: str
    scale_factor: float
    weight: float
    multiplier: float
    peer_mean: float
    peer_sd: float
    higher_is_better: bool
    derivation_rule: str


class MethodologyVersion(TypedDict, total=False):
    id: str
    label: str
    previous_version_id: Optional[str]
    measure_definitions: List[MeasureDefinition]
    status: str
    publication_date: str
    comparability_index: Optional[float]
    created_at: str
    updated_at: str
    version: int


class Survey(TypedDict, total=False):
    id: str
    hospital_id: str
    methodology_version_id: str
    submitted_by_user_id: str
    started_survey_count: int
    completed_survey_count: int
    entity_annual_discharges: int
    validation_method: Optional[str]
    verification_response: Optional[str]
    verification_cycle: int
    reanalysis_request_count: int
    reliability_weight: Optional[float]
    sample_rate: Optional[float]
    af_status: str
    af_certification_level: str
    created_at: str
    updated_at: str
    version: int


class SurveyMeasure(TypedDict, total=False):
    id: str
    hospital_id: str
    survey_id: str
    measure_code: str
    raw_value: float
    source_program_id: Optional[str]
    derived_value: Optional[float]
    measure_status: str
    flag_hold: bool
    created_at: str
    updated_at: str
    version: int


class HospitalMeasureSet(TypedDict, total=False):
    id: str
    hospital_id: str
    methodology_version_id: str
    source_snapshot_at: str
    measures: List[dict]
    substituted_measure_count: int
    readiness_state: str
    created_at: str
    updated_at: str
    version: int


class ScoreRun(TypedDict, total=False):
    id: str
    hospital_id: str
    methodology_version_id: str
    measure_set_id: str
    reliability_weight: Optional[float]
    domain_scores: List[dict]
    composite_score: float
    base_grade_letter: Optional[str]
    letter_grade: Optional[str]
    score_state: str
    created_at: str
    updated_at: str
    version: int


class ReleaseCycle(TypedDict, total=False):
    id: str
    label: str
    methodology_version_id: str
    preliminary_release_date: str
    correction_window_ends_at: str
    publication_date: str
    embargo_lifted: bool
    state: str
    grade_count: int
    correction_request_count: int
    created_at: str
    updated_at: str
    version: int


class Grade(TypedDict, total=False):
    id: str
    hospital_id: str
    release_cycle_id: str
    score_run_id: str
    composite_score: Optional[float]
    letter_grade: Optional[str]
    grade_cap_applied: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class HospitalReview(TypedDict, total=False):
    id: str
    hospital_id: str
    grade_id: str
    release_cycle_id: str
    preliminary_composite_score: Optional[float]
    preliminary_letter_grade: Optional[str]
    challenged_measure_codes: List[str]
    accepted_at: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class CorrectionRequest(TypedDict, total=False):
    id: str
    hospital_id: str
    hospital_review_id: str
    correction_type: str
    corrected_measure_codes: List[str]
    supporting_reference: str
    delta_points: float
    status: str
    created_at: str
    updated_at: str
    version: int


class ReanalysisRequest(TypedDict, total=False):
    id: str
    hospital_id: str
    survey_id: str
    subset_selector: List[dict]
    supporting_documents: List[dict]
    requested_delta: Optional[float]
    adjusted_delta: Optional[float]
    non_regression_confirmed: bool
    reference_stale: bool
    documents_sufficient: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class Employer(TypedDict, total=False):
    id: str
    name: str
    purchaser_type: str
    status: str
    network_hospital_ids: List[str]
    benefit_window_from: str
    benefit_window_to: str
    network_hospital_count: int
    minimum_acceptable_letter: str
    eligible_hospital_count: int
    utilization_index: Optional[float]
    created_at: str
    updated_at: str
    version: int


class PendingMethodologyChange(TypedDict, total=False):
    id: str
    hospital_id: str
    to_methodology_version_id: str
    from_hospital_methodology_version_id: str
    comparability_index: Optional[float]
    status: str
    decided_by_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int