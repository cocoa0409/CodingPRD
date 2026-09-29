"""Domain types for the School Bus Manufacturing API: status enums, role enum,
and one TypedDict per resource described in the PRD."""

from enum import Enum
from typing import List, Optional, TypedDict


# --------------------------------------------------------------------------
# Roles
# --------------------------------------------------------------------------
class UserRole(str, Enum):
    SALES_ENGINEER = "SalesEngineer"
    CONTRACTS_ADMIN = "ContractsAdmin"
    PLANT_SCHEDULER = "PlantScheduler"
    QUALITY_INSPECTOR = "QualityInspector"
    COMPLIANCE_OFFICER = "ComplianceOfficer"
    DEALER_AGENT = "DealerAgent"


ALL_ROLES: List[str] = [r.value for r in UserRole]


# --------------------------------------------------------------------------
# Enumerations
# --------------------------------------------------------------------------
class SpecProfileStatus(str, Enum):
    DRAFT = "DRAFT"
    PUBLISHED = "PUBLISHED"
    SUPERSEDED = "SUPERSEDED"


class BodyClass(str, Enum):
    TYPE_A = "TYPE_A"
    TYPE_C = "TYPE_C"
    TYPE_D = "TYPE_D"


class PropulsionType(str, Enum):
    DIESEL = "DIESEL"
    PROPANE = "PROPANE"
    ELECTRIC = "ELECTRIC"


class MirrorConfig(str, Enum):
    STANDARD = "STANDARD"
    CROSSVIEW = "CROSSVIEW"
    CROSSVIEW_HEATED = "CROSSVIEW_HEATED"


class TerrainClass(str, Enum):
    FLAT = "FLAT"
    ROLLING = "ROLLING"
    MOUNTAIN = "MOUNTAIN"


class BuyerType(str, Enum):
    DISTRICT = "DISTRICT"
    COOPERATIVE = "COOPERATIVE"


class SolicitationStatus(str, Enum):
    OPEN = "OPEN"
    CLOSED = "CLOSED"
    AWARDED = "AWARDED"


class BidStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    REVISION_REQUESTED = "REVISION_REQUESTED"
    AWARDED = "AWARDED"
    REJECTED = "REJECTED"


class SpecComplianceStatus(str, Enum):
    CONFORMING = "CONFORMING"
    EXCEPTIONS_TAKEN = "EXCEPTIONS_TAKEN"
    NONCONFORMING = "NONCONFORMING"


class ContractOrderStatus(str, Enum):
    ACTIVE = "ACTIVE"
    FULFILLED = "FULFILLED"
    CANCELLED = "CANCELLED"


class DeliveryPosture(str, Enum):
    ON_TRACK = "ON_TRACK"
    AT_RISK = "AT_RISK"
    BREACHED = "BREACHED"


class ProductionLineStatus(str, Enum):
    RUNNING = "RUNNING"
    DOWN_FOR_MAINTENANCE = "DOWN_FOR_MAINTENANCE"


class BuildSlotStatus(str, Enum):
    PLANNED = "PLANNED"
    COMMITTED = "COMMITTED"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    RELEASED = "RELEASED"


class ProductionStatus(str, Enum):
    PLANNED = "PLANNED"
    SLOTTED = "SLOTTED"
    BODY_JOINED = "BODY_JOINED"
    BUILT = "BUILT"
    DELIVERED = "DELIVERED"


class CertificationStatus(str, Enum):
    PENDING = "PENDING"
    CERTIFIED = "CERTIFIED"
    NONCONFORMING = "NONCONFORMING"
    WAIVED = "WAIVED"


class ServiceStatus(str, Enum):
    NONE = "NONE"
    RECALL_OPEN = "RECALL_OPEN"
    RECALL_CLOSED = "RECALL_CLOSED"


class DriverTrainingStatus(str, Enum):
    PENDING = "PENDING"
    COMPLETED = "COMPLETED"


