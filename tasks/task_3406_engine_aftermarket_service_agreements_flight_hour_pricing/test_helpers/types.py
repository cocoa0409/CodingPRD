"""Domain types: entity TypedDicts, status enums, role enum (PRD §2.1, §2.5, §3)."""
from enum import Enum
from typing import TypedDict, Optional, List, Any


class UserRole(str, Enum):
    PLATFORM_ADMIN = "PlatformAdmin"
    CONTRACT_MANAGER = "ContractManager"
    OPERATOR = "Operator"
    SHOP_PLANNER = "ShopPlanner"
    FINANCE_CONTROLLER = "FinanceController"


class CreditRating(str, Enum):
    A = "A"
    B = "B"
    C = "C"


class SeverityTier(str, Enum):
    BENIGN = "BENIGN"
    MODERATE = "MODERATE"
    HARSH = "HARSH"


class EngineStatus(str, Enum):
    IN_SERVICE = "IN_SERVICE"
    IN_SHOP = "IN_SHOP"


class AgreementStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    RENEGOTIATION = "RENEGOTIATION"
    EXPIRED = "EXPIRED"


class ReportStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    VERIFIED = "VERIFIED"


class StatementStatus(str, Enum):
    ISSUED = "ISSUED"
    SETTLED = "SETTLED"


class ShopVisitStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    INDUCTED = "INDUCTED"
    COMPLETED = "COMPLETED"


class ForecastMethod(str, Enum):
    CYCLE_BASED = "CYCLE_BASED"
    CALENDAR_BASED = "CALENDAR_BASED"


class WorkscopeStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    REOPENED = "REOPENED"
    SUPERSEDED = "SUPERSEDED"


class WorkscopeItemType(str, Enum):
    MANDATORY_DIRECTIVE = "MANDATORY_DIRECTIVE"
    LLP_REPLACEMENT = "LLP_REPLACEMENT"
    MODULE_OVERHAUL = "MODULE_OVERHAUL"
    INSPECTION = "INSPECTION"


class SourcingClass(str, Enum):
    NEW = "NEW"
    REPAIRED = "REPAIRED"
    USM = "USM"


class RequisitionStatus(str, Enum):
    REQUESTED = "REQUESTED"
    SOURCED = "SOURCED"
    ESCALATED = "ESCALATED"
    CANCELLED = "CANCELLED"


class SpareEngineStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    LEASED = "LEASED"


class LeaseStatus(str, Enum):
    RESERVED = "RESERVED"
    ACTIVE = "ACTIVE"
    RETURNED = "RETURNED"
    CANCELLED = "CANCELLED"


class DirectiveType(str, Enum):
    AD = "AD"
    SB = "SB"
    ED = "ED"


# ---------------------------------------------------------------------------
# Entity TypedDicts.
# common_fields entities carry id + created_at + updated_at + version (PRD §2.5);
# append-only records (Directive, RecognitionSnapshot) carry ONLY id + created_at.
# ---------------------------------------------------------------------------


class Operator(TypedDict):
    id: str
    name: str
    iata_code: str
    credit_rating: str
    created_at: str
    updated_at: str
    version: int


class Engine(TypedDict):
    id: str
    operator_id: str
    esn: str
    engine_model: str
    base_severity_tier: str
    cumulative_flight_hours: float
    cumulative_cycles: int
    llp_remaining_cycles: int
    agreement_id: Optional[str]
    assumed_annual_hours: Optional[float]
    assumed_cycles_per_month: Optional[int]
    enrolled_at: Optional[str]
    status: str
    projected_next_removal_date: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ServiceAgreement(TypedDict):
    id: str
    contract_ref: str
    base_rate_per_fh_usd: float
    escalation_pct: float
    escalation_anchor_date: str
    start_date: str
    end_date: str
    allowed_sourcing_classes: List[str]
    max_workscope_cost_usd: float
    status: str
    billed_to_date_usd: float
    enrolled_engine_count: int
    created_at: str
    updated_at: str
    version: int


class FlightHourReport(TypedDict):
    id: str
    engine_id: str
    period: str
    flight_hours: float
    cycles: int
    observed_severity: str
    status: str
    verified_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class BillingLineItem(TypedDict):
    engine_id: str
    hours: float
    effective_rate_per_fh_usd: float
    line_amount_usd: float


class BillingStatement(TypedDict):
    id: str
    agreement_id: str
    period: str
    status: str
    line_items: List[BillingLineItem]
    provisional_total_usd: float
    final_total_usd: Optional[float]
    adjustment_usd: Optional[float]
    created_at: str
    updated_at: str
    version: int


class ShopVisit(TypedDict):
    id: str
    engine_id: str
    planned_induction_date: str
    forecast_induction_date: str
    forecast_method: str
    actual_induction_date: Optional[str]
    completion_date: Optional[str]
    status: str
    projected_cost_usd: float
    committed_parts_cost_usd: float
    created_at: str
    updated_at: str
    version: int


class WorkscopeItem(TypedDict):
    item_code: str
    item_type: str
    estimated_cost_usd: float
    restores_cycles: int
    directive_ref: Optional[str]


class Workscope(TypedDict):
    id: str
    shop_visit_id: str
    scope_version: int
    status: str
    items: List[WorkscopeItem]
    total_cost_usd: float
    restores_llp_cycles: int
    decided_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class PartRequisition(TypedDict):
    id: str
    workscope_id: str
    part_number: str
    quantity: int
    list_price_usd: float
    requested_class: str
    required_by_date: str
    sourced_class: Optional[str]
    unit_cost_usd: Optional[float]
    status: str
    created_at: str
    updated_at: str
    version: int


class SpareEngine(TypedDict):
    id: str
    spare_serial: str
    engine_model: str
    daily_lease_rate_usd: float
    status: str
    created_at: str
    updated_at: str
    version: int


class SpareEngineLease(TypedDict):
    id: str
    spare_engine_id: str
    shop_visit_id: str
    start_date: str
    end_date: str
    status: str
    lease_cost_usd: float
    deposit_usd: float
    created_at: str
    updated_at: str
    version: int


class Directive(TypedDict):
    # Append-only record (PRD §2.5): carries ONLY id + created_at.
    id: str
    directive_ref: str
    directive_type: str
    applicability_model: str
    mandatory: bool
    compliance_cycles: Optional[int]
    compliance_date: Optional[str]
    estimated_cost_usd: float
    created_at: str


class RecognitionSnapshot(TypedDict):
    # Append-only record (PRD §2.5): carries ONLY id + created_at.
    id: str
    agreement_id: str
    lifetime_revenue_projection_usd: float
    lifetime_cost_projection_usd: float
    cost_to_date_usd: float
    recognition_pct: float
    recognized_revenue_projected_usd: float
    recognized_revenue_actual_usd: float
    onerous_loss_accrual_usd: float
    created_at: str
