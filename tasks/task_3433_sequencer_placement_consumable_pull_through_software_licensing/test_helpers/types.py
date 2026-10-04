"""Domain types: entity TypedDicts, status enums, role enum (PRD sections 2.1, 2.5, 3.x)."""
from enum import Enum
from typing import Any, Dict, List, Optional, TypedDict

__all__ = [
    "UserRole",
    "RegulatoryClass",
    "SupportStatus",
    "RunMode",
    "FlowCellVersion",
    "ChemistryVersion",
    "RegulatoryClearance",
    "ColdChainClass",
    "ClinicalValidationStatus",
    "ReleaseState",
    "InstallState",
    "InstrumentEventAction",
    "ProgramState",
    "ReviewAction",
    "AmendmentAction",
    "QcStatus",
    "ColdChainStatus",
    "QcOutcome",
    "OrderState",
    "OrderAction",
    "ContractState",
    "LicenseState",
    "LicenseStatusAction",
    "CreditEntryType",
    "GrantType",
    "AnalysisMode",
    "RunOutcome",
    "TransitionProgramState",
    "TransitionAction",
    "ConditionFlag",
    "ForecastState",
    "ForecastAction",
    "Account",
    "InstrumentModel",
    "ReagentKit",
    "SoftwareUpdate",
    "ServiceWindow",
    "Instrument",
    "HardwareLine",
    "PendingAmendment",
    "PlacementProgram",
    "ReagentLot",
    "OrderLine",
    "LineReservation",
    "ReagentOrder",
    "ServiceContract",
    "CreditLedgerEntry",
    "SoftwareLicense",
    "RunRecord",
    "TransitionProgram",
    "ForecastLine",
    "VarianceLine",
    "SupplyForecast",
    "UptimeReconciliationResult",
    "BillingCloseResult",
    "ClockSetResult",
]


# ---------------------------------------------------------------------------
# Role enum (PRD section 2.1)
# ---------------------------------------------------------------------------
class UserRole(str, Enum):
    PLATFORM_ADMIN = "PlatformAdmin"
    ACCOUNT_MANAGER = "AccountManager"
    FINANCE_ADMIN = "FinanceAdmin"
    FIELD_SERVICE_ENGINEER = "FieldServiceEngineer"
    SUPPLY_PLANNER = "SupplyPlanner"
    LAB_OPERATOR = "LabOperator"


# ---------------------------------------------------------------------------
# Entity field enums
# ---------------------------------------------------------------------------
class RegulatoryClass(str, Enum):
    RUO = "RUO"
    CLINICAL = "CLINICAL"


class SupportStatus(str, Enum):
    CURRENT = "CURRENT"
    SUNSET = "SUNSET"
    OBSOLETE = "OBSOLETE"


class RunMode(str, Enum):
    STD_SHORT = "STD_SHORT"
    STD_LONG = "STD_LONG"
    HIGH_OUTPUT = "HIGH_OUTPUT"


class FlowCellVersion(str, Enum):
    FC_LOW = "FC_LOW"
    FC_MID = "FC_MID"
    FC_HIGH = "FC_HIGH"


class ChemistryVersion(str, Enum):
    V1 = "V1"
    V2 = "V2"
    V3 = "V3"


class RegulatoryClearance(str, Enum):
    RUO_ONLY = "RUO_ONLY"
    IVD = "IVD"


class ColdChainClass(str, Enum):
    FROZEN_20 = "FROZEN_20"
    REFRIGERATED_4 = "REFRIGERATED_4"


class ClinicalValidationStatus(str, Enum):
    VALIDATED = "VALIDATED"
    NOT_VALIDATED = "NOT_VALIDATED"


class ReleaseState(str, Enum):
    RELEASED = "RELEASED"
    WITHDRAWN = "WITHDRAWN"


class InstallState(str, Enum):
    ORDERED = "ORDERED"
    SHIPPED = "SHIPPED"
    INSTALLED = "INSTALLED"
    OPERATIONAL = "OPERATIONAL"
    DOWN_FOR_SERVICE = "DOWN_FOR_SERVICE"
    DECOMMISSIONED = "DECOMMISSIONED"


class InstrumentEventAction(str, Enum):
    SHIP = "SHIP"
    INSTALL = "INSTALL"
    COMMISSION = "COMMISSION"
    SERVICE_OPEN = "SERVICE_OPEN"
    SERVICE_CLOSE = "SERVICE_CLOSE"
    DECOMMISSION = "DECOMMISSION"


class ProgramState(str, Enum):
    DRAFT = "DRAFT"
    PENDING_APPROVAL = "PENDING_APPROVAL"
    ACTIVE = "ACTIVE"
    UNDER_AMENDMENT = "UNDER_AMENDMENT"
    COMPLETED = "COMPLETED"
    BREACHED = "BREACHED"


