"""Domain types for the accelerator allocation API: status enums, role enum, entity shapes.

Every entity in this system declares the full common-field set, so `updated_at` and
`version` are present on all of them.
"""
from enum import Enum
from typing import List, Optional, TypedDict


class UserRole(str, Enum):
    PLATFORM_ADMIN = "PlatformAdmin"
    SUPPLY_PLANNER = "SupplyPlanner"
    PARTNER_PROGRAM_MANAGER = "PartnerProgramManager"
    PARTNER_OPS = "PartnerOps"
    SUPPORT_ACCOUNT_MANAGER = "SupportAccountManager"
    SUPPLY_COMPLIANCE_OFFICER = "SupplyComplianceOfficer"
    LIFECYCLE_PROGRAM_MANAGER = "LifecycleProgramManager"


class PartnerType(str, Enum):
    CLOUD_PROVIDER = "CLOUD_PROVIDER"
    SYSTEM_BUILDER = "SYSTEM_BUILDER"
    ENTERPRISE_OEM = "ENTERPRISE_OEM"
    EMBEDDED_VENDOR = "EMBEDDED_VENDOR"
    DIRECT_ENTERPRISE = "DIRECT_ENTERPRISE"


class QualificationStatus(str, Enum):
    APPLIED = "APPLIED"
    IN_VALIDATION = "IN_VALIDATION"
    QUALIFIED = "QUALIFIED"
    REJECTED = "REJECTED"


