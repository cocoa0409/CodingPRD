"""Domain types: entity TypedDicts, status enums, role enum (PRD §2.6, §2.7)."""
from enum import Enum
from typing import Any, Dict, List, Optional, TypedDict


class CampaignStatus(str, Enum):
    DRAFT = "DRAFT"
    LIVE = "LIVE"
    CLOSED_SUCCESS = "CLOSED_SUCCESS"
    CLOSED_FAILED = "CLOSED_FAILED"
    IN_PRODUCTION = "IN_PRODUCTION"
    FULFILLING = "FULFILLING"
    COMPLETE = "COMPLETE"
    CANCELLED = "CANCELLED"


class ChargeStatus(str, Enum):
    PENDING = "PENDING"
    CHARGED = "CHARGED"
    CHARGE_FAILED = "CHARGE_FAILED"
    REFUNDED = "REFUNDED"


class AddressStatus(str, Enum):
    UNCONFIRMED = "UNCONFIRMED"
    CONFIRMED = "CONFIRMED"
    LOCKED = "LOCKED"


class FulfillmentStatus(str, Enum):
    QUEUED = "QUEUED"
    WAVE_ASSIGNED = "WAVE_ASSIGNED"
    PICKED = "PICKED"
    SHIPPED = "SHIPPED"
    DELIVERED = "DELIVERED"


class QuoteStatus(str, Enum):
    PROVISIONAL = "PROVISIONAL"
    SUBMITTED = "SUBMITTED"
    FINAL = "FINAL"
    SUPERSEDED = "SUPERSEDED"


class ProductionRunStatus(str, Enum):
    QUOTED = "QUOTED"
    LOCKED = "LOCKED"
    IN_PRODUCTION = "IN_PRODUCTION"
    SHIPPED = "SHIPPED"
    CANCELLED = "CANCELLED"


class FreightStatus(str, Enum):
    BOOKED = "BOOKED"
    IN_TRANSIT = "IN_TRANSIT"
    CUSTOMS_HOLD = "CUSTOMS_HOLD"
    DUTY_ASSESSED = "DUTY_ASSESSED"
    CLEARED = "CLEARED"
    DELIVERED = "DELIVERED"


class DutyVariant(str, Enum):
    DECLARED_VALUE = "DECLARED_VALUE"
    TRANSACTION_VALUE = "TRANSACTION_VALUE"


class WaveStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    OPEN = "OPEN"
    CLOSED = "CLOSED"
    DISPATCHED = "DISPATCHED"
    CANCELLED = "CANCELLED"


class AllocationStatus(str, Enum):
    RESERVED = "RESERVED"
    CONFIRMED = "CONFIRMED"
    SHIPPED = "SHIPPED"
    RELEASED = "RELEASED"


