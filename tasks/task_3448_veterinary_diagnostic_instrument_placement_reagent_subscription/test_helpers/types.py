"""Domain types: entity TypedDicts, status enums, role enum.

All shapes mirror the PRD's resource narratives (PRD §2.5, §3.1-§3.9).
LabResult is the one immutable record (PRD §2.5): it carries only
``id`` + ``created_at`` of the common fields — its TypedDict deliberately
omits ``updated_at`` and ``version``.
"""
from enum import Enum
from typing import TypedDict, Optional, List

__all__ = [
    "UserRole", "GroupType", "GroupPricingAgreementStatus", "ClinicStatus",
    "AnalyzerModel", "ProgramType", "AgreementStatus", "OperationalStatus",
    "ConnectivityStatus", "ProficiencyStanding", "ReagentOrderStatus",
    "PeriodStatus", "BillingStatus", "TestOrderOrigin", "TestOrderKind",
    "LabTestOrderStatus", "DeliveryStatus", "LabResultSource",
    "ProficiencyVerdict", "ServiceCaseType", "ServiceCaseStatus",
    "ServiceCaseAction", "LabTestOrderAction", "PriceSource", "SkuFamily",
    "SkuOverride", "OrderLine", "PricingDetailLine",
    "GroupPricingAgreement", "Clinic", "PlacementAgreement", "Analyzer",
    "ReagentOrder", "CommitmentPeriod", "LabTestOrder", "LabResult",
    "ServiceCase",
]


# ---------------------------------------------------------------------------
# Role enum (PRD §2.1 — exactly five roles)
# ---------------------------------------------------------------------------
class UserRole(str, Enum):
    PLATFORM_ADMIN = "PlatformAdmin"
    FINANCE_REVIEWER = "FinanceReviewer"
    CLINIC_MANAGER = "ClinicManager"
    FIELD_SERVICE_ENGINEER = "FieldServiceEngineer"
    LABORATORY_TECHNICIAN = "LaboratoryTechnician"


# ---------------------------------------------------------------------------
# Status / field enums (PRD §3 narratives)
# ---------------------------------------------------------------------------
class GroupType(str, Enum):
    CORPORATE = "CORPORATE"
    BUYING = "BUYING"


class GroupPricingAgreementStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    EXPIRED = "EXPIRED"


class ClinicStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    TERMINATED = "TERMINATED"


class AnalyzerModel(str, Enum):
    VETCHEM_300 = "VETCHEM_300"
    VETHEMAT_500 = "VETHEMAT_500"
    VETURINE_200 = "VETURINE_200"


class ProgramType(str, Enum):
    PURCHASE = "PURCHASE"
    LEASE = "LEASE"
    REAGENT_COMMITMENT = "REAGENT_COMMITMENT"


class AgreementStatus(str, Enum):
    DRAFT = "DRAFT"
    APPROVED = "APPROVED"
    ACTIVE = "ACTIVE"
    RENEGOTIATION = "RENEGOTIATION"
    BREACHED = "BREACHED"
    COMPLETED = "COMPLETED"


class OperationalStatus(str, Enum):
    INSTALLED = "INSTALLED"
    IN_SERVICE = "IN_SERVICE"
    UNDER_SERVICE = "UNDER_SERVICE"
    ON_LOAN = "ON_LOAN"
    DECOMMISSIONED = "DECOMMISSIONED"


class ConnectivityStatus(str, Enum):
    NOT_CONFIGURED = "NOT_CONFIGURED"
    ACTIVE = "ACTIVE"
    DEGRADED = "DEGRADED"


class ProficiencyStanding(str, Enum):
    LAPSED = "LAPSED"
    CURRENT = "CURRENT"


class ReagentOrderStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    FULFILLED = "FULFILLED"
    CANCELLED = "CANCELLED"


class PeriodStatus(str, Enum):
    OPEN = "OPEN"
    CLOSED = "CLOSED"


class BillingStatus(str, Enum):
    NONE = "NONE"
    ISSUED = "ISSUED"
    PAID = "PAID"
    WAIVED = "WAIVED"


class TestOrderOrigin(str, Enum):
    IN_CLINIC = "IN_CLINIC"
    SEND_OUT = "SEND_OUT"


class TestOrderKind(str, Enum):
    PATIENT = "PATIENT"
    PROFICIENCY = "PROFICIENCY"


class LabTestOrderStatus(str, Enum):
    ORDERED = "ORDERED"
    RECEIVED = "RECEIVED"
    RESULT_RECORDED = "RESULT_RECORDED"
    DELIVERED = "DELIVERED"
    CANCELLED = "CANCELLED"


class DeliveryStatus(str, Enum):
    NOT_READY = "NOT_READY"
    PENDING = "PENDING"
    DELIVERED = "DELIVERED"


class LabResultSource(str, Enum):
    IN_CLINIC = "IN_CLINIC"
    REFERENCE_LAB = "REFERENCE_LAB"


