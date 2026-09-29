"""Domain types for the structured-cabling contracting API.

Entity TypedDicts, status enums and the crew-role enum, all named exactly as the
PRD names them.
"""
from enum import Enum
from typing import List, Optional, TypedDict


# ─── Roles ────────────────────────────────────────────────────────────────────

class UserRole(str, Enum):
    PROJECT_MANAGER = "ProjectManager"
    DESIGN_ENGINEER = "DesignEngineer"
    INSTALLER = "Installer"
    TEST_TECHNICIAN = "TestTechnician"
    CERTIFIER = "Certifier"
    MANUFACTURER_AGENT = "ManufacturerAgent"
    CLIENT = "Client"


ALL_ROLES = [r.value for r in UserRole]


# ─── Enumerated domains ───────────────────────────────────────────────────────

class OccupancyStatus(str, Enum):
    PRE_OCCUPANCY = "PRE_OCCUPANCY"
    OCCUPIED = "OCCUPIED"


class WarrantyStatus(str, Enum):
    NOT_ELIGIBLE = "NOT_ELIGIBLE"
    ELIGIBLE = "ELIGIBLE"
    SUBMITTED = "SUBMITTED"
    REGISTERED = "REGISTERED"
    REJECTED = "REJECTED"
    REVOKED = "REVOKED"


class WarrantyProgram(str, Enum):
    NONE = "NONE"
    STANDARD_15Y = "STANDARD_15Y"
    EXTENDED_25Y = "EXTENDED_25Y"


class ManufacturerProgram(str, Enum):
    """The programmes a registration may actually apply for.

    The project-level warranty_program records an intention and may be NONE; a
    registration must name one of the two real programmes.
    """

    STANDARD_15Y = "STANDARD_15Y"
    EXTENDED_25Y = "EXTENDED_25Y"


class IdentifierScheme(str, Enum):
    TIA_606_CLASS_1 = "TIA_606_CLASS_1"
    TIA_606_CLASS_2 = "TIA_606_CLASS_2"


class RoomState(str, Enum):
    ROUGH_IN = "ROUGH_IN"
    GROUNDED = "GROUNDED"
    ENERGIZED = "ENERGIZED"


class GroundingStatus(str, Enum):
    UNVERIFIED = "UNVERIFIED"
    COMPLIANT = "COMPLIANT"
    NON_COMPLIANT = "NON_COMPLIANT"


class AssignmentState(str, Enum):
    ACTIVE = "ACTIVE"
    RELEASED = "RELEASED"


class PathwayType(str, Enum):
    CABLE_TRAY = "CABLE_TRAY"
    EMT_CONDUIT = "EMT_CONDUIT"
    INNERDUCT = "INNERDUCT"
    J_HOOK = "J_HOOK"


class PathwayState(str, Enum):
    SERVICEABLE = "SERVICEABLE"
    CONDEMNED = "CONDEMNED"


class CableCategory(str, Enum):
    CAT5E = "CAT5E"
    CAT6 = "CAT6"
    CAT6A = "CAT6A"
    OM4_MMF = "OM4_MMF"
    OS2_SMF = "OS2_SMF"
    COAX_RG6 = "COAX_RG6"


class JacketRating(str, Enum):
    CM = "CM"
    CMR = "CMR"
    CMP = "CMP"
    LSZH = "LSZH"


class Application(str, Enum):
    DATA_HORIZONTAL = "DATA_HORIZONTAL"
    BACKBONE = "BACKBONE"
    WAP = "WAP"
    CAMERA = "CAMERA"
    ACCESS_CONTROL = "ACCESS_CONTROL"
    AV_DISTRIBUTION = "AV_DISTRIBUTION"


class InstallState(str, Enum):
    DESIGNED = "DESIGNED"
    PULLED = "PULLED"
    TERMINATED = "TERMINATED"
    TESTED_PASS = "TESTED_PASS"
    TESTED_FAIL = "TESTED_FAIL"
    CERTIFIED = "CERTIFIED"


class RecordState(str, Enum):
    UNLABELED = "UNLABELED"
    LABELED = "LABELED"
    RECORDED = "RECORDED"


class RouteState(str, Enum):
    OCCUPYING = "OCCUPYING"
    WITHDRAWN = "WITHDRAWN"
    SUSPENDED = "SUSPENDED"


class TestStandard(str, Enum):
    PERMANENT_LINK = "PERMANENT_LINK"
    CHANNEL = "CHANNEL"


class TestOutcome(str, Enum):
    PASS = "PASS"
    PASS_ASTERISK = "PASS_ASTERISK"
    FAIL = "FAIL"


class FailureReason(str, Enum):
    LENGTH_LIMIT = "LENGTH_LIMIT"
    INSERTION_LOSS = "INSERTION_LOSS"
    MARGIN = "MARGIN"


class RegistrationState(str, Enum):
    DRAFT = "DRAFT"
    READY = "READY"
    SUBMITTED = "SUBMITTED"
    REGISTERED = "REGISTERED"
    REJECTED = "REJECTED"
    REVOKED = "REVOKED"


class WarrantyDecision(str, Enum):
    REGISTER = "REGISTER"
    REJECT = "REJECT"


class TicketState(str, Enum):
    SUBMITTED = "SUBMITTED"
    SCHEDULED = "SCHEDULED"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    REJECTED = "REJECTED"


class TicketType(str, Enum):
    MOVE = "MOVE"
    ADD = "ADD"
    CHANGE = "CHANGE"


class Trade(str, Enum):
    CEILING = "CEILING"
    ELECTRICAL = "ELECTRICAL"
    MECHANICAL = "MECHANICAL"
    FIRE_ALARM = "FIRE_ALARM"


