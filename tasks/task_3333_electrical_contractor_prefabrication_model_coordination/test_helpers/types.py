"""Domain types for the prefabrication & model coordination service.

Every resource in this service carries the common field set (id, created_at,
updated_at, version) — see PRD §2.4 — so every TypedDict below lists all four.
"""
from enum import Enum
from typing import List, Optional, TypedDict


class UserRole(str, Enum):
    PLATFORM_ADMIN = "PlatformAdmin"
    PROJECT_MANAGER = "ProjectManager"
    MODEL_COORDINATOR = "ModelCoordinator"
    SHOP_FOREMAN = "ShopForeman"
    LOGISTICS_COORDINATOR = "LogisticsCoordinator"
    PROCUREMENT_LEAD = "ProcurementLead"
    GENERAL_FOREMAN = "GeneralForeman"
    INSTALL_FOREMAN = "InstallForeman"


class ProjectPosture(str, Enum):
    ON_TRACK = "ON_TRACK"
    RELEASE_PENDING = "RELEASE_PENDING"
    RECOVERY_MODE = "RECOVERY_MODE"
    HOLD = "HOLD"
    FROZEN = "FROZEN"


class CreditPolicy(str, Enum):
    FIRST_ACCEPTED = "FIRST_ACCEPTED"
    HIGHEST_TOTAL = "HIGHEST_TOTAL"


class Classification(str, Enum):
    APPRENTICE = "APPRENTICE"
    JOURNEYMAN = "JOURNEYMAN"
    FOREMAN = "FOREMAN"
    GENERAL_FOREMAN = "GENERAL_FOREMAN"


class ModelVersionStatus(str, Enum):
    DRAFT = "DRAFT"
    COORDINATED = "COORDINATED"
    SUPERSEDED = "SUPERSEDED"


class ConduitRunType(str, Enum):
    MC_CABLE = "MC_CABLE"
    EMT_OVERHEAD = "EMT_OVERHEAD"
    EMT_EMBEDDED = "EMT_EMBEDDED"
    RIGID_RACK = "RIGID_RACK"
    OVERHEAD_RACK = "OVERHEAD_RACK"
    UNDERGROUND_DUCTBANK = "UNDERGROUND_DUCTBANK"
    ALUMINUM_RACEWAY = "ALUMINUM_RACEWAY"


class AssemblyKind(str, Enum):
    RACK = "RACK"
    BRANCH_TRUNK = "BRANCH_TRUNK"
    PANEL_FEEDER = "PANEL_FEEDER"
    DEVICE_STRAP = "DEVICE_STRAP"
    SWITCHGEAR_SECTION = "SWITCHGEAR_SECTION"


class StageCode(str, Enum):
    FIRST_STAGE = "FIRST_STAGE"
    SECOND_STAGE = "SECOND_STAGE"
    TRIM_OUT = "TRIM_OUT"


class FabricateStatus(str, Enum):
    PLANNED = "PLANNED"
    RELEASED = "RELEASED"
    IN_FABRICATION = "IN_FABRICATION"
    FABRICATED = "FABRICATED"
    CANCELLED = "CANCELLED"


class DeliverStatus(str, Enum):
    AWAITING = "AWAITING"
    STAGED = "STAGED"
    LOADED = "LOADED"
    IN_TRANSIT = "IN_TRANSIT"
    DELIVERED = "DELIVERED"


class ShipmentStatus(str, Enum):
    PENDING = "PENDING"
    RESERVED = "RESERVED"
    STAGED = "STAGED"
    LOADED = "LOADED"
    IN_TRANSIT = "IN_TRANSIT"
    DELIVERED = "DELIVERED"
    LOST = "LOST"
    LOCKED = "LOCKED"


class ReleasableStatus(str, Enum):
    ENGINEERING_HOLD = "ENGINEERING_HOLD"
    MATERIAL_HOLD = "MATERIAL_HOLD"
    READY = "READY"
    PERMITTED = "PERMITTED"
    ALLOWED = "ALLOWED"


class InstallStatus(str, Enum):
    PLANNED = "PLANNED"
    FABRICATED = "FABRICATED"
    LOADED = "LOADED"
    SET = "SET"
    REWORK = "REWORK"
    SCRAPPED = "SCRAPPED"


class ChainMode(str, Enum):
    CHAIN_DEPENDENT = "CHAIN_DEPENDENT"
    PARALLEL_FABRICATION = "PARALLEL_FABRICATION"


