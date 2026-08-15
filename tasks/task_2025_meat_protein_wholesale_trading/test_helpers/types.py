"""Domain types: entity TypedDicts, status enums, role enum (PRD §2.5, §3)."""
from enum import Enum
from typing import List, Optional, TypedDict


class SupplierStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class CustomerStatus(str, Enum):
    ACTIVE = "ACTIVE"
    CREDIT_HOLD = "CREDIT_HOLD"


class AllocationTier(str, Enum):
    TIER_1 = "TIER_1"
    TIER_2 = "TIER_2"
    TIER_3 = "TIER_3"


class WarehouseZone(str, Enum):
    CHILLER = "CHILLER"
    FROZEN = "FROZEN"


class ProductKind(str, Enum):
    CARCASS = "CARCASS"
    PRIMAL = "PRIMAL"
    SUBPRIMAL = "SUBPRIMAL"


class Species(str, Enum):
    BEEF = "BEEF"
    PORK = "PORK"


class PriceSheetStatus(str, Enum):
    DRAFT = "DRAFT"
    PUBLISHED = "PUBLISHED"
    CLOSED = "CLOSED"
    SUPERSEDED = "SUPERSEDED"
    DISCARDED = "DISCARDED"


class PurchaseOrderStatus(str, Enum):
    BOOKED = "BOOKED"
    RECEIVED = "RECEIVED"
    GRADED = "GRADED"
    CANCELLED = "CANCELLED"


class PoCancelReason(str, Enum):
    MANUAL = "MANUAL"
    SUPPLIER_SUSPENDED = "SUPPLIER_SUSPENDED"


class LotStatus(str, Enum):
    IN_INSPECTION = "IN_INSPECTION"
    AVAILABLE = "AVAILABLE"
    QUARANTINED = "QUARANTINED"
    DEPLETED = "DEPLETED"
    EXPIRED = "EXPIRED"


class UsdaGrade(str, Enum):
    UNGRADED = "UNGRADED"
    PRIME = "PRIME"
    CHOICE = "CHOICE"
    SELECT = "SELECT"
    STANDARD = "STANDARD"
    NO_ROLL = "NO_ROLL"


class QuarantineReason(str, Enum):
    SPEC_NONCOMPLIANCE = "SPEC_NONCOMPLIANCE"
    YIELD_OUT_OF_BAND = "YIELD_OUT_OF_BAND"
    USDA_HOLD = "USDA_HOLD"
    CERT_REVOKED = "CERT_REVOKED"
    RETURNED_REJECTED = "RETURNED_REJECTED"


class BatchStatus(str, Enum):
    DRAFT = "DRAFT"
    POSTED = "POSTED"
    VOIDED = "VOIDED"


class ContractStatus(str, Enum):
    OPEN = "OPEN"
    SETTLED = "SETTLED"
    DEFAULTED = "DEFAULTED"
    CANCELLED = "CANCELLED"


class AllocationStatus(str, Enum):
    REQUESTED = "REQUESTED"
    CONFIRMED = "CONFIRMED"
    SHORTFALL = "SHORTFALL"
    SHIPPED = "SHIPPED"
    CANCELLED = "CANCELLED"


class AllocationCancelReason(str, Enum):
    MANUAL = "MANUAL"
    SHEET_SUPERSEDED = "SHEET_SUPERSEDED"
    SHEET_CLOSED = "SHEET_CLOSED"
    CONTRACT_CANCELLED = "CONTRACT_CANCELLED"


class ShipmentStatus(str, Enum):
    STAGING = "STAGING"
    IN_TRANSIT = "IN_TRANSIT"
    DELIVERED = "DELIVERED"
    REJECTED_AT_RECEIVING = "REJECTED_AT_RECEIVING"


class TempCompliance(str, Enum):
    UNKNOWN = "UNKNOWN"
    COMPLIANT = "COMPLIANT"
    BREACHED = "BREACHED"


class ClaimType(str, Enum):
    TEMPERATURE_ABUSE = "TEMPERATURE_ABUSE"
    SPEC_NONCONFORMANCE = "SPEC_NONCONFORMANCE"
    WEIGHT_SHORTAGE = "WEIGHT_SHORTAGE"
    QUALITY_DEFECT = "QUALITY_DEFECT"


class ClaimStatus(str, Enum):
    FILED = "FILED"
    OFFER_MADE = "OFFER_MADE"
    COUNTERED = "COUNTERED"
    SETTLED_PAID = "SETTLED_PAID"
    SETTLED_DENIED = "SETTLED_DENIED"
    WITHDRAWN = "WITHDRAWN"


class CertificateType(str, Enum):
    USDA_GRADE = "USDA_GRADE"
    USDA_INSPECTION = "USDA_INSPECTION"
    COA = "COA"


class CertificateStatus(str, Enum):
    VALID = "VALID"
    REVOKED = "REVOKED"


