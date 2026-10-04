"""Domain types: entity TypedDicts, status enums, role enum.

Common-field branching follows PRD section 2.5: every primary resource carries
id, created_at, updated_at, and version; TelemetryReading is the single
exception — an append-only measurement carrying only id and created_at, with
updated_at and version absent entirely.
"""
from enum import Enum
from typing import Any, Dict, List, Optional, TypedDict


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class UserRole(str, Enum):
    PLATFORM_ADMIN = "PlatformAdmin"
    SUPPLY_PLANNER = "SupplyPlanner"
    CUSTOMER_OPS = "CustomerOps"
    PLANT_OPERATOR = "PlantOperator"
    PIPELINE_DISPATCHER = "PipelineDispatcher"
    TELEMETRY_GATEWAY = "TelemetryGateway"
    QUALITY_ANALYST = "QualityAnalyst"
    QUALITY_CERTIFIER = "QualityCertifier"
    BILLING_SPECIALIST = "BillingSpecialist"


class CustomerSegment(str, Enum):
    ELECTRONICS = "ELECTRONICS"
    MEDICAL = "MEDICAL"
    METALS = "METALS"
    CHEMICAL = "CHEMICAL"


class CreditStanding(str, Enum):
    PRIME = "PRIME"
    STANDARD = "STANDARD"
    WATCH = "WATCH"


class Product(str, Enum):
    N2 = "N2"
    O2 = "O2"
    H2 = "H2"
    AR = "AR"
    HE = "HE"


class SupplyMode(str, Enum):
    ONSITE_PLANT = "ONSITE_PLANT"
    PIPELINE = "PIPELINE"
    BULK_LIQUID = "BULK_LIQUID"
    CYLINDER = "CYLINDER"


class EvaluationStatus(str, Enum):
    EVALUATED = "EVALUATED"
    ACCEPTED = "ACCEPTED"
    SUPERSEDED = "SUPERSEDED"


class ContractStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    RENEWAL_OPEN = "RENEWAL_OPEN"
    EXPIRED = "EXPIRED"
    TERMINATED = "TERMINATED"


class PlantStatus(str, Enum):
    PROPOSED = "PROPOSED"
    UNDER_CONSTRUCTION = "UNDER_CONSTRUCTION"
    COMMISSIONING = "COMMISSIONING"
    OPERATING = "OPERATING"
    TURNAROUND = "TURNAROUND"
    DECOMMISSIONED = "DECOMMISSIONED"


class ConnectionStatus(str, Enum):
    ACTIVE = "ACTIVE"
    RELEASED = "RELEASED"


class ConnectionPurpose(str, Enum):
    PRIMARY = "PRIMARY"
    BACKUP = "BACKUP"


class TankStatus(str, Enum):
    NORMAL = "NORMAL"
    REORDER_DUE = "REORDER_DUE"
    CRITICAL = "CRITICAL"


class TransportStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    DELIVERED = "DELIVERED"
    COMPLETED = "COMPLETED"
    REJECTED = "REJECTED"
    CANCELLED = "CANCELLED"


class QualityStatus(str, Enum):
    QC_PENDING = "QC_PENDING"
    CERTIFIED = "CERTIFIED"
    FAILED = "FAILED"


class DeliveryTrigger(str, Enum):
    TELEMETRY = "TELEMETRY"
    BACKUP = "BACKUP"
    REDELIVERY = "REDELIVERY"


class CertificateResult(str, Enum):
    RECORDED = "RECORDED"
    CERTIFIED = "CERTIFIED"
    FAILED = "FAILED"


class CertifyDecision(str, Enum):
    CERTIFIED = "CERTIFIED"
    FAILED = "FAILED"


class TurnaroundStatus(str, Enum):
    PROPOSED = "PROPOSED"
    AGREED = "AGREED"
    SCHEDULED = "SCHEDULED"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class RespondDecision(str, Enum):
    AGREE = "AGREE"
    COUNTER = "COUNTER"


class SettlementVariant(str, Enum):
    PROVISIONAL = "PROVISIONAL"
    FINAL = "FINAL"


class SettlementStatus(str, Enum):
    PROVISIONAL = "PROVISIONAL"
    FINAL = "FINAL"
    SUPERSEDED = "SUPERSEDED"


class AmendmentKind(str, Enum):
    AMENDMENT = "AMENDMENT"
    RENEWAL = "RENEWAL"


# ---------------------------------------------------------------------------
# Entity TypedDicts (response shapes)
# ---------------------------------------------------------------------------

class Customer(TypedDict, total=False):
    id: str
    name: str
    segment: str
    credit_standing: str
    blackout_windows: List[Dict[str, str]]
    created_at: str
    updated_at: str
    version: int


