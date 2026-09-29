"""Domain types: role enum, status enums, value enums and entity TypedDicts.

Nine entity types carry the full audit triple (created_at, updated_at, version).
SpendTransaction is append-only and therefore carries only id and created_at.
"""

from enum import Enum
from typing import Optional, TypedDict


class UserRole(str, Enum):
    DEAN_OFFICE = "DeanOffice"
    DEPARTMENT_CHAIR = "DepartmentChair"
    DEAN = "Dean"
    FACILITIES_MANAGER = "FacilitiesManager"
    FACULTY = "Faculty"


# --- value enums -------------------------------------------------------------

class UnitType(str, Enum):
    COLLEGE = "COLLEGE"
    DEPARTMENT = "DEPARTMENT"
    DEAN_OFFICE = "DEAN_OFFICE"


class FacultyRank(str, Enum):
    ASSISTANT = "ASSISTANT"
    ASSOCIATE = "ASSOCIATE"
    FULL = "FULL"


class PackageKind(str, Enum):
    INITIAL = "INITIAL"
    RETENTION_COUNTEROFFER = "RETENTION_COUNTEROFFER"


class TrancheCategory(str, Enum):
    EQUIPMENT = "EQUIPMENT"
    PERSONNEL = "PERSONNEL"
    RENOVATION = "RENOVATION"
    DISCRETIONARY = "DISCRETIONARY"


class CarryforwardPolicy(str, Enum):
    NONE = "NONE"
    FULL = "FULL"
    CAPPED = "CAPPED"


class SpaceClass(str, Enum):
    WET = "WET"
    DRY = "DRY"
    COMPUTATIONAL = "COMPUTATIONAL"


class ScopeTier(str, Enum):
    COSMETIC = "COSMETIC"
    MODERATE = "MODERATE"
    GUT = "GUT"


class AppointmentType(str, Enum):
    LAB_MANAGER = "LAB_MANAGER"
    POSTDOC = "POSTDOC"
    GRAD_RA = "GRAD_RA"
    TECHNICIAN = "TECHNICIAN"


class DepartureIntent(str, Enum):
    DEPARTURE = "DEPARTURE"
    INTERNAL_TRANSFER = "INTERNAL_TRANSFER"
    OUTSIDE_OFFER = "OUTSIDE_OFFER"


class SettlementVariant(str, Enum):
    DEPARTURE_RECAPTURE = "DEPARTURE_RECAPTURE"
    INTERNAL_TRANSFER = "INTERNAL_TRANSFER"


class UtilityBlockReason(str, Enum):
    POWER = "POWER"
    CHILLED_WATER = "CHILLED_WATER"
    FUME_HOOD = "FUME_HOOD"
    FLOOR_LOAD = "FLOOR_LOAD"


class TransferDisposition(str, Enum):
    RETAINED_BY_UNIT = "RETAINED_BY_UNIT"
    TRANSFERRED_WITH_FACULTY = "TRANSFERRED_WITH_FACULTY"
    SURPLUSED = "SURPLUSED"


class SpendTransactionKind(str, Enum):
    ENCUMBRANCE = "ENCUMBRANCE"
    RELEASE = "RELEASE"
    DISBURSEMENT = "DISBURSEMENT"
    EXPIRY = "EXPIRY"
    CARRYFORWARD_OUT = "CARRYFORWARD_OUT"
    CARRYFORWARD_IN = "CARRYFORWARD_IN"
    RECAPTURE = "RECAPTURE"


class SpendSourceKind(str, Enum):
    EQUIPMENT_ORDER = "EQUIPMENT_ORDER"
    STAFF_APPOINTMENT = "STAFF_APPOINTMENT"
    RENOVATION_PROJECT = "RENOVATION_PROJECT"
    ROLLOVER = "ROLLOVER"
    SETTLEMENT = "SETTLEMENT"


# --- status enums ------------------------------------------------------------

