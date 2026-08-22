"""Domain types for the Modular Space Leasing API: entity shapes, status enums, roles."""
from enum import Enum
from typing import List, Optional, TypedDict


# ─── Roles (PRD §2.1) ────────────────────────────────────────────────────────

class UserRole(str, Enum):
    FLEET_ADMIN = "FleetAdmin"
    BRANCH_OPS = "BranchOps"
    LEASING_AGENT = "LeasingAgent"
    DAMAGE_ASSESSOR = "DamageAssessor"
    CUSTOMER = "Customer"


# ─── Status enums ────────────────────────────────────────────────────────────

class BranchStatus(str, Enum):
    OPERATIONAL = "OPERATIONAL"
    SUSPENDED = "SUSPENDED"


class AnchoringStandard(str, Enum):
    NONE = "NONE"
    GROUND_ANCHOR = "GROUND_ANCHOR"
    PIER_FOUNDATION = "PIER_FOUNDATION"
    ENGINEERED_SLAB = "ENGINEERED_SLAB"


class ConfigurationStatus(str, Enum):
    DRAFT = "DRAFT"
    PUBLISHED = "PUBLISHED"


class UnitStatus(str, Enum):
    IN_FLEET = "IN_FLEET"
    RESERVED = "RESERVED"
    IN_TRANSIT = "IN_TRANSIT"
    ON_LEASE = "ON_LEASE"
    RETURNED = "RETURNED"
    REFURBISHING = "REFURBISHING"


class ConditionGrade(str, Enum):
    A = "A"
    B = "B"
    C = "C"
    D = "D"


class CreditTier(str, Enum):
    PLATINUM = "PLATINUM"
    GOLD = "GOLD"
    STANDARD = "STANDARD"
    WATCH = "WATCH"


class OccupancyStatus(str, Enum):
    PENDING = "PENDING"
    INSTALLED = "INSTALLED"
    VACATED = "VACATED"
    CANCELLED = "CANCELLED"


class BillingStatus(str, Enum):
    UNBILLED = "UNBILLED"
    ACCRUING = "ACCRUING"
    SETTLED = "SETTLED"
    VOIDED = "VOIDED"


class PackageType(str, Enum):
    STEPS = "STEPS"
    RAMP_ADA = "RAMP_ADA"
    COMBO = "COMBO"


class ComplianceStatus(str, Enum):
    COMPLIANT = "COMPLIANT"
    NON_COMPLIANT = "NON_COMPLIANT"


class PermitStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


class JobType(str, Enum):
    DELIVERY_INSTALL = "DELIVERY_INSTALL"
    TEARDOWN_RETURN = "TEARDOWN_RETURN"
    RELOCATION = "RELOCATION"


class JobStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    DISPATCHED = "DISPATCHED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class AssessmentStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    DISPUTED = "DISPUTED"
    FINALIZED = "FINALIZED"
    SUPERSEDED = "SUPERSEDED"


class DamageComponent(str, Enum):
    FLOOR = "FLOOR"
    WALL = "WALL"
    HVAC = "HVAC"
    ROOF = "ROOF"
    DOOR = "DOOR"
    ELECTRICAL = "ELECTRICAL"


class DamageSeverity(str, Enum):
    MINOR = "MINOR"
    MODERATE = "MODERATE"
    SEVERE = "SEVERE"


class RefurbishmentScope(str, Enum):
    COSMETIC = "COSMETIC"
    STANDARD = "STANDARD"
    FULL = "FULL"


class RefurbishmentStatus(str, Enum):
    QUOTED = "QUOTED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    COMPLETED = "COMPLETED"
    SUPERSEDED = "SUPERSEDED"


# ─── Entity shapes ───────────────────────────────────────────────────────────
# Every top-level resource carries id / created_at / updated_at / version
# (PRD §2.4). The damage line item is the one exception: it is append-only and
# carries only id and created_at.

class Branch(TypedDict):
    id: str
    name: str
    region_code: str
    yard_capacity_units: int
    daily_dispatch_capacity: int
    labor_rate_cents_per_hour: int
    status: str
    units_in_yard: int
    units_available: int
    utilization_pct: float
    created_at: str
    updated_at: str
    version: int


class Jurisdiction(TypedDict):
    id: str
    code: str
    name: str
    permit_required: bool
    permit_lead_days: int
    anchoring_standard: str
    wind_zone: int
    permit_fee_cents: int
    ada_ramp_required: bool
    min_ramp_run_ratio: float
    created_at: str
    updated_at: str
    version: int


