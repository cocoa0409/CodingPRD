"""Domain types: entity TypedDicts, status enums, role enum.

Field names mirror the PRD exactly. Lifecycle-bearing entities carry a
system-managed ``status``; CargoSlot carries the two parallel status
dimensions ``lift_status`` and ``billing_status``.
"""
from enum import Enum
from typing import Optional, TypedDict


class SpaStatus(str, Enum):
    EXECUTED = "EXECUTED"
    DELIVERIES_COMMENCED = "DELIVERIES_COMMENCED"
    EXPIRED = "EXPIRED"


class TrainStatus(str, Enum):
    CONSTRUCTION = "CONSTRUCTION"
    COMMISSIONING = "COMMISSIONING"
    COMMERCIAL_OPERATION = "COMMERCIAL_OPERATION"
    TURNAROUND = "TURNAROUND"
    DECOMMISSIONED = "DECOMMISSIONED"


class AdpStatus(str, Enum):
    DRAFT = "DRAFT"
    PROPOSED = "PROPOSED"
    CONFIRMED = "CONFIRMED"
    LOCKED = "LOCKED"
    SUPERSEDED = "SUPERSEDED"


class SlotLiftStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    VESSEL_NOMINATED = "VESSEL_NOMINATED"
    BERTH_ASSIGNED = "BERTH_ASSIGNED"
    LOADED = "LOADED"
    CANCELLED = "CANCELLED"
    RESCHEDULED = "RESCHEDULED"


class SlotBillingStatus(str, Enum):
    UNBILLED = "UNBILLED"
    PROVISIONALLY_INVOICED = "PROVISIONALLY_INVOICED"
    FINAL_INVOICED = "FINAL_INVOICED"


class BerthStatus(str, Enum):
    IN_SERVICE = "IN_SERVICE"
    OUT_OF_SERVICE = "OUT_OF_SERVICE"


class VesselCallStatus(str, Enum):
    NOMINATED = "NOMINATED"
    ACCEPTED = "ACCEPTED"
    NOR_TENDERED = "NOR_TENDERED"
    BERTHED = "BERTHED"
    DEPARTED = "DEPARTED"
    SUPERSEDED = "SUPERSEDED"


class LaytimeStatementStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    AGREED = "AGREED"
    DISPUTED = "DISPUTED"
    RESOLVED = "RESOLVED"


class PipelineStatus(str, Enum):
    IN_SERVICE = "IN_SERVICE"
    OUTAGE = "OUTAGE"


class ScheduleStatus(str, Enum):
    OPEN = "OPEN"
    CLOSED = "CLOSED"


class NominationStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    CONFIRMED = "CONFIRMED"
    CUT = "CUT"
    RECONCILED = "RECONCILED"


class CancellationStatus(str, Enum):
    REGISTERED = "REGISTERED"
    SETTLED = "SETTLED"


class ResaleStatus(str, Enum):
    OFFERED = "OFFERED"
    SOLD = "SOLD"
    UNSOLD = "UNSOLD"


class TurnaroundStatus(str, Enum):
    PROPOSED = "PROPOSED"
    APPROVED = "APPROVED"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class UserRole(str, Enum):
    TERMINAL_OPERATOR = "TerminalOperator"
    COMMERCIAL_MANAGER = "CommercialManager"
    GAS_SCHEDULER = "GasScheduler"
    MARINE_SCHEDULER = "MarineScheduler"
    CUSTOMER_REP = "CustomerRep"


class CreditRating(str, Enum):
    AAA = "AAA"
    AA = "AA"
    A = "A"
    BBB = "BBB"


class CommodityIndex(str, Enum):
    HENRY_HUB = "HENRY_HUB"
    TTF = "TTF"
    JKM = "JKM"


class DestinationFlexibility(str, Enum):
    FOB = "FOB"
    DES = "DES"


class TitleTransferPoint(str, Enum):
    LOADING_FLANGE = "LOADING_FLANGE"
    DISCHARGE_PORT = "DISCHARGE_PORT"


class BillingBasis(str, Enum):
    SOF_BASIS = "SOF_BASIS"
    PUMP_LOG_BASIS = "PUMP_LOG_BASIS"


class Customer(TypedDict, total=False):
    id: str
    legal_name: str
    credit_rating: str
    billing_currency: str
    created_at: str
    updated_at: str
    version: int


