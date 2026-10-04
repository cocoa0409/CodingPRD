"""Domain types: entity TypedDicts, status enums, role enum (PRD Sections 2-3).

Field inventories follow the PRD resource descriptions. Per PRD Section 2.4,
ModelStrain, HealthScreen, Allocation, and WelfareInspection are deliberately
lighter: they carry only ``id`` and ``created_at`` — no ``updated_at`` and no
``version``. All other resources carry the full audit triple.
"""
from enum import Enum
from typing import TypedDict, Optional, List, Dict, Any


# ---------------------------------------------------------------------------
# Role enum (PRD Section 2.1)
# ---------------------------------------------------------------------------

class UserRole(str, Enum):
    PLATFORM_ADMIN = "PlatformAdmin"
    FACILITY_MANAGER = "FacilityManager"
    VETERINARIAN = "Veterinarian"
    IACUC_REVIEWER = "IACUCReviewer"
    CUSTOMER = "Customer"
    LOGISTICS_COORDINATOR = "LogisticsCoordinator"
    WELFARE_INSPECTOR = "WelfareInspector"


# ---------------------------------------------------------------------------
# Shared enumerations
# ---------------------------------------------------------------------------

class BarrierLevel(str, Enum):
    """PRD Section 2.6 rank order: CONVENTIONAL < MPF < VF < GERM_FREE."""
    CONVENTIONAL = "CONVENTIONAL"
    MPF = "MPF"
    VF = "VF"
    GERM_FREE = "GERM_FREE"


class Species(str, Enum):
    MOUSE = "MOUSE"
    RAT = "RAT"


class ImmuneClass(str, Enum):
    IMMUNOCOMPETENT = "IMMUNOCOMPETENT"
    IMMUNOCOMPROMISED = "IMMUNOCOMPROMISED"


class BreedingType(str, Enum):
    INBRED = "INBRED"
    OUTBRED = "OUTBRED"
    HYBRID = "HYBRID"


# ---------------------------------------------------------------------------
# Status enums (PRD Section 3 state machines)
# ---------------------------------------------------------------------------

class FacilityRegistrationStatus(str, Enum):
    REGISTERED = "REGISTERED"
    UNDER_INSPECTION = "UNDER_INSPECTION"
    SUSPENDED = "SUSPENDED"
    REVOKED = "REVOKED"


class RoomStatus(str, Enum):
    ACTIVE = "ACTIVE"
    QUARANTINED = "QUARANTINED"
    DECOMMISSIONED = "DECOMMISSIONED"


class ColonyLifecycleStatus(str, Enum):
    FOUNDING = "FOUNDING"
    EXPANDING = "EXPANDING"
    PRODUCTION = "PRODUCTION"
    PHASING_OUT = "PHASING_OUT"
    RETIRED = "RETIRED"


class ColonyGeneticStatus(str, Enum):
    CLEAR = "CLEAR"
    PANEL_DUE = "PANEL_DUE"
    DRIFT_DETECTED = "DRIFT_DETECTED"


class CohortStatus(str, Enum):
    WEANED = "WEANED"
    HOLD = "HOLD"
    PARTIALLY_ALLOCATED = "PARTIALLY_ALLOCATED"
    FULLY_ALLOCATED = "FULLY_ALLOCATED"
    SHIPPED = "SHIPPED"
    CULLED = "CULLED"


class HealthScreenStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    RESULTED_NEGATIVE = "RESULTED_NEGATIVE"
    RESULTED_POSITIVE = "RESULTED_POSITIVE"


class PanelType(str, Enum):
    QUARTERLY_SENTINEL = "QUARTERLY_SENTINEL"
    OUTBREAK_DIAGNOSTIC = "OUTBREAK_DIAGNOSTIC"
    PRE_SHIPMENT = "PRE_SHIPMENT"


class CustomerAccountStatus(str, Enum):
    ACTIVE = "ACTIVE"
    CREDIT_HOLD = "CREDIT_HOLD"
    SUSPENDED = "SUSPENDED"


class OrderStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    SOURCING = "SOURCING"
    BACKORDERED = "BACKORDERED"
    ALLOCATED = "ALLOCATED"
    SCHEDULED = "SCHEDULED"
    SHIPPED = "SHIPPED"
    DELIVERED = "DELIVERED"
    CLOSED = "CLOSED"
    CANCELLED = "CANCELLED"
    REJECTED = "REJECTED"


