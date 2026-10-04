"""Domain types: entity shapes, status enums, and the role enum.

Every top-level resource carries the common system fields of PRD section
2.5 - ``id``, ``created_at``, ``updated_at`` and ``version`` - so every
TypedDict below includes them.  Enum members are spelled exactly as the PRD
spells them; the string values are what travels on the wire.
"""

from enum import Enum
from typing import Any, Dict, List, Optional, TypedDict


# --- Roles (PRD section 2.1) -------------------------------------------------
class UserRole(str, Enum):
    PLATFORM_ADMIN = "PlatformAdmin"
    ACCOUNT_MANAGER = "AccountManager"
    LAB_PROCUREMENT = "LabProcurement"
    SERVICE_DISPATCHER = "ServiceDispatcher"
    FIELD_ENGINEER = "FieldEngineer"
    SUPPLY_OPS = "SupplyOps"


# --- Account ------------------------------------------------------------------
class AccountSegment(str, Enum):
    ACADEMIC = "ACADEMIC"
    PHARMA = "PHARMA"
    CLINICAL = "CLINICAL"
    INDUSTRIAL = "INDUSTRIAL"


class PriorityClass(str, Enum):
    STANDARD = "STANDARD"
    PRIORITY = "PRIORITY"
    CRITICAL = "CRITICAL"


class AccountStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    CLOSED = "CLOSED"


class CreditStatus(str, Enum):
    GOOD = "GOOD"
    HOLD = "HOLD"


class Account(TypedDict):
    id: str
    name: str
    segment: str
    priority_class: str
    territory_code: str
    controlled_substance_license: bool
    status: str
    credit_status: str
    outstanding_balance_cents: int
    trailing_spend_cents: int
    created_at: str
    updated_at: str
    version: int


# --- EnterpriseAgreement -------------------------------------------------------
class AgreementStatus(str, Enum):
    ACTIVE = "ACTIVE"
    EXPIRING = "EXPIRING"
    EXPIRED = "EXPIRED"
    TERMINATED = "TERMINATED"


class AgreementTier(str, Enum):
    BASE = "BASE"
    SILVER = "SILVER"
    GOLD = "GOLD"
    PLATINUM = "PLATINUM"


class EnterpriseAgreement(TypedDict):
    id: str
    account_id: str
    start_date: str
    end_date: str
    committed_annual_spend_cents: int
    status: str
    current_tier: str
    discount_pct: int
    renewal_count: int
    terminated_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


# --- Instrument -----------------------------------------------------------------
class PlacementType(str, Enum):
    CAPITAL = "CAPITAL"
    REAGENT_RENTAL = "REAGENT_RENTAL"
    LEASE = "LEASE"


class PlacementStatus(str, Enum):
    ORDERED = "ORDERED"
    INSTALLED = "INSTALLED"
    DECOMMISSIONED = "DECOMMISSIONED"


class OperationalStatus(str, Enum):
    UP = "UP"
    DOWN = "DOWN"


class Instrument(TypedDict):
    id: str
    account_id: str
    model: str
    serial_number: str
    placement_type: str
    monthly_consumable_commitment_cents: int
    monthly_baseline_consumable_cents: int
    placement_status: str
    operational_status: str
    installed_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


# --- ServiceContract ------------------------------------------------------------
class ContractTier(str, Enum):
    BRONZE = "BRONZE"
    SILVER = "SILVER"
    GOLD = "GOLD"
    PLATINUM = "PLATINUM"


class ContractStatus(str, Enum):
    ACTIVE = "ACTIVE"
    RENEWAL_DUE = "RENEWAL_DUE"
    EXPIRED = "EXPIRED"
    CANCELLED = "CANCELLED"


class ServiceContract(TypedDict):
    id: str
    instrument_id: str
    tier: str
    response_hours: int
    pm_visits_per_year: int
    parts_coverage_pct: int
    loaner_eligible: bool
    monthly_value_cents: int
    start_date: str
    end_date: str
    status: str
    used_pm_visits: int
    renewal_count: int
    cancelled_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


