"""Domain types: entity TypedDicts, status enums, role enum.

Every resource carries the common system-managed fields (id, created_at,
updated_at, version) described in PRD §2.4; nullable fields are Optional.
"""
from enum import Enum
from typing import List, Optional, TypedDict


# ---------------------------------------------------------------------------
# Roles (PRD §2.1)
# ---------------------------------------------------------------------------
class UserRole(str, Enum):
    CORPORATE_ADMIN = "CorporateAdmin"
    DISTRIBUTOR_MANAGER = "DistributorManager"
    COURSE_MANAGER = "CourseManager"
    IRRIGATION_DEALER = "IrrigationDealer"


# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------
class DistributorChannel(str, Enum):
    EQUIPMENT = "EQUIPMENT"
    IRRIGATION = "IRRIGATION"


class DistributorStatus(str, Enum):
    ONBOARDING = "ONBOARDING"
    ACTIVE = "ACTIVE"
    PROBATION = "PROBATION"
    SUSPENDED = "SUSPENDED"
    TERMINATED = "TERMINATED"


class CertLevel(str, Enum):
    APPRENTICE = "APPRENTICE"
    JOURNEYMAN = "JOURNEYMAN"
    MASTER = "MASTER"


class CertStatus(str, Enum):
    CERT_PENDING = "CERT_PENDING"
    CERT_ACTIVE = "CERT_ACTIVE"
    CERT_EXPIRED = "CERT_EXPIRED"


class TurfProfile(str, Enum):
    BENTGRASS = "BENTGRASS"
    BERMUDA = "BERMUDA"
    POA_ANNUA = "POA_ANNUA"
    MIXED = "MIXED"


class CutQualityStandard(str, Enum):
    CHAMPIONSHIP = "CHAMPIONSHIP"
    CLUB = "CLUB"
    MAINTENANCE = "MAINTENANCE"


class GolfCourseStatus(str, Enum):
    PROSPECT = "PROSPECT"
    ACTIVE_LEASE = "ACTIVE_LEASE"
    IN_RENEWAL = "IN_RENEWAL"


class ModelCategory(str, Enum):
    MOWER = "MOWER"
    UTILITY_VEHICLE = "UTILITY_VEHICLE"
    AERATOR = "AERATOR"
    IRRIGATION_CONTROLLER = "IRRIGATION_CONTROLLER"


class ModelTier(str, Enum):
    TOURNAMENT = "TOURNAMENT"
    PRO = "PRO"
    STANDARD = "STANDARD"


class ModelLifecycleStatus(str, Enum):
    CATALOG_ACTIVE = "CATALOG_ACTIVE"
    DISCONTINUED = "DISCONTINUED"


class PartSupportStatus(str, Enum):
    ACTIVE = "ACTIVE"
    LAST_BUY = "LAST_BUY"
    DISCONTINUED = "DISCONTINUED"
    SUPERSEDED = "SUPERSEDED"


class OrderType(str, Enum):
    STOCK = "STOCK"
    CUSTOMER = "CUSTOMER"


class PartsOrderStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    ALLOCATED = "ALLOCATED"
    SHIPPED = "SHIPPED"
    RECEIVED = "RECEIVED"
    CANCELLED = "CANCELLED"


class FleetLeaseStatus(str, Enum):
    DRAFT = "DRAFT"
    SPEC_REVIEW = "SPEC_REVIEW"
    APPROVED = "APPROVED"
    ACTIVE = "ACTIVE"
    TURNOVER_IN_PROGRESS = "TURNOVER_IN_PROGRESS"
    CLOSED = "CLOSED"
    CANCELLED = "CANCELLED"


class ConditionGrade(str, Enum):
    A = "A"
    B = "B"
    C = "C"
    D = "D"


class LeaseUnitStatus(str, Enum):
    ORDERED = "ORDERED"
    DELIVERED = "DELIVERED"
    IN_SERVICE = "IN_SERVICE"
    RETURN_REQUESTED = "RETURN_REQUESTED"
    RETURNED = "RETURNED"
    REMARKET_LISTED = "REMARKET_LISTED"
    RESERVED = "RESERVED"
    SOLD = "SOLD"
    RETIRED = "RETIRED"


class AppraisalPolicy(str, Enum):
    BOOK = "BOOK"
    MARKET = "MARKET"


class AppraisalStatus(str, Enum):
    VALUED = "VALUED"
    ACCEPTED = "ACCEPTED"
    DISPUTED = "DISPUTED"
    VOIDED = "VOIDED"
    CREDITED = "CREDITED"


class WarrantyClaimStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    UNDER_REVIEW = "UNDER_REVIEW"
    APPROVED = "APPROVED"
    PARTIAL_APPROVED = "PARTIAL_APPROVED"
    DENIED = "DENIED"
    DISPUTED = "DISPUTED"
    PAID = "PAID"


