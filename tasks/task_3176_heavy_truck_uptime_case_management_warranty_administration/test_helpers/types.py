"""Domain types: entity TypedDicts, status enums, role enum.

Field sets follow the PRD's entity descriptions and the common-resource
convention (PRD section on common resource properties): most resources carry
id/created_at/updated_at/version; FaultEvent and ReliabilityReport are
append-only and carry only id/created_at.
"""
from enum import Enum
from typing import Optional, TypedDict


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class FleetStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    CLOSED = "CLOSED"


class TruckStatus(str, Enum):
    IN_SERVICE = "IN_SERVICE"
    DOWN = "DOWN"
    DECOMMISSIONED = "DECOMMISSIONED"


class DealerStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class BayStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    RESERVED = "RESERVED"
    IN_USE = "IN_USE"
    DOWN = "DOWN"
    DECOMMISSIONED = "DECOMMISSIONED"


class FaultEventStatus(str, Enum):
    UNLINKED = "UNLINKED"
    LINKED = "LINKED"
    DISMISSED = "DISMISSED"


class FaultSeverity(str, Enum):
    INFO = "INFO"
    WARNING = "WARNING"
    CRITICAL = "CRITICAL"


class RecommendedAction(str, Enum):
    MONITOR = "MONITOR"
    SCHEDULE_SERVICE = "SCHEDULE_SERVICE"
    STOP_IMMEDIATELY = "STOP_IMMEDIATELY"


class CaseStatus(str, Enum):
    OPEN = "OPEN"
    TRIAGE = "TRIAGE"
    SCHEDULED = "SCHEDULED"
    IN_SERVICE = "IN_SERVICE"
    AWAITING_PART = "AWAITING_PART"
    PENDING_CLOSE = "PENDING_CLOSE"
    CLOSED = "CLOSED"
    CANCELLED = "CANCELLED"


class WorkOrderStatus(str, Enum):
    DRAFT = "DRAFT"
    AUTHORIZED = "AUTHORIZED"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class RepairOutcome(str, Enum):
    FIXED = "FIXED"
    NOT_FIXED = "NOT_FIXED"
    PARTIAL = "PARTIAL"


class PartOrderStatus(str, Enum):
    PENDING = "PENDING"
    SHIPPED = "SHIPPED"
    RECEIVED = "RECEIVED"
    INSTALLED = "INSTALLED"
    CANCELLED = "CANCELLED"


class ExpediteDecision(str, Enum):
    PENDING_EVAL = "PENDING_EVAL"
    EXPEDITE_OVERNIGHT = "EXPEDITE_OVERNIGHT"
    EXPEDITE_STANDARD = "EXPEDITE_STANDARD"
    DENIED = "DENIED"


class DistanceBand(str, Enum):
    INTRA_REGION = "INTRA_REGION"
    CROSS_COUNTRY = "CROSS_COUNTRY"
    INTERNATIONAL = "INTERNATIONAL"


class ClaimType(str, Enum):
    BASE_WARRANTY = "BASE_WARRANTY"
    EXTENDED_COVERAGE = "EXTENDED_COVERAGE"
    CAMPAIGN = "CAMPAIGN"
    GOODWILL = "GOODWILL"


class SubmissionStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    UNDER_REVIEW = "UNDER_REVIEW"
    APPROVED = "APPROVED"
    DENIED = "DENIED"
    PARTIAL_APPROVED = "PARTIAL_APPROVED"


class ClaimRecoveryStatus(str, Enum):
    NOT_INITIATED = "NOT_INITIATED"
    PART_RETURN_REQUESTED = "PART_RETURN_REQUESTED"
    PART_IN_TRANSIT = "PART_IN_TRANSIT"
    PART_RECEIVED = "PART_RECEIVED"
    RECOVERY_FILED = "RECOVERY_FILED"
    RECOVERY_PAID = "RECOVERY_PAID"
    RECOVERY_DENIED = "RECOVERY_DENIED"


class PartReturnStatus(str, Enum):
    REQUESTED = "REQUESTED"
    IN_TRANSIT = "IN_TRANSIT"
    RECEIVED = "RECEIVED"
    INSPECTED_OK = "INSPECTED_OK"
    INSPECTED_FAILED = "INSPECTED_FAILED"
    LATE_REJECTED = "LATE_REJECTED"


class InspectionDisposition(str, Enum):
    OK = "OK"
    FAILED = "FAILED"


class SupplierRecoveryStatus(str, Enum):
    FILED = "FILED"
    UNDER_DISPUTE = "UNDER_DISPUTE"
    PAID = "PAID"
    DENIED = "DENIED"


class ContractType(str, Enum):
    EXTENDED_POWERTRAIN = "EXTENDED_POWERTRAIN"
    EXTENDED_AFTERTREATMENT = "EXTENDED_AFTERTREATMENT"
    EXTENDED_FULL = "EXTENDED_FULL"


class ContractStatus(str, Enum):
    ACTIVE = "ACTIVE"
    EXPIRED = "EXPIRED"
    CANCELLED = "CANCELLED"


class CampaignKind(str, Enum):
    RECALL = "RECALL"
    SERVICE_CAMPAIGN = "SERVICE_CAMPAIGN"


