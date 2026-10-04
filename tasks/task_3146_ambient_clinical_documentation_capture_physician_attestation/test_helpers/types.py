"""Domain types: entity TypedDicts, status enums, role enum."""

from enum import Enum
from typing import List, Optional, TypedDict


class UserRole(str, Enum):
    PATIENT = "Patient"
    PHYSICIAN = "Physician"
    QA_AUDITOR = "QAAuditor"
    COMPLIANCE_OFFICER = "ComplianceOfficer"
    PLATFORM_ADMIN = "PlatformAdmin"


class PhysicianStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class AuditorStatus(str, Enum):
    ACTIVE = "ACTIVE"
    INACTIVE = "INACTIVE"


class EncounterStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class AudioStatus(str, Enum):
    NOT_RECORDING = "NOT_RECORDING"
    RECORDING_ACTIVE = "RECORDING_ACTIVE"
    AUDIO_STOPPED = "AUDIO_STOPPED"


class DocumentationStatus(str, Enum):
    NOT_STARTED = "NOT_STARTED"
    DRAFTING = "DRAFTING"
    IN_REVIEW = "IN_REVIEW"
    ATTESTED = "ATTESTED"
    AMENDED = "AMENDED"


class ConsentStatus(str, Enum):
    GRANTED = "GRANTED"
    OPTED_OUT = "OPTED_OUT"
    REVOKED = "REVOKED"
    EXPIRED = "EXPIRED"


class ConsentEndReason(str, Enum):
    OPT_OUT = "OPT_OUT"
    REVOKE = "REVOKE"
    EXPIRE = "EXPIRE"


class CapturedVia(str, Enum):
    ROOM_SIGNAGE = "ROOM_SIGNAGE"
    VERBAL = "VERBAL"
    PORTAL = "PORTAL"


class CaptureStatus(str, Enum):
    RECORDING = "RECORDING"
    PAUSED = "PAUSED"
    CAPTURED = "CAPTURED"
    TRANSCRIBED = "TRANSCRIBED"
    PURGED = "PURGED"
    RETENTION_EXPIRED = "RETENTION_EXPIRED"


class PurgeReason(str, Enum):
    OPT_OUT = "OPT_OUT"
    REVOKE = "REVOKE"
    CANCEL = "CANCEL"
    MANUAL = "MANUAL"
    RETENTION = "RETENTION"


class SpeakerRole(str, Enum):
    PHYSICIAN = "PHYSICIAN"
    PATIENT = "PATIENT"
    CAREGIVER = "CAREGIVER"
    OTHER = "OTHER"


class DraftStatus(str, Enum):
    DRAFT = "DRAFT"
    IN_REVIEW = "IN_REVIEW"
    EDITED = "EDITED"
    ATTESTED = "ATTESTED"
    AMENDED = "AMENDED"
    VOID = "VOID"


class FieldImportance(str, Enum):
    CRITICAL = "CRITICAL"
    MAJOR = "MAJOR"
    MINOR = "MINOR"


class FieldSource(str, Enum):
    SYSTEM = "SYSTEM"
    AUDIO = "AUDIO"
    MANUAL = "MANUAL"


class AttestationType(str, Enum):
    INITIAL = "INITIAL"
    AMENDMENT = "AMENDMENT"


class CodeType(str, Enum):
    DIAGNOSIS = "DIAGNOSIS"
    ORDER = "ORDER"
    BILLING = "BILLING"


class SuggestionStatus(str, Enum):
    SUGGESTED = "SUGGESTED"
    MODIFIED = "MODIFIED"
    CONFIRMED = "CONFIRMED"
    REJECTED = "REJECTED"
    EXPIRED = "EXPIRED"


class QASampleStatus(str, Enum):
    QUEUED = "QUEUED"
    ASSIGNED = "ASSIGNED"
    SCORED = "SCORED"
    APPEALED = "APPEALED"
    RESCORED = "RESCORED"
    CLOSED = "CLOSED"


