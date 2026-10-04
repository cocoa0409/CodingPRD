"""Domain types: entity TypedDicts, status enums, and the role enum.

Every resource carries the four system-managed fields ``id``, ``created_at``,
``updated_at`` and ``version`` (PRD §2.5). Fields the PRD describes as "null
until <event>" are typed Optional: they are present on the resource with a
null value, not absent.
"""

from enum import Enum
from typing import Any, Dict, List, Optional, TypedDict


# ── Role enum (PRD §2.1) ────────────────────────────────────────────────────

class UserRole(str, Enum):
    PLATFORM_ADMIN = "PlatformAdmin"
    PROGRAM_MANAGER = "ProgramManager"
    RETAIL_DESIGNER = "RetailDesigner"
    DEALER_REP = "DealerRep"
    PLANT_SCHEDULER = "PlantScheduler"
    LOGISTICS_COORDINATOR = "LogisticsCoordinator"
    CLAIMS_ADJUSTER = "ClaimsAdjuster"
    FIELD_SERVICE_REP = "FieldServiceRep"


# ── Shared value enums ──────────────────────────────────────────────────────

class Channel(str, Enum):
    RETAIL = "RETAIL"
    DEALER = "DEALER"
    BUILDER = "BUILDER"


class PricingClass(str, Enum):
    STANDARD = "STANDARD"
    VOLUME = "VOLUME"
    NATIONAL = "NATIONAL"


class LeadTimeClass(str, Enum):
    STANDARD = "STANDARD"
    EXTENDED = "EXTENDED"


class DestinationType(str, Enum):
    JOB_SITE = "JOB_SITE"
    STORE = "STORE"


class PlantCode(str, Enum):
    PLANT_EAST = "PLANT_EAST"
    PLANT_WEST = "PLANT_WEST"
    PLANT_SOUTH = "PLANT_SOUTH"


class DispositionActionType(str, Enum):
    RTV = "RTV"
    LIQUIDATE = "LIQUIDATE"
    TRANSFER = "TRANSFER"
    DESTROY = "DESTROY"


class ClaimResolution(str, Enum):
    REPLACEMENT = "REPLACEMENT"
    CREDIT = "CREDIT"


# ── Per-entity status enums ─────────────────────────────────────────────────

class AccountStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    CLOSED = "CLOSED"


class ProgramStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    TRANSITIONING = "TRANSITIONING"


class ProgramLineStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUNSETTING = "SUNSETTING"
    RETIRED = "RETIRED"


class FinishBatchStatus(str, Enum):
    CURRENT = "CURRENT"
    RETIRED = "RETIRED"


class DesignJobStatus(str, Enum):
    REQUESTED = "REQUESTED"
    MEASURED = "MEASURED"
    LAYOUT_READY = "LAYOUT_READY"
    QUOTED = "QUOTED"
    CONVERTED = "CONVERTED"
    CANCELLED = "CANCELLED"


class OrderStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    ACKNOWLEDGED = "ACKNOWLEDGED"
    SCHEDULED = "SCHEDULED"
    IN_PRODUCTION = "IN_PRODUCTION"
    MFG_COMPLETE = "MFG_COMPLETE"
    SHIPPED = "SHIPPED"
    DELIVERED = "DELIVERED"
    CANCELLED = "CANCELLED"


class PaymentStatus(str, Enum):
    UNINVOICED = "UNINVOICED"
    CREDIT_HOLD = "CREDIT_HOLD"
    INVOICED = "INVOICED"
    PAID = "PAID"


class ProductionSlotStatus(str, Enum):
    OPEN = "OPEN"
    LOCKED = "LOCKED"


class ShipmentStatus(str, Enum):
    PLANNED = "PLANNED"
    LOADED = "LOADED"
    IN_TRANSIT = "IN_TRANSIT"
    DELIVERED = "DELIVERED"
    FAILED = "FAILED"
    RETURNED = "RETURNED"


class DamageClaimStatus(str, Enum):
    FILED = "FILED"
    UNDER_REVIEW = "UNDER_REVIEW"
    APPROVED = "APPROVED"
    DENIED = "DENIED"


class ReplacementOrderStatus(str, Enum):
    CREATED = "CREATED"
    SCHEDULED = "SCHEDULED"
    IN_PRODUCTION = "IN_PRODUCTION"
    SHIPPED = "SHIPPED"
    RECEIVED = "RECEIVED"
    REMAKE = "REMAKE"
    CANCELLED = "CANCELLED"


