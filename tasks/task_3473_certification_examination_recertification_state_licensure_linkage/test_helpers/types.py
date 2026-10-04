"""Domain types: entity TypedDicts, status enums, role enum.

Field sets follow PRD §2.4 (common resource properties) and the per-entity
narratives of PRD §3. The two configuration resources (LevelDefinition,
StateAdoptionPolicy) carry only `id` and `created_at` — `updated_at` and
`version` are absent on them (PRD §2.4). Every operational resource carries
`id`, `created_at`, `updated_at`, and `version`.
"""
from enum import Enum
from typing import Any, Dict, List, Optional, TypedDict


# ---------------------------------------------------------------------------
# Role enum (PRD §2.1 — spelled exactly)
# ---------------------------------------------------------------------------
class UserRole(str, Enum):
    ANONYMOUS = "Anonymous"
    CANDIDATE = "Candidate"
    PROGRAM_DIRECTOR = "ProgramDirector"
    STATE_OFFICIAL = "StateOfficial"
    REGISTRY_ADMIN = "RegistryAdmin"
    EXAM_PROCTOR = "ExamProctor"
    HEARING_OFFICER = "HearingOfficer"


# ---------------------------------------------------------------------------
# Value enums (PRD §3)
# ---------------------------------------------------------------------------
class LevelCode(str, Enum):
    EMR = "EMR"
    EMT = "EMT"
    AEMT = "AEMT"
    PARAMEDIC = "PARAMEDIC"


class AdoptionMode(str, Enum):
    NREMT_ACCEPTED = "NREMT_ACCEPTED"
    STATE_EXAM = "STATE_EXAM"
    HYBRID = "HYBRID"


class CandidateStatus(str, Enum):
    REGISTERED = "REGISTERED"
    BARRED = "BARRED"


class AccreditationStatus(str, Enum):
    ACCREDITED = "ACCREDITED"
    PROVISIONAL = "PROVISIONAL"
    SUSPENDED = "SUSPENDED"
    REVOKED = "REVOKED"


class CompletionRecordStatus(str, Enum):
    PENDING_VERIFICATION = "PENDING_VERIFICATION"
    VERIFIED = "VERIFIED"
    REJECTED = "REJECTED"
    INVALIDATED = "INVALIDATED"


class ExamApplicationStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    DENIED = "DENIED"


class AuthorizationToTestStatus(str, Enum):
    ISSUED = "ISSUED"
    CONSUMED = "CONSUMED"
    EXPIRED = "EXPIRED"
    REVOKED = "REVOKED"


class CognitiveExamAttemptStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    SCORED_PASS = "SCORED_PASS"
    SCORED_FAIL = "SCORED_FAIL"
    NO_SHOW = "NO_SHOW"
    VOIDED = "VOIDED"