class SalesPurchaseAgreement(TypedDict, total=False):
    id: str
    customer_id: str
    contract_year_start: int
    term_years: int
    annual_contract_quantity_mmbtu: int
    fixed_liquefaction_fee_usd_per_mmbtu: float
    commodity_multiplier: float
    commodity_index: str
    destination_flexibility: str
    title_transfer_point: str
    cancellation_notice_days: int
    tolerance_pct: float
    estimated_index_price_usd_per_mmbtu: float
    status: str
    created_at: str
    updated_at: str
    version: int


class LiquefactionTrain(TypedDict, total=False):
    id: str
    name: str
    design_capacity_mtpa: float
    daily_capacity_mmbtu: int
    commissioning_cargoes_required: int
    commissioning_cargoes_completed: int
    cod_date: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class AnnualDeliveryProgram(TypedDict, total=False):
    id: str
    spa_id: str
    contract_year: int
    revision_no: int
    status: str
    scheduled_quantity_mmbtu: int
    cancelled_quantity_mmbtu: int
    unallocated_quantity_mmbtu: int
    delivered_equivalent_mmbtu: Optional[int]
    shortfall_mmbtu: Optional[int]
    deficiency_amount_usd: Optional[float]
    created_at: str
    updated_at: str
    version: int


class CargoSlot(TypedDict, total=False):
    id: str
    adp_id: str
    window_start: str
    window_end: str
    quantity_mmbtu: int
    lift_status: str
    billing_status: str
    scheduled_feed_gas_mmbtu: int
    provisional_invoice_usd: Optional[float]
    final_invoice_usd: Optional[float]
    created_at: str
    updated_at: str
    version: int


class Berth(TypedDict, total=False):
    id: str
    name: str
    max_loa_m: float
    max_dwt_t: int
    status: str
    created_at: str
    updated_at: str
    version: int


class VesselCall(TypedDict, total=False):
    id: str
    cargo_slot_id: str
    berth_id: Optional[str]
    vessel_name: str
    imo_number: str
    vessel_loa_m: float
    vessel_dwt_t: int
    demurrage_rate_usd_per_day: float
    status: str
    window_start: Optional[str]
    window_end: Optional[str]
    nor_tendered_at: Optional[str]
    berthed_at: Optional[str]
    departed_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class LaytimeStatement(TypedDict, total=False):
    id: str
    vessel_call_id: str
    billing_basis: str
    excluded_periods: Optional[list]
    pump_hours: Optional[float]
    laytime_start_at: Optional[str]
    allowed_laytime_hours: Optional[float]
    elapsed_hours: Optional[float]
    used_laytime_hours_sof: Optional[float]
    used_laytime_hours_pumplog: Optional[float]
    demurrage_amount_sof_usd: Optional[float]
    demurrage_amount_pumplog_usd: Optional[float]
    billed_demurrage_usd: Optional[float]
    adjusted_demurrage_usd: Optional[float]
    status: str
    created_at: str
    updated_at: str
    version: int


class Pipeline(TypedDict, total=False):
    id: str
    name: str
    daily_capacity_mmbtu: int
    status: str
    created_at: str
    updated_at: str
    version: int


class PipelineDaySchedule(TypedDict, total=False):
    id: str
    pipeline_id: str
    gas_day: str
    capacity_mmbtu: int
    status: str
    total_nominated_mmbtu: int
    total_confirmed_mmbtu: int
    total_cut_mmbtu: int
    created_at: str
    updated_at: str
    version: int


class FeedGasNomination(TypedDict, total=False):
    id: str
    pipeline_day_schedule_id: str
    cargo_slot_id: str
    nominated_mmbtu: int
    confirmed_mmbtu: int
    cut_mmbtu: int
    status: str
    created_at: str
    updated_at: str
    version: int


class CargoCancellation(TypedDict, total=False):
    id: str
    cargo_slot_id: str
    cancelled_at: str
    notice_days_provided: int
    fixed_fee_due_usd: float
    resale_credit_usd: float
    net_due_usd: float
    status: str
    created_at: str
    updated_at: str
    version: int


class FeedGasResale(TypedDict, total=False):
    id: str
    cargo_cancellation_id: str
    offered_volume_mmbtu: int
    status: str
    sale_price_usd_per_mmbtu: Optional[float]
    gross_proceeds_usd: Optional[float]
    created_at: str
    updated_at: str
    version: int


class MaintenanceTurnaround(TypedDict, total=False):
    id: str
    train_id: str
    planned_start_date: str
    planned_end_date: str
    status: str
    proposed_by_user_id: str
    approved_by_user_id: Optional[str]
    lost_production_mmbtu: Optional[int]
    shifted_cargo_slot_count: Optional[int]
    created_at: str
    updated_at: str
    version: int