class TestType(str, Enum):
    BRAKE = "BRAKE"
    EMERGENCY_EXIT = "EMERGENCY_EXIT"
    ELECTRICAL = "ELECTRICAL"
    JOINT_STRENGTH = "JOINT_STRENGTH"
    ROLLOVER = "ROLLOVER"


class QualityTestStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    PASSED = "PASSED"
    FAILED = "FAILED"
    VOIDED = "VOIDED"


class TestOutcome(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"


class CertificationStanding(str, Enum):
    GOOD = "GOOD"
    RESTRICTED = "RESTRICTED"
    SUSPENDED = "SUSPENDED"


class DefectCategory(str, Enum):
    BRAKE_LINE_CORROSION = "BRAKE_LINE_CORROSION"
    EMERGENCY_EXIT_LATCH = "EMERGENCY_EXIT_LATCH"
    WIRING_HARNESS = "WIRING_HARNESS"
    BATTERY_CONTACTOR = "BATTERY_CONTACTOR"


class RecallCampaignStatus(str, Enum):
    DRAFT = "DRAFT"
    LAUNCHED = "LAUNCHED"
    COMPLETED = "COMPLETED"


class RemedyTaskStatus(str, Enum):
    OPEN = "OPEN"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class EscalationLevel(str, Enum):
    DEALER_DIRECTED = "DEALER_DIRECTED"
    FACTORY_DIRECTED = "FACTORY_DIRECTED"


# --------------------------------------------------------------------------
# Resources carrying id + created_at + updated_at + version
# --------------------------------------------------------------------------
class StateSpecProfile(TypedDict, total=False):
    id: str
    state_code: str
    school_year: str
    status: str
    min_seat_capacity: int
    min_emergency_exit_count: int
    min_joint_strength_kn: float
    required_route_range_mi: float
    requires_eight_lamp_system: bool
    requires_crossing_arm: bool
    required_mirror_config: str
    requires_lap_shoulder_belts: bool
    requires_rollover_protection: bool
    requires_joint_strength_test: bool
    terrain_class: str
    published_at: Optional[str]
    superseded_by_profile_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class BusModel(TypedDict, total=False):
    id: str
    model_code: str
    body_class: str
    base_seat_capacity: int
    base_emergency_exit_count: int
    base_price_cents: int
    body_joint_strength_kn: float
    max_battery_bays: int
    curb_weight_lb: int
    created_at: str
    updated_at: str
    version: int


class PropulsionPackage(TypedDict, total=False):
    id: str
    package_code: str
    compatible_bus_model_id: str
    propulsion_type: str
    option_price_cents: int
    battery_pack_count: int
    usable_kwh: float
    nominal_consumption_kwh_per_mi: float
    hvac_load_kw: float
    fuel_capacity_gal: float
    rated_mpg: float
    cold_weather_derate_pct: float
    reserve_floor_pct: float
    created_at: str
    updated_at: str
    version: int


class Solicitation(TypedDict, total=False):
    id: str
    solicitation_code: str
    buyer_type: str
    buyer_name: str
    spec_profile_id: str
    state_code: str
    school_year: str
    unit_count: int
    required_delivery_date: str
    price_cap_cents_per_unit: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Bid(TypedDict, total=False):
    id: str
    solicitation_id: str
    bus_model_id: str
    propulsion_package_id: str
    evaluated_spec_profile_id: str
    unit_count: int
    offered_seat_capacity: int
    offered_emergency_exit_count: int
    offered_mirror_config: str
    offered_lap_shoulder_belts: bool
    offered_eight_lamp_system: bool
    offered_crossing_arm: bool
    offered_rollover_reinforcement: bool
    offered_joint_strength_kn: float
    nominal_range_mi: int
    derated_route_range_mi: float
    provisional_unit_price_cents: int
    spec_compliance_status: str
    exception_count: int
    unmet_mandatory_items: List[str]
    exception_items: List[str]
    revision_round: int
    status: str
    submitted_at: Optional[str]
    submitted_by_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ContractOrder(TypedDict, total=False):
    id: str
    bid_id: str
    solicitation_id: str
    spec_profile_id: str
    bus_model_id: str
    propulsion_package_id: str
    unit_count: int
    awarded_seat_capacity: int
    awarded_emergency_exit_count: int
    awarded_mirror_config: str
    awarded_lap_shoulder_belts: bool
    awarded_eight_lamp_system: bool
    awarded_crossing_arm: bool
    awarded_rollover_reinforcement: bool
    awarded_joint_strength_kn: float
    awarded_unit_price_cents: int
    total_contract_cents: int
    promised_delivery_date: str
    created_unit_count: int
    delivered_unit_count: int
    at_risk_unit_count: int
    delivery_posture: str
    liquidated_damages_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class ProductionLine(TypedDict, total=False):
    id: str
    line_code: str
    plant_code: str
    supported_body_classes: List[str]
    horizon_slot_day_capacity: int
    changeover_buffer_days: int
    committed_slot_days: int
    status: str
    created_at: str
    updated_at: str
    version: int


class BuildSlot(TypedDict, total=False):
    id: str
    production_line_id: str
    bus_unit_id: str
    start_date: str
    end_date: str
    slot_days: int
    propulsion_type: str
    status: str
    created_at: str
    updated_at: str
    version: int


class BusUnit(TypedDict, total=False):
    id: str
    contract_order_id: Optional[str]
    bus_model_id: str
    propulsion_package_id: str
    spec_profile_id: str
    dealer_id: Optional[str]
    vin: str
    registration_state_code: str
    seat_capacity: int
    emergency_exit_count: int
    mirror_config: str
    lap_shoulder_belts: bool
    eight_lamp_system: bool
    crossing_arm: bool
    rollover_reinforcement: bool
    joint_strength_kn: float
    nominal_range_mi: int
    derated_route_range_mi: float
    production_status: str
    certification_status: str
    service_status: str
    driver_training_status: str
    waiver_justification: Optional[str]
    certified_at: Optional[str]
    delivered_at: Optional[str]
    is_legacy_import: bool
    created_at: str
    updated_at: str
    version: int


class TestBay(TypedDict, total=False):
    id: str
    bay_code: str
    plant_code: str
    supported_test_types: List[str]
    max_concurrent_electrical: int
    created_at: str
    updated_at: str
    version: int


class QualityTest(TypedDict, total=False):
    id: str
    bus_unit_id: str
    test_bay_id: str
    test_type: str
    window_start: str
    window_end: str
    min_required_value: Optional[float]
    measured_value: Optional[float]
    status: str
    result_notes: Optional[str]
    recorded_by_user_id: Optional[str]
    recorded_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Dealer(TypedDict, total=False):
    id: str
    dealer_code: str
    dealer_name: str
    licensed_state_codes: List[str]
    training_capacity_per_month: int
    delivered_unit_count: int
    open_recall_unit_count: int
    certification_standing: str
    created_at: str
    updated_at: str
    version: int


class RecallCampaign(TypedDict, total=False):
    id: str
    campaign_code: str
    affected_bus_model_id: str
    affected_propulsion_type: str
    defect_category: str
    build_window_start: str
    build_window_end: str
    kits_per_unit: int
    total_kits: int
    reserved_kits: int
    consumed_kits: int
    available_kits: int
    affected_unit_count: int
    escalated_task_count: int
    kit_shortfall_count: int
    status: str
    launched_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class RemedyTask(TypedDict, total=False):
    id: str
    recall_campaign_id: str
    bus_unit_id: str
    dealer_id: str
    escalation_level: str
    kits_reserved: int
    status: str
    completed_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


# --------------------------------------------------------------------------
# Append-only resource: carries ONLY id + created_at
# --------------------------------------------------------------------------
class BidRevision(TypedDict, total=False):
    id: str
    bid_id: str
    round_index: int
    offered_seat_capacity: int
    offered_emergency_exit_count: int
    offered_mirror_config: str
    offered_lap_shoulder_belts: bool
    offered_eight_lamp_system: bool
    offered_crossing_arm: bool
    offered_rollover_reinforcement: bool
    unit_price_cents: int
    note: Optional[str]
    is_superseded: bool
    created_at: str
