"""Domain types: entity TypedDicts, status enums, role enum (PRD §2.1, §2.5, §3)."""
from enum import Enum
from typing import List, Optional, TypedDict


class UserRole(str, Enum):
    SUPPLY_CHAIN_ADMIN = "SupplyChainAdmin"
    REGULATORY_SPECIALIST = "RegulatorySpecialist"
    MANUFACTURING_PLANNER = "ManufacturingPlanner"
    QUALITY_MANAGER = "QualityManager"
    CONVERSION_MANAGER = "ConversionManager"
    CLINICIAN = "Clinician"
    FACILITY_SUPPLY_DIRECTOR = "FacilitySupplyDirector"
    GPO_ANALYST = "GPOAnalyst"


class BrandType(str, Enum):
    BRANDED = "BRANDED"
    PRIVATE_LABEL = "PRIVATE_LABEL"


class ProductCategory(str, Enum):
    SURGICAL_INSTRUMENTS = "SURGICAL_INSTRUMENTS"
    WOUND_CARE = "WOUND_CARE"
    EXAM_GLOVES = "EXAM_GLOVES"
    STERILIZATION_SUPPLIES = "STERILIZATION_SUPPLIES"
    UROLOGICAL = "UROLOGICAL"
    RESPIRATORY = "RESPIRATORY"


class DeviceClass(str, Enum):
    CLASS_I = "CLASS_I"
    CLASS_II = "CLASS_II"
    CLASS_III = "CLASS_III"


class RegistrationStatus(str, Enum):
    UNREGISTERED = "UNREGISTERED"
    SUBMITTED = "SUBMITTED"
    REGISTERED = "REGISTERED"
    REJECTED = "REJECTED"


class Availability(str, Enum):
    ACTIVE = "ACTIVE"
    DISCONTINUED = "DISCONTINUED"


class LotStatus(str, Enum):
    AWAITING_QA = "AWAITING_QA"
    RELEASED = "RELEASED"
    REJECTED = "REJECTED"
    QUARANTINED = "QUARANTINED"


class SterilityStatus(str, Enum):
    PENDING = "PENDING"
    PASSED = "PASSED"
    FAILED = "FAILED"
    NOT_REQUIRED = "NOT_REQUIRED"


class BatchStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    COMPLETED = "COMPLETED"


class SterilityResult(str, Enum):
    PENDING = "PENDING"
    PASSED = "PASSED"
    FAILED = "FAILED"


class FacilityType(str, Enum):
    ACUTE_CARE = "ACUTE_CARE"
    SURGERY_CENTER = "SURGERY_CENTER"
    CLINIC = "CLINIC"
    LONG_TERM_CARE = "LONG_TERM_CARE"


class ProgramStatus(str, Enum):
    IN_EVALUATION = "IN_EVALUATION"
    IN_REVIEW = "IN_REVIEW"
    CONVERTED = "CONVERTED"


class EvaluationStatus(str, Enum):
    PENDING = "PENDING"
    PASSED = "PASSED"
    FAILED = "FAILED"


class TrayStatus(str, Enum):
    DRAFT = "DRAFT"
    PENDING_APPROVAL = "PENDING_APPROVAL"
    ACTIVE = "ACTIVE"
    UNDER_CHANGE = "UNDER_CHANGE"


class AgreementStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    EXPIRED = "EXPIRED"


class OrderStatus(str, Enum):
    PLACED = "PLACED"
    PARTIALLY_SHIPPED = "PARTIALLY_SHIPPED"
    SHIPPED = "SHIPPED"
    RECEIVED = "RECEIVED"


class ClaimStatus(str, Enum):
    ACCRUED = "ACCRUED"
    SUBMITTED = "SUBMITTED"
    PAID = "PAID"
    DISPUTED = "DISPUTED"


class DisruptionStatus(str, Enum):
    DECLARED = "DECLARED"
    MITIGATING = "MITIGATING"
    RESOLVED = "RESOLVED"


class DisruptionReason(str, Enum):
    RAW_MATERIAL_SHORTAGE = "RAW_MATERIAL_SHORTAGE"
    FDA_HOLD = "FDA_HOLD"
    TRANSPORTATION = "TRANSPORTATION"
    DEMAND_SURGE = "DEMAND_SURGE"
    RECALL = "RECALL"