class ReviewAction(str, Enum):
    SUBMIT = "SUBMIT"
    APPROVE = "APPROVE"
    REJECT = "REJECT"


class AmendmentAction(str, Enum):
    CREATE = "CREATE"
    APPROVE = "APPROVE"
    REJECT = "REJECT"


class QcStatus(str, Enum):
    PENDING_QC = "PENDING_QC"
    QC_PASSED = "QC_PASSED"
    QC_FAILED = "QC_FAILED"
    EXPIRED = "EXPIRED"


class ColdChainStatus(str, Enum):
    INTACT = "INTACT"
    BREACHED = "BREACHED"


class QcOutcome(str, Enum):
    PASSED = "PASSED"
    FAILED = "FAILED"
    COLD_CHAIN_BREACH = "COLD_CHAIN_BREACH"


class OrderState(str, Enum):
    DRAFT = "DRAFT"
    ALLOCATED = "ALLOCATED"
    BACKORDERED = "BACKORDERED"
    SHIPPED = "SHIPPED"
    DELIVERED = "DELIVERED"
    CANCELLED = "CANCELLED"
    RETURNED = "RETURNED"


class OrderAction(str, Enum):
    SUBMIT = "SUBMIT"
    SHIP = "SHIP"
    DELIVER = "DELIVER"
    CANCEL = "CANCEL"
    RETURN = "RETURN"


