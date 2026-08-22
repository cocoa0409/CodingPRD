"""Domain types: entity TypedDicts, status enums, role enum.

Most resources carry the four common properties described in PRD §2.4 —
``id``, ``created_at``, ``updated_at`` and ``version``.  Four reference kinds
(commodities, compatibility rules, fuel index postings and river stage
readings) are deliberately immutable and carry ONLY ``id`` and ``created_at``.
"""
from enum import Enum
from typing import Any, List, Optional, TypedDict


# ---------------------------------------------------------------------------
# Roles (PRD §2.1)
# ---------------------------------------------------------------------------
class UserRole(str, Enum):
    WATERWAY_ADMIN = "WaterwayAdmin"
    TARIFF_ANALYST = "TariffAnalyst"
    RATE_AUTHORITY = "RateAuthority"
    TOWBOAT_DISPATCHER = "TowboatDispatcher"
    LOCK_MASTER = "LockMaster"
    HARBOR_AGENT = "HarborAgent"
    CONTRACT_MANAGER = "ContractManager"
    CLAIMS_ADJUSTER = "ClaimsAdjuster"
    SHIPPER = "Shipper"


# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------
class CommodityGroup(str, Enum):
    GRAIN = "GRAIN"
    COAL = "COAL"
    CHEMICAL = "CHEMICAL"
    PETROLEUM = "PETROLEUM"
    FERTILIZER = "FERTILIZER"
    AGGREGATE = "AGGREGATE"


class ResidueClass(str, Enum):
    CLEAN = "CLEAN"
    DUSTY = "DUSTY"
    OILY = "OILY"
    TOXIC = "TOXIC"


class CleaningLevel(str, Enum):
    NONE = "NONE"
    SWEEP = "SWEEP"
    WASH = "WASH"
    STEAM_CERT = "STEAM_CERT"


class CleanlinessStatus(str, Enum):
    DIRTY = "DIRTY"
    SWEPT = "SWEPT"
    WASHED = "WASHED"
    STEAM_CERTIFIED = "STEAM_CERTIFIED"


class BargeOperationalStatus(str, Enum):
    IDLE = "IDLE"
    FLEETED = "FLEETED"
    IN_TOW = "IN_TOW"
    OUT_OF_SERVICE = "OUT_OF_SERVICE"


class ShipperStatus(str, Enum):
    ACTIVE = "ACTIVE"
    CREDIT_HOLD = "CREDIT_HOLD"


class TariffFilingStatus(str, Enum):
    DRAFT = "DRAFT"
    FILED = "FILED"
    EFFECTIVE = "EFFECTIVE"
    SUPERSEDED = "SUPERSEDED"


class DraftRestrictionBand(str, Enum):
    HIGH_WATER = "HIGH_WATER"
    NORMAL = "NORMAL"
    LOW = "LOW"
    CRITICAL = "CRITICAL"


class CleaningOrderStatus(str, Enum):
    ORDERED = "ORDERED"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    FAILED_INSPECTION = "FAILED_INSPECTION"


class FleetingAssignmentStatus(str, Enum):
    RESERVED = "RESERVED"
    RELEASED = "RELEASED"
    CANCELLED = "CANCELLED"


class LockStatus(str, Enum):
    OPEN = "OPEN"
    RESTRICTED = "RESTRICTED"
    CLOSED = "CLOSED"


class LockReservationStatus(str, Enum):
    REQUESTED = "REQUESTED"
    GRANTED = "GRANTED"
    IN_CHAMBER = "IN_CHAMBER"
    CLEARED = "CLEARED"
    DENIED = "DENIED"
    CANCELLED = "CANCELLED"


class PriorityClass(str, Enum):
    PRIORITY = "PRIORITY"
    COMMERCIAL = "COMMERCIAL"
    RECREATIONAL = "RECREATIONAL"


class TowStatus(str, Enum):
    BUILDING = "BUILDING"
    SEALED = "SEALED"
    UNDERWAY = "UNDERWAY"
    DELAYED = "DELAYED"
    ARRIVED = "ARRIVED"
    BROKEN_UP = "BROKEN_UP"


