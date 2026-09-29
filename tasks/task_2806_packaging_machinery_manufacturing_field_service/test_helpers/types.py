"""Domain types for the Packaging Machinery OEM API: status enums, role enum, entity shapes."""

from enum import Enum
from typing import List, Optional, TypedDict


class UserRole(str, Enum):
    PLATFORM_ADMIN = "PlatformAdmin"
    APPLICATION_ENGINEER = "ApplicationEngineer"
    PRODUCTION_PLANNER = "ProductionPlanner"
    QUALITY_INSPECTOR = "QualityInspector"
    SERVICE_MANAGER = "ServiceManager"
    CUSTOMER_CONTACT = "CustomerContact"


class RegionCode(str, Enum):
    NA = "NA"
    EU = "EU"
    APAC = "APAC"
    LATAM = "LATAM"


class MachineFamily(str, Enum):
    FILLER = "FILLER"
    CAPPER = "CAPPER"
    LABELER = "LABELER"
    CARTONER = "CARTONER"


class CustomerStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class MachineModelLifecycleStatus(str, Enum):
    ACTIVE = "ACTIVE"
    OBSOLETE = "OBSOLETE"


class ProductionLineStatus(str, Enum):
    OPEN = "OPEN"
    MAINTENANCE = "MAINTENANCE"


class FieldEngineerStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    ON_LEAVE = "ON_LEAVE"


class ProductTrialStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    TESTING = "TESTING"
    RETEST_REQUIRED = "RETEST_REQUIRED"
    PASSED = "PASSED"
    REJECTED = "REJECTED"


class TrialOutcome(str, Enum):
    PASS = "PASS"
    RETEST = "RETEST"
    REJECT = "REJECT"


class ConfigRecommendation(str, Enum):
    PENDING = "PENDING"
    STANDARD = "STANDARD"
    HEAVY_DUTY = "HEAVY_DUTY"
    NOT_FEASIBLE = "NOT_FEASIBLE"


class FulfillmentStatus(str, Enum):
    DRAFT = "DRAFT"
    ENGINEERED = "ENGINEERED"
    SLOTTED = "SLOTTED"
    IN_BUILD = "IN_BUILD"
    FAT_PASSED = "FAT_PASSED"
    FAT_FAILED = "FAT_FAILED"
    SHIPPED = "SHIPPED"
    INSTALLED = "INSTALLED"
    ACCEPTED = "ACCEPTED"
    CANCELLED = "CANCELLED"


class CommercialStatus(str, Enum):
    QUOTED = "QUOTED"
    PO_RECEIVED = "PO_RECEIVED"
    INVOICED = "INVOICED"
    PAID = "PAID"
    WRITTEN_OFF = "WRITTEN_OFF"


class DiscountTier(str, Enum):
    NONE = "NONE"
    T1 = "T1"
    T2 = "T2"
    T3 = "T3"


class GuaranteeBasis(str, Enum):
    NAMEPLATE = "NAMEPLATE"
    PRODUCT_ADJUSTED = "PRODUCT_ADJUSTED"


class ComponentStatus(str, Enum):
    PLANNED = "PLANNED"
    ON_ORDER = "ON_ORDER"
    RECEIVED = "RECEIVED"


class BuildSlotStatus(str, Enum):
    RESERVED = "RESERVED"
    CONFIRMED = "CONFIRMED"
    IN_BUILD = "IN_BUILD"
    REWORK_HOLD = "REWORK_HOLD"
    RELEASED = "RELEASED"
    DISPLACED = "DISPLACED"
    COMPLETED = "COMPLETED"


class AcceptanceTestKind(str, Enum):
    FAT = "FAT"
    SAT = "SAT"


class AcceptanceTestStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    IN_PROGRESS = "IN_PROGRESS"
    PASSED = "PASSED"
    FAILED = "FAILED"


class InstalledMachineStatus(str, Enum):
    INSTALLED = "INSTALLED"
    ACCEPTED = "ACCEPTED"


class FormatKitStatus(str, Enum):
    DRAFT = "DRAFT"
    QUOTED = "QUOTED"
    ORDERED = "ORDERED"
    DELIVERED = "DELIVERED"


class ServiceContractTier(str, Enum):
    BRONZE = "BRONZE"
    SILVER = "SILVER"
    GOLD = "GOLD"


class ServiceContractStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    EXPIRED = "EXPIRED"
    TERMINATED = "TERMINATED"


class CoveragePosture(str, Enum):
    OPEN = "OPEN"
    RESTRICTED = "RESTRICTED"
    BUDGET_EXHAUSTED = "BUDGET_EXHAUSTED"


class VisitType(str, Enum):
    PM = "PM"
    REMOTE_DIAGNOSTIC = "REMOTE_DIAGNOSTIC"
    CORRECTIVE = "CORRECTIVE"


class VisitStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    BILLABLE_HOLD = "BILLABLE_HOLD"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class FindingsCode(str, Enum):
    NONE = "NONE"
    OK = "OK"
    WEAR_FOUND = "WEAR_FOUND"
    FAULT_FOUND = "FAULT_FOUND"


class WarrantyClaimStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    PRODUCT_VARIATION_REVIEW = "PRODUCT_VARIATION_REVIEW"
    DEFECT_REVIEW = "DEFECT_REVIEW"
    ADJUDICATED = "ADJUDICATED"
    REJECTED = "REJECTED"
    VOID = "VOID"


class ClaimCause(str, Enum):
    UNDETERMINED = "UNDETERMINED"
    MACHINE_DEFECT = "MACHINE_DEFECT"
    PRODUCT_VARIATION = "PRODUCT_VARIATION"
    MIXED = "MIXED"