class PartnerStanding(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    TERMINATED = "TERMINATED"


class PriorityClass(str, Enum):
    TIER_1 = "TIER_1"
    TIER_2 = "TIER_2"
    TIER_3 = "TIER_3"
    UNQUALIFIED = "UNQUALIFIED"


class ProductFamily(str, Enum):
    DATACENTER = "DATACENTER"
    WORKSTATION = "WORKSTATION"
    EMBEDDED = "EMBEDDED"
    CONSUMER = "CONSUMER"


class LifecycleStage(str, Enum):
    PREVIEW = "PREVIEW"
    GENERAL_AVAILABILITY = "GENERAL_AVAILABILITY"
    MATURE = "MATURE"
    END_OF_LIFE = "END_OF_LIFE"


class SupplyNodeStage(str, Enum):
    OPEN = "OPEN"
    FRICTION_HOLD = "FRICTION_HOLD"
    DRAINING = "DRAINING"
    BINDING = "BINDING"


class HotnessTier(str, Enum):
    COOL = "COOL"
    WARM = "WARM"
    HOT = "HOT"
    SCALDING = "SCALDING"


class HoldState(str, Enum):
    REQUESTED = "REQUESTED"
    COMMITTED = "COMMITTED"
    CANCELLED = "CANCELLED"
    RECLAIMED = "RECLAIMED"
    EXPIRED = "EXPIRED"


class ForecastTrackingStatus(str, Enum):
    DRAFT = "DRAFT"
    FORECAST_SUBMITTED = "FORECAST_SUBMITTED"
    ACTIVE = "ACTIVE"
    COMMITTED = "COMMITTED"
    CANCELLED = "CANCELLED"


class HorizonBand(str, Enum):
    SHORT = "SHORT"
    MEDIUM = "MEDIUM"
    LONG = "LONG"


class DeploymentState(str, Enum):
    PENDING = "PENDING"
    ACTIVATED = "ACTIVATED"
    TERMINATED = "TERMINATED"


class SubscriptionStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    RECLAIMED = "RECLAIMED"
    EXPIRED = "EXPIRED"


class LoanState(str, Enum):
    REQUESTED = "REQUESTED"
    APPROVED = "APPROVED"
    ACTIVE = "ACTIVE"
    RETURNED = "RETURNED"
    RECLAIMED = "RECLAIMED"
    OVERDUE = "OVERDUE"


class StackLicenseState(str, Enum):
    DRAFT = "DRAFT"
    RELEASED = "RELEASED"
    RETIRED = "RETIRED"


class MembershipStatus(str, Enum):
    REQUESTED = "REQUESTED"
    UNDER_EVALUATION = "UNDER_EVALUATION"
    ACTIVE = "ACTIVE"
    LAPSED = "LAPSED"
    REVOKED = "REVOKED"


class MembershipTier(str, Enum):
    COMMUNITY = "COMMUNITY"
    REGISTERED = "REGISTERED"
    PREFERRED = "PREFERRED"
    ELITE = "ELITE"


class CommitmentStatus(str, Enum):
    REQUESTED = "REQUESTED"
    GRANTED = "GRANTED"
    DECLINED = "DECLINED"


class SupportTier(str, Enum):
    BASIC = "BASIC"
    BUSINESS = "BUSINESS"
    PREMIUM = "PREMIUM"
    ENTERPRISE = "ENTERPRISE"


# --- Entity shapes (response bodies) ---

class PartnerAccount(TypedDict, total=False):
    id: str
    legal_name: str
    partner_type: str
    destination_country: str
    origin_epoch_index: int
    export_restriction_tier: str
    qualification_status: str
    qualification_attempt_count: int
    allocation_priority_class: str
    entitlement_units_held: int
    capacity_ledger_net: int
    cancellation_forfeit_rate: float
    committed_volume_units: int
    lifecycle_floor_expires_at: Optional[str]
    eligibility_deadline_at: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class AcceleratorProduct(TypedDict, total=False):
    id: str
    sku_code: str
    product_family: str
    lifecycle_stage: str
    form_factor: str
    hbm_capacity_gb: int
    tdp_watts: int
    export_performance_density: int
    supply_ceiling_units: int
    reserved_evaluation_units: int
    allocated_units: int
    available_units: int
    long_term_availability_through: str
    lifecycle_min_remaining_days: int
    created_at: str
    updated_at: str
    version: int


class SupplyNode(TypedDict, total=False):
    id: str
    node_code: str
    product_sku_id: str
    node_region: str
    capacity_units: int
    held_units: int
    stage: str
    requested_hotness_tier: str
    hotness_tier: str
    temp_band_ceiling: str
    friction_penalty_score: float
    total_committed_rate: float
    committed_fee_cents: int
    created_at: str
    updated_at: str
    version: int


class AllocationHold(TypedDict, total=False):
    id: str
    partner_id: str
    product_sku_id: str
    supply_node_id: str
    hold_friction_tier: str
    quantity_units: int
    committed_rate_v2: float
    cancellation_forfeit_units: float
    economic_tag: str
    state: str
    expected_partner_version: int
    created_at: str
    updated_at: str
    version: int


class DemandForecast(TypedDict, total=False):
    id: str
    partner_id: str
    product_sku_id: str
    requested_quantity_units: int
    acknowledged_at: Optional[str]
    horizon_band: Optional[str]
    committed_quantity_units: int
    cancellation_notice_days: Optional[int]
    forfeit_rate: float
    tracking_status: str
    expected_partner_version: int
    created_at: str
    updated_at: str
    version: int


class EnterpriseSubscription(TypedDict, total=False):
    id: str
    partner_id: str
    deployment_id: str
    stack_license_id: str
    support_tier: str
    seat_count: int
    annual_fee_cents: int
    support_credit_units: int
    status: str
    billed_fee_cents: int
    settled_fee_cents: int
    created_at: str
    updated_at: str
    version: int


class HardwareDeployment(TypedDict, total=False):
    id: str
    product_sku_id: str
    partner_id: str
    destination_country_code: str
    export_classification: str
    stack_manifest: List[dict]
    activation_state: str
    bound_stack_ids: List[str]
    service_ready: bool
    termination_effect_units: int
    expected_product_version: int
    activation_actor_user_id: str
    created_at: str
    updated_at: str
    version: int


class SoftwareStackLicense(TypedDict, total=False):
    id: str
    license_code: str
    product_sku_id: str
    stack_name: str
    entitlement_units: int
    preview_stack_flag: bool
    license_state: str
    min_package_version: str
    bound_deployment_count: int
    created_at: str
    updated_at: str
    version: int


class EvaluationLoan(TypedDict, total=False):
    id: str
    product_sku_id: str
    partner_id: str
    blueprint_id: str
    loan_units: int
    loan_state: str
    required_return_at: Optional[str]
    late_fee_units: float
    expected_product_version: int
    created_at: str
    updated_at: str
    version: int


class LifecycleCommitment(TypedDict, total=False):
    id: str
    product_sku_id: str
    embedded_partner_id: str
    availability_through: str
    commitment_floor_days: int
    commitment_status: str
    covered_units: int
    expected_product_version: int
    created_at: str
    updated_at: str
    version: int


class SupplyContract(TypedDict, total=False):
    id: str
    partner_id: str
    product_sku_id: str
    start_month: str
    end_month: str
    contracted_units: int
    window_status: str
    created_at: str
    updated_at: str
    version: int


class ValidationEvidence(TypedDict, total=False):
    id: str
    partner_id: str
    blueprint_id: str
    validation_minutes: int
    evidence_pack_status: str
    test_count: int
    created_at: str
    updated_at: str
    version: int


class DeveloperProgramMembership(TypedDict, total=False):
    id: str
    partner_id: str
    requested_tier: str
    stored_tier: str
    preview_kit_units: int
    support_incidents_included: int
    evaluation_deadline_at: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class AllocationEpoch(TypedDict, total=False):
    id: str
    epoch_index: int
    opened_at: str
    half_life_next: str
    epoch_status: str
    created_at: str
    updated_at: str
    version: int