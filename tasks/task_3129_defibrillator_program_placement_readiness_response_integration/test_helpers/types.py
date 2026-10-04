"""Domain types: entity TypedDicts, status enums, role enum for the
Defibrillator Program API (PRD)."""

from enum import Enum
from typing import Any, List, Optional, TypedDict


# ---------------------------------------------------------------------------
# Role enum (PRD section on user and role-based access control)
# ---------------------------------------------------------------------------

class UserRole(str, Enum):
    PLATFORM_ADMIN = "PlatformAdmin"
    PROGRAM_MANAGER = "ProgramManager"
    INSPECTOR = "Inspector"
    MEDICAL_DIRECTOR = "MedicalDirector"
    RESPONDER = "Responder"
    SYSTEM = "System"
    ANONYMOUS = "Anonymous"


# ---------------------------------------------------------------------------
# Status enums
# ---------------------------------------------------------------------------

class CampusPosture(str, Enum):
    OPERATIONAL = "OPERATIONAL"
    DEGRADED = "DEGRADED"
    CRITICAL = "CRITICAL"


class CabinetStatus(str, Enum):
    EMPTY = "EMPTY"
    OCCUPIED = "OCCUPIED"
    ALARM_OPEN = "ALARM_OPEN"


class DeviceStatus(str, Enum):
    REGISTERED = "REGISTERED"
    INSTALLED = "INSTALLED"
    IN_SERVICE = "IN_SERVICE"
    POST_EVENT = "POST_EVENT"
    MAINTENANCE = "MAINTENANCE"
    DECOMMISSIONED = "DECOMMISSIONED"


class DevicePosture(str, Enum):
    READY = "READY"
    DEGRADED = "DEGRADED"
    OUT_OF_SERVICE = "OUT_OF_SERVICE"


class SelfTestStatus(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"
    UNKNOWN = "UNKNOWN"


class ConsumableKind(str, Enum):
    PAD = "PAD"
    BATTERY = "BATTERY"


class InstallDisposition(str, Enum):
    ACTIVE = "ACTIVE"
    CONSUMED_IN_EVENT = "CONSUMED_IN_EVENT"
    EXPIRED_REMOVED = "EXPIRED_REMOVED"
    REPLACED = "REPLACED"


class InspectionOutcome(str, Enum):
    SCHEDULED = "SCHEDULED"
    PASS = "PASS"
    FAIL = "FAIL"
    OVERDUE = "OVERDUE"


class ResponderRole(str, Enum):
    LAY_RESPONDER = "LAY_RESPONDER"
    MEDICAL_DIRECTOR = "MEDICAL_DIRECTOR"
    PROGRAM_MANAGER = "PROGRAM_MANAGER"
    INSPECTOR = "INSPECTOR"


class ResponderStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    INACTIVE = "INACTIVE"


class TrainingSessionStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class EmergencyEventStatus(str, Enum):
    OPEN = "OPEN"
    RESPONDING = "RESPONDING"
    RESOLVED = "RESOLVED"
    CASE_REVIEW = "CASE_REVIEW"
    CLOSED = "CLOSED"


class CaseReviewStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    ACCEPTED = "ACCEPTED"
    REOPENED = "REOPENED"


class CaseReviewOutcomeCode(str, Enum):
    SURVIVED_TO_DISCHARGE = "SURVIVED_TO_DISCHARGE"
    SURVIVED_TO_ADMISSION = "SURVIVED_TO_ADMISSION"
    DECEASED = "DECEASED"
    NO_SHOCK_INDICATED = "NO_SHOCK_INDICATED"


class ReplenishmentOrderStatus(str, Enum):
    PENDING = "PENDING"
    RECEIVED = "RECEIVED"
    CANCELLED = "CANCELLED"


# ---------------------------------------------------------------------------
# Entity TypedDicts
# Entities with common fields carry id, created_at, updated_at, version.
# SelfTestReport is immutable telemetry and carries only id + created_at.
# ---------------------------------------------------------------------------

class Campus(TypedDict, total=False):
    id: str
    name: str
    jurisdiction_code: str
    jurisdiction_registration_number: str
    medical_director_id: str
    response_time_target_seconds: int
    readiness_posture: str
    created_at: str
    updated_at: str
    version: int


class Zone(TypedDict, total=False):
    id: str
    campus_id: str
    zone_code: str
    floor_area_sqm: int
    avg_walk_speed_mps: float
    requires_elevator: bool
    elevator_delay_seconds: int
    created_at: str
    updated_at: str
    version: int


class DeviceModel(TypedDict, total=False):
    id: str
    model_code: str
    manufacturer: str
    pad_shelf_life_months: int
    battery_shelf_life_months: int
    prescription_required: bool
    created_at: str
    updated_at: str
    version: int


class Cabinet(TypedDict, total=False):
    id: str
    zone_id: str
    location_label: str
    centroid_x_m: float
    centroid_y_m: float
    installed_device_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class Device(TypedDict, total=False):
    id: str
    campus_id: str
    device_model_id: str
    serial_number: str
    cabinet_id: Optional[str]
    prescription_number: str
    current_pad_install_id: Optional[str]
    current_battery_install_id: Optional[str]
    last_inspection_at: Optional[str]
    last_selftest_status: str
    readiness_posture: str
    status: str
    created_at: str
    updated_at: str
    version: int


class ConsumableLot(TypedDict, total=False):
    id: str
    campus_id: str
    device_model_id: str
    kind: str
    lot_code: str
    manufacturer_expires_at: str
    quantity_received: int
    quantity_available: int
    created_at: str
    updated_at: str
    version: int


class Install(TypedDict, total=False):
    id: str
    device_id: str
    consumable_lot_id: str
    kind: str
    installed_at: str
    expires_at: str
    removed_at: Optional[str]
    disposition: str
    created_at: str
    updated_at: str
    version: int


class Inspection(TypedDict, total=False):
    id: str
    device_id: str
    inspector_id: str
    scheduled_for: str
    completed_at: Optional[str]
    checklist_items: List[Any]
    outcome: str
    fail_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class SelfTestReport(TypedDict, total=False):
    # Immutable telemetry: only id and created_at are guaranteed alongside
    # the report's own payload fields. No updated_at, no version.
    id: str
    device_id: str
    reported_at: str
    result: str
    fault_code: Optional[str]
    created_at: str


class Responder(TypedDict, total=False):
    id: str
    campus_id: str
    full_name: str
    badge_number: str
    responder_role: str
    certified_through: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class TrainingSession(TypedDict, total=False):
    id: str
    campus_id: str
    instructor_id: str
    starts_at: str
    ends_at: str
    capacity: int
    certification_months_granted: int
    status: str
    created_at: str
    updated_at: str
    version: int


class EmergencyEvent(TypedDict, total=False):
    id: str
    campus_id: str
    cabinet_id: str
    device_id: str
    opened_at: str
    closed_at: Optional[str]
    hospital_code: Optional[str]
    patient_transported: Optional[bool]
    pads_consumed: Optional[bool]
    status: str
    created_at: str
    updated_at: str
    version: int


class CaseReview(TypedDict, total=False):
    id: str
    emergency_event_id: str
    reviewer_id: str
    hospital_reviewer_name: str
    device_data_retrieved: bool
    outcome_code: str
    notes: str
    status: str
    created_at: str
    updated_at: str
    version: int


class ReplenishmentOrder(TypedDict, total=False):
    id: str
    campus_id: str
    emergency_event_id: Optional[str]
    kind: str
    quantity: int
    status: str
    received_lot_id: Optional[str]
    created_at: str
    updated_at: str
    version: int