class ActivityKind(str, Enum):
    ELECTRICAL_INSTALL = "ELECTRICAL_INSTALL"
    MECHANICAL_ROUGH = "MECHANICAL_ROUGH"
    PLUMBING_ROUGH = "PLUMBING_ROUGH"
    SPRINKLER_MAIN = "SPRINKLER_MAIN"
    DRYWALL_CLOSEOUT = "DRYWALL_CLOSEOUT"


class ActivityStatus(str, Enum):
    PLANNED = "PLANNED"
    PERMITTED = "PERMITTED"
    ACTIVE = "ACTIVE"
    DISALLOWED = "DISALLOWED"
    COMPLETE = "COMPLETE"


class RevisionStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    SUPERSEDED = "SUPERSEDED"


class RevisionKind(str, Enum):
    DESIGN_CHANGE = "DESIGN_CHANGE"
    RFI_RESPONSE = "RFI_RESPONSE"
    CLASH_RESOLUTION = "CLASH_RESOLUTION"
    OWNER_DIRECTIVE = "OWNER_DIRECTIVE"


class ReworkJobStatus(str, Enum):
    OPEN = "OPEN"
    IN_PROGRESS = "IN_PROGRESS"
    CLOSED = "CLOSED"
    RECUT_DEFERRED = "RECUT_DEFERRED"


class MaterialReleaseStatus(str, Enum):
    PLANNED = "PLANNED"
    RELEASED = "RELEASED"
    SHIPPED = "SHIPPED"
    RECEIVED = "RECEIVED"
    RESTRICTED = "RESTRICTED"


class MaterialCommodity(str, Enum):
    MC_CABLE = "MC_CABLE"
    EMT_CONDUIT = "EMT_CONDUIT"
    RIGID_CONDUIT = "RIGID_CONDUIT"
    STRUT = "STRUT"
    FITTINGS = "FITTINGS"
    SWITCHGEAR = "SWITCHGEAR"
    WIRE = "WIRE"
    BOX = "BOX"


class Project(TypedDict, total=False):
    id: str
    project_code: str
    project_name: str
    jurisdiction_key: str
    power_on_iso: str
    laydown_slots: int
    credit_policy: str
    posture_thresholds: dict
    shop_utilization_pct: float
    released_quantity: float
    total_quantity: float
    project_posture: str
    slippage_pct: float
    installed_pct: float
    pipeline_value_cents: float
    completed_value_cents: float
    man_hours_total: float
    apprentice_ratio_max: float
    effective_flow_pct: float
    approved_change_value_cents: float
    apprentice_breach_flag: bool
    external_gate_open: bool
    fabrication_locked: bool
    fabricated_revision_active: bool
    craft_hours_credit: float
    craft_hours_balance: float
    idle_capacity_cents: float
    created_at: str
    updated_at: str
    version: int


class Worker(TypedDict, total=False):
    id: str
    worker_code: str
    full_name: str
    classification: str
    apprentice_period: Optional[int]
    home_jurisdiction_key: str
    qualification_state_code: str
    shift_band_delta: int
    safety_verified_status: str
    journey_ring_claim_hours: float
    upgrade_eligible: bool
    credited_field_hours: float
    created_at: str
    updated_at: str
    version: int


class TradeContractRate(TypedDict, total=False):
    id: str
    jurisdiction_key: str
    classification: str
    apprentice_period: Optional[int]
    hourly_rate_cents: float
    burden_pct: float
    apprentice_ratio_max: float
    wait_ratio_max: float
    effective_from_iso: str
    created_at: str
    updated_at: str
    version: int


class TradeActivity(TypedDict, total=False):
    id: str
    project_id: str
    trade_key: str
    activity_kind: str
    work_front_code: str
    bay_code: str
    written_sequence_index: int
    planned_start_iso: str
    planned_duration_days: int
    revision_id: Optional[str]
    rate_id: Optional[str]
    permit_id: Optional[str]
    status: str
    suspension_reason: Optional[str]
    actual_start_iso: Optional[str]
    craft_hours_credit: float
    rework_trade_value_cents: float
    created_at: str
    updated_at: str
    version: int


class CrewDay(TypedDict, total=False):
    id: str
    project_id: str
    worker_id: str
    foreman_id: str
    trade_activity_id: str
    work_date_iso: str
    regular_hours: float
    overtime_hours: float
    report_sequence: int
    acknowledge_mode: str
    accepted_for_credit: bool
    guilt_added: bool
    credited_hours: float
    labor_cost_cents: float
    adjusted_value_cents: float
    apprentice_hours: float
    journeyman_hours: float
    created_at: str
    updated_at: str
    version: int