class Severity(str, Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class SubstitutionStatus(str, Enum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


class ProgramType(str, Enum):
    STOCKROOM_MANAGED = "STOCKROOM_MANAGED"
    CRASH_CART = "CRASH_CART"
    OR_CORE = "OR_CORE"


class ReorderStatus(str, Enum):
    OK = "OK"
    DUE = "DUE"
    CRITICAL = "CRITICAL"


class StockEventType(str, Enum):
    RECEIPT = "RECEIPT"
    ISSUE = "ISSUE"
    CYCLE_COUNT_ADJUST = "CYCLE_COUNT_ADJUST"


# --- Entity TypedDicts (all top-level resources carry id/created_at/updated_at/version) ---


class Product(TypedDict, total=False):
    id: str
    sku: str
    name: str
    brand_type: str
    category: str
    sterile: bool
    device_class: str
    registration_status: str
    availability: str
    units_per_case: int
    each_price_cents: int
    order_multiple: int
    lum_eligible: bool
    created_at: str
    updated_at: str
    version: int


class ManufacturingLot(TypedDict, total=False):
    id: str
    lot_code: str
    product_id: str
    quantity: int
    manufacture_date: str
    expiry_date: str
    status: str
    sterilization_batch_id: Optional[str]
    sterility_status: str
    created_by: str
    qa_disposition_by: Optional[str]
    qa_disposition_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class SterilizationBatch(TypedDict, total=False):
    id: str
    batch_code: str
    chamber_id: str
    scheduled_start: str
    scheduled_end: str
    lot_ids: List[str]
    status: str
    sterility_result: str
    recorded_by: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Facility(TypedDict, total=False):
    id: str
    name: str
    health_system_name: str
    facility_type: str
    ship_to_address: str
    created_at: str
    updated_at: str
    version: int


class ConversionLineItem(TypedDict, total=False):
    line_id: str
    incumbent_product_id: str
    replacement_product_id: str
    evaluation_status: str
    training_completed: bool
    evaluated_by: Optional[str]
    evaluation_notes: Optional[str]


class ConversionProgram(TypedDict, total=False):
    id: str
    facility_id: str
    name: str
    target_categories: List[str]
    line_items: List[ConversionLineItem]
    status: str
    reviewed_by: Optional[str]
    review_decision_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class TrayComponent(TypedDict, total=False):
    product_id: str
    quantity: int


class TrayTemplate(TypedDict, total=False):
    id: str
    facility_id: str
    name: str
    procedure_type: str
    sterile_assembly: bool
    components: List[TrayComponent]
    status: str
    proposed_by: Optional[str]
    approved_version: Optional[int]
    approved_by: Optional[str]
    created_at: str
    updated_at: str
    version: int


class PrimeVendorAgreement(TypedDict, total=False):
    id: str
    facility_id: str
    committed_fill_rate_pct: float
    deliveries_per_week: int
    lum_commitment: bool
    annual_commitment_cents: int
    spent_cents: int
    rolling_fill_rate_pct: Optional[float]
    start_date: str
    end_date: str
    status: str
    created_at: str
    updated_at: str
    version: int


class OrderLine(TypedDict, total=False):
    product_id: str
    ordered_qty: int
    shipped_qty: int
    backorder_cancelled: bool


class DistributionOrder(TypedDict, total=False):
    id: str
    agreement_id: str
    requested_delivery_date: str
    lines: List[OrderLine]
    status: str
    provisional_fill_rate_pct: Optional[float]
    final_fill_rate_pct: Optional[float]
    total_price_cents: int
    received_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class RebateClaim(TypedDict, total=False):
    id: str
    facility_id: str
    gpo_name: str
    period_start: str
    period_end: str
    eligible_purchase_cents: int
    private_label_share: float
    compliant: bool
    provisional_amount_cents: int
    final_amount_cents: Optional[int]
    status: str
    dispute_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class AllocationRecord(TypedDict, total=False):
    allocation_id: str
    facility_id: str
    quantity: int
    created_at: str


class SubstitutionRequest(TypedDict, total=False):
    request_id: str
    facility_id: str
    proposed_product_id: str
    covered_quantity: int
    status: str
    decided_by: Optional[str]
    rationale: Optional[str]


class SupplyDisruption(TypedDict, total=False):
    id: str
    product_id: str
    disrupted_quantity: int
    reason: str
    severity: str
    expected_resolution_date: str
    status: str
    allocations: List[AllocationRecord]
    substitution_requests: List[SubstitutionRequest]
    allocated_total: int
    approved_sub_total: int
    remaining_pool: int
    covered_quantity: int
    created_at: str
    updated_at: str
    version: int


class InventoryPosition(TypedDict, total=False):
    product_id: str
    par_level: int
    reorder_point: int
    on_hand: int
    reorder_status: str
    suggested_order_qty: int


class InventoryProgram(TypedDict, total=False):
    id: str
    facility_id: str
    program_type: str
    positions: List[InventoryPosition]
    auto_replenish_enabled: bool
    created_at: str
    updated_at: str
    version: int
