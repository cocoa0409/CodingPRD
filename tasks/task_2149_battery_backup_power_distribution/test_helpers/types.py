"""Domain types for the Battery Backup Distribution API.

Entity TypedDicts, status enums and the role enum. Every resource in this
system carries id, created_at, updated_at and version.
"""
from enum import Enum
from typing import TypedDict, Optional, List


class UserRole(str, Enum):
    PLATFORM_ADMIN = "PlatformAdmin"
    SALES_REP = "SalesRep"
    WAREHOUSE_OPERATOR = "WarehouseOperator"
    HAZMAT_CERTIFIER = "HazmatCertifier"
    COMPLIANCE_OFFICER = "ComplianceOfficer"
    CUSTOMER = "Customer"


class AccountTier(str, Enum):
    PLATINUM = "PLATINUM"
    GOLD = "GOLD"
    STANDARD = "STANDARD"


class AccountStatus(str, Enum):
    ACTIVE = "ACTIVE"
    CREDIT_HOLD = "CREDIT_HOLD"


class Chemistry(str, Enum):
    FLOODED_LEAD_ACID = "FLOODED_LEAD_ACID"
    AGM = "AGM"
    GEL = "GEL"
    LITHIUM_IRON_PHOSPHATE = "LITHIUM_IRON_PHOSPHATE"
    NICKEL_CADMIUM = "NICKEL_CADMIUM"


class HazmatClassCode(str, Enum):
    NON_REGULATED = "NON_REGULATED"
    UN2800_EXCEPTED = "UN2800_EXCEPTED"
    UN2795 = "UN2795"
    UN2800 = "UN2800"
    UN2794 = "UN2794"
    UN3480_SECTION_II = "UN3480_SECTION_II"
    UN3480_SECTION_IA = "UN3480_SECTION_IA"


class BatteryModelStatus(str, Enum):
    ACTIVE = "ACTIVE"
    DISCONTINUED = "DISCONTINUED"


class ConditionState(str, Enum):
    SELLABLE = "SELLABLE"
    REFRESH_REQUIRED = "REFRESH_REQUIRED"
    SHELF_EXPIRED = "SHELF_EXPIRED"
    SCRAPPED = "SCRAPPED"


class FulfillmentStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    ALLOCATED = "ALLOCATED"
    SHIPPED = "SHIPPED"
    DELIVERED = "DELIVERED"
    CANCELLED = "CANCELLED"


class CreditStatus(str, Enum):
    PENDING = "PENDING"
    CLEARED = "CLEARED"
    HELD = "HELD"
    CLOSED = "CLOSED"


class ShipmentStatus(str, Enum):
    PACKED = "PACKED"
    CERTIFIED = "CERTIFIED"
    HAZMAT_REJECTED = "HAZMAT_REJECTED"
    DISPATCHED = "DISPATCHED"
    DELIVERED = "DELIVERED"
    VOIDED = "VOIDED"


class CoreReturnStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    INSPECTED = "INSPECTED"
    DISPUTED = "DISPUTED"
    REJECTED = "REJECTED"
    CREDITED = "CREDITED"


class WarrantyClaimStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    APPROVED_FREE = "APPROVED_FREE"
    APPROVED_PRORATA = "APPROVED_PRORATA"
    DENIED = "DENIED"
    SETTLED = "SETTLED"


class CoverageBand(str, Enum):
    FREE = "FREE"
    PRORATA = "PRORATA"
    EXPIRED = "EXPIRED"


class SettlementMode(str, Enum):
    ACCOUNT_CREDIT = "ACCOUNT_CREDIT"
    REPLACEMENT_ORDER = "REPLACEMENT_ORDER"


class ServiceContractStatus(str, Enum):
    DRAFT = "DRAFT"
    SIZED = "SIZED"
    ATTACHED = "ATTACHED"
    ACTIVE = "ACTIVE"
    SUPERSEDED = "SUPERSEDED"
    CANCELLED = "CANCELLED"


class CoverageTier(str, Enum):
    BRONZE = "BRONZE"
    SILVER = "SILVER"
    GOLD = "GOLD"


class StormSeverityTier(str, Enum):
    WATCH = "WATCH"
    WARNING = "WARNING"
    EMERGENCY = "EMERGENCY"


class StormEventStatus(str, Enum):
    DECLARED = "DECLARED"
    ALLOCATING = "ALLOCATING"
    CLOSED = "CLOSED"


class DisposalManifestStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    FILED = "FILED"


class CertificationDecision(str, Enum):
    APPROVE = "APPROVE"
    REJECT = "REJECT"


class Account(TypedDict):
    id: str
    name: str
    account_tier: str
    state_code: str
    storm_priority_rank: int
    credit_limit_cents: int
    open_receivable_cents: int
    core_deposit_balance_cents: int
    warranty_credit_cents: int
    lifetime_lead_recovered_kg: float
    status: str
    created_at: str
    updated_at: str
    version: int


