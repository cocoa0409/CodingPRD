"""Domain types: entity TypedDicts, status enums, role enum (PRD §2.1, §2.5, §3)."""
from enum import Enum
from typing import Optional, TypedDict


class UserRole(str, Enum):
    PLATFORM_ADMIN = "PlatformAdmin"
    MISSION_OPS = "MissionOps"
    CONTRACT_MANAGER = "ContractManager"
    CUSTOMER = "Customer"
    INTEGRATION_ENGINEER = "IntegrationEngineer"
    SAFETY_OFFICER = "SafetyOfficer"
    RANGE_OFFICER = "RangeOfficer"
    REGULATOR = "Regulator"


class MissionStatus(str, Enum):
    MANIFEST_OPEN = "MANIFEST_OPEN"
    MANIFEST_LOCKED = "MANIFEST_LOCKED"
    RANGE_SCHEDULED = "RANGE_SCHEDULED"
    LAUNCHED = "LAUNCHED"
    COMPLETED = "COMPLETED"
    SCRUBBED = "SCRUBBED"


class ContractStatus(str, Enum):
    DRAFT = "DRAFT"
    SIGNED = "SIGNED"
    MANIFESTED = "MANIFESTED"
    FULFILLED = "FULFILLED"
    EXPIRED = "EXPIRED"


class PayloadStatus(str, Enum):
    REGISTERED = "REGISTERED"
    MANIFESTED = "MANIFESTED"
    DEPLOYED = "DEPLOYED"


class AssignmentStatus(str, Enum):
    PROVISIONAL = "PROVISIONAL"
    CONFIRMED = "CONFIRMED"
    INTEGRATED = "INTEGRATED"
    DEPLOYED = "DEPLOYED"
    REMOVED = "REMOVED"


class LicenseStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    GRANTED = "GRANTED"
    DENIED = "DENIED"
    REVOKED = "REVOKED"
    EXPIRED = "EXPIRED"


class RangeSlotStatus(str, Enum):
    REQUESTED = "REQUESTED"
    RESERVED = "RESERVED"
    CONFIRMED = "CONFIRMED"
    CONSUMED = "CONSUMED"
    RELEASED = "RELEASED"


class SeparationEventStatus(str, Enum):
    PLANNED = "PLANNED"
    EXECUTED = "EXECUTED"
    ANOMALOUS = "ANOMALOUS"


class AnomalyStatus(str, Enum):
    OPEN = "OPEN"
    UNDER_INVESTIGATION = "UNDER_INVESTIGATION"
    ESCALATED = "ESCALATED"
    RESOLVED = "RESOLVED"


class Orbit(str, Enum):
    SSO = "SSO"
    LEO = "LEO"
    GTO = "GTO"


class InterfaceClass(str, Enum):
    RING_15 = "RING_15"
    RING_24 = "RING_24"
    CUBESAT = "CUBESAT"


class RangeCode(str, Enum):
    CCAFS = "CCAFS"
    VAFB = "VAFB"


# --- common_fields entities: id + created_at + updated_at + version (PRD §2.5) ---


class Customer(TypedDict, total=False):
    id: str
    org_name: str
    contact_email: str
    default_rebookings: int
    created_at: str
    updated_at: str
    version: int


class Mission(TypedDict, total=False):
    id: str
    mission_name: str
    target_orbit: str
    window_open_utc: str
    window_close_utc: str
    mass_capacity_kg: float
    volume_capacity_m3: float
    committed_mass_kg: float
    committed_volume_m3: float
    firm_mass_kg: float
    integration_revenue_cents: int
    revenue_estimate_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class DispenserPort(TypedDict, total=False):
    id: str
    mission_id: str
    port_code: str
    stack_position: int
    max_mass_kg: float
    supported_interface_classes: list
    created_at: str
    updated_at: str
    version: int


class LaunchContract(TypedDict, total=False):
    id: str
    customer_id: str
    target_mission_id: Optional[str]
    pricing_mode: str
    window_open_utc: str
    window_close_utc: str
    rebookings_remaining: int
    quoted_price_cents: int
    total_rebooking_fees_cents: int
    rebook_eligible: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class Payload(TypedDict, total=False):
    id: str
    contract_id: str
    payload_name: str
    mass_kg: float
    volume_m3: float
    interface_class: str
    required_orbit: str
    status: str
    created_at: str
    updated_at: str
    version: int


class ManifestAssignment(TypedDict, total=False):
    id: str
    mission_id: str
    payload_id: str
    dispenser_port_id: str
    integration_fee_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class RegulatoryLicense(TypedDict, total=False):
    id: str
    subject_type: str
    mission_id: Optional[str]
    customer_id: Optional[str]
    kind: str
    debris_score: int
    spectrum_score: int
    operator_history_score: int
    composite_score: int
    valid_until: str
    status: str
    created_at: str
    updated_at: str
    version: int


class RangeSlot(TypedDict, total=False):
    id: str
    mission_id: str
    range_code: str
    window_open_utc: str
    window_close_utc: str
    status: str
    created_at: str
    updated_at: str
    version: int


class SeparationEvent(TypedDict, total=False):
    id: str
    mission_id: str
    assignment_id: str
    sequence_index: int
    offset_seconds: int
    status: str
    created_at: str
    updated_at: str
    version: int


class AnomalyReport(TypedDict, total=False):
    id: str
    mission_id: str
    category: str
    severity: str
    status: str
    disposition: Optional[str]
    resolution_notes: Optional[str]
    created_at: str
    updated_at: str
    version: int


# --- append-only records: ONLY id + created_at (PRD §2.5); no updated_at/version ---


class InterfaceVerification(TypedDict, total=False):
    id: str
    assignment_id: str
    check_type: str
    outcome: str
    notes: Optional[str]
    created_by_user_id: str
    created_at: str


class SafetyReview(TypedDict, total=False):
    id: str
    assignment_id: str
    decision: str
    rationale: Optional[str]
    created_by_user_id: str
    created_at: str


class ExclusionWindow(TypedDict, total=False):
    id: str
    scope_type: str
    scope_value: str
    kind: str
    start_utc: str
    end_utc: str
    created_at: str


class DelayEvent(TypedDict, total=False):
    id: str
    mission_id: str
    previous_window_open_utc: str
    previous_window_close_utc: str
    new_window_open_utc: str
    new_window_close_utc: str
    reason_code: str
    slot_released: bool
    assignments_removed_count: int
    created_at: str
