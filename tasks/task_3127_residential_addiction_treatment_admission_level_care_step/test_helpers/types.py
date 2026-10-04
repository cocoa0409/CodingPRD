"""Domain types: ASAM levels, entity statuses, role enum and entity TypedDicts.

Every persisted resource in this network carries the common fields described in
PRD §2.4 — ``id``, ``created_at``, ``updated_at`` and ``version`` — and none of
them opts out, so every TypedDict below carries all four.
"""

from enum import Enum
from typing import List, Optional, TypedDict


class AsamLevel(str, Enum):
    """Levels of care, lowest rank first (PRD §3.1)."""

    ASAM_1_0 = "ASAM_1_0"
    ASAM_2_1 = "ASAM_2_1"
    ASAM_3_1 = "ASAM_3_1"
    ASAM_3_5 = "ASAM_3_5"
    ASAM_3_7 = "ASAM_3_7"


# Rank order used by every comparison in the PRD: lowest first (PRD §3.1).
ASAM_RANK = {
    "ASAM_1_0": 0,
    "ASAM_2_1": 1,
    "ASAM_3_1": 2,
    "ASAM_3_5": 3,
    "ASAM_3_7": 4,
}


class CredentialTier(str, Enum):
    """The clinical credential ladder, ascending (PRD §2.5)."""

    TIER_1_SUPPORT = "TIER_1_SUPPORT"
    TIER_2_COUNSELOR = "TIER_2_COUNSELOR"
    TIER_3_LICENSED = "TIER_3_LICENSED"
    TIER_4_INDEPENDENT = "TIER_4_INDEPENDENT"


CREDENTIAL_RANK = {
    "TIER_1_SUPPORT": 1,
    "TIER_2_COUNSELOR": 2,
    "TIER_3_LICENSED": 3,
    "TIER_4_INDEPENDENT": 4,
}


class UserRole(str, Enum):
    """The seven roles the network declares (PRD §2.1)."""

    PLATFORM_ADMIN = "PlatformAdmin"
    CLINICAL_DIRECTOR = "ClinicalDirector"
    UTILIZATION_REVIEWER = "UtilizationReviewer"
    ADMISSIONS_INTAKE_NURSE = "AdmissionsIntakeNurse"
    CLINICIAN = "Clinician"
    ALUMNI_COORDINATOR = "AlumniCoordinator"
    ANY = "Any"


class FacilityPosture(str, Enum):
    OPEN = "OPEN"
    RESTRICTED = "RESTRICTED"
    FROZEN = "FROZEN"


class AccreditationClass(str, Enum):
    ACCREDITATION_BODY = "ACCREDITATION_BODY"
    STATE_LICENSE = "STATE_LICENSE"
    RECOVERY_HOUSE = "RECOVERY_HOUSE"


class AccreditationStatus(str, Enum):
    GRANTED = "GRANTED"
    SUSPENDED = "SUSPENDED"
    REVOKED = "REVOKED"
    EXPIRED = "EXPIRED"


class ClinicalStatus(str, Enum):
    AWAITING_ASSESSMENT = "AWAITING_ASSESSMENT"
    UNDER_ASSESSMENT = "UNDER_ASSESSMENT"
    AWAITING_AUTHORIZATION = "AWAITING_AUTHORIZATION"
    AWAITING_ADMISSION = "AWAITING_ADMISSION"
    IN_TREATMENT = "IN_TREATMENT"
    COMPLETED = "COMPLETED"
    DISCHARGED = "DISCHARGED"


class CareLevelStatus(str, Enum):
    NOT_STARTED = "NOT_STARTED"
    ACTIVE = "ACTIVE"
    STEP_DOWN_PENDING = "STEP_DOWN_PENDING"
    STEPPED_DOWN = "STEPPED_DOWN"


