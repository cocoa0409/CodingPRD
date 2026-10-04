"""Domain types: entity TypedDicts, status enums, role enum.

Derived from the PRD entity and workflow descriptions. All entities except
ReviewDecision carry id/created_at/updated_at/version; ReviewDecision is the
append-only exception carrying only id/created_at among the common fields.
"""
from enum import Enum
from typing import Optional, TypedDict


class UserRole(str, Enum):
    PLATFORM_ADMIN = "PlatformAdmin"
    TELEMATICS_INGEST = "TelematicsIngest"
    SAFETY_MANAGER = "SafetyManager"
    CLAIMS_ADJUSTER = "ClaimsAdjuster"
    DRIVER = "Driver"
    FLEET_ADMIN = "FleetAdmin"


class FleetPosture(str, Enum):
    NORMAL = "NORMAL"
    INCIDENT_LOCKDOWN = "INCIDENT_LOCKDOWN"


class DriverStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    COACHING_HOLD = "COACHING_HOLD"
    INACTIVE = "INACTIVE"


class VehicleStatus(str, Enum):
    ACTIVE = "ACTIVE"
    DECOMMISSIONED = "DECOMMISSIONED"


class UnionAgreementStatus(str, Enum):
    DRAFT = "DRAFT"
    RATIFIED = "RATIFIED"
    EXPIRED = "EXPIRED"


class CameraPolicyStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    ARCHIVED = "ARCHIVED"


class SafetyEventStatus(str, Enum):
    DETECTED = "DETECTED"
    IN_REVIEW = "IN_REVIEW"
    CONFIRMED = "CONFIRMED"
    DISMISSED = "DISMISSED"
    RECLASSIFIED = "RECLASSIFIED"
    EXONERATED = "EXONERATED"


class EventType(str, Enum):
    HARSH_BRAKE = "HARSH_BRAKE"
    FOLLOWING_DISTANCE = "FOLLOWING_DISTANCE"
    DISTRACTION = "DISTRACTION"
    SEAT_BELT = "SEAT_BELT"
    COLLISION = "COLLISION"