class ProficiencyVerdict(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"


class ServiceCaseType(str, Enum):
    REPAIR = "REPAIR"
    PREVENTIVE_CALIBRATION = "PREVENTIVE_CALIBRATION"
    PROFICIENCY_REMEDIATION = "PROFICIENCY_REMEDIATION"  # system-created only


class ServiceCaseStatus(str, Enum):
    OPEN = "OPEN"
    DISPATCHED = "DISPATCHED"
    RESOLVED = "RESOLVED"
    CANCELLED = "CANCELLED"


class ServiceCaseAction(str, Enum):
    DISPATCH = "DISPATCH"
    RESOLVE = "RESOLVE"
    CANCEL = "CANCEL"


class LabTestOrderAction(str, Enum):
    RECEIVE = "RECEIVE"
    RECORD_RESULT = "RECORD_RESULT"
    DELIVER = "DELIVER"
    CANCEL = "CANCEL"


class PriceSource(str, Enum):
    OVERRIDE = "OVERRIDE"
    CORPORATE_DISCOUNT = "CORPORATE_DISCOUNT"
    BUYING_DISCOUNT = "BUYING_DISCOUNT"
    LIST = "LIST"
    PROGRAM_INCLUDED = "PROGRAM_INCLUDED"


class SkuFamily(str, Enum):
    SLIDE = "SLIDE"
    CARTRIDGE = "CARTRIDGE"
    QC_MATERIAL = "QC_MATERIAL"
    CALIBRATOR = "CALIBRATOR"


# ---------------------------------------------------------------------------
# Payload sub-shapes
# ---------------------------------------------------------------------------
class SkuOverride(TypedDict):
    sku: str
    unit_price_cents: int


class OrderLine(TypedDict):
    sku: str
    quantity: int


class PricingDetailLine(TypedDict, total=False):
    sku: str
    quantity: int
    unit_price_cents: int
    price_source: str
    line_total_cents: int


# ---------------------------------------------------------------------------
# Entity shapes (common_fields: true — id + created_at + updated_at + version)
# ---------------------------------------------------------------------------
class GroupPricingAgreement(TypedDict):
    id: str
    group_type: str
    group_code: str
    effective_from: str
    effective_to: str
    discount_pct: float
    sku_overrides: List[dict]
    status: str
    created_at: str
    updated_at: str
    version: int


class Clinic(TypedDict):
    id: str
    name: str
    corporate_group_code: Optional[str]
    buying_group_code: Optional[str]
    caseload_baseline_tests: int
    caseload_current_tests: int
    status: str
    created_at: str
    updated_at: str
    version: int


class PlacementAgreement(TypedDict):
    id: str
    clinic_id: str
    model: str
    program_type: str
    term_months: int
    start_date: str
    end_date: str
    monthly_minimum_cents: Optional[int]
    lease_rate_cents: Optional[int]
    purchase_price_cents: Optional[int]
    baseline_caseload_snapshot: Optional[int]
    proposed_minimum_cents: Optional[int]
    cumulative_billed_cents: int
    cumulative_unpaid_billed_cents: int
    service_credit_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Analyzer(TypedDict):
    id: str
    clinic_id: str
    agreement_id: str
    model: str
    serial_number: str
    is_loaner_unit: bool
    operational_status: str
    connectivity_status: str
    proficiency_standing: str
    qc_valid_until: Optional[str]
    total_downtime_hours: int
    reported_uptime_pct: float
    breach_uptime_pct: float
    created_at: str
    updated_at: str
    version: int


class ReagentOrder(TypedDict):
    id: str
    clinic_id: str
    agreement_id: str
    order_month: str
    lines: List[dict]
    pricing_detail: dict
    list_total_cents: int
    final_total_cents: int
    fulfilled_at: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class CommitmentPeriod(TypedDict):
    id: str
    agreement_id: str
    period_month: str
    minimum_cents: int
    provisional_fulfilled_cents: Optional[int]
    fulfilled_cents: Optional[int]
    shortfall_cents: Optional[int]
    billed_cents: Optional[int]
    period_status: str
    billing_status: str
    created_at: str
    updated_at: str
    version: int


class LabTestOrder(TypedDict):
    id: str
    clinic_id: str
    analyzer_id: Optional[str]
    origin: str
    order_kind: str
    test_code: str
    expected_result: Optional[float]
    status: str
    delivery_status: str
    created_at: str
    updated_at: str
    version: int


class LabResult(TypedDict):
    # Immutable record (PRD §2.5): carries ONLY id + created_at of the
    # common fields — no updated_at, no version.
    id: str
    created_at: str
    test_order_id: str
    source: str
    result_value: float
    expected_value: Optional[float]
    verdict: Optional[str]
    resulted_at: str


class ServiceCase(TypedDict):
    id: str
    analyzer_id: str
    case_type: str
    loaner_analyzer_id: Optional[str]
    status: str
    opened_at: str
    response_due_at: str
    resolved_at: Optional[str]
    downtime_hours: Optional[int]
    sla_met: Optional[bool]
    resolution_note: Optional[str]
    created_at: str
    updated_at: str
    version: int