class UserRole(str, Enum):
    DESK_ADMIN = "DeskAdmin"
    TRADER = "Trader"
    RISK_OFFICER = "RiskOfficer"
    QUALITY_GRADER = "QualityGrader"
    WAREHOUSE_OPERATOR = "WarehouseOperator"
    CLAIMS_ADJUSTER = "ClaimsAdjuster"
    CUSTOMER_REP = "CustomerRep"


# ---------------------------------------------------------------------------
# Entity payloads. Resources with the standard system-managed field set carry
# id + created_at + updated_at + version (PRD §2.5). Product, YieldSpec,
# TemperatureReading, and InspectionCertificate are deliberately lighter and
# carry only id + created_at — updated_at and version are absent from them.
# ---------------------------------------------------------------------------

class Supplier(TypedDict, total=False):
    id: str
    name: str
    establishment_number: str
    contact_email: str
    status: str
    suspension_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Customer(TypedDict, total=False):
    id: str
    name: str
    customer_code: str
    credit_limit_cents: int
    allocation_tier: str
    status: str
    outstanding_exposure_cents: int
    created_at: str
    updated_at: str
    version: int


class Warehouse(TypedDict, total=False):
    id: str
    name: str
    zone: str
    capacity_lbs: int
    occupied_lbs: float
    created_at: str
    updated_at: str
    version: int


class Product(TypedDict, total=False):
    id: str
    product_code: str
    kind: str
    species: str
    max_fat_pct: Optional[float]
    shelf_life_days: int
    required_temp_max_f: float
    created_at: str


class PriceSheet(TypedDict, total=False):
    id: str
    week_start_date: str
    status: str
    supersedes_sheet_id: Optional[str]
    published_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class PriceSheetLine(TypedDict, total=False):
    id: str
    price_sheet_id: str
    product_id: str
    price_per_lb_cents: int
    weekly_supply_lbs: int
    allocated_lbs: float
    created_at: str
    updated_at: str
    version: int


class YieldSpec(TypedDict, total=False):
    id: str
    carcass_product_id: str
    output_product_id: str
    expected_yield_pct: float
    min_yield_pct: float
    max_yield_pct: float
    created_at: str


class PurchaseOrder(TypedDict, total=False):
    id: str
    po_number: str
    supplier_id: str
    product_id: str
    ordered_weight_lbs: float
    contract_price_per_cwt_cents: int
    required_delivery_date: str
    received_weight_lbs: Optional[float]
    estimated_cutout_value_cents: Optional[int]
    actual_cutout_value_cents: Optional[int]
    status: str
    cancel_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class InventoryLot(TypedDict, total=False):
    id: str
    lot_code: str
    po_id: Optional[str]
    parent_lot_id: Optional[str]
    fabrication_batch_id: Optional[str]
    product_id: str
    warehouse_id: str
    received_weight_lbs: float
    current_weight_lbs: float
    production_date: str
    age_days: int
    usda_grade: str
    measured_fat_pct: Optional[float]
    spec_compliant: Optional[bool]
    unit_value_cents_per_lb: Optional[int]
    quarantine_reason: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class FabricationBatch(TypedDict, total=False):
    id: str
    input_lot_id: str
    loss_lbs: float
    outputs: List[dict]
    total_output_weight_lbs: float
    yield_efficiency_pct: float
    status: str
    created_at: str
    updated_at: str
    version: int


class ForwardContract(TypedDict, total=False):
    id: str
    contract_number: str
    customer_id: str
    product_id: str
    committed_lbs: int
    fixed_price_per_lb_cents: int
    delivery_week_start: str
    delivered_lbs: float
    earmarked_lbs: float
    amendment_round: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Allocation(TypedDict, total=False):
    id: str
    customer_id: str
    price_sheet_line_id: str
    forward_contract_id: Optional[str]
    requested_lbs: float
    allocated_lbs: float
    unit_price_cents: Optional[int]
    status: str
    cancel_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Shipment(TypedDict, total=False):
    id: str
    allocation_id: str
    carrier_name: str
    trailer_temp_setpoint_f: float
    shipped_lbs: float
    lot_ids: Optional[List[str]]
    min_temp_f_reading: Optional[float]
    max_temp_f_reading: Optional[float]
    temp_compliance: str
    rejection_reason: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class TemperatureReading(TypedDict, total=False):
    id: str
    shipment_id: str
    reading_f: float
    recorded_at: str
    created_at: str


class Claim(TypedDict, total=False):
    id: str
    shipment_id: str
    claim_type: str
    claimed_amount_cents: int
    provisional_credit_cents: int
    current_offer_cents: Optional[int]
    offer_round: int
    final_settlement_cents: Optional[int]
    status: str
    created_at: str
    updated_at: str
    version: int


class InspectionCertificate(TypedDict, total=False):
    id: str
    lot_id: str
    certificate_type: str
    grade_result: Optional[str]
    certificate_number: str
    issued_by: str
    issue_date: str
    status: str
    created_at: str