class FacultyAppointmentStatus(str, Enum):
    CANDIDATE = "CANDIDATE"
    ACTIVE = "ACTIVE"
    DEPARTURE_NOTICE = "DEPARTURE_NOTICE"
    DEPARTED = "DEPARTED"
    TRANSFERRED_INTERNAL = "TRANSFERRED_INTERNAL"


class NegotiationStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    DEAN_REVIEW = "DEAN_REVIEW"
    COUNTERED = "COUNTERED"
    APPROVED = "APPROVED"
    ACTIVE = "ACTIVE"
    CLOSED_OUT = "CLOSED_OUT"
    SUPERSEDED = "SUPERSEDED"


class SpendStatus(str, Enum):
    NOT_YET_AVAILABLE = "NOT_YET_AVAILABLE"
    SPENDING = "SPENDING"
    FROZEN = "FROZEN"
    SETTLED = "SETTLED"


class TrancheStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    OPEN = "OPEN"
    OBLIGATED = "OBLIGATED"
    CARRIED_FORWARD = "CARRIED_FORWARD"
    EXPIRED = "EXPIRED"
    RECAPTURED = "RECAPTURED"


class LabSpaceStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    ASSIGNED = "ASSIGNED"
    UNDER_RENOVATION = "UNDER_RENOVATION"
    DECOMMISSIONED = "DECOMMISSIONED"


class SpaceAssignmentStatus(str, Enum):
    PROPOSED = "PROPOSED"
    ACTIVE = "ACTIVE"
    RELEASED = "RELEASED"
    WITHDRAWN = "WITHDRAWN"


class RenovationProjectStatus(str, Enum):
    SCOPING = "SCOPING"
    BID = "BID"
    AWARDED = "AWARDED"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class RenovationPhaseStatus(str, Enum):
    PENDING = "PENDING"
    ACTIVE = "ACTIVE"
    COMPLETE = "COMPLETE"


class EquipmentOrderStatus(str, Enum):
    REQUESTED = "REQUESTED"
    ORDERED = "ORDERED"
    DELIVERED = "DELIVERED"
    UTILITY_BLOCKED = "UTILITY_BLOCKED"
    INSTALLED = "INSTALLED"
    CANCELLED = "CANCELLED"


class StaffAppointmentStatus(str, Enum):
    PROPOSED = "PROPOSED"
    ACTIVE = "ACTIVE"
    ENDED = "ENDED"
    CANCELLED = "CANCELLED"


# --- entity TypedDicts -------------------------------------------------------

class FundingUnit(TypedDict):
    id: str
    name: str
    unit_type: str
    parent_unit_id: Optional[str]
    cost_share_pool_cents: int
    reserved_cents: int
    committed_cents: int
    disbursed_cents: int
    refunded_cents: int
    available_pool_cents: int
    created_at: str
    updated_at: str
    version: int


class Faculty(TypedDict):
    id: str
    full_name: str
    rank: str
    funding_unit_id: str
    planned_start_date: str
    appointment_status: str
    activated_on: Optional[str]
    retention_round: int
    departure_intent: Optional[str]
    departure_effective_on: Optional[str]
    target_funding_unit_id: Optional[str]
    separated_on: Optional[str]
    created_at: str
    updated_at: str
    version: int


class StartupPackage(TypedDict):
    id: str
    faculty_id: str
    package_kind: str
    superseded_package_id: Optional[str]
    department_unit_id: str
    college_unit_id: str
    dean_unit_id: str
    dept_share_pct: int
    college_share_pct: int
    dean_share_pct: int
    proposed_total_cents: int
    counter_total_cents: Optional[int]
    spend_deadline_on: str
    negotiation_status: str
    spend_status: str
    negotiation_round: int
    proposed_by_user_id: Optional[str]
    endorsed_by_user_id: Optional[str]
    approved_by_user_id: Optional[str]
    activated_on: Optional[str]
    closed_out_on: Optional[str]
    settlement_variant: Optional[str]
    recaptured_unspent_cents: int
    transferred_balance_cents: int
    college_holdback_cents: int
    total_committed_cents: int
    total_encumbered_cents: int
    total_disbursed_cents: int
    total_expired_cents: int
    total_recaptured_cents: int
    total_available_cents: int
    spend_down_ratio: float
    created_at: str
    updated_at: str
    version: int


