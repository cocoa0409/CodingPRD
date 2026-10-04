"""Domain types: entity TypedDicts, status enums, role enum."""
from enum import Enum
from typing import Optional, TypedDict


class UserRole(str, Enum):
    AGENCY_ADMIN = "AgencyAdmin"
    DEVICE_COORDINATOR = "DeviceCoordinator"
    OFFICER = "Officer"
    SUPERVISOR = "Supervisor"
    REDACTION_TECHNICIAN = "RedactionTechnician"
    RECORDS_OFFICER = "RecordsOfficer"
    PROSECUTOR = "Prosecutor"
    DEFENSE_COUNSEL = "DefenseCounsel"


class PolicyStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    SUPERSEDED = "SUPERSEDED"


class BudgetPlanStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUPERSEDED = "SUPERSEDED"


class OfficerStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    RETIRED = "RETIRED"


class OfficerRank(str, Enum):
    OFFICER = "OFFICER"
    CORPORAL = "CORPORAL"
    SERGEANT = "SERGEANT"
    LIEUTENANT = "LIEUTENANT"


class AssignmentStatus(str, Enum):
    UNASSIGNED = "UNASSIGNED"
    ASSIGNED = "ASSIGNED"


class DockStatus(str, Enum):
    DOCKED = "DOCKED"
    UNDOCKED = "UNDOCKED"


class HealthStatus(str, Enum):
    HEALTHY = "HEALTHY"
    RETIRED = "RETIRED"


class RecordingCategory(str, Enum):
    INCIDENT = "INCIDENT"
    ARREST = "ARREST"
    TRAFFIC_STOP = "TRAFFIC_STOP"
    TRAINING = "TRAINING"
    TEST = "TEST"


class UploadStatus(str, Enum):
    RECEIVED = "RECEIVED"
    INTEGRITY_VERIFIED = "INTEGRITY_VERIFIED"
    INTEGRITY_FAILED = "INTEGRITY_FAILED"
    ACTIVE = "ACTIVE"
    RETENTION_DUE = "RETENTION_DUE"
    PURGED = "PURGED"


class ReviewStatus(str, Enum):
    NOT_FLAGGED = "NOT_FLAGGED"
    PENDING_REVIEW = "PENDING_REVIEW"
    REVIEWED = "REVIEWED"


class CaseStatus(str, Enum):
    OPEN = "OPEN"
    UNDER_REVIEW = "UNDER_REVIEW"
    CLOSED = "CLOSED"
    ARCHIVED = "ARCHIVED"


class LinkStatus(str, Enum):
    LINKED = "LINKED"
    UNLINKED = "UNLINKED"


class RedactionJobStatus(str, Enum):
    QUEUED = "QUEUED"
    IN_PROGRESS = "IN_PROGRESS"
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    RELEASED = "RELEASED"
    RETURNED = "RETURNED"
    CANCELLED = "CANCELLED"


class RedactionPasses(str, Enum):
    SINGLE_PASS = "SINGLE_PASS"
    MULTI_PASS = "MULTI_PASS"


class ShareGrantStatus(str, Enum):
    ACTIVE = "ACTIVE"
    REVOKED = "REVOKED"
    EXPIRED = "EXPIRED"


class RecipientRole(str, Enum):
    PROSECUTOR = "PROSECUTOR"
    DEFENSE = "DEFENSE"


class LegalHoldStatus(str, Enum):
    ACTIVE = "ACTIVE"
    RELEASED = "RELEASED"


class HoldScopeType(str, Enum):
    RECORDING = "RECORDING"
    CASE = "CASE"


class StoragePosture(str, Enum):
    OK = "OK"
    WARNING = "WARNING"
    OVER_BUDGET = "OVER_BUDGET"


