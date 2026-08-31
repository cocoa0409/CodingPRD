"""Domain types for the Lubricant Blending & Packaging API.

Entity TypedDicts, status enumerations and the role enumeration, all named with
the exact field names the PRD uses.
"""

from enum import Enum
from typing import List, Optional, TypedDict


# --------------------------------------------------------------------------
# Role enumeration (PRD 2.1 — the eight declared role names)
# --------------------------------------------------------------------------
class UserRole(str, Enum):
    PLATFORM_ADMIN = "PlatformAdmin"
    PRODUCT_MANAGER = "ProductManager"
    BLEND_OPERATOR = "BlendOperator"
    QC_TECHNICIAN = "QCTechnician"
    QUALITY_MANAGER = "QualityManager"
    COMPLIANCE_OFFICER = "ComplianceOfficer"
    SALES_REP = "SalesRep"
    CUSTOMER = "Customer"


# --------------------------------------------------------------------------
# Enumerations carried on entity fields
# --------------------------------------------------------------------------
class CustomerType(str, Enum):
    DISTRIBUTOR = "DISTRIBUTOR"
    FLEET = "FLEET"
    PRIVATE_LABEL = "PRIVATE_LABEL"
    INDUSTRIAL = "INDUSTRIAL"


class ContractTier(str, Enum):
    TIER_A = "TIER_A"
    TIER_B = "TIER_B"
    TIER_C = "TIER_C"


class TakebackAgreementStatus(str, Enum):
    NONE = "NONE"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class ComponentType(str, Enum):
    BASE_OIL = "BASE_OIL"
    VI_IMPROVER = "VI_IMPROVER"
    ADDITIVE_PACKAGE = "ADDITIVE_PACKAGE"
    DYE = "DYE"


class AdditiveFamily(str, Enum):
    NONE = "NONE"
    ZDDP_PCMO = "ZDDP_PCMO"
    LOW_SAPS = "LOW_SAPS"
    HDEO_API_CK4 = "HDEO_API_CK4"
    GEAR_EP = "GEAR_EP"
    FOOD_GRADE_H1 = "FOOD_GRADE_H1"


class BaseStockGroup(str, Enum):
    GROUP_I = "GROUP_I"
    GROUP_II = "GROUP_II"
    GROUP_III = "GROUP_III"
    GROUP_IV = "GROUP_IV"


class ComponentLotStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    QUARANTINED = "QUARANTINED"
    DEPLETED = "DEPLETED"


class ProductSpecStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    WITHDRAWN = "WITHDRAWN"


class BlendRecipeStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    RETIRED = "RETIRED"


class BlendTankStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    CHARGED = "CHARGED"
    QUARANTINED = "QUARANTINED"


class ProductionStatus(str, Enum):
    PLANNED = "PLANNED"
    CHARGING = "CHARGING"
    BLENDED = "BLENDED"
    RELEASED = "RELEASED"
    QUARANTINED = "QUARANTINED"
    REWORKED = "REWORKED"
    DISPOSED = "DISPOSED"


class QcStatus(str, Enum):
    PENDING = "PENDING"
    SAMPLED = "SAMPLED"
    PASSED = "PASSED"
    FAILED = "FAILED"
    WAIVED = "WAIVED"


class ComponentDrawStatus(str, Enum):
    RESERVED = "RESERVED"
    CONSUMED = "CONSUMED"
    RETURNED = "RETURNED"


class TestType(str, Enum):
    KV100 = "KV100"
    KV40 = "KV40"
    TBN = "TBN"
    FLASH_POINT = "FLASH_POINT"


