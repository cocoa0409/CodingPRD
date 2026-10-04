"""Domain types: entity TypedDicts, status enums, and the role enum.

Field names match the PRD exactly. Every entity in this API carries the four
common system properties (id, created_at, updated_at, version) per the PRD's
common-resource-properties section.
"""
from enum import Enum
from typing import Any, Dict, List, Optional, TypedDict


# =============================================================================
# Enums
# =============================================================================

class UserRole(str, Enum):
    """The eleven declared X-User-Role values."""
    PLATFORM_ADMIN = "PlatformAdmin"
    PRODUCTION_PLANNER = "ProductionPlanner"
    QUALITY_INSPECTOR = "QualityInspector"
    COMPLIANCE_OFFICER = "ComplianceOfficer"
    CHARGING_COORDINATOR = "ChargingCoordinator"
    FLEET_MANAGER = "FleetManager"
    SERVICE_DISPATCHER = "ServiceDispatcher"
    SERVICE_TECHNICIAN = "ServiceTechnician"
    CLAIMS_ADJUSTER = "ClaimsAdjuster"
    RELEASE_MANAGER = "ReleaseManager"
    TELEMATICS_INGESTION = "TelematicsIngestion"


class AccountTier(str, Enum):
    STANDARD = "STANDARD"
    PRIORITY = "PRIORITY"


class ChargingProjectStatus(str, Enum):
    SURVEY = "SURVEY"
    UTILITY_REVIEW = "UTILITY_REVIEW"
    REDESIGN = "REDESIGN"
    PERMITTING = "PERMITTING"
    INSTALLATION = "INSTALLATION"
    COMMISSIONED = "COMMISSIONED"
    CANCELLED = "CANCELLED"


class ReadinessTier(str, Enum):
    UNAUDITED = "UNAUDITED"
    A = "A"
    B = "B"
    C = "C"


class BatteryModuleStatus(str, Enum):
    REGISTERED = "REGISTERED"
    IN_QA = "IN_QA"
    PASSED = "PASSED"
    FAILED = "FAILED"
    REWORK = "REWORK"
    QUARANTINED = "QUARANTINED"
    ALLOCATED = "ALLOCATED"
    SCRAPPED = "SCRAPPED"


class VehicleOrderStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    FRANCHISE_HOLD = "FRANCHISE_HOLD"
    CONFIRMED = "CONFIRMED"
    IN_PRODUCTION = "IN_PRODUCTION"
    FULFILLED = "FULFILLED"
    CANCELLED = "CANCELLED"


class DeliveryMethod(str, Enum):
    DIRECT_DELIVERY = "DIRECT_DELIVERY"
    CUSTOMER_PICKUP = "CUSTOMER_PICKUP"


class TelematicsTier(str, Enum):
    STANDARD = "STANDARD"
    ADVANCED = "ADVANCED"


class TelematicsTierScope(str, Enum):
    STANDARD = "STANDARD"
    ADVANCED = "ADVANCED"
    ALL = "ALL"


class VehicleDeliveryStatus(str, Enum):
    ASSEMBLED = "ASSEMBLED"
    IN_TRANSIT = "IN_TRANSIT"
    AT_DEPOT = "AT_DEPOT"
    COMMISSIONED = "COMMISSIONED"


class VehicleTelematicsStatus(str, Enum):
    OFFLINE = "OFFLINE"
    PROVISIONED = "PROVISIONED"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class BatteryEolStatus(str, Enum):
    NONE = "NONE"
    EOL_REVIEW = "EOL_REVIEW"


class ServiceVisitStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class VisitPurpose(str, Enum):
    MAINTENANCE = "MAINTENANCE"
    REPAIR = "REPAIR"
    RECALL = "RECALL"


class CampaignStatus(str, Enum):
    DRAFT = "DRAFT"
    CANARY = "CANARY"
    EXPANDED = "EXPANDED"
    GENERAL = "GENERAL"
    PAUSED = "PAUSED"
    COMPLETE = "COMPLETE"
    ROLLED_BACK = "ROLLED_BACK"


class CampaignResult(str, Enum):
    SUCCESS = "SUCCESS"
    FAILED = "FAILED"


class ProRating(str, Enum):
    ROUTE_DAY = "ROUTE_DAY"
    VEHICLE_HOUR = "VEHICLE_HOUR"


class WarrantyClaimStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    DIAGNOSED = "DIAGNOSED"
    SETTLED = "SETTLED"
    DENIED = "DENIED"


class ComponentClass(str, Enum):
    BATTERY = "BATTERY"
    POWERTRAIN = "POWERTRAIN"
    CHARGING = "CHARGING"
    BODY = "BODY"


class AdjudicateDecision(str, Enum):
    APPROVE = "APPROVE"
    DENY = "DENY"


class TransitionDimension(str, Enum):
    DELIVERY = "DELIVERY"
    TELEMATICS = "TELEMATICS"