class BargeAssignmentStatus(str, Enum):
    PLANNED = "PLANNED"
    CONFIRMED = "CONFIRMED"
    LOADED = "LOADED"
    DISCHARGED = "DISCHARGED"
    DROPPED = "DROPPED"


class DischargeStatus(str, Enum):
    NOT_ARRIVED = "NOT_ARRIVED"
    ARRIVED = "ARRIVED"
    UNLOADING = "UNLOADING"
    COMPLETED = "COMPLETED"
    DISPUTED = "DISPUTED"


class ContractMovementStatus(str, Enum):
    DRAFT = "DRAFT"
    BOOKED = "BOOKED"
    ACTIVE = "ACTIVE"
    IN_TRANSIT = "IN_TRANSIT"
    DISCHARGED = "DISCHARGED"
    CLOSED = "CLOSED"
    CANCELLED = "CANCELLED"


class ContractBillingStatus(str, Enum):
    NOT_BILLED = "NOT_BILLED"
    INVOICED = "INVOICED"
    ADJUSTED = "ADJUSTED"
    PAID = "PAID"
    VOID = "VOID"


class ClaimSettlementBasis(str, Enum):
    DEDUCTIBLE = "DEDUCTIBLE"
    FRANCHISE = "FRANCHISE"


class ClaimType(str, Enum):
    SHORTAGE = "SHORTAGE"
    DAMAGE = "DAMAGE"
    CONTAMINATION = "CONTAMINATION"


class CargoClaimStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    UNDER_REVIEW = "UNDER_REVIEW"
    INFO_REQUESTED = "INFO_REQUESTED"
    ASSESSED = "ASSESSED"
    APPROVED = "APPROVED"
    DENIED = "DENIED"
    WITHDRAWN = "WITHDRAWN"


class ChargeVariant(str, Enum):
    PROVISIONAL = "PROVISIONAL"
    FINAL = "FINAL"


# ---------------------------------------------------------------------------
# Entities carrying the full common-property set (PRD §2.4)
# ---------------------------------------------------------------------------
class Shipper(TypedDict):
    id: str
    name: str
    credit_limit_cents: int
    outstanding_balance_cents: int
    status: str
    open_claim_count: int
    created_at: str
    updated_at: str
    version: int


class TariffFiling(TypedDict):
    id: str
    tariff_code: str
    commodity_group: str
    base_rate_cents_per_ton_mile: float
    min_charge_cents: int
    demurrage_rate_cents_per_hour: int
    fuel_surcharge_table: List[Any]
    effective_from: str
    effective_to: str
    status: str
    filed_by_user_id: Optional[str]
    effectuated_by_user_id: Optional[str]
    supersedes_tariff_filing_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Barge(TypedDict):
    id: str
    hull_number: str
    capacity_tons: int
    light_draft_feet: float
    tons_per_inch_immersion: float
    operational_status: str
    cleanliness_status: str
    last_cargo_commodity_id: Optional[str]
    last_cleaning_certificate_number: Optional[str]
    created_at: str
    updated_at: str
    version: int


class CleaningOrder(TypedDict):
    id: str
    barge_id: str
    required_for_commodity_id: str
    freight_contract_id: Optional[str]
    required_cleaning_level: str
    performed_level: Optional[str]
    inspection_passed: Optional[bool]
    certificate_number: Optional[str]
    status: str
    fee_cents: int
    created_at: str
    updated_at: str
    version: int


class FleetingBerth(TypedDict):
    id: str
    harbor_name: str
    river_mile: float
    capacity_barges: int
    daily_fee_cents_per_barge: int
    switch_fee_cents: int
    occupied_barge_count: int
    created_at: str
    updated_at: str
    version: int


class FleetingAssignment(TypedDict):
    id: str
    barge_id: str
    fleeting_berth_id: str
    freight_contract_id: Optional[str]
    start_at: str
    end_at: str
    released_at: Optional[str]
    status: str
    estimated_fee_cents: int
    billable_days: int
    fee_cents: int
    created_at: str
    updated_at: str
    version: int


class Lock(TypedDict):
    id: str
    lock_name: str
    river_mile: float
    chamber_capacity_barges: int
    cycle_minutes: int
    turnback_buffer_minutes: int
    status: str
    granted_reservation_count: int
    created_at: str
    updated_at: str
    version: int