class CampaignStatus(str, Enum):
    OPEN = "OPEN"
    CLOSED = "CLOSED"


class CompletionStatus(str, Enum):
    OPEN = "OPEN"
    SCHEDULED = "SCHEDULED"
    COMPLETED = "COMPLETED"
    EXEMPTED = "EXEMPTED"


class UserRole(str, Enum):
    FLEET_MANAGER = "FleetManager"
    UPTIME_COORDINATOR = "UptimeCoordinator"
    DEALER_ADVISOR = "DealerAdvisor"
    PARTS_MANAGER = "PartsManager"
    WARRANTY_ADMIN = "WarrantyAdmin"
    SUPPLIER_MANAGER = "SupplierManager"


# ---------------------------------------------------------------------------
# Entity TypedDicts
# ---------------------------------------------------------------------------

class Fleet(TypedDict):
    id: str
    fleet_name: str
    home_region: str
    reliability_score: int
    total_downtime_hours: float
    open_case_count: int
    fleet_status: str
    created_at: str
    updated_at: str
    version: int


class Truck(TypedDict):
    id: str
    fleet_id: str
    vin: str
    model_code: str
    in_service_on: str
    odometer_miles: int
    base_warranty_until_miles: int
    base_warranty_until_on: str
    truck_status: str
    open_case_count: int
    repeat_repair_flag: bool
    created_at: str
    updated_at: str
    version: int


class Dealer(TypedDict):
    id: str
    dealer_name: str
    region: str
    hourly_labor_rate_cents: int
    dealer_status: str
    bay_count: int
    active_case_count: int
    created_at: str
    updated_at: str
    version: int


class ServiceBay(TypedDict):
    id: str
    dealer_id: str
    bay_code: str
    bay_status: str
    created_at: str
    updated_at: str
    version: int


class FaultEvent(TypedDict):
    # append-only: id + created_at only (no updated_at, no version)
    id: str
    truck_id: str
    fault_code: str
    severity: str
    recommended_action: str
    occurred_at: str
    event_status: str
    created_at: str


class Case(TypedDict):
    id: str
    truck_id: str
    fleet_id: str
    dealer_id: Optional[str]
    opened_from_fault_event_id: Optional[str]
    case_status: str
    fault_code: str
    severity_at_open: Optional[str]
    opened_at: str
    closed_at: Optional[str]
    downtime_hours: float
    diagnostic_minutes_authorized: int
    expedite_count: int
    created_at: str
    updated_at: str
    version: int


class WorkOrder(TypedDict):
    id: str
    case_id: str
    dealer_id: str
    bay_id: str
    scheduled_start_at: str
    scheduled_end_at: str
    work_order_status: str
    diagnostic_minutes_authorized: int
    labor_minutes_actual: int
    repair_outcome: Optional[str]
    created_at: str
    updated_at: str
    version: int


class PartOrder(TypedDict):
    id: str
    case_id: str
    part_number: str
    quantity: int
    expedite_decision: str
    expedite_cost_cents: int
    downtime_cost_cents: int
    part_order_status: str
    created_at: str
    updated_at: str
    version: int


class WarrantyClaim(TypedDict):
    id: str
    case_id: str
    claim_type: str
    labor_minutes_claimed: int
    parts_claimed_cents: int
    labor_rate_cents_per_hour: int
    labor_hours_allowed: float
    labor_amount_allowed_cents: int
    parts_amount_allowed_cents: int
    submission_status: str
    recovery_status: str
    recovery_amount_cents: int
    created_at: str
    updated_at: str
    version: int


class PartReturn(TypedDict):
    id: str
    claim_id: str
    part_number: str
    return_window_days: int
    shipped_at: Optional[str]
    received_at: Optional[str]
    part_return_status: str
    inspection_disposition: Optional[str]
    created_at: str
    updated_at: str
    version: int


class SupplierRecovery(TypedDict):
    id: str
    claim_id: str
    part_return_id: str
    supplier_id: str
    claimed_amount_cents: int
    paid_amount_cents: int
    recovery_status: str
    created_at: str
    updated_at: str
    version: int


class CoverageContract(TypedDict):
    id: str
    truck_id: str
    contract_type: str
    starts_on: str
    ends_on: str
    max_miles: int
    premium_cents: int
    contract_status: str
    prorated_credit_cents: int
    created_at: str
    updated_at: str
    version: int


class Campaign(TypedDict):
    id: str
    campaign_code: str
    campaign_kind: str
    affected_model_codes: list
    fault_code: str
    opens_on: str
    closes_on: str
    campaign_status: str
    completion_pct: float
    overdue_count: int
    created_at: str
    updated_at: str
    version: int


class CampaignCompletion(TypedDict):
    id: str
    campaign_id: str
    truck_id: str
    case_id: Optional[str]
    completion_status: str
    exemption_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ReliabilityReport(TypedDict):
    # append-only snapshot: id + created_at only
    id: str
    fleet_id: str
    ops_run_index: int
    computed_at: str
    trucks_in_service: int
    trucks_down: int
    total_downtime_hours: float
    repeat_repair_truck_count: int
    campaign_completion_pct: float
    reliability_score: int
    created_at: str