class Severity(str, Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class BandwidthTier(str, Enum):
    LOW = "LOW"
    STANDARD = "STANDARD"
    HIGH = "HIGH"


class CameraAngle(str, Enum):
    FORWARD = "FORWARD"
    INWARD = "INWARD"
    SIDE = "SIDE"


class ClipUploadStatus(str, Enum):
    QUEUED = "QUEUED"
    UPLOADING = "UPLOADING"
    UPLOADED = "UPLOADED"
    PURGED = "PURGED"


class RetentionClass(str, Enum):
    STANDARD = "STANDARD"
    COLLISION = "COLLISION"
    LITIGATION_HOLD = "LITIGATION_HOLD"


class CoachingSessionStatus(str, Enum):
    ASSIGNED = "ASSIGNED"
    ACKNOWLEDGED = "ACKNOWLEDGED"
    OVERDUE = "OVERDUE"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class EscalationCaseStatus(str, Enum):
    OPEN = "OPEN"
    UNDER_REVIEW = "UNDER_REVIEW"
    RESOLVED_ACTION = "RESOLVED_ACTION"
    RESOLVED_NO_ACTION = "RESOLVED_NO_ACTION"


class ExonerationClaimStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    EVIDENCE_REVIEW = "EVIDENCE_REVIEW"
    EXONERATED = "EXONERATED"
    REJECTED = "REJECTED"


class LitigationHoldStatus(str, Enum):
    ACTIVE = "ACTIVE"
    RELEASED = "RELEASED"


class LitigationHoldScope(str, Enum):
    DRIVER = "DRIVER"
    EVENT = "EVENT"


class SnapshotStatus(str, Enum):
    PROVISIONAL = "PROVISIONAL"
    FINAL = "FINAL"


class SnapshotScopeType(str, Enum):
    DRIVER = "DRIVER"
    TERMINAL = "TERMINAL"
    FLEET = "FLEET"


class IncentiveAwardStatus(str, Enum):
    PROJECTED = "PROJECTED"
    APPROVED = "APPROVED"
    PAID = "PAID"
    FORFEITED = "FORFEITED"


class IncentiveTier(str, Enum):
    GOLD = "GOLD"
    SILVER = "SILVER"
    BRONZE = "BRONZE"
    NONE = "NONE"


class ReviewAction(str, Enum):
    CONFIRM = "CONFIRM"
    DISMISS = "DISMISS"
    RECLASSIFY = "RECLASSIFY"
    REOPEN = "REOPEN"


class ClaimDecision(str, Enum):
    EXONERATE = "EXONERATE"
    REJECT = "REJECT"


class SessionOutcome(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"


class Fleet(TypedDict, total=False):
    id: str
    name: str
    incentive_budget_cents: int
    posture: str
    ops_run_index: int
    retention_used_mb: int
    safety_score_cached: float
    created_at: str
    updated_at: str
    version: int


class Terminal(TypedDict, total=False):
    id: str
    fleet_id: str
    name: str
    region_code: str
    safety_score_cached: float
    created_at: str
    updated_at: str
    version: int


class Driver(TypedDict, total=False):
    id: str
    terminal_id: str
    employee_ref: str
    name: str
    hire_date: str
    inward_camera_consent: bool
    status: str
    confirmed_events_90d: int
    safety_score_provisional: float
    safety_score_final: float
    incentive_tier: str
    created_at: str
    updated_at: str
    version: int


class Vehicle(TypedDict, total=False):
    id: str
    terminal_id: str
    vin: str
    camera_unit_id: str
    bandwidth_tier: str
    status: str
    created_at: str
    updated_at: str
    version: int


class UnionAgreement(TypedDict, total=False):
    id: str
    terminal_id: str
    agreement_code: str
    inward_camera_allowed: bool
    live_view_allowed: bool
    audio_recording_allowed: bool
    coaching_requires_steward_present: bool
    effective_from: str
    effective_until: str
    status: str
    created_at: str
    updated_at: str
    version: int


class CameraPolicy(TypedDict, total=False):
    id: str
    fleet_id: str
    name: str
    retention_days_standard: int
    retention_days_collision: int
    daily_upload_cap_mb: int
    inward_capture_enabled: bool
    distraction_detection_enabled: bool
    seatbelt_detection_enabled: bool
    effective_from: str
    status: str
    created_at: str
    updated_at: str
    version: int


class SafetyEvent(TypedDict, total=False):
    id: str
    fleet_id: str
    driver_id: str
    vehicle_id: str
    event_type: str
    severity: str
    occurred_at: str
    detected_at: str
    status: str
    upload_priority_score: int
    review_count: int
    confirmed_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ReviewDecision(TypedDict, total=False):
    """Append-only audit record: carries ONLY id and created_at among the
    common fields — updated_at and version are absent entirely."""
    id: str
    created_at: str
    event_id: str
    reviewer_id: str
    action: str
    prior_event_type: str
    prior_severity: str
    new_event_type: Optional[str]
    new_severity: Optional[str]
    rationale: str
    decided_at: str


class FootageClip(TypedDict, total=False):
    id: str
    event_id: str
    camera_angle: str
    size_mb: int
    captured_at: str
    upload_status: str
    retention_class: str
    uploaded_at: Optional[str]
    purged_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class CoachingSession(TypedDict, total=False):
    id: str
    driver_id: str
    event_id: str
    status: str
    starts_at: str
    ends_at: str
    due_at: str
    assigned_by: str
    steward_required: bool
    reassign_count: int
    completed_at: Optional[str]
    outcome: Optional[str]
    created_at: str
    updated_at: str
    version: int


class EscalationCase(TypedDict, total=False):
    id: str
    driver_id: str
    trigger_event_id: str
    status: str
    offense_count: int
    window_days: int
    resolution: Optional[str]
    resolution_note: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ExonerationClaim(TypedDict, total=False):
    id: str
    event_id: str
    driver_id: str
    claim_ref: str
    police_report_ref: Optional[str]
    status: str
    submitted_at: str
    decided_at: Optional[str]
    decided_by: Optional[str]
    created_at: str
    updated_at: str
    version: int


class LitigationHold(TypedDict, total=False):
    id: str
    fleet_id: str
    scope: str
    driver_id: Optional[str]
    event_id: Optional[str]
    reason: str
    status: str
    placed_by: str
    placed_at: str
    released_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class SafetyScoreSnapshot(TypedDict, total=False):
    id: str
    fleet_id: str
    scope_type: str
    scope_id: Optional[str]
    period_start: str
    period_end: str
    score: float
    status: str
    rank: Optional[int]
    computed_at: str
    created_at: str
    updated_at: str
    version: int


class IncentiveAward(TypedDict, total=False):
    id: str
    fleet_id: str
    driver_id: str
    snapshot_id: str
    period_start: str
    period_end: str
    tier: str
    amount_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int