class BuildingSpec(TypedDict):
    id: str
    model_code: str
    width_ft: float
    length_ft: float
    sections: int
    floor_height_in: float
    base_monthly_rate_cents: int
    delivery_base_cents: int
    install_base_cents: int
    replacement_value_cents: int
    max_occupancy: int
    floor_area_sqft: float
    created_at: str
    updated_at: str
    version: int


class FloorplanConfiguration(TypedDict):
    id: str
    building_spec_id: str
    name: str
    private_offices: int
    restrooms: int
    partition_linear_ft: float
    hvac_tons: float
    config_surcharge_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Unit(TypedDict):
    id: str
    serial_number: str
    building_spec_id: str
    current_branch_id: str
    installed_config_id: Optional[str]
    status: str
    condition_grade: str
    lifetime_relocations: int
    refurb_cycles: int
    accumulated_damage_cents: int
    latest_quote_estimate_cents: int
    created_at: str
    updated_at: str
    version: int


class Customer(TypedDict):
    id: str
    name: str
    billing_email: str
    credit_tier: str
    credit_limit_cents: int
    outstanding_balance_cents: int
    credit_hold: bool
    created_at: str
    updated_at: str
    version: int


class Lease(TypedDict):
    id: str
    customer_id: str
    unit_id: str
    jurisdiction_id: str
    floorplan_configuration_id: str
    extends_lease_id: Optional[str]
    site_address: str
    start_date: str
    term_months: int
    end_date: str
    occupancy_status: str
    billing_status: str
    pinned_credit_tier: str
    monthly_base_rate_cents: int
    monthly_accessory_rate_cents: int
    mobilization_fee_cents: int
    quoted_total_cents: int
    final_settlement_cents: Optional[int]
    relocation_surcharge_cents: int
    billed_to_date_cents: int
    credited_cents: int
    actual_vacated_date: Optional[str]
    assessment_round: int
    created_at: str
    updated_at: str
    version: int


class AccessoryPackage(TypedDict):
    id: str
    lease_id: str
    package_type: str
    ramp_run_ft: float
    landing_count: int
    step_count: int
    monthly_accessory_rate_cents: int
    compliance_status: str
    created_at: str
    updated_at: str
    version: int


class PermitApplication(TypedDict):
    id: str
    lease_id: str
    jurisdiction_id: str
    foundation_type: str
    status: str
    permit_fee_cents: int
    submitted_on: Optional[str]
    decided_on: Optional[str]
    reviewer_note: Optional[str]
    created_at: str
    updated_at: str
    version: int


class LogisticsJob(TypedDict):
    id: str
    lease_id: str
    unit_id: str
    origin_branch_id: str
    destination_branch_id: Optional[str]
    job_type: str
    scheduled_date: str
    mileage_miles: float
    crew_hours: float
    new_site_address: Optional[str]
    status: str
    transport_cost_cents: int
    created_at: str
    updated_at: str
    version: int


class DamageAssessment(TypedDict):
    id: str
    unit_id: str
    lease_id: str
    logistics_job_id: str
    assessor_user_id: str
    status: str
    dispute_rounds: int
    condition_grade_before: str
    condition_grade_after: Optional[str]
    gross_damage_cents: int
    wear_allowance_cents: int
    chargeable_cents: int
    dispute_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class DamageLineItem(TypedDict):
    """Append-only audit record — carries only id and created_at (PRD §2.4)."""
    id: str
    damage_assessment_id: str
    component: str
    severity: str
    quantity: float
    wear_and_tear: bool
    repair_cost_cents: int
    created_at: str


class RefurbishmentOrder(TypedDict):
    id: str
    unit_id: str
    branch_id: str
    damage_assessment_id: str
    scope: str
    labor_hours: float
    parts_cost_cents: int
    target_condition_grade: str
    estimated_cost_cents: int
    actual_cost_cents: Optional[int]
    status: str
    approved_by_user_id: Optional[str]
    rejection_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


YARD_STATUSES: List[str] = [
    UnitStatus.IN_FLEET.value,
    UnitStatus.RESERVED.value,
    UnitStatus.RETURNED.value,
    UnitStatus.REFURBISHING.value,
]

OFF_YARD_STATUSES: List[str] = [
    UnitStatus.IN_TRANSIT.value,
    UnitStatus.ON_LEASE.value,
]