class SamplingReason(str, Enum):
    LOW_CONFIDENCE = "LOW_CONFIDENCE"
    MANUAL = "MANUAL"


class MetricStatus(str, Enum):
    PROVISIONAL = "PROVISIONAL"
    FINAL = "FINAL"


class FieldSpec(TypedDict):
    key: str
    importance: str
    required: bool


class Patient(TypedDict, total=False):
    id: str
    mrn: str
    full_name: str
    default_ambient_opt_in: bool
    created_at: str
    updated_at: str
    version: int


class Physician(TypedDict, total=False):
    id: str
    npi: str
    full_name: str
    specialty_code: str
    status: str
    created_at: str
    updated_at: str
    version: int


class QAAuditor(TypedDict, total=False):
    id: str
    employee_code: str
    full_name: str
    specialty_codes: List[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class NoteTemplate(TypedDict, total=False):
    id: str
    specialty_code: str
    template_version: str
    field_specs: List[FieldSpec]
    completeness_multiplier: float
    low_confidence_threshold: int
    active: bool
    created_at: str
    updated_at: str
    version: int


class Encounter(TypedDict, total=False):
    id: str
    patient_id: str
    physician_id: str
    scheduled_start: Optional[str]
    started_at: Optional[str]
    ended_at: Optional[str]
    encounter_status: str
    audio_status: str
    documentation_status: str
    cancel_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class AmbientConsent(TypedDict, total=False):
    id: str
    encounter_id: str
    patient_id: str
    status: str
    signage_posted: bool
    captured_via: str
    granted_at: str
    ended_at: Optional[str]
    end_reason: Optional[str]
    revocation_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class AudioCapture(TypedDict, total=False):
    id: str
    encounter_id: str
    status: str
    started_at: str
    ended_at: Optional[str]
    planned_retention_days: int
    retention_days_effective: int
    legal_hold: bool
    recorded_seconds: int
    purge_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class SpeakerSegment(TypedDict, total=False):
    id: str
    audio_capture_id: str
    start_offset_ms: int
    end_offset_ms: int
    speaker_role: str
    base_confidence: float
    reassignment_count: int
    effective_confidence: float
    created_at: str
    updated_at: str
    version: int


class NoteDraft(TypedDict, total=False):
    id: str
    encounter_id: str
    template_id: str
    author_physician_id: str
    status: str
    completeness_score: int
    billing_provisional_cents: int
    billing_final_cents: int
    regeneration_count: int
    amendment_count: int
    phi_review_required: bool
    attested_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class NoteField(TypedDict, total=False):
    id: str
    note_draft_id: str
    field_key: str
    field_value: Optional[str]
    importance: str
    required: bool
    source: str
    validated: bool
    created_at: str
    updated_at: str
    version: int


# Append-only legal record: carries ONLY id + created_at (no updated_at, no version)
class Attestation(TypedDict, total=False):
    id: str
    note_draft_id: str
    physician_id: str
    attestation_type: str
    attested_at: str
    completeness_at_attestation: int
    created_at: str


class CodeSuggestion(TypedDict, total=False):
    id: str
    note_draft_id: str
    code_type: str
    code_value: str
    confidence: float
    quantity: int
    unit_fee_cents: Optional[int]
    adjustment_pct: float
    status: str
    rank: int
    line_total_cents: int
    confirmed_by: Optional[str]
    created_at: str
    updated_at: str
    version: int


class QASample(TypedDict, total=False):
    id: str
    note_draft_id: str
    auditor_id: Optional[str]
    status: str
    sampling_reason: str
    created_by_user_id: str
    accuracy_score: Optional[int]
    completeness_score: Optional[int]
    timeliness_score: Optional[int]
    composite_score: Optional[int]
    appeal_count: int
    last_scorer_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class DocumentationMetric(TypedDict, total=False):
    id: str
    physician_id: str
    period_start: str
    period_end: str
    notes_attested: int
    provisional_minutes: int
    final_minutes: int
    after_hours_minutes: int
    status: str
    finalized_at: Optional[str]
    created_at: str
    updated_at: str
    version: int
