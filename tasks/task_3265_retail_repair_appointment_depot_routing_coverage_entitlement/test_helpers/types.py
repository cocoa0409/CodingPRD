"""Domain types: entity TypedDicts, status enums, role enum."""
from enum import Enum
from typing import Optional, TypedDict


class UserRole(str, Enum):
    ANONYMOUS = "Anonymous"
    CUSTOMER = "Customer"
    TECHNICIAN = "Technician"
    CUSTOMER_SERVICE = "CustomerService"
    DEPOT_AGENT = "DepotAgent"
    PLATFORM_ADMIN = "PlatformAdmin"


class AccountStatus(str, Enum):
    ACTIVE = "ACTIVE"
    LOCKED = "LOCKED"
    CLOSED = "CLOSED"


class DeviceStatus(str, Enum):
    ACTIVE = "ACTIVE"
    IN_SERVICE = "IN_SERVICE"
    RETIRED = "RETIRED"


class CoverageStatus(str, Enum):
    ACTIVE = "ACTIVE"
    EXPIRED = "EXPIRED"
    EXHAUSTED = "EXHAUSTED"
    CANCELLED = "CANCELLED"


class PlanType(str, Enum):
    LIMITED_WARRANTY = "LIMITED_WARRANTY"
    APPLECARE_PLUS = "APPLECARE_PLUS"
    OUT_OF_WARRANTY = "OUT_OF_WARRANTY"


class LocationType(str, Enum):
    RETAIL_STORE = "RETAIL_STORE"
    AUTHORIZED_PROVIDER = "AUTHORIZED_PROVIDER"
    MAIL_IN_DEPOT = "MAIL_IN_DEPOT"


class LocationStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    CLOSED = "CLOSED"


class CertificationLevel(str, Enum):
    BASIC = "BASIC"
    ADVANCED = "ADVANCED"
    EXPERT = "EXPERT"


class PartCategory(str, Enum):
    DISPLAY = "DISPLAY"
    BATTERY = "BATTERY"
    LOGIC_BOARD = "LOGIC_BOARD"
    CAMERA = "CAMERA"
    ENCLOSURE = "ENCLOSURE"
    OTHER = "OTHER"


class PartStatus(str, Enum):
    ACTIVE = "ACTIVE"
    DISCONTINUED = "DISCONTINUED"
    RECALLED = "RECALLED"


class AppointmentStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    CHECKED_IN = "CHECKED_IN"
    IN_DIAGNOSIS = "IN_DIAGNOSIS"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"
    NO_SHOW = "NO_SHOW"


class IssueCategory(str, Enum):
    SCREEN_DAMAGE = "SCREEN_DAMAGE"
    BATTERY = "BATTERY"
    WATER_DAMAGE = "WATER_DAMAGE"
    SOFTWARE = "SOFTWARE"
    HARDWARE_OTHER = "HARDWARE_OTHER"


class TriageMode(str, Enum):
    SAME_DAY_IN_STORE = "SAME_DAY_IN_STORE"
    MAIL_IN_DEPOT = "MAIL_IN_DEPOT"
    WHOLE_UNIT_REPLACEMENT = "WHOLE_UNIT_REPLACEMENT"


class RepairStatus(str, Enum):
    TRIAGED = "TRIAGED"
    PARTS_ALLOCATED = "PARTS_ALLOCATED"
    IN_PROGRESS = "IN_PROGRESS"
    QUALITY_CHECK = "QUALITY_CHECK"
    READY_FOR_PICKUP = "READY_FOR_PICKUP"
    SHIPPED_TO_DEPOT = "SHIPPED_TO_DEPOT"
    IN_TRANSIT_BACK = "IN_TRANSIT_BACK"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"
    ESCALATED_REPEAT = "ESCALATED_REPEAT"


class AllocationStatus(str, Enum):
    RESERVED = "RESERVED"
    CONSUMED = "CONSUMED"
    RELEASED = "RELEASED"
    BACKORDERED = "BACKORDERED"


class EntitlementStatus(str, Enum):
    PENDING_VERIFICATION = "PENDING_VERIFICATION"
    ENTITLED = "ENTITLED"
    PARTIALLY_ENTITLED = "PARTIALLY_ENTITLED"
    NOT_ENTITLED = "NOT_ENTITLED"
    WAIVED = "WAIVED"


class VerificationType(str, Enum):
    ACTIVATION_LOCK_REMOVAL = "ACTIVATION_LOCK_REMOVAL"
    OWNERSHIP_PROOF = "OWNERSHIP_PROOF"
    ACCOUNT_UNLOCK = "ACCOUNT_UNLOCK"


class VerificationStatus(str, Enum):
    PENDING = "PENDING"
    VERIFIED = "VERIFIED"
    FAILED = "FAILED"
    EXPIRED = "EXPIRED"