# Valid energy-capacity classes for modules and orders (PRD: exactly 52 or 77).
PACK_KWH_VALUES = (52, 77)


# =============================================================================
# Entity TypedDicts (all entities carry id / created_at / updated_at / version)
# =============================================================================

class FleetCustomer(TypedDict, total=False):
    id: str
    company_name: str
    contact_email: str
    account_tier: str
    created_at: str
    updated_at: str
    version: int


class Depot(TypedDict, total=False):
    id: str
    fleet_customer_id: str
    name: str
    state_code: str
    address: str
    total_capacity_kw: float
    committed_capacity_kw: float
    created_at: str
    updated_at: str
    version: int


class ChargingProject(TypedDict, total=False):
    id: str
    depot_id: str
    requested_capacity_kw: float
    install_window_start: str
    install_window_end: str
    crew_count: int
    status: str
    utility_denial_reason: Optional[str]
    commissioned_capacity_kw: Optional[float]
    created_at: str
    updated_at: str
    version: int


class Supplier(TypedDict, total=False):
    id: str
    name: str
    contact_email: str
    readiness_tier: str
    last_on_time_pct: Optional[float]
    last_first_pass_yield_pct: Optional[float]
    open_corrective_actions: Optional[int]
    created_by_user_id: str
    created_at: str
    updated_at: str
    version: int


class BatteryModule(TypedDict, total=False):
    id: str
    supplier_id: str
    module_serial: str
    pack_kwh: int
    quality_status: str
    failure_count: int
    registered_by_user_id: str
    last_inspector_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class VehicleOrder(TypedDict, total=False):
    id: str
    fleet_customer_id: str
    depot_id: str
    battery_supplier_id: str
    quantity: int
    battery_pack_kwh: int
    telematics_tier: str
    delivery_method: str
    requires_depot_charging: bool
    status: str
    exemption_document_ref: Optional[str]
    promised_delivery_date: Optional[str]
    supply_risk_flag: bool
    registered_count: int
    hold_count: int
    created_at: str
    updated_at: str
    version: int


class Vehicle(TypedDict, total=False):
    id: str
    vehicle_order_id: str
    battery_module_id: str
    vin: str
    delivery_status: str
    telematics_status: str
    software_version: str
    software_hold: bool
    current_soh_pct: float
    battery_eol_status: str
    eol_valuation_refurbish_cents: Optional[int]
    eol_valuation_recovery_cents: Optional[int]
    last_battery_report_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ServiceCenter(TypedDict, total=False):
    id: str
    name: str
    region_code: str
    state_code: str
    bay_count: int
    created_at: str
    updated_at: str
    version: int


class MobileVan(TypedDict, total=False):
    id: str
    service_center_id: str
    van_code: str
    created_at: str
    updated_at: str
    version: int


class PartsLine(TypedDict, total=False):
    sku: str
    qty: int


class ServiceVisit(TypedDict, total=False):
    id: str
    vehicle_id: str
    service_center_id: Optional[str]
    mobile_van_id: Optional[str]
    window_start: str
    window_end: str
    purpose: str
    parts_lines: List[Dict[str, Any]]
    status: str
    completed_by_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class PartsStock(TypedDict, total=False):
    id: str
    service_center_id: str
    sku: str
    reorder_threshold: int
    on_hand_qty: int
    reserved_qty: int
    consumed_total_qty: int
    received_total_qty: int
    restock_needed: bool
    created_at: str
    updated_at: str
    version: int


class CampaignResultEntry(TypedDict, total=False):
    vehicle_id: str
    result: str
    reported_at: str


class SoftwareCampaign(TypedDict, total=False):
    id: str
    target_version: str
    telematics_tier_scope: str
    status: str
    paused_from: Optional[str]
    results: List[Dict[str, Any]]
    succeeded_count: int
    failed_count: int
    created_at: str
    updated_at: str
    version: int


class DowntimeEvent(TypedDict, total=False):
    vehicle_id: str
    started_at: str
    ended_at: Optional[str]


class UptimeContract(TypedDict, total=False):
    id: str
    fleet_customer_id: str
    committed_uptime_pct: float
    monthly_service_fee_cents: int
    pro_rating: str
    measurement_start_date: str
    downtime_events: List[Dict[str, Any]]
    last_closed_month: Optional[str]
    last_uptime_pct: Optional[float]
    last_credit_cents: Optional[int]
    lifetime_credit_cents: int
    created_at: str
    updated_at: str
    version: int


class ClaimLine(TypedDict, total=False):
    component_class: str
    part_cost_cents: int
    labor_hours: float


class WarrantyClaim(TypedDict, total=False):
    id: str
    vehicle_id: str
    service_visit_id: Optional[str]
    claim_lines: List[Dict[str, Any]]
    status: str
    diagnosed_by_user_id: Optional[str]
    diagnosis_notes: Optional[str]
    adjudicated_by_user_id: Optional[str]
    settlement_cents: Optional[int]
    denial_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int