class CustodyEventType(str, Enum):
    UPLOADED = "UPLOADED"
    HASH_VERIFIED = "HASH_VERIFIED"
    HASH_MISMATCH = "HASH_MISMATCH"
    CASE_LINKED = "CASE_LINKED"
    CASE_UNLINKED = "CASE_UNLINKED"
    REDACTION_STARTED = "REDACTION_STARTED"
    REDACTION_RELEASED = "REDACTION_RELEASED"
    SHARED = "SHARED"
    ACCESSED = "ACCESSED"
    HOLD_PLACED = "HOLD_PLACED"
    HOLD_RELEASED = "HOLD_RELEASED"
    PURGE_EXECUTED = "PURGE_EXECUTED"


# --- Entities (primary resources carry id/created_at/updated_at/version) ---

class Agency(TypedDict):
    id: str
    name: str
    timezone: str
    storage_used_bytes: int
    storage_posture: str
    created_at: str
    updated_at: str
    version: int


class AgencyPolicy(TypedDict):
    id: str
    agency_id: str
    recording_triggers: list
    tagging_required: bool
    supervisor_review_rate_pct: int
    default_share_expiry_days: int
    status: str
    created_at: str
    updated_at: str
    version: int


class StorageBudgetPlan(TypedDict):
    id: str
    agency_id: str
    fiscal_year_start_month: int
    monthly_budget_cents: int
    cost_per_gb_month_cents: int
    alert_threshold_pct: int
    effective_from_month: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Officer(TypedDict):
    id: str
    agency_id: str
    badge_number: str
    full_name: str
    rank: str
    status: str
    recordings_uploaded_count: int
    pending_review_count: int
    created_at: str
    updated_at: str
    version: int


class Device(TypedDict):
    id: str
    agency_id: str
    serial_number: str
    model: str
    battery_pct: int
    battery_pct_at_dock: Optional[int]
    docked_at: Optional[str]
    assignment_status: str
    dock_status: str
    health_status: str
    assigned_officer_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Recording(TypedDict):
    id: str
    agency_id: str
    device_id: str
    officer_id: str
    trigger_code: str
    duration_seconds: int
    size_bytes: int
    recorded_at: str
    content_hash_sha256: str
    category: Optional[str]
    upload_status: str
    review_status: str
    retention_due_at: Optional[str]
    legal_hold_count: int
    integrity_check_count: int
    created_at: str
    updated_at: str
    version: int


class CaseEntity(TypedDict):
    id: str
    agency_id: str
    case_number: str
    title: str
    status: str
    lead_officer_id: str
    evidence_count: int
    total_evidence_bytes: int
    retention_due_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class CaseEvidenceLink(TypedDict):
    id: str
    agency_id: str
    case_id: str
    recording_id: str
    linked_by_officer_id: str
    status: str
    unlinked_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class RedactionJob(TypedDict):
    id: str
    agency_id: str
    recording_id: str
    request_reference: str
    scope_face: bool
    scope_audio: bool
    passes: str
    estimated_minutes: int
    actual_minutes: Optional[int]
    status: str
    created_at: str
    updated_at: str
    version: int


class ShareGrant(TypedDict):
    id: str
    agency_id: str
    case_id: str
    recipient_role: str
    recipient_email: str
    access_token: str
    expires_at: str
    expires_in_days: Optional[int]
    access_count: int
    status: str
    created_at: str
    updated_at: str
    version: int


class LegalHold(TypedDict):
    id: str
    agency_id: str
    scope_type: str
    recording_id: Optional[str]
    case_id: Optional[str]
    authority_reference: str
    status: str
    created_at: str
    updated_at: str
    version: int


# --- Append-only compliance logs: id + created_at only, no updated_at/version ---

class AuditLogEntry(TypedDict):
    id: str
    agency_id: str
    actor_role: str
    actor_id: str
    action: str
    entity_type: str
    entity_id: str
    detail: str
    created_at: str


class CustodyEvent(TypedDict):
    id: str
    agency_id: str
    recording_id: str
    event_type: str
    actor_role: str
    actor_id: str
    hash_at_event: Optional[str]
    created_at: str