class ShipmentType(str, Enum):
    CUSTOMER_TO_DEPOT = "CUSTOMER_TO_DEPOT"
    DEPOT_TO_CUSTOMER = "DEPOT_TO_CUSTOMER"
    STORE_TO_DEPOT = "STORE_TO_DEPOT"
    DEPOT_TO_STORE = "DEPOT_TO_STORE"


class ShipmentStatus(str, Enum):
    LABEL_CREATED = "LABEL_CREATED"
    IN_TRANSIT = "IN_TRANSIT"
    RECEIVED = "RECEIVED"
    DELIVERED = "DELIVERED"
    LOST = "LOST"


class FollowUpStatus(str, Enum):
    OPEN = "OPEN"
    RESOLVED_SATISFIED = "RESOLVED_SATISFIED"
    RESOLVED_REPEAT_REPAIR = "RESOLVED_REPEAT_REPAIR"
    ESCALATED = "ESCALATED"


# All entities participate in mutation workflows per the PRD (§2.4): each
# carries id + created_at + updated_at + version.


class Customer(TypedDict, total=False):
    id: str
    email: str
    full_name: str
    phone: str
    account_status: str
    created_at: str
    updated_at: str
    version: int


class Device(TypedDict, total=False):
    id: str
    customer_id: str
    serial_number: str
    model_code: str
    activation_lock_enabled: bool
    proof_of_purchase_on_file: bool
    purchase_date: str
    device_status: str
    created_at: str
    updated_at: str
    version: int


class CoveragePlan(TypedDict, total=False):
    id: str
    device_id: str
    plan_type: str
    starts_on: str
    expires_on: str
    accidental_damage_incidents_used: int
    accidental_damage_incident_limit: int
    service_fee_cents: int
    coverage_status: str
    created_at: str
    updated_at: str
    version: int


class ServiceLocation(TypedDict, total=False):
    id: str
    location_code: str
    location_type: str
    address: str
    supports_same_day_repair: bool
    supports_express_replacement: bool
    diagnostic_slot_duration_minutes: int
    location_status: str
    created_at: str
    updated_at: str
    version: int


class Technician(TypedDict, total=False):
    id: str
    location_id: str
    full_name: str
    certification_level: str
    is_active: bool
    created_at: str
    updated_at: str
    version: int


class Part(TypedDict, total=False):
    id: str
    part_number: str
    model_code: str
    part_category: str
    is_whole_unit_replacement: bool
    part_status: str
    created_at: str
    updated_at: str
    version: int


class PartInventory(TypedDict, total=False):
    id: str
    location_id: str
    part_id: str
    on_hand_quantity: int
    reserved_quantity: int
    express_replacement_quantity: int
    available_quantity: int
    created_at: str
    updated_at: str
    version: int


class Appointment(TypedDict, total=False):
    id: str
    customer_id: str
    device_id: str
    location_id: str
    technician_id: str
    slot_start: str
    slot_end: str
    issue_category: str
    appointment_status: str
    created_at: str
    updated_at: str
    version: int


class RepairOrder(TypedDict, total=False):
    id: str
    appointment_id: str
    device_id: str
    customer_id: str
    origin_location_id: str
    current_location_id: str
    issue_category: str
    is_accidental_damage: bool
    triage_mode: str
    repair_status: str
    quoted_price_cents: int
    data_backup_acknowledged: bool
    privacy_wipe_consent: bool
    repeat_repair_count: int
    created_at: str
    updated_at: str
    version: int


class PartAllocation(TypedDict, total=False):
    id: str
    repair_order_id: str
    part_id: str
    location_id: str
    quantity: int
    allocation_status: str
    created_at: str
    updated_at: str
    version: int


class CoverageEntitlement(TypedDict, total=False):
    id: str
    repair_order_id: str
    coverage_plan_id: str
    entitlement_status: str
    quoted_price_cents: int
    requires_proof_of_purchase: bool
    incident_counted: bool
    created_at: str
    updated_at: str
    version: int


class QualityFollowUp(TypedDict, total=False):
    id: str
    repair_order_id: str
    customer_id: str
    follow_up_status: str
    opened_at: str
    resolved_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class SecurityVerification(TypedDict, total=False):
    id: str
    repair_order_id: str
    verification_type: str
    verification_status: str
    verified_by: Optional[str]
    verified_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class RepairShipment(TypedDict, total=False):
    id: str
    repair_order_id: str
    from_location_id: str
    to_location_id: str
    shipment_type: str
    shipment_status: str
    tracking_number: str
    shipped_at: Optional[str]
    received_at: Optional[str]
    created_at: str
    updated_at: str
    version: int
