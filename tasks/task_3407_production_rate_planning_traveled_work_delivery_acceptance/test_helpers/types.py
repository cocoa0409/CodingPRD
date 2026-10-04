"""Domain types: entity TypedDicts, status enums, role enum (PRD §2.1, §3)."""
from enum import Enum
from typing import TypedDict, Optional, List


class UserRole(str, Enum):
    """The seven declared roles (PRD §2.1)."""
    PROGRAM_ADMIN = "ProgramAdmin"
    PRODUCTION_PLANNER = "ProductionPlanner"
    SUPPLIER_MANAGER = "SupplierManager"
    LINE_MANAGER = "LineManager"
    QUALITY_INSPECTOR = "QualityInspector"
    DELIVERY_MANAGER = "DeliveryManager"
    CUSTOMER = "Customer"


class RateCaseStatus(str, Enum):
    """PRD §3.2: DRAFT -> ANNOUNCED -> GATED_REVIEW -> COMMITTED / SHELVED."""
    DRAFT = "DRAFT"
    ANNOUNCED = "ANNOUNCED"
    GATED_REVIEW = "GATED_REVIEW"
    COMMITTED = "COMMITTED"
    SHELVED = "SHELVED"


class GatingVerdict(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"


class CommitmentStatus(str, Enum):
    """PRD §3.3: DRAFT -> CONFIRMED -> ORDERED -> AT_RISK -> CANCELLED."""
    DRAFT = "DRAFT"
    CONFIRMED = "CONFIRMED"
    ORDERED = "ORDERED"
    AT_RISK = "AT_RISK"
    CANCELLED = "CANCELLED"


class WorkPackageStatus(str, Enum):
    """PRD §3.4: OPEN -> COMPLETE / TRAVELED (both terminal)."""
    OPEN = "OPEN"
    COMPLETE = "COMPLETE"
    TRAVELED = "TRAVELED"


class ReworkOrderStatus(str, Enum):
    """PRD §3.5: OPEN -> CLOSED -> CREDITED."""
    OPEN = "OPEN"
    CLOSED = "CLOSED"
    CREDITED = "CREDITED"


class ReworkOrderSource(str, Enum):
    TRAVELED_WORK = "TRAVELED_WORK"
    QUALITY_ESCAPE = "QUALITY_ESCAPE"
    FLIGHT_TEST_FAILURE = "FLIGHT_TEST_FAILURE"
    WALKTHROUGH_SNAG = "WALKTHROUGH_SNAG"


class EscapeSeverity(str, Enum):
    MAJOR = "MAJOR"
    CRITICAL = "CRITICAL"


class EscapeStatus(str, Enum):
    """PRD §3.6: OPEN -> ROOT_CAUSE -> DISPOSITIONED -> CLOSED; reopen cycle."""
    OPEN = "OPEN"
    ROOT_CAUSE = "ROOT_CAUSE"
    DISPOSITIONED = "DISPOSITIONED"
    CLOSED = "CLOSED"


class DispositionCode(str, Enum):
    USE_AS_IS = "USE_AS_IS"
    REWORK = "REWORK"
    SCRAP = "SCRAP"


class RangeCode(str, Enum):
    RANGE_ALPHA = "RANGE_ALPHA"
    RANGE_BRAVO = "RANGE_BRAVO"


class FlightTestStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    COMPLETED = "COMPLETED"


class FlightTestOutcome(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"


class StorageStatus(str, Enum):
    """PRD §3.7: ACTIVE -> RELEASED (terminal)."""
    ACTIVE = "ACTIVE"
    RELEASED = "RELEASED"


class CreditStanding(str, Enum):
    GOOD = "GOOD"
    WATCH = "WATCH"
    POOR = "POOR"


class ProductionStatus(str, Enum):
    IN_PRODUCTION = "IN_PRODUCTION"
    ASSEMBLY_COMPLETE = "ASSEMBLY_COMPLETE"
    IN_STORAGE = "IN_STORAGE"
    DELIVERED = "DELIVERED"


class QualityStatus(str, Enum):
    CLEAR = "CLEAR"
    HOLD = "HOLD"


class DeliveryStatus(str, Enum):
    NOT_STARTED = "NOT_STARTED"
    FLIGHT_TESTING = "FLIGHT_TESTING"
    CONFIG_VERIFIED = "CONFIG_VERIFIED"
    WALKTHROUGH_PASSED = "WALKTHROUGH_PASSED"
    REJECTED = "REJECTED"
    ACCEPTED = "ACCEPTED"


class NegotiationStatus(str, Enum):
    """PRD §3.9: PROPOSED <-> COUNTERED -> AGREED / EXPIRED."""
    PROPOSED = "PROPOSED"
    COUNTERED = "COUNTERED"
    AGREED = "AGREED"
    EXPIRED = "EXPIRED"


class CompensationVariant(str, Enum):
    CONTRACTUAL_LIQUIDATED = "CONTRACTUAL_LIQUIDATED"
    GOODWILL = "GOODWILL"


class Posture(str, Enum):
    """PRD §2.9 posture derivation."""
    DISTRESSED = "DISTRESSED"
    STABILIZING = "STABILIZING"
    STABLE = "STABLE"


# --- Entity bodies (all carry id / created_at / updated_at / version, PRD §2.5) ---


class ProductionProgram(TypedDict, total=False):
    id: str
    model_code: str
    current_rate_per_month: int
    required_component_codes: int
    rework_budget_total_cents: int
    announced_target_rate: int
    rework_budget_consumed_cents: int
    cancellation_reserve_cents: int
    supply_chain_readiness_pct: float
    workforce_readiness_pct: float
    traveled_work_open_hours: int
    open_escape_count: int
    readiness_index: float
    posture: str
    storage_fees_accrued_cents: int
    undelivered_inventory_count: int
    created_at: str
    updated_at: str
    version: int


class RateCase(TypedDict, total=False):
    id: str
    program_id: str
    proposed_rate: int
    effective_month: str
    demand_backlog_units: int
    supply_readiness_snapshot_pct: Optional[float]
    workforce_readiness_snapshot_pct: Optional[float]
    burden_penalty_snapshot: Optional[float]
    readiness_index_snapshot: Optional[float]
    gating_verdict: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class Supplier(TypedDict, total=False):
    id: str
    supplier_code: str
    name: str
    region: str
    created_at: str
    updated_at: str
    version: int


class SupplierCapacityCommitment(TypedDict, total=False):
    id: str
    supplier_id: str
    program_id: str
    component_code: str
    committed_rate_per_month: int
    lead_time_months: int
    unit_price_cents: int
    ordered_quantity: int
    cancelled_quantity: int
    active_ordered_quantity: int
    assumed_rate_at_order: Optional[int]
    cancellation_penalty_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class WorkforcePlan(TypedDict, total=False):
    id: str
    program_id: str
    skill_code: str
    required_headcount: int
    hired_headcount: int
    readiness_ratio: float
    created_at: str
    updated_at: str
    version: int


class Customer(TypedDict, total=False):
    id: str
    airline_code: str
    name: str
    credit_standing: str
    created_at: str
    updated_at: str
    version: int


class AircraftUnit(TypedDict, total=False):
    id: str
    program_id: str
    customer_id: str
    line_number: int
    configuration_code: str
    ordered_configuration_code: str
    contract_price_cents: int
    contracted_delivery_date: str
    production_status: str
    quality_status: str
    delivery_status: str
    rework_cost_total_cents: int
    scheduled_delivery_date: Optional[str]
    created_at: str
    updated_at: str
    version: int


class WorkPackage(TypedDict, total=False):
    id: str
    aircraft_id: str
    station_sequence: int
    description: str
    planned_hours: int
    traveled_hours: Optional[int]
    status: str
    created_at: str
    updated_at: str
    version: int


class ReworkOrder(TypedDict, total=False):
    id: str
    aircraft_id: str
    work_package_id: Optional[str]
    escape_id: Optional[str]
    source: str
    estimated_cost_cents: int
    actual_cost_cents: Optional[int]
    status: str
    created_at: str
    updated_at: str
    version: int


class QualityEscape(TypedDict, total=False):
    id: str
    aircraft_id: str
    severity: str
    description: str
    reported_by_id: str
    conformance_documented: bool
    conformance_refs: List[str]
    regulator_notified_at: Optional[str]
    is_late_notification: bool
    dispositioned_by_id: Optional[str]
    disposition_code: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class FlightTest(TypedDict, total=False):
    id: str
    aircraft_id: str
    range_code: str
    window_start: str
    window_end: str
    outcome: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class StoragePreservation(TypedDict, total=False):
    id: str
    aircraft_id: str
    bay_code: str
    window_start: str
    window_end: str
    daily_rate_cents: int
    preservation_cycle_days: int
    last_preserved_at: str
    next_preservation_due: str
    is_overdue: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class DeliveryNegotiation(TypedDict, total=False):
    id: str
    aircraft_id: str
    customer_id: str
    proposed_delivery_date: str
    compensation_variant: str
    days_late: int
    compensation_cents: int
    round_number: int
    status: str
    created_at: str
    updated_at: str
    version: int
