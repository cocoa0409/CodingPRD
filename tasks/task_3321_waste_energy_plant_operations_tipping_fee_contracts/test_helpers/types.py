"""Domain types: entity TypedDicts, status enums, role enum.

All entities carry common fields (id, created_at, updated_at, version).
"""
from enum import Enum
from typing import TypedDict, Optional


class UserRole(str, Enum):
    PLANT_OPERATOR = "PlantOperator"
    CONTRACTS_MANAGER = "ContractsManager"
    ENERGY_TRADER = "EnergyTrader"
    ENVIRONMENTAL_OFFICER = "EnvironmentalOfficer"
    REGULATOR = "Regulator"


class AgreementState(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    EXPIRED = "EXPIRED"
    TERMINATED = "TERMINATED"


class DeliveryStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    RECEIVED = "RECEIVED"
    REJECTED = "REJECTED"
    DIVERTED = "DIVERTED"
    ACCEPTED = "ACCEPTED"


class BoilerStatus(str, Enum):
    ONLINE = "ONLINE"
    OUTAGE = "OUTAGE"
    DERATED = "DERATED"
    OFFLINE = "OFFLINE"


class OutageStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    ACTIVE = "ACTIVE"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class ReportStatus(str, Enum):
    DRAFT = "DRAFT"
    FINALIZED = "FINALIZED"


class CapacityCheck(str, Enum):
    OK = "OK"
    EXCEEDS = "EXCEEDS"


class PpaStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    EXPIRED = "EXPIRED"
    TERMINATED = "TERMINATED"


class PpaKind(str, Enum):
    PPA = "PPA"
    MERCHANT = "MERCHANT"


class ContractStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    TERMINATED = "TERMINATED"


class BatchStatus(str, Enum):
    RECORDED = "RECORDED"
    SETTLED = "SETTLED"
    DISPUTED = "DISPUTED"


class LandfillStatus(str, Enum):
    ACTIVE = "ACTIVE"
    CLOSED = "CLOSED"


class ShipmentStatus(str, Enum):
    PLANNED = "PLANNED"
    TEST_PENDING = "TEST_PENDING"
    DISPOSED = "DISPOSED"
    REJECTED = "REJECTED"


class PermitStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    EXPIRED = "EXPIRED"


class SettlementCadence(str, Enum):
    ANNUAL = "ANNUAL"
    MONTHLY = "MONTHLY"


class OutageKind(str, Enum):
    PLANNED = "PLANNED"
    EMERGENCY = "EMERGENCY"


class Municipality(TypedDict, total=False):
    id: str
    legal_name: str
    population_served: int
    is_host_community: bool
    priority_group: str
    created_at: str
    updated_at: str
    version: int


class HostCommunityAgreement(TypedDict, total=False):
    id: str
    municipality_id: str
    annual_payment_cents: int
    payment_due_month: int
    local_waste_priority_enabled: bool
    effective_start: str
    effective_end: str
    created_at: str
    updated_at: str
    version: int


class WasteSupplyAgreement(TypedDict, total=False):
    id: str
    municipality_id: str
    term_start: str
    term_end: str
    guaranteed_annual_tonnage: float
    tipping_fee_per_tonne_cents: int
    put_or_pay_settlement_cadence: str
    state: str
    amendment_of_agreement_id: Optional[str]
    cumulative_delivered_tonnes: float
    created_at: str
    updated_at: str
    version: int


class WasteDelivery(TypedDict, total=False):
    id: str
    agreement_id: str
    manifest_ref: str
    tonnes: float
    heating_value_mj_per_kg: float
    delivered_at: str
    status: str
    tipping_fee_cents: Optional[int]
    projected_fee_cents: Optional[int]
    diversion_outage_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Boiler(TypedDict, total=False):
    id: str
    name: str
    max_thermal_capacity_mw: float
    max_steam_tph: float
    status: str
    derated_capacity_mw: Optional[float]
    created_at: str
    updated_at: str
    version: int


class OutageWindow(TypedDict, total=False):
    id: str
    boiler_id: str
    starts_at: str
    ends_at: str
    reason: str
    kind: str
    status: str
    created_at: str
    updated_at: str
    version: int


class DiversionPlan(TypedDict, total=False):
    id: str
    outage_id: str
    approved: bool
    max_diversion_tpd: float
    planned_diverted_tonnes: float
    created_at: str
    updated_at: str
    version: int


class DiversionLeg(TypedDict, total=False):
    id: str
    diversion_plan_id: str
    receiving_facility_name: str
    planned_tonnes: float
    executed: bool
    created_at: str
    updated_at: str
    version: int


class DailyThroughputReport(TypedDict, total=False):
    id: str
    report_date: str
    waste_processed_tonnes: float
    avg_heating_value_mj_per_kg: float
    operating_hours: float
    thermal_input_mw: float
    steam_output_tph: float
    ash_generated_tonnes: float
    capacity_check: str
    status: str
    created_at: str
    updated_at: str
    version: int


class PowerPurchaseAgreement(TypedDict, total=False):
    id: str
    counterparty_name: str
    kind: str
    energy_rate_cents_per_mwh: int
    capacity_payment_cents_per_mw_month: int
    contracted_mw: float
    term_start: str
    term_end: str
    status: str
    created_at: str
    updated_at: str
    version: int


class EnergyDelivery(TypedDict, total=False):
    id: str
    ppa_id: str
    period_start: str
    period_end: str
    delivered_mwh: float
    merchant_price_cents_per_mwh: Optional[int]
    billed_amount_cents: int
    capacity_payment_cents: int
    created_at: str
    updated_at: str
    version: int


class MetalsRecoveryContract(TypedDict, total=False):
    id: str
    processor_name: str
    ferrous_recovery_pct: float
    nonferrous_recovery_pct: float
    processing_fee_cents_per_tonne: int
    status: str
    created_at: str
    updated_at: str
    version: int


class MetalsRecoveryBatch(TypedDict, total=False):
    id: str
    contract_id: str
    ash_input_tonnes: float
    ferrous_price_cents_per_tonne: int
    nonferrous_price_cents_per_tonne: int
    ferrous_tonnes: float
    nonferrous_tonnes: float
    gross_revenue_cents: int
    processing_fee_cents: int
    net_settlement_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Landfill(TypedDict, total=False):
    id: str
    name: str
    permit_number: str
    remaining_capacity_tonnes: float
    daily_receipt_limit_tonnes: float
    status: str
    created_at: str
    updated_at: str
    version: int


class AshShipment(TypedDict, total=False):
    id: str
    landfill_id: str
    tonnes: float
    shipped_on: str
    disposal_fee_cents_per_tonne: int
    status: str
    created_at: str
    updated_at: str
    version: int


class AshTest(TypedDict, total=False):
    id: str
    shipment_id: str
    parameter: str
    measured_value: float
    limit_value: float
    passed: bool
    recorded_at: str
    created_at: str
    updated_at: str
    version: int


class EmissionsPermit(TypedDict, total=False):
    id: str
    pollutant: str
    hourly_limit: float
    daily_limit: float
    rolling_avg_window_hours: int
    status: str
    created_at: str
    updated_at: str
    version: int


class EmissionsReading(TypedDict, total=False):
    id: str
    permit_id: str
    value: float
    measured_at: str
    exceedance: bool
    created_at: str
    updated_at: str
    version: int
