"""Domain types: entity TypedDicts, status enums, role enum.

Every entity in this API carries the four common system-managed properties
(id, created_at, updated_at, version) described in PRD §2.5, so every
TypedDict below includes them.
"""
from enum import Enum
from typing import Any, Dict, List, Optional, TypedDict


class UserRole(str, Enum):
    MANUFACTURER_ADMIN = "ManufacturerAdmin"
    DEALER_REP = "DealerRep"
    END_USER_REP = "EndUserRep"


class DealerStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class AgreementStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    EXPIRED = "EXPIRED"


class LifecycleStatus(str, Enum):
    CURRENT = "CURRENT"
    SUNSETTING = "SUNSETTING"
    DISCONTINUED = "DISCONTINUED"


class Category(str, Enum):
    SYSTEMS = "SYSTEMS"
    SEATING = "SEATING"
    STORAGE = "STORAGE"


class ModuleType(str, Enum):
    WORKSTATION_6X6 = "WORKSTATION_6X6"
    WORKSTATION_8X8 = "WORKSTATION_8X8"
    PRIVATE_OFFICE = "PRIVATE_OFFICE"
    STORAGE_WALL = "STORAGE_WALL"
    TASK_CHAIR_SET = "TASK_CHAIR_SET"


class FabricGrade(str, Enum):
    A = "A"
    B = "B"
    C = "C"
    COM = "COM"


class ConfigurationStatus(str, Enum):
    DRAFT = "DRAFT"
    LOCKED = "LOCKED"


class OrderStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    ON_HOLD = "ON_HOLD"
    ACKNOWLEDGED = "ACKNOWLEDGED"
    CLOSED = "CLOSED"
    CANCELLED = "CANCELLED"


class LogisticsStatus(str, Enum):
    PLANNED = "PLANNED"
    SCHEDULED = "SCHEDULED"
    DELIVERED = "DELIVERED"
    CANCELLED = "CANCELLED"


class InstallStatus(str, Enum):
    NOT_STARTED = "NOT_STARTED"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETE = "COMPLETE"
    CANCELLED = "CANCELLED"


class PlantCode(str, Enum):
    PLANT_GR = "PLANT_GR"
    PLANT_DAL = "PLANT_DAL"


class WindowStatus(str, Enum):
    RESERVED = "RESERVED"
    CANCELLED = "CANCELLED"


class PunchSeverity(str, Enum):
    CRITICAL = "CRITICAL"
    MAJOR = "MAJOR"
    MINOR = "MINOR"


class PunchStatus(str, Enum):
    OPEN = "OPEN"
    RESOLVED = "RESOLVED"
    VERIFIED = "VERIFIED"
    VOID = "VOID"


class ClaimType(str, Enum):
    PARTS = "PARTS"
    LABOR = "LABOR"


class ClaimStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    DENIED = "DENIED"


class VerifyOutcome(str, Enum):
    CONFIRMED = "CONFIRMED"
    REJECTED = "REJECTED"


class ReviewDecision(str, Enum):
    APPROVE = "APPROVE"
    DENY = "DENY"


class ModuleEntry(TypedDict):
    module_type: str
    fabric_grade: Optional[str]  # null exactly for STORAGE_WALL modules
    qty: int


class Dealer(TypedDict):
    id: str
    name: str
    territory_codes: List[str]
    service_capability_level: int
    showroom_compliant: bool
    status: str
    suspended_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class EndUser(TypedDict):
    id: str
    name: str
    industry: str
    created_at: str
    updated_at: str
    version: int


class VolumeAgreement(TypedDict):
    id: str
    end_user_id: str
    effective_start: str
    effective_end: str
    tier1_discount_pct: float
    tier2_discount_pct: float
    tier3_discount_pct: float
    status: str
    cumulative_volume_cents: int
    current_tier: int
    activated_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ProductFamily(TypedDict):
    id: str
    family_code: str
    name: str
    category: str
    base_lead_time_days: int
    lifecycle_status: str
    last_order_date: Optional[str]
    discontinued_at: Optional[str]
    parts_support_until: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ConfigurationSpec(TypedDict):
    id: str
    dealer_id: str
    name: str
    modules: List[ModuleEntry]
    status: str
    revision_number: int
    total_units: Optional[int]
    list_total_cents: Optional[int]
    max_lead_time_days: Optional[int]
    locked_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ProjectOrder(TypedDict):
    id: str
    dealer_id: str
    volume_agreement_id: str
    configuration_id: str
    configuration_revision: Optional[int]
    territory_code: str
    requested_install_date: str
    status: str
    pre_discount_total_cents: Optional[int]
    provisional_tier: Optional[int]
    provisional_total_cents: Optional[int]
    final_tier: Optional[int]
    final_total_cents: Optional[int]
    submitted_at: Optional[str]
    acknowledged_at: Optional[str]
    cancelled_at: Optional[str]
    cancel_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class InstallationPhase(TypedDict):
    id: str
    project_order_id: str
    floor_number: int
    phase_sequence: int
    building_zone_id: str
    planned_units: int
    logistics_status: str
    install_status: str
    plant_code: Optional[str]
    production_date: Optional[str]
    delivered_at: Optional[str]
    install_started_at: Optional[str]
    actual_install_complete_date: Optional[str]
    created_at: str
    updated_at: str
    version: int


class InstallWindow(TypedDict):
    id: str
    installation_phase_id: str
    building_zone_id: str
    start_at: str
    end_at: str
    union_required: bool
    elevator_required: bool
    crew_size: int
    status: str
    created_at: str
    updated_at: str
    version: int


class PunchTicket(TypedDict):
    id: str
    installation_phase_id: str
    severity: str
    description: str
    requires_part: bool
    part_number: Optional[str]
    status: str
    resolution_note: Optional[str]
    escalated: bool
    created_at: str
    updated_at: str
    version: int


class WarrantyClaim(TypedDict):
    id: str
    project_order_id: str
    installation_phase_id: str
    punch_ticket_id: Optional[str]
    claim_type: str
    part_number: Optional[str]
    description: str
    status: str
    filed_date: str
    review_note: Optional[str]
    reviewed_at: Optional[str]
    created_at: str
    updated_at: str
    version: int