class CommitmentTranche(TypedDict):
    id: str
    package_id: str
    category: str
    fiscal_year: int
    amount_cents: int
    available_on: str
    expires_on: str
    carryforward_policy: str
    carryforward_cap_pct: int
    status: str
    opened_on: Optional[str]
    available_balance_cents: int
    carried_in_cents: int
    carried_out_cents: int
    encumbered_cents: int
    disbursed_cents: int
    expired_cents: int
    recaptured_cents: int
    created_at: str
    updated_at: str
    version: int


class LabSpace(TypedDict):
    id: str
    building_code: str
    room_number: str
    net_sq_ft: int
    space_class: str
    power_kw_capacity: float
    chilled_water_available: bool
    fume_hood_count: int
    floor_load_psf: int
    status: str
    allocated_share_pct: int
    installed_power_kw: float
    installed_fume_hoods: int
    created_at: str
    updated_at: str
    version: int


class SpaceAssignment(TypedDict):
    id: str
    space_id: str
    faculty_id: str
    share_pct: int
    effective_from: str
    effective_to: Optional[str]
    status: str
    released_on: Optional[str]
    created_at: str
    updated_at: str
    version: int


class RenovationProject(TypedDict):
    id: str
    package_id: str
    space_id: str
    scope_tier: str
    estimate_cents: int
    status: str
    rescope_count: int
    awarded_cents: Optional[int]
    awarded_on: Optional[str]
    subsidy_estimate_cents: Optional[int]
    package_charge_estimate_cents: Optional[int]
    actual_total_cents: Optional[int]
    subsidy_final_cents: Optional[int]
    package_charge_final_cents: Optional[int]
    cost_variance_cents: Optional[int]
    completed_on: Optional[str]
    created_at: str
    updated_at: str
    version: int


class RenovationPhase(TypedDict):
    id: str
    project_id: str
    sequence_no: int
    name: str
    planned_start: str
    planned_end: str
    budget_cents: int
    status: str
    actual_cost_cents: Optional[int]
    actual_start: Optional[str]
    actual_end: Optional[str]
    created_at: str
    updated_at: str
    version: int


class EquipmentOrder(TypedDict):
    id: str
    package_id: str
    install_space_id: str
    vendor_name: str
    item_description: str
    quoted_cents: int
    lead_time_days: int
    required_power_kw: float
    requires_chilled_water: bool
    required_fume_hoods: int
    required_floor_load_psf: int
    status: str
    placed_on: Optional[str]
    expected_delivery_on: Optional[str]
    delivered_on: Optional[str]
    installed_on: Optional[str]
    utility_block_reason: Optional[str]
    transfer_disposition: Optional[str]
    encumbered_cents: int
    disbursed_cents: int
    created_at: str
    updated_at: str
    version: int


class StaffAppointment(TypedDict):
    id: str
    package_id: str
    appointment_type: str
    fte: float
    monthly_cost_cents: int
    start_date: str
    end_date: str
    committed_months: int
    status: str
    encumbered_cents: int
    disbursed_cents: int
    ended_on: Optional[str]
    created_at: str
    updated_at: str
    version: int


class SpendTransaction(TypedDict):
    """Append-only ledger row: carries only id and created_at from the audit
    triple. updated_at and version are deliberately absent."""
    id: str
    package_id: str
    tranche_id: str
    kind: str
    amount_cents: int
    dept_share_cents: int
    college_share_cents: int
    dean_share_cents: int
    source_kind: str
    source_id: Optional[str]
    reverses_transaction_id: Optional[str]
    memo: str
    created_at: str