class AllocationStatus(str, Enum):
    RESERVED = "RESERVED"
    RELEASED = "RELEASED"
    CONSUMED = "CONSUMED"


class ShipmentStatus(str, Enum):
    PLANNED = "PLANNED"
    LOADED = "LOADED"
    IN_TRANSIT = "IN_TRANSIT"
    ARRIVED = "ARRIVED"
    ACCEPTED = "ACCEPTED"
    REJECTED_AT_RECEIPT = "REJECTED_AT_RECEIPT"
    CANCELLED = "CANCELLED"


class ProtocolStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    UNDER_REVIEW = "UNDER_REVIEW"
    REVISION_REQUESTED = "REVISION_REQUESTED"
    APPROVED = "APPROVED"
    SUSPENDED = "SUSPENDED"
    EXPIRED = "EXPIRED"
    WITHDRAWN = "WITHDRAWN"
    REJECTED = "REJECTED"


class InspectionStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    CORRECTIVE_ACTION = "CORRECTIVE_ACTION"
    CLOSED_VERIFIED = "CLOSED_VERIFIED"
    ESCALATED = "ESCALATED"


class InspectionType(str, Enum):
    ROUTINE = "ROUTINE"
    FOR_CAUSE = "FOR_CAUSE"
    PRE_PLACEMENT = "PRE_PLACEMENT"


class FindingSeverity(str, Enum):
    MINOR = "MINOR"
    SIGNIFICANT = "SIGNIFICANT"


class VerifyOutcome(str, Enum):
    VERIFIED_OK = "VERIFIED_OK"
    VERIFIED_FAILED = "VERIFIED_FAILED"


class ContractType(str, Enum):
    CUSTOM_GENERATION = "CUSTOM_GENERATION"
    CRYOPRESERVATION = "CRYOPRESERVATION"


class IpOwnership(str, Enum):
    CUSTOMER_EXCLUSIVE = "CUSTOMER_EXCLUSIVE"
    SHARED = "SHARED"
    VENDOR_RETAINED = "VENDOR_RETAINED"


class ContractMilestoneStatus(str, Enum):
    DRAFT = "DRAFT"
    EXECUTED = "EXECUTED"
    IN_PROGRESS = "IN_PROGRESS"
    VALIDATION = "VALIDATION"
    VALIDATION_FAILED = "VALIDATION_FAILED"
    COMPLETED = "COMPLETED"
    CLOSED = "CLOSED"
    CANCELLED = "CANCELLED"


class SnpPanelResult(str, Enum):
    CLEAR = "CLEAR"
    DRIFT_DETECTED = "DRIFT_DETECTED"


# ---------------------------------------------------------------------------
# Entity TypedDicts
# ---------------------------------------------------------------------------

class Facility(TypedDict, total=False):
    id: str
    name: str
    site_code: str
    registration_number: str
    registration_status: str
    registration_expires_at: str
    suspension_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class BarrierRoom(TypedDict, total=False):
    id: str
    facility_id: str
    room_code: str
    barrier_level: str
    excluded_agents: List[str]
    cage_capacity: int
    occupied_cages: int
    status: str
    quarantined_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ModelStrain(TypedDict, total=False):
    # PRD Section 2.4: light resource — only id + created_at, no version.
    id: str
    strain_code: str
    species: str
    immune_class: str
    breeding_type: str
    min_barrier_level: str
    gestation_days: int
    wean_age_days: int
    typical_litter_size: int
    base_price_cents: int
    created_at: str


class Colony(TypedDict, total=False):
    id: str
    room_id: str
    strain_id: str
    protocol_id: str
    breeding_pair_count: int
    generation_number: int
    lifecycle_status: str
    genetic_status: str
    last_snp_panel_at: str
    snp_panel_interval_weeks: int
    confirmed_available_count: int
    projected_pipeline_count: int
    created_at: str
    updated_at: str
    version: int


class Cohort(TypedDict, total=False):
    id: str
    colony_id: str
    birth_date: str
    count_male: int
    count_female: int
    initial_count_total: int
    reserved_male: int
    reserved_female: int
    avg_weight_g_male: float
    avg_weight_g_female: float
    health_status: str
    status: str
    age_weeks: int
    created_at: str
    updated_at: str
    version: int