class ExamOutcome(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"


class PsychomotorStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    VERIFIED = "VERIFIED"
    REJECTED = "REJECTED"


class AdministeredBy(str, Enum):
    PROGRAM = "PROGRAM"
    STATE = "STATE"


class CertificationStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    LAPSED = "LAPSED"
    EXPIRED = "EXPIRED"
    REVOKED = "REVOKED"


class RecertModel(str, Enum):
    NCCP = "NCCP"
    HOURLY = "HOURLY"


class RecertApplicationStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    AUDIT_PENDING = "AUDIT_PENDING"
    APPROVED = "APPROVED"
    DENIED = "DENIED"
    AUDIT_FAILED = "AUDIT_FAILED"
    SUPERSEDED = "SUPERSEDED"


class CEComponent(str, Enum):
    NATIONAL = "NATIONAL"
    LOCAL = "LOCAL"
    INDIVIDUAL = "INDIVIDUAL"


class DeliveryMethod(str, Enum):
    DISTRIBUTED = "DISTRIBUTED"
    IN_PERSON = "IN_PERSON"


class CECreditEntryStatus(str, Enum):
    RECORDED = "RECORDED"
    VERIFIED = "VERIFIED"
    REJECTED = "REJECTED"


class ReentryTier(str, Enum):
    TIER_CE_ONLY = "TIER_CE_ONLY"
    TIER_REFRESHER = "TIER_REFRESHER"


class ReentryApplicationStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    DENIED = "DENIED"


class LicensePath(str, Enum):
    NREMT = "NREMT"
    STATE_EXAM = "STATE_EXAM"


class LicenseApplicationStatus(str, Enum):
    UNDER_REVIEW = "UNDER_REVIEW"
    MORE_INFO_REQUIRED = "MORE_INFO_REQUIRED"
    GRANTED = "GRANTED"
    DENIED = "DENIED"


class StateExamRecordStatus(str, Enum):
    VALID = "VALID"
    VOIDED = "VOIDED"


class ViolationType(str, Enum):
    EXAM_SECURITY = "EXAM_SECURITY"
    FALSIFIED_EDUCATION = "FALSIFIED_EDUCATION"
    CRIMINAL_CONDUCT = "CRIMINAL_CONDUCT"


class InterimAction(str, Enum):
    NONE = "NONE"
    SUSPEND_CERTIFICATION = "SUSPEND_CERTIFICATION"
    HOLD_NEW_APPLICATIONS = "HOLD_NEW_APPLICATIONS"


class SanctionType(str, Enum):
    NONE = "NONE"
    WARNING = "WARNING"
    SUSPENSION_12M = "SUSPENSION_12M"
    REVOCATION = "REVOCATION"
    PERMANENT_BAR = "PERMANENT_BAR"


class DisciplinaryCaseStatus(str, Enum):
    OPENED = "OPENED"
    NOTICE_ISSUED = "NOTICE_ISSUED"
    UNDER_REVIEW = "UNDER_REVIEW"
    HEARING_SCHEDULED = "HEARING_SCHEDULED"
    DECIDED = "DECIDED"
    APPEAL_PENDING = "APPEAL_PENDING"
    REHEARING = "REHEARING"
    FINAL = "FINAL"


class AuditReason(str, Enum):
    SEQ_MOD = "SEQ_MOD"
    PRIOR_AUDIT_FAILURE = "PRIOR_AUDIT_FAILURE"
    SINGLE_PROVIDER_CONCENTRATION = "SINGLE_PROVIDER_CONCENTRATION"


# ---------------------------------------------------------------------------
# Configuration resources (PRD §2.4: id + created_at only — NO updated_at /
# version on these two)
# ---------------------------------------------------------------------------
class LevelDefinition(TypedDict):
    id: str
    code: str
    display_name: str
    scope_summary: str
    cognitive_cut_score: float
    ce_total_hours: float
    ce_national_min_hours: float
    ce_local_min_hours: float
    ce_individual_min_hours: float
    hourly_model_total_hours: float
    remedial_hours_required: float
    refresher_hours_required: float
    initial_application_fee_cents: int
    recert_application_fee_cents: int
    created_at: str


class StateAdoptionPolicy(TypedDict):
    id: str
    state_code: str
    adoption_mode: str
    accepted_level_codes: Optional[List[str]]
    jurisprudence_exam_required: bool
    base_license_fee_cents: int
    national_verification_surcharge_cents: int
    state_exam_fee_cents: int
    registry_share_bps: int
    created_at: str


# ---------------------------------------------------------------------------
# Operational resources (id + created_at + updated_at + version)
# ---------------------------------------------------------------------------
class Candidate(TypedDict):
    id: str
    full_name: str
    email: str
    status: str
    disciplinary_hold: bool
    created_at: str
    updated_at: str
    version: int


class EducationProgram(TypedDict):
    id: str
    name: str
    level_id: str
    director_user_id: str
    accreditation_status: str
    accreditation_history: List[Dict[str, Any]]
    created_at: str
    updated_at: str
    version: int


class ProgramCompletionRecord(TypedDict):
    id: str
    candidate_id: str
    program_id: str
    completion_date: str
    created_by_user_id: str
    status: str
    verified_at: Optional[str]
    within_validity_window: bool
    attempts_consumed: int
    attempts_remaining: int
    invalidated_by_case_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ExamApplication(TypedDict):
    id: str
    candidate_id: str
    level_id: str
    completion_record_id: str
    application_fee_cents: int
    status: str
    denial_reason: Optional[str]
    decided_at: Optional[str]
    att_id: Optional[str]
    resubmission_count: int
    created_at: str
    updated_at: str
    version: int


class AuthorizationToTest(TypedDict):
    id: str
    exam_application_id: str
    candidate_id: str
    issued_on: str
    expires_on: str
    attempt_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class CognitiveExamAttempt(TypedDict):
    id: str
    att_id: str
    candidate_id: str
    level_id: str
    basis_completion_record_id: str
    attempt_number: int
    scheduled_start: str
    scheduled_end: str
    delivered_at: Optional[str]
    responses: Optional[List[Dict[str, Any]]]
    items_delivered_count: Optional[int]
    provisional_outcome: Optional[str]
    final_outcome: Optional[str]
    theta_final: Optional[float]
    status: str
    voided_by_case_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class RemedialEducationRecord(TypedDict):
    id: str
    candidate_id: str
    level_id: str
    hours: float
    completed_date: str
    provider_name: str
    attested_by_user_id: str
    created_at: str
    updated_at: str
    version: int


class PsychomotorVerification(TypedDict):
    id: str
    candidate_id: str
    level_id: str
    administered_by: str
    program_id: Optional[str]
    evaluator_user_id: str
    completion_record_id: str
    exam_date: str
    stations: List[Dict[str, Any]]
    documentation_attached: bool
    status: str
    verified_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Certification(TypedDict):
    id: str
    candidate_id: str
    level_id: str
    basis_completion_record_id: str
    basis_attempt_id: str
    basis_psychomotor_id: str
    issued_on: str
    expires_on: str
    lapse_deadline: str
    renewed_count: int
    status: str
    suspension_ends: Optional[str]
    pre_sanction_status: Optional[str]
    revoked_by_case_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class RecertApplication(TypedDict):
    id: str
    certification_id: str
    candidate_id: str
    model: str
    cycle_window_start: str
    cert_expires_on_at_creation: str
    recert_seq: Optional[int]
    audit_selected: Optional[bool]
    audit_reasons: Optional[List[str]]
    national_credited_hours: Optional[float]
    local_credited_hours: Optional[float]
    individual_credited_hours: Optional[float]
    total_credited_hours: Optional[float]
    status: str
    submitted_at: Optional[str]
    decided_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class CECreditEntry(TypedDict):
    id: str
    recert_application_id: str
    component: str
    hours: float
    delivery_method: str
    course_code: str
    course_date: str
    provider_name: str
    status: str
    reject_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ReentryApplication(TypedDict):
    id: str
    certification_id: str
    candidate_id: str
    lapse_months_at_submission: float
    tier: str
    ce_makeup_hours_claimed: Optional[float]
    refresher_hours_claimed: Optional[float]
    status: str
    decided_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class LicenseApplication(TypedDict):
    id: str
    candidate_id: str
    state_code: str
    level_id: str
    policy_id: str
    adoption_mode_snapshot: str
    registry_share_bps_snapshot: int
    fee_lines_snapshot: List[Dict[str, Any]]
    path: str
    certification_id: Optional[str]
    certification_version_at_submission: Optional[int]
    state_exam_record_id: Optional[str]
    jurisprudence_completed: bool
    assessed_fee_cents: Optional[int]
    registry_share_cents: Optional[int]
    status: str
    decision_reason: Optional[str]
    more_info_note: Optional[str]
    granted_on: Optional[str]
    created_at: str
    updated_at: str
    version: int


class StateExamRecord(TypedDict):
    id: str
    candidate_id: str
    state_code: str
    level_id: str
    exam_date: str
    score: float
    passing_score: float
    passed: bool
    status: str
    voided_by_case_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class DisciplinaryCase(TypedDict):
    id: str
    subject_candidate_id: str
    violation_type: str
    description: str
    opened_by_user_id: str
    interim_action: str
    implicated_attempt_ids: Optional[List[str]]
    implicated_completion_record_ids: Optional[List[str]]
    hearing_officer_user_id: Optional[str]
    sanction_type: Optional[str]
    findings: Optional[str]
    response_deadline: Optional[str]
    appeal_deadline: Optional[str]
    decided_at: Optional[str]
    finalized_at: Optional[str]
    rehearing_count: int
    status: str
    created_at: str
    updated_at: str
    version: int
