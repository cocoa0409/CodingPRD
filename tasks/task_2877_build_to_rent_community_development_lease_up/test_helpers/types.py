"""Domain types for the Build-To-Rent Leaseup API: role enum, status enums, entity TypedDicts."""

from enum import Enum
from typing import List, Optional, TypedDict


class UserRole(str, Enum):
    DEVELOPER_PRINCIPAL = "DeveloperPrincipal"
    ENTITLEMENT_OFFICER = "EntitlementOfficer"
    CONSTRUCTION_MANAGER = "ConstructionManager"
    LEASING_AGENT = "LeasingAgent"
    ASSET_MANAGER = "AssetManager"
    PROPERTY_MANAGER = "PropertyManager"
    HOUSEHOLD = "Household"


class ProductType(str, Enum):
    DETACHED = "DETACHED"
    COTTAGE = "COTTAGE"
    TOWNHOME = "TOWNHOME"


class PlatStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    REVISION_REQUESTED = "REVISION_REQUESTED"
    REJECTED = "REJECTED"


class PlatDecision(str, Enum):
    APPROVE = "APPROVE"
    REQUEST_REVISION = "REQUEST_REVISION"
    REJECT = "REJECT"


class LifecycleStatus(str, Enum):
    PLANNING = "PLANNING"
    CONSTRUCTION = "CONSTRUCTION"
    LEASE_UP = "LEASE_UP"
    STABILIZED = "STABILIZED"


class ManagementMode(str, Enum):
    DEVELOPER_SELF_MANAGED = "DEVELOPER_SELF_MANAGED"
    PM_TRANSITION_PENDING = "PM_TRANSITION_PENDING"
    PM_MANAGED = "PM_MANAGED"


class FacilityStatus(str, Enum):
    CONSTRUCTION_DRAW = "CONSTRUCTION_DRAW"
    ADVANCE_ELIGIBLE = "ADVANCE_ELIGIBLE"
    CONVERSION_PENDING = "CONVERSION_PENDING"
    PERM_CONVERTED = "PERM_CONVERTED"


class Posture(str, Enum):
    OPEN = "OPEN"
    RESTRICTED = "RESTRICTED"
    FROZEN = "FROZEN"


class PhaseKind(str, Enum):
    HOUSING = "HOUSING"
    AMENITY = "AMENITY"


class PhaseStatus(str, Enum):
    PLANNED = "PLANNED"
    UNDER_CONSTRUCTION = "UNDER_CONSTRUCTION"
    SECTIONS_RELEASED = "SECTIONS_RELEASED"
    CONSTRUCTION_HALTED = "CONSTRUCTION_HALTED"
    COMPLETE = "COMPLETE"


class HomesiteStatus(str, Enum):
    PLANNED = "PLANNED"
    AVAILABLE = "AVAILABLE"
    LEASED = "LEASED"
    NOTICE_GIVEN = "NOTICE_GIVEN"
    IN_TURN = "IN_TURN"
    OFF_MARKET = "OFF_MARKET"


class OffMarketReason(str, Enum):
    POSTURE_FREEZE = "POSTURE_FREEZE"


class ScheduleStatus(str, Enum):
    PUBLISHED = "PUBLISHED"
    SUPERSEDED = "SUPERSEDED"


class RepricingMode(str, Enum):
    MANUAL = "MANUAL"
    ABSORPTION_INDEXED = "ABSORPTION_INDEXED"


class ConcessionProgramStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUPERSEDED = "SUPERSEDED"


class ConcessionTier(str, Enum):
    NONE = "NONE"
    LIGHT = "LIGHT"
    MODERATE = "MODERATE"
    AGGRESSIVE = "AGGRESSIVE"


class AmortizationMode(str, Enum):
    STRAIGHT_LINE_NET_EFFECTIVE = "STRAIGHT_LINE_NET_EFFECTIVE"
    UPFRONT_FREE_RENT = "UPFRONT_FREE_RENT"


class CreditTier(str, Enum):
    A = "A"
    B = "B"
    C = "C"


class LeaseStatus(str, Enum):
    DRAFT = "DRAFT"
    PENDING_SIGNATURE = "PENDING_SIGNATURE"
    EXECUTED = "EXECUTED"
    ACTIVE = "ACTIVE"
    ENDING = "ENDING"
    ENDED = "ENDED"
    CANCELLED = "CANCELLED"


class ConcessionStatus(str, Enum):
    NONE = "NONE"
    REQUESTED = "REQUESTED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    AMORTIZING = "AMORTIZING"
    EXHAUSTED = "EXHAUSTED"
    REVOKED = "REVOKED"


class ConcessionDecision(str, Enum):
    APPROVE = "APPROVE"
    REJECT = "REJECT"


class CancellationReason(str, Enum):
    POSTURE_FREEZE = "POSTURE_FREEZE"
    APPLICANT_WITHDREW = "APPLICANT_WITHDREW"
    OPERATOR_CANCELLED = "OPERATOR_CANCELLED"


class TurnScope(str, Enum):
    MAKE_READY = "MAKE_READY"
    DETACHED_YARD_RESTORE = "DETACHED_YARD_RESTORE"
    MAJOR_REHAB = "MAJOR_REHAB"


class TurnStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    COMPLETED = "COMPLETED"


class ValuationBasis(str, Enum):
    TRAILING_ACTUAL = "TRAILING_ACTUAL"
    FORWARD_STABILIZED = "FORWARD_STABILIZED"


# --- Entities carrying id + created_at + updated_at + version ---


class Community(TypedDict):
    id: str
    name: str
    market_code: str
    total_planned_units: int
    product_mix: dict
    concession_budget_cents: int
    facility_commitment_cents: int
    maintenance_tech_headcount: int
    single_ownership_covenant: bool
    plat_status: str
    plat_revision_round: int
    plat_submitted_by_user_id: Optional[str]
    plat_package_reference: Optional[str]
    lifecycle_status: str
    management_mode: str
    pm_company_name: Optional[str]
    pm_effective_from: Optional[str]
    facility_status: str
    posture: str
    released_unit_count: int
    available_unit_count: int
    leased_unit_count: int
    occupancy_ratio: float
    amenity_delivery_ratio: float
    committed_concession_cents: int
    construction_impact_credit_cents: int
    created_at: str
    updated_at: str
    version: int


class Phase(TypedDict):
    id: str
    community_id: str
    sequence_index: int
    kind: str
    planned_unit_count: int
    amenity_weight: int
    construction_window_start: str
    construction_window_end: str
    predecessor_phase_id: Optional[str]
    status: str
    halt_count: int
    pre_halt_status: Optional[str]
    released_homesite_count: int
    leased_homesite_count: int
    created_at: str
    updated_at: str
    version: int


class Homesite(TypedDict):
    id: str
    phase_id: str
    lot_number: str
    product_type: str
    bedrooms: int
    square_feet: int
    status: str
    off_market_reason: Optional[str]
    occupancy_certificate_number: Optional[str]
    occupancy_certificate_issued_at: Optional[str]
    released_at: Optional[str]
    last_turn_ready_at: Optional[str]
    turn_cycle_count: int
    created_at: str
    updated_at: str
    version: int


class MarketRentSchedule(TypedDict):
    id: str
    community_id: str
    product_type: str
    effective_from: str
    repricing_mode: str
    asking_rent_cents: int
    applied_growth_bps: int
    status: str
    superseded_at: Optional[str]
    published_by_user_id: str
    created_at: str
    updated_at: str
    version: int


class ConcessionProgram(TypedDict):
    id: str
    community_id: str
    program_code: str
    tier: str
    free_weeks: int
    amortization_mode: str
    eligible_product_types: List[str]
    restricted_posture_eligible: bool
    max_budget_cents: int
    committed_cents: int
    status: str
    superseded_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Household(TypedDict):
    id: str
    primary_applicant_name: str
    email: str
    household_size: int
    monthly_income_cents: int
    credit_tier: str
    active_lease_count: int
    created_at: str
    updated_at: str
    version: int


class Lease(TypedDict):
    id: str
    homesite_id: str
    household_id: str
    term_months: int
    start_date: str
    end_date: str
    base_rent_cents: int
    priced_by_schedule_id: str
    community_services_fee_cents: int
    gross_monthly_charge_cents: int
    lease_status: str
    concession_status: str
    concession_program_id: Optional[str]
    concession_requested_by_user_id: Optional[str]
    concession_decided_by_user_id: Optional[str]
    concession_schedule: List[dict]
    total_concession_cents: int
    monthly_concession_credit_cents: int
    first_period_charge_cents: int
    net_effective_rent_cents: int
    concession_applied_cents: int
    concession_remaining_cents: int
    credits_applied_count: int
    construction_impact_credit_cents: int
    cancellation_reason: Optional[str]
    signed_by_name: Optional[str]
    executed_at: Optional[str]
    notice_date: Optional[str]
    move_out_date: Optional[str]
    created_at: str
    updated_at: str
    version: int


class TurnWorkOrder(TypedDict):
    id: str
    homesite_id: str
    window_start: str
    window_end: str
    window_hours: int
    scope: str
    tech_count: int
    material_cost_cents: int
    labor_cost_cents: int
    total_turn_cost_cents: int
    tenant_recoverable_cents: int
    community_opex_cents: int
    capital_reserve_cents: int
    status: str
    completed_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


# --- Immutable snapshot: carries ONLY id + created_at (PRD §2.4) ---


class AbsorptionReview(TypedDict):
    id: str
    community_id: str
    product_type: str
    window_start: str
    window_end: str
    planned_absorption_units: int
    actual_absorption_units: int
    available_supply_units: int
    posture_at_review: str
    pacing_index: float
    concession_tier: str
    recommended_growth_bps: int
    created_by_user_id: str
    created_at: str


class Valuation(TypedDict):
    basis: str
    in_place_monthly_cents: int
    pro_forma_monthly_cents: int
    annual_gross_cents: int
    vacancy_deduction_cents: int
    egi_cents: int
    opex_cents: int
    noi_cents: int
    value_cents: int
    loan_to_value_bps: int
    covenant_satisfied: bool