class ReplacementStatus(str, Enum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    SHIPPED = "SHIPPED"


class LocalizationStatus(str, Enum):
    NEGOTIATING = "NEGOTIATING"
    SIGNED = "SIGNED"
    PRINTED = "PRINTED"
    TERMINATED = "TERMINATED"


class ReprintStatus(str, Enum):
    PROPOSED = "PROPOSED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    LOCKED = "LOCKED"


class RegionCode(str, Enum):
    NA = "NA"
    EU = "EU"
    APAC = "APAC"
    ROW = "ROW"


class UserRole(str, Enum):
    CAMPAIGN_OWNER = "CampaignOwner"
    BACKER = "Backer"
    FACTORY_COORDINATOR = "FactoryCoordinator"
    FREIGHT_BROKER = "FreightBroker"
    CUSTOMS_AGENT = "CustomsAgent"
    FULFILLMENT_OPERATOR = "FulfillmentOperator"
    DISTRIBUTOR = "Distributor"
    LOCALIZATION_PARTNER = "LocalizationPartner"
    PLATFORM_ADMIN = "PlatformAdmin"


class PledgeLevel(TypedDict, total=False):
    name: str
    price_cents: int
    contents: List[str]
    quantity_cap: Optional[int]
    late_pledge_premium_pct: float
    status: str


class StretchGoal(TypedDict, total=False):
    goal_id: str
    threshold_cents: int
    target_pledge_level_name: str
    bonus_component_sku: str
    status: str
    unlocked_at: Optional[str]


class AddOnCatalogEntry(TypedDict, total=False):
    sku: str
    price_cents: int
    per_backer_cap: int
    status: str


class Campaign(TypedDict, total=False):
    id: str
    title: str
    owner_user_id: str
    goal_cents: int
    currency: str
    closes_at: str
    pledge_levels: List[PledgeLevel]
    stretch_goals: List[StretchGoal]
    add_on_catalog: List[AddOnCatalogEntry]
    gross_charged_cents: int
    platform_fee_cents: int
    payment_fee_cents: int
    customs_duty_paid_cents: int
    net_payable_cents: int
    total_backers_charged: int
    retail_release_at: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class Pledge(TypedDict, total=False):
    id: str
    campaign_id: str
    backer_user_id: str
    backer_email: str
    region_code: str
    pledge_level_name: str
    is_late_pledge: bool
    add_on_lines: List[Dict[str, Any]]
    pledge_total_cents: int
    charge_status: str
    address_status: str
    fulfillment_status: str
    assigned_wave_id: Optional[str]
    address_locked_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class TierBreak(TypedDict):
    min_units: int
    unit_price_cents: int


class ManufacturingQuote(TypedDict, total=False):
    id: str
    campaign_id: str
    factory_name: str
    tier_breaks: List[TierBreak]
    provisional_units: int
    provisional_unit_price_cents: int
    final_units: Optional[int]
    final_unit_price_cents: Optional[int]
    status: str
    created_at: str
    updated_at: str
    version: int


class ProductionRun(TypedDict, total=False):
    id: str
    campaign_id: str
    quote_id: str
    planned_units: Optional[int]
    spare_units_by_region: Dict[str, int]
    status: str
    created_at: str
    updated_at: str
    version: int


class FreightShipment(TypedDict, total=False):
    id: str
    production_run_id: str
    region_code: str
    container_count: int
    declared_value_cents: int
    departs_at: str
    arrives_at: str
    customs_duty_cents: Optional[int]
    cost_cents: Optional[int]
    duty_variant_used: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class WaveAssignment(TypedDict, total=False):
    pledge_id: str
    status: str  # ASSIGNED | REASSIGNED | REMOVED


class Wave(TypedDict, total=False):
    id: str
    campaign_id: str
    region_code: str
    sequence_index: int
    capacity: int
    assignments: List[WaveAssignment]
    capacity_used: int
    dispatch_window_start: str
    dispatch_window_end: str
    address_lock_at: str
    status: str
    created_at: str
    updated_at: str
    version: int


class DistributorAllocation(TypedDict, total=False):
    id: str
    campaign_id: str
    distributor_user_id: str
    distributor_name: str
    region_code: str
    msrp_positioning_pct: float
    allocation_priority: int
    production_run_id: str
    units_reserved: int
    status: str
    created_at: str
    updated_at: str
    version: int


class ReplacementRequest(TypedDict, total=False):
    id: str
    campaign_id: str
    pledge_id: str
    component_sku: str
    quantity: int
    region_code: str
    spare_units_debited: int
    status: str
    created_at: str
    updated_at: str
    version: int


class LocalizationAgreement(TypedDict, total=False):
    id: str
    campaign_id: str
    partner_name: str
    language_code: str
    royalty_pct: float
    print_commitment_units: int
    print_window_start: str
    print_window_end: str
    status: str
    created_at: str
    updated_at: str
    version: int


class ReprintDecision(TypedDict, total=False):
    id: str
    campaign_id: str
    proposed_units: int
    demand_signal_cents: int
    inventory_risk_score: int
    status: str
    created_at: str
    updated_at: str
    version: int