class BatteryModel(TypedDict):
    id: str
    sku: str
    chemistry: str
    nominal_voltage: float
    amp_hour_capacity: float
    peukert_exponent: float
    unit_weight_kg: float
    lead_content_kg: float
    core_deposit_cents: int
    list_price_cents: int
    warranty_free_replacement_months: int
    warranty_prorata_months: int
    shelf_life_days: int
    self_discharge_pct_per_month: float
    watt_hour_rating: float
    hazmat_class_code: str
    hazmat_severity_rank: int
    replacement_model_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class Warehouse(TypedDict):
    id: str
    code: str
    state_code: str
    hazmat_endorsement: bool
    storm_reserve_pct: float
    dock_capacity_kg_per_window: float
    created_at: str
    updated_at: str
    version: int


class Carrier(TypedDict):
    id: str
    code: str
    name: str
    accepts_hazmat_classes: List[str]
    max_lithium_watt_hours_per_package: float
    ground_only: bool
    created_at: str
    updated_at: str
    version: int


class InventoryLot(TypedDict):
    id: str
    battery_model_id: str
    warehouse_id: str
    manufactured_on: str
    quantity_on_hand: int
    quantity_reserved: int
    quantity_available: int
    last_refresh_charged_at: Optional[str]
    refresh_charge_count: int
    last_measured_open_circuit_voltage: Optional[float]
    state_of_charge_pct: float
    condition_state: str
    scrap_manifest_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Order(TypedDict):
    id: str
    account_id: str
    warehouse_id: str
    storm_event_id: Optional[str]
    requested_ship_date: str
    fulfillment_status: str
    credit_status: str
    hazmat_hold: bool
    rejected_carrier_ids: List[str]
    line_count: int
    subtotal_cents: int
    core_deposit_charge_cents: int
    hazmat_fee_waived: bool
    hazmat_fee_cents: int
    service_contract_fee_cents: int
    total_cents: int
    allocation_priority_score: int
    cancellation_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class OrderLine(TypedDict):
    id: str
    order_id: str
    battery_model_id: str
    quantity: int
    core_expected_count: int
    unit_price_cents: int
    discount_pct: float
    line_total_cents: int
    allocated_quantity: int
    allocated_lot_id: Optional[str]
    core_due_by: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Shipment(TypedDict):
    id: str
    order_id: str
    carrier_id: str
    pickup_window_start: str
    pickup_window_end: str
    packed_by_user_id: str
    certified_by_user_id: Optional[str]
    status: str
    hazmat_class_code: str
    total_weight_kg: float
    total_lead_kg: float
    package_count: int
    hazmat_surcharge_cents: int
    rejection_reason: Optional[str]
    dispatched_at: Optional[str]
    delivered_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class CoreReturn(TypedDict):
    id: str
    account_id: str
    order_id: str
    battery_model_id: str
    declared_core_count: int
    accepted_core_count: int
    inspection_round: int
    late_return: bool
    provisional_credit_cents: int
    lead_recovered_kg: float
    scrap_value_cents: int
    final_credit_cents: int
    dispute_reason: Optional[str]
    status: str
    disposal_manifest_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class WarrantyClaim(TypedDict):
    id: str
    account_id: str
    battery_model_id: str
    serial_number: str
    installed_on: str
    failed_on: str
    months_in_service: int
    coverage_band: Optional[str]
    credit_cents: int
    settlement_mode: Optional[str]
    replacement_order_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class ServiceContract(TypedDict):
    id: str
    account_id: str
    order_id: Optional[str]
    coverage_tier: str
    load_watts: float
    required_runtime_minutes: int
    system_voltage: float
    ambient_temp_c: float
    allowed_chemistries: List[str]
    dc_load_amps: float
    required_peukert_ah: float
    temp_derate_factor: float
    sized_battery_model_id: Optional[str]
    sized_string_count: int
    sized_units_per_string: int
    sized_unit_count: int
    covered_value_cents: int
    monthly_fee_cents: int
    prepay_total_cents: int
    attached_at: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class StormEvent(TypedDict):
    id: str
    name: str
    region_state_code: str
    severity_tier: str
    allocation_pool_units: int
    allocated_units: int
    remaining_pool_units: int
    min_priority_score: int
    status: str
    created_at: str
    updated_at: str
    version: int


class DisposalManifest(TypedDict):
    id: str
    warehouse_id: str
    epa_id: str
    reporting_period: str
    created_by_user_id: str
    filed_by_user_id: Optional[str]
    attached_core_return_count: int
    scrapped_lot_count: int
    core_lead_kg: float
    lot_lead_kg: float
    total_lead_kg: float
    rejection_reason: Optional[str]
    filed_at: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int