class AuthorizationPosture(str, Enum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    CONCURRENT_REVIEW_DUE = "CONCURRENT_REVIEW_DUE"
    EXTENDED = "EXTENDED"
    STEP_DOWN_REQUIRED = "STEP_DOWN_REQUIRED"
    DENIED = "DENIED"
    EXHAUSTED = "EXHAUSTED"
    EXPIRED = "EXPIRED"


class AssessmentStatus(str, Enum):
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    SUPERSEDED = "SUPERSEDED"
    CANCELLED = "CANCELLED"


class ClearanceStatus(str, Enum):
    PENDING = "PENDING"
    CLEARED = "CLEARED"
    FAILED = "FAILED"
    EXPIRED = "EXPIRED"


class SessionStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    ATTENDED = "ATTENDED"
    NO_SHOW = "NO_SHOW"
    CANCELLED = "CANCELLED"


class BedStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    OCCUPIED = "OCCUPIED"
    CLEANING = "CLEANING"


class LevelOfCareChangeStatus(str, Enum):
    PLANNED = "PLANNED"
    PENDING_DISCHARGE_ORDER = "PENDING_DISCHARGE_ORDER"
    AWAITING_DISCHARGE = "AWAITING_DISCHARGE"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class CommonFields(TypedDict):
    """The four common fields carried by every persisted resource (PRD §2.4)."""

    id: str
    created_at: str
    updated_at: str
    version: int


class Facility(CommonFields):
    name: str
    state_code: str
    licensed: bool
    as_level_max: str
    state_min_credential_tier: str
    is_accepting_admissions: bool
    facility_posture: str
    compliance_risk_points: int
    ops_epoch: int
    last_ops_run_at: Optional[str]


class Bed(CommonFields):
    facility_id: str
    unit_name: str
    bed_label: str
    level_of_care: str
    cleaning_turnaround_hours: int
    next_available_at: Optional[str]
    status: str


class Clinician(CommonFields):
    full_name: str
    credential_tier: str
    is_medical_provider: bool


class ClinicianFacilityCredential(CommonFields):
    clinician_id: str
    facility_id: str
    effective_at: str
    expires_at: str
    status: str
    is_usable: bool


class ServiceOffering(CommonFields):
    facility_id: str
    service_code: str
    level_of_care: str
    required_min_credential_tier: str
    requires_medical_provider: bool


class Payer(CommonFields):
    name: str
    initial_authorized_days_by_loc: dict
    step_down_coverage_map: dict
    concurrent_review_interval_days: int
    credential_min_tier_by_loc: dict


class TreatmentEpisode(CommonFields):
    facility_id: str
    patient_ref: str
    assigned_level: Optional[str]
    admitted_at: Optional[str]
    discharged_at: Optional[str]
    clinical_status: str
    care_level_status: str
    step_down_count: int
    therapy_revenue_cents: int
    revcap_pre_step_down_cents: Optional[int]
    revcap_post_step_down_cents: Optional[int]


class ClinicalAssessment(CommonFields):
    episode_id: str
    facility_id: str
    assessor_clinician_id: str
    assessed_at: Optional[str]
    dimension_scores: dict
    placement_basis: str
    total_score: Optional[int]
    recommended_level: Optional[str]
    status: str


class LevelOfCareAuthorization(CommonFields):
    episode_id: str
    facility_id: str
    payer_id: str
    requested_level: str
    granted_level: Optional[str]
    authorized_days: Optional[int]
    days_used: int
    days_remaining: Optional[int]
    review_due_at: Optional[str]
    concurrent_review_count: int
    urgency_score: Optional[float]
    posture: str


class MedicalClearance(CommonFields):
    episode_id: str
    facility_id: str
    clearance_type: str
    status: str
    ordered_at: str
    cleared_at: Optional[str]
    expires_at: Optional[str]
    window_hours_remaining: Optional[int]
    window_days_remaining: Optional[int]
    effective_status: Optional[str]


class WithdrawalManagementPlan(CommonFields):
    episode_id: str
    facility_id: str
    protocol: str
    ciwa_score: int
    ciwa_recorded_at: str
    dose_records: List[dict]
    status: str


class TreatmentPlan(CommonFields):
    episode_id: str
    facility_id: str
    author_clinician_id: str
    required_sessions_per_week: int
    status: str
    cosign_rationale_code: str


class SessionAttendance(CommonFields):
    episode_id: str
    facility_id: str
    service_id: str
    clinician_id: str
    scheduled_at: str
    duration_minutes: int
    attended: bool
    status: str
    billing_amount_cents: int


class LevelOfCareChange(CommonFields):
    episode_id: str
    facility_id: str
    authorization_id: str
    bed_id: Optional[str]
    from_level: str
    to_level: str
    change_type: str
    effective_at: str
    retry_available_at: Optional[str]
    status: str


class ContinuingCarePlan(CommonFields):
    episode_id: str
    facility_id: str
    housing_selection_basis: str
    housing_id: Optional[str]
    housing_window_start: str
    housing_window_end: str
    shelter_class: str
    wants_recovery_only_house: bool
    alumni_contact_interval_days: int
    alumni_contacts_required: int
    authorizing_clinician_id: str
    status: str


class RecoveryHousing(CommonFields):
    facility_id: str
    house_name: str
    proximity_rank: int
    day_rate_cents: int
    grab_barrier_hours: int
    capacity_beds: int
    licensed: bool
    status: str


class AlumniContact(CommonFields):
    episode_id: str
    facility_id: str
    scheduled_for: str
    attempt_number: int
    outcome: str
    abstinent_at_contact: Optional[bool]
    record_filed_at: Optional[str]
    recorded_by_user_id: Optional[str]


class Accreditation(CommonFields):
    facility_id: str
    accreditation_class: str
    granting_body: str
    status: str
    effective_at: str
    expires_at: str
    license_level_max: Optional[str]
    credential_tier_min: Optional[str]