class DisplayResetStatus(str, Enum):
    PLANNED = "PLANNED"
    SCHEDULED = "SCHEDULED"
    COMPLETE = "COMPLETE"
    WAIVED = "WAIVED"


# ── Nested payloads ─────────────────────────────────────────────────────────

class FamilySpec(TypedDict):
    family_code: str
    standard_price_cents: int
    base_lead_weeks: int
    complexity_units_per_cabinet: int


class OrderLine(TypedDict, total=False):
    # Input fields
    family_code: str
    finish_code: str
    quantity: int
    # Server-added fields (PRD §3.3)
    unit_quoted_cents: Optional[int]
    unit_invoiced_cents: Optional[int]
    finish_batch_id: Optional[str]
    units: int


class DispositionAction(TypedDict):
    action_type: str
    qty: int
    created_at: str


# ── Entity TypedDicts (all carry id / created_at / updated_at / version) ────

class Account(TypedDict):
    id: str
    name: str
    channel: str
    pricing_class: str
    lead_time_class: str
    credit_limit_cents: int
    store_codes: List[str]
    status: str
    open_exposure_cents: int
    created_at: str
    updated_at: str
    version: int


class Program(TypedDict):
    id: str
    account_id: str
    name: str
    program_discount_pct: float
    status: str
    transition_started_at: Optional[str]
    display_reset_deadline: Optional[str]
    disposition_deadline: Optional[str]
    open_order_count: int
    created_at: str
    updated_at: str
    version: int


class ProgramLine(TypedDict):
    id: str
    program_id: str
    line_code: str
    status: str
    effective_start_week: str
    families: List[Dict[str, Any]]
    supersedes_line_id: Optional[str]
    original_disposition_qty: int
    remaining_disposition_qty: Optional[int]
    disposition_actions: List[Dict[str, Any]]
    created_at: str
    updated_at: str
    version: int


class FinishBatch(TypedDict):
    id: str
    finish_code: str
    batch_code: str
    lab_l: float
    lab_a: float
    lab_b: float
    effective_from: str
    status: str
    created_at: str
    updated_at: str
    version: int


class DesignJob(TypedDict):
    id: str
    account_id: str
    program_id: str
    store_code: str
    designer_user_id: str
    measure_window_start: str
    measure_window_end: str
    layout_lines: Optional[List[Dict[str, Any]]]
    status: str
    revision_count: int
    quoted_total_cents: Optional[int]
    quoted_line_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Order(TypedDict):
    id: str
    account_id: str
    program_id: str
    design_job_id: Optional[str]
    destination_type: str
    store_code: Optional[str]
    jobsite_address: Optional[str]
    requested_delivery_week: str
    lines: List[Dict[str, Any]]
    status: str
    payment_status: str
    promised_delivery_week: Optional[str]
    scheduled_week: Optional[str]
    scheduled_delivery_week: Optional[str]
    quoted_total_cents: Optional[int]
    invoiced_total_cents: Optional[int]
    price_lock: bool
    repricing_required: bool
    created_at: str
    updated_at: str
    version: int


class ProductionSlot(TypedDict):
    id: str
    plant_code: str
    family_code: str
    week: str
    capacity_units: int
    committed_units: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Shipment(TypedDict):
    id: str
    order_id: str
    destination_type: str
    store_code: Optional[str]
    jobsite_address: Optional[str]
    status: str
    attempt_count: int
    delivered_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class DamageClaim(TypedDict):
    id: str
    shipment_id: str
    order_id: str
    line_index: int
    claimed_qty: int
    filed_by_user_id: str
    filed_at: str
    status: str
    resolution: Optional[str]
    settlement_cents: Optional[int]
    decided_by_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ReplacementOrder(TypedDict):
    id: str
    damage_claim_id: str
    order_id: str
    line_index: int
    quantity: int
    finish_batch_id: str
    original_finish_batch_id: str
    status: str
    scheduled_week: Optional[str]
    created_at: str
    updated_at: str
    version: int


class DisplayReset(TypedDict):
    id: str
    program_id: str
    line_id: str
    store_code: str
    status: str
    scheduled_date: Optional[str]
    completed_at: Optional[str]
    completed_late: bool
    created_at: str
    updated_at: str
    version: int