class ComplianceLedger(TypedDict, total=False):
    id: str
    project_id: str
    worker_id: str
    trade_activity_id: str
    rate_id: str
    jurisdiction_key: str
    classification: str
    regular_hours: float
    overtime_hours: float
    pay_rate_cents: float
    burden_pct: float
    projected_ratio: float
    total_cents: float
    certified_hours: float
    ledger_credit_cents: float
    gross_payroll_cents: float
    adjusted_payroll_cents: float
    apprentice_hours: float
    journeyman_hours: float
    ratio_limit: float
    wait_ratio_limit: float
    excess_apprentice_hours: float
    adjustment_delta_hours: float
    created_at: str
    updated_at: str
    version: int


class ModelVersion(TypedDict, total=False):
    id: str
    model_id: str
    revision_letter: str
    status: str
    zone_quantity_total: float
    assembly_quantity_total: dict
    empty_takeoff: bool
    coordinated_at_iso: Optional[str]
    created_at: str
    updated_at: str
    version: int


class TakeoffLine(TypedDict, total=False):
    id: str
    model_version_id: str
    zone_code: str
    assembly_code: str
    conduit_run_type: str
    conduit_run_type_code: str
    quantity: float
    prefab_share_pct: float
    takeoff_hash: str
    created_at: str
    updated_at: str
    version: int


class Rack(TypedDict, total=False):
    id: str
    model_version_id: str
    rack_code: str
    zone_code: str
    top_elevation_ft: float
    rack_hoist_date: str
    value_capacity_cf: float
    direct_assignment: bool
    ordering_strength_rule: str
    reserved_streams_and_phase_cf: float
    created_at: str
    updated_at: str
    version: int


class PrefabOrder(TypedDict, total=False):
    id: str
    project_id: str
    model_version_id: str
    stage_code: str
    zone_code: str
    fabricate_status: str
    deliver_status: str
    shipment_status: str
    transport_kind: str
    hoisting_window_id: str
    required_on_site_iso: str
    installation_window_start_iso: str
    fabricate_quantity: float
    shop_utilisation_basis_pct: float
    release_to_shop_iso: Optional[str]
    releasable_status: str
    laydown_slot_index: Optional[int]
    rework_order_count: int
    assembly_count: int
    crafted_hours_total: float
    crafted_hours_credit: float
    rework_hours: float
    hoisting_duration_days: int
    hoisting_start_iso: Optional[str]
    hoisting_end_iso: Optional[str]
    planned_delivery_iso: Optional[str]
    fabrication_utilisation_pct: float
    created_at: str
    updated_at: str
    version: int


class PrefabComponent(TypedDict, total=False):
    id: str
    prefab_order_id: str
    rack_id: Optional[str]
    takeoff_line_id: str
    predecessor_component_id: Optional[str]
    assembly_code: str
    quantity: float
    install_status: str
    chain_mode: str
    chain_dependency_link: str
    crafted_hours: float
    prefab_value_cents: float
    contractual_credit_cents: float
    created_at: str
    updated_at: str
    version: int


class Revision(TypedDict, total=False):
    id: str
    project_id: str
    model_version_id: str
    revised_version_id: str
    revision_kind: str
    status: str
    revision_number: str
    impact_keys: List[str]
    impact_values: List[dict]
    replacement_lifecycle_percent: float
    prior_lifecycle_percent: float
    label_codes: List[str]
    fabricated_content_codes: List[str]
    label_percentage: Optional[float]
    safety_gate_status: str
    affects_fabricated_content: bool
    engineering_hold: bool
    approved_change_value_cents: float
    required_actions: List[str]
    created_at: str
    updated_at: str
    version: int


class ReworkJob(TypedDict, total=False):
    id: str
    project_id: str
    prefab_component_id: str
    revision_id: str
    impact_key: str
    reason_code: str
    reason_question_code: str
    reason_option_code: str
    confirmation_mode: str
    confirmation_mode_effective: str
    scheduled_start_iso: str
    rework_hours: float
    status: str
    created_at: str
    updated_at: str
    version: int


class MaterialRelease(TypedDict, total=False):
    id: str
    project_id: str
    model_version_id: str
    vendor_key: str
    material_commodity: str
    quantity: float
    unit_price_cents: float
    lead_time_days: int
    service_priority: str
    commitment_mode: str
    planned_release_iso: str
    receiving_user_id: str
    status: str
    locked_release_iso: Optional[str]
    priced_hours: float
    list_value_cents: float
    ship_cost_cents: float
    value_cents: float
    declared_for_procurement: bool
    restriction_since_iso: Optional[str]
    created_at: str
    updated_at: str
    version: int