class ClaimResolution(str, Enum):
    APPROVE = "APPROVE"
    REJECT = "REJECT"


class Criticality(str, Enum):
    A = "A"
    B = "B"
    C = "C"


class StockingBasis(str, Enum):
    LEAD_TIME_DEMAND = "LEAD_TIME_DEMAND"
    SERVICE_LEVEL = "SERVICE_LEVEL"


class ObsolescenceStatus(str, Enum):
    ACTIVE = "ACTIVE"
    NOTICE_ISSUED = "NOTICE_ISSUED"
    LAST_TIME_BUY = "LAST_TIME_BUY"
    OBSOLETE = "OBSOLETE"


class StockingRecommendationStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUPERSEDED = "SUPERSEDED"


# --- Entity shapes -------------------------------------------------------
# Every persisted row carries a server-minted `id` and a `created_at`.
# Almost every entity additionally carries `updated_at` and `version`;
# warranty claim cost lines are the single exception (PRD §2.4).


class Customer(TypedDict):
    id: str
    legal_name: str
    region_code: str
    product_variation_pct: float
    status: str
    open_order_count: int
    created_at: str
    updated_at: str
    version: int


class MachineModel(TypedDict):
    id: str
    model_code: str
    machine_family: str
    nameplate_rate_cpm: int
    guarantee_efficiency_pct: float
    base_price_cents: int
    min_container_diameter_mm: int
    max_container_diameter_mm: int
    lifecycle_status: str
    open_defect_review_count: int
    created_at: str
    updated_at: str
    version: int


class ProductionLine(TypedDict):
    id: str
    line_code: str
    machine_family: str
    changeover_buffer_days: int
    capacity_days_per_quarter: int
    status: str
    committed_slot_days: int
    created_at: str
    updated_at: str
    version: int


class FieldEngineer(TypedDict):
    id: str
    full_name: str
    region_code: str
    certifications: List[str]
    travel_buffer_minutes: int
    status: str
    created_at: str
    updated_at: str
    version: int


class ProductTrial(TypedDict):
    id: str
    customer_id: str
    machine_model_id: str
    product_name: str
    container_family: str
    container_diameter_mm: int
    measured_rate_cpm: int
    rate_ratio_pct: float
    config_recommendation: str
    retest_count: int
    status: str
    created_at: str
    updated_at: str
    version: int


class MachineOrder(TypedDict):
    id: str
    customer_id: str
    machine_model_id: str
    product_trial_id: str
    equipment_price_cents: int
    change_parts_price_cents: int
    guarantee_basis: str
    discount_tier: str
    commissioning_fee_cents: int
    order_total_cents: int
    rework_days: int
    fat_failure_count: int
    fulfillment_status: str
    commercial_status: str
    created_at: str
    updated_at: str
    version: int


class LongLeadComponent(TypedDict):
    id: str
    machine_order_id: str
    part_number: str
    lead_time_days: int
    po_released_on: Optional[str]
    promised_date: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class BuildSlot(TypedDict):
    id: str
    machine_order_id: str
    production_line_id: str
    start_date: str
    slot_days: int
    end_date: str
    superseded_by_slot_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class AcceptanceTest(TypedDict):
    id: str
    machine_order_id: str
    kind: str
    scheduled_on: str
    customer_product_supplied: bool
    containers_supplied_count: int
    required_operators_trained: int
    operators_trained_count: int
    measured_rate_cpm: int
    measured_efficiency_pct: float
    attainment_pct: float
    guarantee_met: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class InstalledMachine(TypedDict):
    id: str
    machine_order_id: str
    customer_id: str
    serial_number: str
    current_format_family: str
    remote_diagnostics_enabled: bool
    open_claim_count: int
    status: str
    created_at: str
    updated_at: str
    version: int


class FormatKit(TypedDict):
    id: str
    installed_machine_id: str
    container_family: str
    container_diameter_mm: int
    component_count: int
    quoted_lead_time_days: int
    price_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class ServiceContract(TypedDict):
    id: str
    installed_machine_id: str
    tier: str
    start_date: str
    end_date: str
    pm_visits_included: int
    pm_visits_used: int
    goodwill_budget_initial_cents: int
    goodwill_budget_cents: int
    coverage_posture: str
    status: str
    created_at: str
    updated_at: str
    version: int


class PreventiveMaintenanceVisit(TypedDict):
    id: str
    service_contract_id: str
    field_engineer_id: Optional[str]
    visit_type: str
    start_ts: str
    end_ts: str
    billable: bool
    findings_code: str
    status: str
    created_at: str
    updated_at: str
    version: int


class WarrantyClaim(TypedDict):
    id: str
    installed_machine_id: str
    service_contract_id: str
    failure_summary: str
    claimed_cost_cents: int
    product_variation_review_done: bool
    defect_review_done: bool
    cause: str
    oem_share_cents: int
    customer_share_cents: int
    goodwill_charged_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class WarrantyClaimLine(TypedDict):
    """Immutable cost line: carries only `id` and `created_at` (PRD §2.4)."""

    id: str
    warranty_claim_id: str
    line_label: str
    amount_cents: int
    defect_attribution_pct: float
    oem_line_share_cents: int
    created_at: str


class StockingRecommendation(TypedDict):
    id: str
    installed_machine_id: str
    part_number: str
    annual_usage_qty: int
    unit_lead_time_days: int
    criticality: str
    basis: str
    obsolescence_status: str
    recommended_qty: int
    status: str
    created_at: str
    updated_at: str
    version: int