class SupplyModeEvaluation(TypedDict, total=False):
    id: str
    customer_id: str
    site_label: str
    demand_avg_nm3h: float
    demand_peak_nm3h: float
    required_purity_percent: float
    required_product: str
    pipeline_available: bool
    recommended_mode: str
    status: str
    created_at: str
    updated_at: str
    version: int


class SupplyContract(TypedDict, total=False):
    id: str
    customer_id: str
    evaluation_id: str
    mode: str
    product: str
    site_label: str
    term_months: int
    start_date: str
    end_date: str
    min_monthly_volume_nm3: int
    unit_price_cents_per_nm3: int
    monthly_facility_fee_cents: int
    facility_fee_escalation_pct_annual: float
    base_power_index: float
    power_kwh_per_nm3: float
    makeup_credit_cap_pct: float
    makeup_credit_balance_cents: int
    failover_active: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class OnsitePlant(TypedDict, total=False):
    id: str
    contract_id: str
    customer_id: str
    name: str
    nameplate_capacity_nm3h: int
    capital_cost_cents: int
    power_kwh_per_nm3: float
    status: str
    effective_capacity_nm3h: int
    created_at: str
    updated_at: str
    version: int


class PipelineNetwork(TypedDict, total=False):
    id: str
    name: str
    nameplate_capacity_nm3h: int
    reserved_capacity_nm3h: int
    available_capacity_nm3h: int
    created_at: str
    updated_at: str
    version: int


class PipelineConnection(TypedDict, total=False):
    id: str
    network_id: str
    contract_id: str
    reserved_flow_nm3h: int
    purpose: str
    status: str
    created_at: str
    updated_at: str
    version: int


class StorageTank(TypedDict, total=False):
    id: str
    customer_id: str
    site_label: str
    product: str
    capacity_liters: int
    reorder_point_liters: int
    safety_stock_liters: int
    required_purity_percent: float
    max_impurity_ppm: int
    current_level_liters: Optional[int]
    last_reading_at: Optional[str]
    burn_rate_instant_lph: Optional[float]
    burn_rate_wma_lph: Optional[float]
    projected_runout_instant_at: Optional[str]
    projected_runout_wma_at: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class TelemetryReading(TypedDict, total=False):
    # Append-only (PRD section 2.5): carries ONLY id + created_at among the
    # system-managed fields — updated_at and version are absent entirely.
    id: str
    tank_id: str
    measured_at: str
    level_liters: int
    created_at: str


class Delivery(TypedDict, total=False):
    id: str
    tank_id: str
    customer_id: str
    product: str
    quantity_liters: int
    triggered_by: str
    route_date: str
    route_code: str
    stop_sequence: int
    required_purity_percent: float
    max_impurity_ppm: int
    transport_status: str
    quality_status: str
    delivered_quantity_liters: Optional[int]
    confirmed_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class QualityCertificate(TypedDict, total=False):
    id: str
    delivery_id: str
    sampled_at: str
    measured_purity_percent: float
    measured_impurity_ppm: int
    analyst_user_id: str
    certifier_user_id: Optional[str]
    result: str
    decided_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Turnaround(TypedDict, total=False):
    id: str
    plant_id: str
    window_start: str
    window_end: str
    scope: str
    proposal_round: int
    status: str
    created_at: str
    updated_at: str
    version: int


class SettlementStatement(TypedDict, total=False):
    id: str
    contract_id: str
    period_month: str
    variant: str
    metered_volume_nm3: Optional[int]
    projected_volume_nm3: Optional[int]
    power_index_actual: Optional[float]
    apply_makeup_cents: Optional[int]
    months_elapsed: int
    escalation_multiplier: float
    billable_volume_nm3: int
    volume_charge_cents: int
    power_passthrough_cents: int
    facility_fee_cents: int
    capital_recovery_cents: int
    subtotal_cents: int
    shortfall_volume_nm3: int
    makeup_credit_granted_cents: int
    makeup_credit_applied_cents: int
    total_due_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


__all__ = [
    "UserRole",
    "CustomerSegment",
    "CreditStanding",
    "Product",
    "SupplyMode",
    "EvaluationStatus",
    "ContractStatus",
    "PlantStatus",
    "ConnectionStatus",
    "ConnectionPurpose",
    "TankStatus",
    "TransportStatus",
    "QualityStatus",
    "DeliveryTrigger",
    "CertificateResult",
    "CertifyDecision",
    "TurnaroundStatus",
    "RespondDecision",
    "SettlementVariant",
    "SettlementStatus",
    "AmendmentKind",
    "Customer",
    "SupplyModeEvaluation",
    "SupplyContract",
    "OnsitePlant",
    "PipelineNetwork",
    "PipelineConnection",
    "StorageTank",
    "TelemetryReading",
    "Delivery",
    "QualityCertificate",
    "Turnaround",
    "SettlementStatement",
]