class ContractState(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    EXPIRED = "EXPIRED"
    TERMINATED = "TERMINATED"


class LicenseState(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class LicenseStatusAction(str, Enum):
    ACTIVATE = "ACTIVATE"
    SUSPEND = "SUSPEND"
    REINSTATE = "REINSTATE"


class CreditEntryType(str, Enum):
    GRANT = "GRANT"
    PURCHASE = "PURCHASE"
    CONSUMPTION = "CONSUMPTION"
    OFFSET = "OFFSET"
    EXPIRY = "EXPIRY"


class GrantType(str, Enum):
    GRANT = "GRANT"
    PURCHASE = "PURCHASE"


class AnalysisMode(str, Enum):
    LOCAL = "LOCAL"
    CLOUD_STANDARD = "CLOUD_STANDARD"
    CLOUD_DEEP = "CLOUD_DEEP"


class RunOutcome(str, Enum):
    SUCCESS = "SUCCESS"
    PARTIAL = "PARTIAL"
    FAILED = "FAILED"


class TransitionProgramState(str, Enum):
    ENROLLED = "ENROLLED"
    APPRAISED = "APPRAISED"
    COMPLETED = "COMPLETED"
    EXPIRED = "EXPIRED"


class TransitionAction(str, Enum):
    APPRAISE = "APPRAISE"
    COMPLETE = "COMPLETE"


class ConditionFlag(str, Enum):
    COSMETIC_DAMAGE = "COSMETIC_DAMAGE"
    FUNCTIONAL_DEFECT = "FUNCTIONAL_DEFECT"
    MISSING_ACCESSORIES = "MISSING_ACCESSORIES"


class ForecastState(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    FROZEN = "FROZEN"
    SUPERSEDED = "SUPERSEDED"


class ForecastAction(str, Enum):
    SUBMIT = "SUBMIT"
    FREEZE = "FREEZE"


# ---------------------------------------------------------------------------
# Entity TypedDicts.
# Every entity except RunRecord carries the common fields id / created_at /
# updated_at / version (PRD section 2.5). RunRecord is an immutable event
# record and carries ONLY id and created_at from the common set.
# ---------------------------------------------------------------------------
class Account(TypedDict):
    id: str
    name: str
    regulatory_class: str
    region: str
    credit_hold: bool
    credit_balance_cents: int
    created_at: str
    updated_at: str
    version: int


class InstrumentModel(TypedDict):
    id: str
    model_code: str
    generation: int
    base_price_cents: int
    supported_chemistry_versions: List[str]
    base_run_modes: List[str]
    support_status: str
    created_at: str
    updated_at: str
    version: int


class ReagentKit(TypedDict):
    id: str
    kit_code: str
    run_type: str
    flow_cell_version: str
    chemistry_version: str
    regulatory_clearance: str
    shelf_life_days: int
    cold_chain_class: str
    price_cents: int
    samples_per_kit: int
    min_model_generation: int
    capacity_gb: float
    created_at: str
    updated_at: str
    version: int


class SoftwareUpdate(TypedDict):
    id: str
    update_version: str
    min_model_generation: int
    unlocks_run_modes: List[str]
    clinical_validation_status: str
    release_state: str
    created_at: str
    updated_at: str
    version: int


class ServiceWindow(TypedDict):
    opened_at: str
    closed_at: Optional[str]


class Instrument(TypedDict):
    id: str
    account_id: str
    model_id: str
    serial_number: str
    regulatory_mode: str
    installed_at: Optional[str]
    install_state: str
    software_version: str
    applied_update_ids: List[str]
    unlocked_run_modes: List[str]
    service_windows: List[ServiceWindow]
    decommissioned_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class HardwareLine(TypedDict):
    description: str
    quantity: int
    unit_price_cents: int


class PendingAmendment(TypedDict):
    new_committed_annual_reagent_cents: Optional[int]
    new_subsidy_pct: Optional[float]
    created_by_user_id: str


class PlacementProgram(TypedDict):
    id: str
    account_id: str
    term_months: int
    committed_annual_reagent_cents: int
    subsidy_pct: float
    hardware_lines: List[HardwareLine]
    program_state: str
    subsidy_pool_cents: int
    pinned_kit_prices: Dict[str, int]
    committed_total_cents: int
    delivered_spend_cents: int
    pipeline_spend_cents: int
    shortfall_flag: bool
    penalty_cents: int
    period_index: int
    created_by_user_id: str
    approved_by_user_id: Optional[str]
    pending_amendment: Optional[PendingAmendment]
    created_at: str
    updated_at: str
    version: int


class ReagentLot(TypedDict):
    id: str
    kit_id: str
    lot_number: str
    manufacture_date: str
    quantity_units: int
    qc_status: str
    cold_chain_status: str
    expiry_date: str
    reserved_units: int
    consumed_units: int
    available_units: int
    created_at: str
    updated_at: str
    version: int


class OrderLine(TypedDict):
    kit_code: str
    quantity: int


class LineReservation(TypedDict):
    kit_code: str
    lot_id: str
    quantity: int


class ReagentOrder(TypedDict):
    id: str
    account_id: str
    program_id: Optional[str]
    lines: List[OrderLine]
    order_state: str
    total_cents: int
    attributed_total_cents: int
    line_reservations: List[LineReservation]
    submitted_at: Optional[str]
    delivered_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ServiceContract(TypedDict):
    id: str
    account_id: str
    instrument_id: str
    coverage_start: str
    coverage_end: str
    committed_uptime_percent: float
    monthly_fee_cents: int
    annual_credit_cap_cents: int
    reagent_guarantee: bool
    contract_state: str
    credits_issued_ytd_cents: int
    last_reconciliation_end: Optional[str]
    terminated_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class CreditLedgerEntry(TypedDict):
    entry_type: str
    credits: int
    granted_on: Optional[str]
    created_at: str


class SoftwareLicense(TypedDict):
    id: str
    account_id: str
    license_state: str
    activated_at: Optional[str]
    pinned_sample_rate_cents: Optional[Dict[str, int]]
    credit_ledger: List[CreditLedgerEntry]
    credits_balance: int
    samples_this_period: int
    period_index: int
    created_at: str
    updated_at: str
    version: int


class RunRecord(TypedDict):
    # Immutable event record: NO updated_at, NO version (PRD section 2.5).
    id: str
    instrument_id: str
    lot_id: str
    license_id: str
    run_at: str
    run_mode: str
    analysis_mode: str
    samples_count: int
    output_gb: float
    outcome: str
    credits_consumed: int
    created_at: str


class TransitionProgram(TypedDict):
    id: str
    account_id: str
    old_instrument_id: str
    new_model_id: str
    enrollment_window_end: str
    program_state: str
    provisional_credit_cents: int
    condition_flags: List[str]
    final_credit_cents: Optional[int]
    created_by_user_id: str
    appraised_by_user_id: Optional[str]
    appraised_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ForecastLine(TypedDict):
    kit_code: str
    week_start: str
    quantity: int


class VarianceLine(TypedDict):
    kit_code: str
    week_start: str
    forecast_quantity: int
    actual_delivered_units: int
    variance: int
    coverage_optimistic_units: int
    coverage_conservative_units: int


class SupplyForecast(TypedDict):
    id: str
    account_id: str
    lines: List[ForecastLine]
    forecast_state: str
    variance_lines: List[VarianceLine]
    created_at: str
    updated_at: str
    version: int


# ---------------------------------------------------------------------------
# Non-entity response payloads
# ---------------------------------------------------------------------------
class UptimeReconciliationResult(TypedDict):
    downtime_minutes: int
    uptime_percent: float
    credit_cents: int
    credits_issued_ytd_cents: int


class BillingCloseResult(TypedDict):
    billable_samples: int
    tier: str
    gross_cents: int
    expired_credits: int
    offset_credits: int
    offset_cents: int
    net_cents: int
    credits_balance: int
    provisional_samples: int
    provisional_gross_cents: int


class ClockSetResult(TypedDict):
    current_utc: str
    lots_expired: int
    contracts_expired: int
    transitions_expired: int
