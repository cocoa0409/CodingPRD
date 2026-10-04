"""Domain types: entity status enums, role enum and entity TypedDicts."""

from enum import Enum
from typing import List, Optional, TypedDict


class DeviceType(str, Enum):
    SMART_LOCK = "SMART_LOCK"
    THERMOSTAT = "THERMOSTAT"
    LEAK_SENSOR = "LEAK_SENSOR"
    COMMUNITY_ACCESS = "COMMUNITY_ACCESS"
    HUB = "HUB"


class FirmwareVersion(str, Enum):
    LATEST = "LATEST"
    OLD = "OLD"
    CRITICAL = "CRITICAL"


class NetworkDesign(str, Enum):
    POINT_TO_POINT = "POINT_TO_POINT"
    FIELD_MESH = "FIELD_MESH"
    HUB_RELAY = "HUB_RELAY"


class UnitOccupancyStatus(str, Enum):
    VACANT = "VACANT"
    OCCUPIED = "OCCUPIED"
    NOTICE = "NOTICE"
    NOTICE_ENDED = "NOTICE_ENDED"


class HvacMode(str, Enum):
    VACANT_AUTO = "VACANT_AUTO"
    OCCUPIED = "OCCUPIED"


class DeviceStatus(str, Enum):
    PROVISIONED = "PROVISIONED"
    ONLINE = "ONLINE"
    UNREACHABLE = "UNREACHABLE"
    DECOMMISSIONED = "DECOMMISSIONED"


class LockState(str, Enum):
    LOCKED = "LOCKED"
    UNLOCKED = "UNLOCKED"


class DeviceAlertStatus(str, Enum):
    OPEN = "OPEN"
    ACKNOWLEDGED = "ACKNOWLEDGED"
    RESOLVED = "RESOLVED"


class AlertType(str, Enum):
    OFFLINE = "OFFLINE"
    LOW_BATTERY = "LOW_BATTERY"
    UNAUTHORIZED_ENTRY = "UNAUTHORIZED_ENTRY"


class AlertSeverity(str, Enum):
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"


class WorkOrderStatus(str, Enum):
    OPEN = "OPEN"
    ASSIGNED = "ASSIGNED"
    CLOSED = "CLOSED"


class ResidentStatus(str, Enum):
    PENDING_CREDENTIAL = "PENDING_CREDENTIAL"
    ACTIVE = "ACTIVE"
    DEACTIVATING = "DEACTIVATING"
    REVOKED = "REVOKED"


class PortalCredentialStatus(str, Enum):
    NOT_ISSUED = "NOT_ISSUED"
    ACTIVE = "ACTIVE"
    REVOKED = "REVOKED"


class CredentialType(str, Enum):
    RESIDENT = "RESIDENT"
    GUEST = "GUEST"
    TOUR = "TOUR"


class CredentialStatus(str, Enum):
    ISSUED = "ISSUED"
    ACTIVE = "ACTIVE"
    EXPIRED = "EXPIRED"
    REVOKED = "REVOKED"


class GuestPassStatus(str, Enum):
    ACTIVE = "ACTIVE"
    EXPIRED = "EXPIRED"
    REVOKED = "REVOKED"


class TourSessionStatus(str, Enum):
    REQUESTED = "REQUESTED"
    DENIED = "DENIED"
    VERIFIED = "VERIFIED"
    ACTIVE = "ACTIVE"
    COMPLETED = "COMPLETED"


class MaintenanceVisitStatus(str, Enum):
    REQUESTED = "REQUESTED"
    NOTICE_CERTIFIED = "NOTICE_CERTIFIED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class InstallationJobStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    ABORTED = "ABORTED"


class UserRole(str, Enum):
    PLATFORM_ADMIN = "PlatformAdmin"
    PROPERTY_MANAGER = "PropertyManager"
    HARDWARE_TECHNICIAN = "HardwareTechnician"
    MAINTENANCE_TECHNICIAN = "MaintenanceTechnician"
    LEASING_AGENT = "LeasingAgent"
    RESIDENT = "Resident"


# --- Entity representations (system-managed fields included) ---------------
# Every long-lived resource carries id + created_at + updated_at + version.
# ResidentStatusEvent is the one append-only audit record: id + created_at only.

class Property(TypedDict):
    id: str
    name: str
    address_line: str
    unit_capacity: int
    temp_budget_cents_per_day: int
    budget_committed_cents: int
    created_at: str
    updated_at: str
    version: int


class Building(TypedDict):
    id: str
    property_id: str
    name: str
    network_design: str
    wifi_rssi_dbm: int
    last_hub_service_at: Optional[str]
    connectivity_ok: bool
    created_at: str
    updated_at: str
    version: int


class Unit(TypedDict):
    id: str
    property_id: str
    building_id: Optional[str]
    unit_number: str
    occupancy_status: str
    target_setpoint_c: float
    hvac_mode: str
    pod_entry_window_start: Optional[str]
    pod_entry_window_end: Optional[str]
    unauthorized_entry_detected: bool
    created_at: str
    updated_at: str
    version: int


class Device(TypedDict):
    id: str
    unit_id: Optional[str]
    building_id: str
    device_type: str
    firmware_version: str
    battery_pct: int
    status: str
    lock_state: str
    battery_replacements: int
    created_at: str
    updated_at: str
    version: int


class DeviceAlert(TypedDict):
    id: str
    building_id: str
    device_id: str
    alert_type: str
    status: str
    severity: str
    created_at: str
    updated_at: str
    version: int


class WorkOrder(TypedDict):
    id: str
    device_id: str
    alert_id: str
    assigned_technician_id: Optional[str]
    status: str
    battery_replaced: bool
    created_at: str
    updated_at: str
    version: int


class Resident(TypedDict):
    id: str
    property_id: str
    unit_id: str
    full_name: str
    email: str
    status: str
    portal_credential_status: str
    created_at: str
    updated_at: str
    version: int


class ResidentStatusEvent(TypedDict):
    """Append-only audit record — carries only id and created_at."""
    id: str
    resident_id: str
    from_status: str
    to_status: str
    recorded_at: str
    created_at: str


class AccessCredential(TypedDict):
    id: str
    unit_id: str
    subject_resident_id: Optional[str]
    credential_type: str
    status: str
    valid_from: str
    valid_until: str
    created_at: str
    updated_at: str
    version: int


class GuestPass(TypedDict):
    id: str
    unit_id: str
    host_resident_id: str
    guest_label: str
    status: str
    start_at: str
    end_at: str
    created_at: str
    updated_at: str
    version: int


class TourSession(TypedDict):
    id: str
    unit_id: str
    prospect_name: str
    prospect_id_document: str
    status: str
    requested_start_at: str
    duration_minutes: int
    identity_verified_at: Optional[str]
    verify_attempts: int
    created_at: str
    updated_at: str
    version: int


class MaintenanceVisit(TypedDict):
    id: str
    unit_id: str
    technician_id: str
    start_at: str
    end_at: str
    planned_hours: float
    actual_hours: Optional[float]
    is_emergency: bool
    notice_mailed_at: Optional[str]
    status: str
    accrued_cost_cents: int
    created_at: str
    updated_at: str
    version: int


class InstallationJob(TypedDict):
    id: str
    property_id: str
    building_id: str
    unit_id: Optional[str]
    device_type: str
    requires_resident_coordination: bool
    access_window_start: str
    access_window_end: str
    scheduled_start_at: Optional[str]
    status: str
    labor_hours: float
    created_at: str
    updated_at: str
    version: int