class IrrigationProjectStatus(str, Enum):
    BRIEF = "BRIEF"
    DESIGN_SUBMITTED = "DESIGN_SUBMITTED"
    APPROVED = "APPROVED"
    INSTALLED = "INSTALLED"
    COMMISSIONED = "COMMISSIONED"
    CANCELLED = "CANCELLED"


# ---------------------------------------------------------------------------
# Entity TypedDicts (all resources carry id/created_at/updated_at/version)
# ---------------------------------------------------------------------------
class Distributor(TypedDict, total=False):
    id: str
    name: str
    territory_codes: List[str]
    channel: str
    min_parts_stock_value_cents: int
    labor_rate_cents: int
    annual_claim_cap_cents: int
    status: str
    fill_rate: float
    stock_value_trailing_cents: int
    committed_parts_cents: int
    service_credit_balance_cents: int
    claims_paid_ytd_cents: int
    created_at: str
    updated_at: str
    version: int


class Technician(TypedDict, total=False):
    id: str
    distributor_id: str
    full_name: str
    cert_level: Optional[str]
    cert_status: str
    cert_expires_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class GolfCourse(TypedDict, total=False):
    id: str
    name: str
    turf_profile: str
    cut_quality_standard: str
    credit_limit_cents: int
    assigned_distributor_id: str
    status: str
    created_at: str
    updated_at: str
    version: int


class EquipmentModel(TypedDict, total=False):
    id: str
    model_code: str
    category: str
    tier: str
    list_price_cents: int
    eligible_turf_types: List[str]
    factory_warranty_months: int
    warranty_labor_hourly_cap_cents: int
    parts_support_years: int
    lifecycle_status: str
    created_at: str
    updated_at: str
    version: int


class Part(TypedDict, total=False):
    id: str
    sku: str
    name: str
    primary_model_id: str
    unit_cost_cents: int
    min_stock_qty: int
    support_status: str
    superseded_by_part_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class PartsOrderLine(TypedDict):
    part_id: str
    qty: int


class PartsOrder(TypedDict, total=False):
    id: str
    distributor_id: str
    order_type: str
    lines: List[PartsOrderLine]
    off_season_applied: bool
    discount_tier_pct: float
    subtotal_cents: int
    discount_cents: int
    total_cents: int
    ordered_units: int
    received_units: int
    status: str
    created_at: str
    updated_at: str
    version: int


class LeaseLine(TypedDict):
    model_id: str
    qty: int


class FleetLease(TypedDict, total=False):
    id: str
    course_id: str
    distributor_id: str
    cycle_months: int
    start_date: str
    end_date: str
    lines: List[LeaseLine]
    spec_compliant: Optional[bool]
    base_value_cents: Optional[int]
    total_contract_value_cents: Optional[int]
    trade_in_credit_cents: Optional[int]
    net_contract_value_cents: Optional[int]
    monthly_rate_cents: Optional[int]
    billed_to_date_cents: Optional[int]
    remaining_balance_cents: Optional[int]
    status: str
    created_at: str
    updated_at: str
    version: int


class LeaseUnit(TypedDict, total=False):
    id: str
    lease_id: str
    model_id: str
    unit_seq: int
    serial_number: Optional[str]
    hours_used: Optional[int]
    condition_grade: Optional[str]
    delivered_at: Optional[str]
    returned_at: Optional[str]
    asking_price_cents: Optional[int]
    floor_price_cents: Optional[int]
    sale_price_cents: Optional[int]
    reserved_by_course_id: Optional[str]
    reservation_expires_at: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class TradeInAppraisal(TypedDict, total=False):
    id: str
    lease_id: str
    model_id: str
    external_serial: str
    hours: int
    condition_grade: str
    policy: str
    book_value_cents: int
    market_value_cents: int
    valued_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class WarrantyClaim(TypedDict, total=False):
    id: str
    distributor_id: str
    lease_unit_id: str
    technician_id: str
    labor_hours: float
    parts_cost_cents: int
    claimed_labor_cents: int
    factory_allowance_cents: int
    approved_labor_hours: Optional[float]
    adjudicated_labor_cents: Optional[int]
    parts_reimbursed_cents: Optional[int]
    payable_total_cents: Optional[int]
    paid_at: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class IrrigationProject(TypedDict, total=False):
    id: str
    dealer_id: str
    course_id: str
    acreage: int
    zone_count: int
    controller_model_id: Optional[str]
    controllers_required: Optional[int]
    design_fee_cents: Optional[int]
    water_budget_gpd: Optional[int]
    install_window_start: Optional[str]
    install_window_end: Optional[str]
    pinned_config_version: Optional[int]
    controller_program_version: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int