class Milestone(str, Enum):
    PATHWAY_ROUGH_IN = "PATHWAY_ROUGH_IN"
    CEILING_CLOSE = "CEILING_CLOSE"
    POWER_ENERGIZE = "POWER_ENERGIZE"
    DUCT_CLOSE = "DUCT_CLOSE"


class CoordinationState(str, Enum):
    REQUESTED = "REQUESTED"
    CONFIRMED = "CONFIRMED"
    RELEASED = "RELEASED"
    BLOCKED = "BLOCKED"


# ─── Entity shapes ────────────────────────────────────────────────────────────
# Resources carrying the full common property set expose id, created_at,
# updated_at and version. The two immutable resource kinds — a cable type in the
# selection catalogue and a recorded field-test result — expose only id and
# created_at.

class CablingProject(TypedDict):
    id: str
    name: str
    site_code: str
    plenum_ceiling: bool
    identifier_scheme: str
    warranty_program: str
    mac_budget_cents: int
    occupancy_status: str
    total_link_count: int
    certified_link_count: int
    failed_link_count: int
    completeness_pct_strict: float
    completeness_pct_provisional: float
    warranty_status: str
    as_built_cost_cents: int
    consumed_mac_cents: int
    created_at: str
    updated_at: str
    version: int


class TelecomRoom(TypedDict):
    id: str
    project_id: str
    room_code: str
    floor: int
    branch_circuit_amps: int
    ups_capacity_va: int
    room_state: str
    tgb_installed: bool
    bonding_conductor_awg: Optional[int]
    ground_resistance_milliohms: Optional[float]
    grounding_status: str
    power_load_va: int
    power_headroom_va: int
    created_at: str
    updated_at: str
    version: int


class Rack(TypedDict):
    id: str
    telecom_room_id: str
    rack_code: str
    total_ru: int
    occupied_ru: int
    available_ru: int
    power_draw_va: int
    created_at: str
    updated_at: str
    version: int


class RackUnitAssignment(TypedDict):
    id: str
    rack_id: str
    equipment_label: str
    start_ru: int
    end_ru: int
    span_ru: int
    power_va: int
    assignment_state: str
    released_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class PathwaySegment(TypedDict):
    id: str
    project_id: str
    segment_code: str
    pathway_type: str
    usable_area_sq_mm: float
    length_m: float
    bend_count: int
    in_plenum_space: bool
    shared_with_power: bool
    power_separation_mm: int
    upstream_segment_id: Optional[str]
    pathway_depth: int
    occupying_route_count: int
    fill_area_used_sq_mm: float
    allowed_fill_pct: int
    fill_ratio: float
    pathway_state: str
    condemned_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class CableType(TypedDict):
    """Immutable catalogue row — carries neither updated_at nor version."""
    id: str
    category: str
    jacket_rating: str
    outer_diameter_mm: float
    cross_section_area_sq_mm: float
    max_channel_length_m: float
    shielded: bool
    cost_per_meter_cents: int
    applications: List[str]
    created_at: str


class Link(TypedDict):
    id: str
    project_id: str
    telecom_room_id: str
    cable_type_id: str
    identifier: str
    application: str
    horizontal_length_m: float
    consolidation_point_stub_m: float
    patch_cord_allowance_m: float
    permanent_link_length_m: float
    channel_length_m: float
    install_state: str
    record_state: str
    applied_identifier: Optional[str]
    drawing_sheet_ref: Optional[str]
    installer_user_id: Optional[str]
    certifier_user_id: Optional[str]
    routed_segment_count: int
    test_attempt_count: int
    latest_test_outcome: Optional[str]
    material_cost_cents: int
    created_at: str
    updated_at: str
    version: int


class LinkPathwayRoute(TypedDict):
    id: str
    link_id: str
    pathway_segment_id: str
    sequence_index: int
    consumed_area_sq_mm: float
    route_state: str
    created_at: str
    updated_at: str
    version: int


class TestResult(TypedDict):
    """Immutable measurement row — carries neither updated_at nor version."""
    id: str
    link_id: str
    test_standard: str
    tester_model: str
    insertion_loss_db: float
    insertion_loss_budget_db: float
    next_margin_db: float
    return_loss_margin_db: float
    worst_margin_db: float
    length_measured_m: float
    outcome: str
    failure_reason: Optional[str]
    tester_user_id: str
    recorded_at: str
    created_at: str


class WarrantyRegistration(TypedDict):
    id: str
    project_id: str
    manufacturer_program: str
    registration_state: str
    pinned_project_version: Optional[int]
    submitted_certified_link_count: Optional[int]
    coverage_years: Optional[int]
    registration_number: Optional[str]
    rejection_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class MacTicket(TypedDict):
    id: str
    project_id: str
    link_id: str
    telecom_room_id: str
    ticket_type: str
    requested_window_start: str
    requested_window_end: str
    scheduled_window_start: Optional[str]
    scheduled_window_end: Optional[str]
    labor_hours_estimate: float
    actual_labor_hours: Optional[float]
    expedite_requested: bool
    estimated_billed_cents: Optional[int]
    final_billed_cents: Optional[int]
    new_identifier: Optional[str]
    ticket_state: str
    rework_count: int
    created_at: str
    updated_at: str
    version: int


class TradeCoordination(TypedDict):
    id: str
    project_id: str
    trade: str
    milestone: str
    predecessor_coordination_id: Optional[str]
    confirmed_date: Optional[str]
    coordination_state: str
    block_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int