class HealthScreenResultEntry(TypedDict, total=False):
    agent: str
    positive: bool


class HealthScreen(TypedDict, total=False):
    # PRD Section 2.4: light resource — only id + created_at, no version.
    id: str
    room_id: str
    panel_type: str
    scheduled_at: str
    status: str
    results: List[Dict[str, Any]]
    resulted_at: Optional[str]
    created_at: str


class Customer(TypedDict, total=False):
    id: str
    institution_name: str
    account_number: str
    credit_limit_cents: int
    account_status: str
    accepted_min_health_status: str
    is_commercial: bool
    outstanding_balance_cents: int
    credit_exposure_cents: int
    created_at: str
    updated_at: str
    version: int


class CustomerOrder(TypedDict, total=False):
    id: str
    customer_id: str
    strain_id: str
    quantity_male: int
    quantity_female: int
    min_age_weeks: int
    max_age_weeks: int
    min_weight_g: float
    max_weight_g: float
    required_delivery_date: str
    min_health_status: str
    status: str
    quoted_total_cents: Optional[int]
    allocated_male: int
    allocated_female: int
    created_at: str
    updated_at: str
    version: int


class Allocation(TypedDict, total=False):
    # PRD Section 2.4: light resource — only id + created_at, no version.
    id: str
    order_id: str
    cohort_id: str
    qty_male: int
    qty_female: int
    status: str
    created_at: str


class Shipment(TypedDict, total=False):
    id: str
    order_id: str
    vehicle_code: str
    vehicle_barrier_cert: str
    sanitized_at: str
    departure_date: str
    planned_arrival_date: str
    actual_arrival_at: Optional[str]
    box_count: int
    received_male: Optional[int]
    received_female: Optional[int]
    status: str
    created_at: str
    updated_at: str
    version: int


class IACUCProtocol(TypedDict, total=False):
    id: str
    facility_id: str
    protocol_number: str
    pi_name: str
    species: str
    approved_animal_quota: int
    animals_used: int
    effective_date: str
    expiration_date: str
    submitted_by_user_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class InspectionFinding(TypedDict, total=False):
    deficiency: str
    severity: str


class WelfareInspection(TypedDict, total=False):
    # PRD Section 2.4: light resource — only id + created_at, no version.
    id: str
    facility_id: Optional[str]
    customer_id: Optional[str]
    inspection_type: str
    scheduled_date: str
    findings: List[Dict[str, Any]]
    corrective_deadline: Optional[str]
    reported_by_user_id: Optional[str]
    status: str
    created_at: str


class ServiceContract(TypedDict, total=False):
    id: str
    customer_id: str
    contract_type: str
    source_strain_id: str
    new_strain_spec: Optional[Dict[str, Any]]
    ip_ownership: str
    exclusivity_fee_cents: Optional[int]
    royalty_rate_pct: Optional[float]
    straw_count: Optional[int]
    viability_pct: Optional[float]
    generated_strain_id: Optional[str]
    milestone_status: str
    created_at: str
    updated_at: str
    version: int


__all__ = [
    "UserRole",
    "BarrierLevel",
    "Species",
    "ImmuneClass",
    "BreedingType",
    "FacilityRegistrationStatus",
    "RoomStatus",
    "ColonyLifecycleStatus",
    "ColonyGeneticStatus",
    "CohortStatus",
    "HealthScreenStatus",
    "PanelType",
    "CustomerAccountStatus",
    "OrderStatus",
    "AllocationStatus",
    "ShipmentStatus",
    "ProtocolStatus",
    "InspectionStatus",
    "InspectionType",
    "FindingSeverity",
    "VerifyOutcome",
    "ContractType",
    "IpOwnership",
    "ContractMilestoneStatus",
    "SnpPanelResult",
    "Facility",
    "BarrierRoom",
    "ModelStrain",
    "Colony",
    "Cohort",
    "HealthScreenResultEntry",
    "HealthScreen",
    "Customer",
    "CustomerOrder",
    "Allocation",
    "Shipment",
    "IACUCProtocol",
    "InspectionFinding",
    "WelfareInspection",
    "ServiceContract",
]