class LockReservation(TypedDict):
    id: str
    lock_id: str
    tow_id: str
    requested_start_at: str
    cut_count: int
    scheduled_start_at: str
    scheduled_end_at: str
    occupied_until_at: str
    actual_start_at: Optional[str]
    actual_end_at: Optional[str]
    delay_minutes: int
    priority_class: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Tow(TypedDict):
    id: str
    towboat_name: str
    horsepower: int
    origin_mile: float
    destination_mile: float
    controlling_gauge_station: str
    status: str
    barge_count: int
    total_loaded_tons: int
    max_draft_feet: float
    allowed_draft_feet: float
    draft_restriction_band: Optional[str]
    accrued_delay_minutes: int
    pending_lock_reservation_count: int
    departed_at: Optional[str]
    arrived_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class BargeAssignment(TypedDict):
    id: str
    tow_id: str
    barge_id: str
    freight_contract_id: str
    cut_position: int
    loaded_tons: int
    barge_draft_feet: float
    status: str
    discharge_status: str
    arrived_at: Optional[str]
    unload_started_at: Optional[str]
    unload_finished_at: Optional[str]
    discharged_tons: Optional[int]
    gross_laytime_hours: int
    net_laytime_hours: int
    delay_attributed_minutes: int
    created_at: str
    updated_at: str
    version: int


class FreightContract(TypedDict):
    id: str
    shipper_id: str
    commodity_id: str
    contracted_tons: int
    origin_mile: float
    destination_mile: float
    distance_miles: Optional[float]
    laytime_hours: int
    declared_value_cents_per_ton: int
    claim_settlement_basis: str
    pinned_tariff_filing_id: Optional[str]
    pinned_fuel_price_cents_per_gallon: Optional[int]
    pinned_fuel_surcharge_pct: Optional[float]
    movement_status: str
    billing_status: str
    accrued_delay_minutes: int
    delay_protection_applied: bool
    linehaul_cents: int
    fuel_surcharge_cents: int
    fleeting_fee_cents: int
    cleaning_fee_cents: int
    demurrage_cents: int
    subtotal_cents: int
    volume_rebate_cents: int
    claim_credit_cents: int
    total_cents: int
    created_at: str
    updated_at: str
    version: int


class CargoClaim(TypedDict):
    id: str
    freight_contract_id: str
    barge_assignment_id: str
    claim_type: str
    claimed_tons: float
    claimed_amount_cents: int
    shortage_tons: float
    tolerance_tons: float
    settlement_deductible_cents: int
    settlement_franchise_cents: int
    settlement_cents: int
    revision_round: int
    status: str
    assessed_by_user_id: Optional[str]
    approved_by_user_id: Optional[str]
    denial_reason: Optional[str]
    info_request_note: Optional[str]
    response_note: Optional[str]
    created_at: str
    updated_at: str
    version: int


# ---------------------------------------------------------------------------
# Immutable reference records — id + created_at ONLY (PRD §2.4)
# ---------------------------------------------------------------------------
class Commodity(TypedDict):
    id: str
    code: str
    commodity_group: str
    residue_class: str
    hazard_flag: bool
    stowage_factor: float
    created_at: str


class CompatibilityRule(TypedDict):
    id: str
    prior_commodity_group: str
    next_commodity_group: str
    required_cleaning_level: str
    prohibited: bool
    created_at: str


class FuelIndexPosting(TypedDict):
    id: str
    posting_date: str
    diesel_price_cents_per_gallon: int
    created_at: str


class RiverStageReading(TypedDict):
    id: str
    gauge_station: str
    reading_at: str
    stage_feet: float
    draft_restriction_band: str
    max_draft_feet: float
    tow_size_cap_barges: int
    created_at: str


class ChargeBreakdown(TypedDict):
    variant: str
    billable_line_count: int
    linehaul_cents: int
    fuel_surcharge_cents: int
    fleeting_fee_cents: int
    cleaning_fee_cents: int
    demurrage_cents: int
    subtotal_cents: int
    volume_rebate_cents: int
    claim_credit_cents: int
    total_cents: int