class QcResultVerdict(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"


class RetainSampleStatus(str, Enum):
    HELD = "HELD"
    DISPOSED = "DISPOSED"


class ClaimBody(str, Enum):
    API = "API"
    ILSAC = "ILSAC"
    OEM_MB = "OEM_MB"
    OEM_VW = "OEM_VW"
    OEM_CAT = "OEM_CAT"
    JASO = "JASO"


class ApprovalClaimStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    REJECTED = "REJECTED"
    WITHDRAWN = "WITHDRAWN"


class PackageType(str, Enum):
    BULK = "BULK"
    IBC_1000L = "IBC_1000L"
    DRUM_205L = "DRUM_205L"
    PAIL_20L = "PAIL_20L"
    CASE_12X1L = "CASE_12X1L"


class PackageConfigurationStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    CLAIM_BLOCKED = "CLAIM_BLOCKED"
    SUPERSEDED = "SUPERSEDED"
    RETIRED = "RETIRED"


class PackagingLineStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    DOWN = "DOWN"


class PackagingRunStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class DeliveryMode(str, Enum):
    BULK_DELIVERY = "BULK_DELIVERY"
    PACKAGED = "PACKAGED"


class OrderStatus(str, Enum):
    DRAFT = "DRAFT"
    CONFIRMED = "CONFIRMED"
    HOLD = "HOLD"
    INVOICED = "INVOICED"
    VOID = "VOID"


class OrderLineStatus(str, Enum):
    OPEN = "OPEN"
    HOLD = "HOLD"
    CANCELLED = "CANCELLED"


class TakebackCollectionStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    COLLECTED = "COLLECTED"
    ASSAYED = "ASSAYED"
    CREDITED = "CREDITED"
    REJECTED = "REJECTED"


class CreditVariant(str, Enum):
    FLAT_RATE = "FLAT_RATE"
    ASSAY_ADJUSTED = "ASSAY_ADJUSTED"


class SpecChangeRequestStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    IN_REVIEW = "IN_REVIEW"
    CLEARED = "CLEARED"
    REJECTED = "REJECTED"
    EFFECTIVE = "EFFECTIVE"
    WITHDRAWN = "WITHDRAWN"


class ReviewVerdict(str, Enum):
    PENDING = "PENDING"
    CLEARED = "CLEARED"
    BLOCKED = "BLOCKED"


# --------------------------------------------------------------------------
# Entity shapes.
#
# Most resources carry id + created_at + updated_at + version (PRD 2.4).
# Recipe components and laboratory results are deliberately immutable and
# carry ONLY id and created_at — no updated_at and no version.
# --------------------------------------------------------------------------
class Customer(TypedDict):
    id: str
    name: str
    customer_type: str
    contract_tier: str
    credit_limit_cents: int
    takeback_agreement_status: str
    takeback_credit_balance_cents: int
    last_credit_event_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ComponentLot(TypedDict):
    id: str
    component_type: str
    component_code: str
    additive_family: str
    received_kg: float
    available_kg: float
    unit_cost_cents_per_kg: int
    kv100_cst: float
    density_kg_per_l: float
    coa_viscosity_verified: bool
    status: str
    quarantine_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ProductSpec(TypedDict):
    id: str
    product_code: str
    sae_grade: str
    revision: int
    status: str
    target_kv100_cst: float
    kv100_tolerance_pct: float
    min_additive_treat_pct: float
    base_stock_group: str
    additive_family: str
    effective_from: Optional[str]
    created_at: str
    updated_at: str
    version: int


class BlendRecipe(TypedDict):
    id: str
    product_spec_id: str
    spec_revision_pinned: int
    status: str
    total_mass_basis_kg: float
    additive_treat_pct: float
    predicted_kv100_cst: float
    component_count: int
    created_at: str
    updated_at: str
    version: int


class RecipeComponent(TypedDict):
    """Immutable child row — carries only id and created_at."""

    id: str
    blend_recipe_id: str
    component_code: str
    component_type: str
    mass_fraction_pct: float
    nominal_kv100_cst: float
    additive_family: str
    created_at: str


class BlendTank(TypedDict):
    id: str
    tank_code: str
    capacity_l: float
    status: str
    heel_volume_l: float
    heel_additive_family: str
    heel_product_code: Optional[str]
    last_flush_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class BlendBatch(TypedDict):
    id: str
    blend_recipe_id: str
    batch_code: str
    planned_volume_l: float
    blend_tank_id: Optional[str]
    charge_volume_l: Optional[float]
    charge_mass_kg: Optional[float]
    window_start: Optional[str]
    window_end: Optional[str]
    production_status: str
    qc_status: str
    predicted_kv100_cst: float
    measured_kv100_cst: Optional[float]
    heel_ratio_actual: Optional[float]
    claim_eligible: bool
    estimated_component_cost_cents: int
    component_cost_cents: int
    retain_count: int
    created_at: str
    updated_at: str
    version: int


class ComponentDraw(TypedDict):
    id: str
    blend_batch_id: str
    component_lot_id: str
    component_code: str
    drawn_kg: float
    unit_cost_cents_per_kg: int
    status: str
    created_at: str
    updated_at: str
    version: int


class QCResult(TypedDict):
    """Immutable laboratory record — carries only id and created_at."""

    id: str
    blend_batch_id: str
    test_type: str
    measured_value: float
    result: str
    tested_at: str
    technician_user_id: str
    created_at: str


class RetainSample(TypedDict):
    id: str
    blend_batch_id: str
    retain_code: str
    volume_ml: float
    retained_at: str
    retention_until: str
    status: str
    created_at: str
    updated_at: str
    version: int


class ApprovalClaim(TypedDict):
    id: str
    product_spec_id: str
    claim_body: str
    claim_code: str
    pinned_spec_revision: Optional[int]
    status: str
    licence_number: Optional[str]
    valid_until: Optional[str]
    requires_recertification: bool
    suspension_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class PackageConfiguration(TypedDict):
    id: str
    product_spec_id: str
    customer_id: Optional[str]
    package_type: str
    label_brand: str
    private_label: bool
    fill_volume_l: float
    units_per_case: Optional[int]
    claim_codes: List[str]
    status: str
    superseded_by_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class PackagingLine(TypedDict):
    id: str
    line_code: str
    max_concurrent_runs: int
    status: str
    scheduled_run_count: int
    created_at: str
    updated_at: str
    version: int


class PackagingRun(TypedDict):
    id: str
    blend_batch_id: str
    package_configuration_id: str
    packaging_line_id: str
    window_start: str
    window_end: str
    planned_units: int
    produced_units: Optional[int]
    status: str
    cancel_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Order(TypedDict):
    id: str
    customer_id: str
    delivery_mode: str
    takeback_linked: bool
    status: str
    subtotal_cents: int
    total_volume_l: float
    freight_surcharge_cents: int
    pre_credit_total_cents: int
    takeback_credit_applied_cents: int
    total_cents: int
    hold_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class OrderLine(TypedDict):
    id: str
    order_id: str
    package_configuration_id: str
    quantity_units: int
    volume_l: float
    unit_price_cents: int
    line_total_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class TakebackCollection(TypedDict):
    id: str
    customer_id: str
    order_id: Optional[str]
    scheduled_volume_l: Optional[float]
    collected_volume_l: Optional[float]
    water_pct: Optional[float]
    sediment_pct: Optional[float]
    status: str
    credit_variant: Optional[str]
    credit_cents: int
    reject_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class SpecChangeRequest(TypedDict):
    id: str
    product_spec_id: str
    requested_kv100_cst: float
    requested_kv100_tolerance_pct: float
    requested_min_additive_treat_pct: float
    requested_additive_family: str
    status: str
    viscosity_review: str
    approval_review: str
    claims_to_suspend_count: int
    effective_revision: Optional[int]
    created_at: str
    updated_at: str
    version: int