# --- Engineer ---------------------------------------------------------------------
class EngineerSkill(str, Enum):
    BREAK_FIX = "BREAK_FIX"
    PM = "PM"
    APP_SUPPORT = "APP_SUPPORT"
    METHOD_DEV = "METHOD_DEV"
    INSTALL = "INSTALL"


class EngineerStatus(str, Enum):
    ACTIVE = "ACTIVE"
    INACTIVE = "INACTIVE"


class Engineer(TypedDict):
    id: str
    name: str
    territory_code: str
    skills: List[str]
    status: str
    open_ticket_count: int
    created_at: str
    updated_at: str
    version: int


# --- ServiceRequest -----------------------------------------------------------------
class RequestType(str, Enum):
    BREAK_FIX = "BREAK_FIX"
    PREVENTIVE_MAINTENANCE = "PREVENTIVE_MAINTENANCE"
    APP_SUPPORT = "APP_SUPPORT"
    METHOD_DEV = "METHOD_DEV"


class Severity(str, Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class RequestStatus(str, Enum):
    OPEN = "OPEN"
    DISPATCHED = "DISPATCHED"
    RESOLVED = "RESOLVED"


class ServiceRequest(TypedDict):
    id: str
    instrument_id: str
    engineer_id: Optional[str]
    loaner_unit_id: Optional[str]
    request_type: str
    severity: str
    scheduled_for: Optional[str]
    status: str
    opened_at: str
    response_deadline: str
    resolved_at: Optional[str]
    sla_breached: bool
    hours_on_site: Optional[float]
    parts_cost_cents: int
    billable_cents: int
    covered_cents: int
    credit_memo_cents: int
    created_at: str
    updated_at: str
    version: int


# --- LoanerUnit -----------------------------------------------------------------------
class LoanerStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    RESERVED = "RESERVED"


class LoanerUnit(TypedDict):
    id: str
    model: str
    serial_number: str
    status: str
    created_at: str
    updated_at: str
    version: int


# --- CatalogItem -----------------------------------------------------------------------
class ItemClass(str, Enum):
    STANDARD = "STANDARD"
    COLD_CHAIN = "COLD_CHAIN"
    HAZARDOUS = "HAZARDOUS"
    CONTROLLED = "CONTROLLED"


class AllocationGroup(str, Enum):
    GROUP_A = "GROUP_A"
    GROUP_B = "GROUP_B"
    GROUP_C = "GROUP_C"


class CatalogItem(TypedDict):
    id: str
    sku: str
    name: str
    item_class: str
    allocation_group: str
    base_price_cents: int
    stock_on_hand: int
    reserved_quantity: int
    available_stock: int
    created_at: str
    updated_at: str
    version: int


# --- Order ------------------------------------------------------------------------------
class OrderStatus(str, Enum):
    DRAFT = "DRAFT"
    ALLOCATED = "ALLOCATED"
    BACKORDERED = "BACKORDERED"
    SHIPPED = "SHIPPED"
    DELIVERED = "DELIVERED"
    CANCELLED = "CANCELLED"


class OrderLine(TypedDict):
    sku: str
    quantity: int


class Order(TypedDict):
    id: str
    account_id: str
    lines: List[Dict[str, Any]]
    status: str
    shipping_class: Optional[str]
    handling_fee_cents: int
    discount_pct: int
    goods_subtotal_cents: int
    total_cents: int
    total_quantity: int
    allocation_score: Optional[float]
    submitted_at: Optional[str]
    shipped_at: Optional[str]
    delivered_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


# --- SurgeEvent ---------------------------------------------------------------------------
class SurgeStatus(str, Enum):
    ACTIVE = "ACTIVE"
    RESOLVED = "RESOLVED"


class SurgeEvent(TypedDict):
    id: str
    allocation_group: str
    reason: str
    status: str
    started_at: str
    resolved_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


# --- Pull-through projection payload (PRD section 3.3) --------------------------------------
class PullThroughProjection(TypedDict):
    installed_base_monthly_cents: int
    forward_looking_monthly_cents: int
    installed_instrument_count: int
    ordered_instrument_count: int
