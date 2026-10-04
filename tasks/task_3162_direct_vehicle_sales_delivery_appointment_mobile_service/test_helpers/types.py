"""Domain types: entity TypedDicts, status enums and the role enum.

Entities carrying `common_fields` expose `id`, `created_at`, `updated_at` and
`version`.  `OrderFeeLedgerEntry` is an append-only ledger fact and therefore
carries only `id` and `created_at`.
"""
from enum import Enum
from typing import Optional, TypedDict


class UserRole(str, Enum):
    ANONYMOUS = "Anonymous"
    BUYER = "Buyer"
    DELIVERY_ADVISOR = "DeliveryAdvisor"
    TRADE_IN_SPECIALIST = "TradeInSpecialist"
    FINANCE_PARTNER = "FinancePartner"
    SERVICE_TECHNICIAN = "ServiceTechnician"
    PARTS_COORDINATOR = "PartsCoordinator"
    PLATFORM_ADMIN = "PlatformAdmin"


def canonical_instant(text):
    """PRD §2.5: every timestamp the API surfaces is ISO 8601 UTC with three
    fractional digits, so the contract's own shape for an instant is
    `2026-09-01T00:00:00.000Z`. A rendered instant compared by value therefore
    has to be brought onto that same shape first; comparing `...00Z` against
    `...00.000Z` compares two spellings of the same instant."""
    if not isinstance(text, str):
        return text
    body = text[:-1] if text.endswith(("Z", "z")) else text
    if "." in body:
        head, _, fraction = body.partition(".")
        return f"{head}.{fraction.ljust(3, '0')[:3]}Z"
    return f"{body}.000Z"


class BuyerStatus(str, Enum):
    PENDING_VERIFICATION = "PENDING_VERIFICATION"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class CreditBand(str, Enum):
    UNRATED = "UNRATED"
    PRIME = "PRIME"
    NEAR_PRIME = "NEAR_PRIME"
    SUBPRIME = "SUBPRIME"


class JurisdictionStatus(str, Enum):
    DRAFT = "DRAFT"
    ENACTED = "ENACTED"
    REPEALED = "REPEALED"


class ConfigurationStatus(str, Enum):
    DRAFT = "DRAFT"
    PUBLISHED = "PUBLISHED"
    RETIRED = "RETIRED"


class OptionStatus(str, Enum):
    ACTIVE = "ACTIVE"
    RETIRED = "RETIRED"


class OrderStatus(str, Enum):
    DRAFT = "DRAFT"
    PLACED = "PLACED"
    CONFIG_LOCKED = "CONFIG_LOCKED"
    ALLOCATED = "ALLOCATED"
    IN_TRANSIT = "IN_TRANSIT"
    AT_DELIVERY_CENTER = "AT_DELIVERY_CENTER"
    DELIVERY_SCHEDULED = "DELIVERY_SCHEDULED"
    DELIVERED = "DELIVERED"
    CANCELLED = "CANCELLED"


class ReadinessPosture(str, Enum):
    READY = "READY"
    RESTRICTED = "RESTRICTED"
    FROZEN = "FROZEN"


class EstimateState(str, Enum):
    PROVISIONAL = "PROVISIONAL"
    FIRM = "FIRM"
    SUPERSEDED = "SUPERSEDED"
    CONSUMED = "CONSUMED"


class NotificationState(str, Enum):
    UNNOTIFIED = "UNNOTIFIED"
    NOTIFIED = "NOTIFIED"
    ACKNOWLEDGED = "ACKNOWLEDGED"
    ESCALATED = "ESCALATED"


class AppointmentStatus(str, Enum):
    BOOKED = "BOOKED"
    CONFIRMED = "CONFIRMED"
    AT_RISK = "AT_RISK"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class DeliveryMode(str, Enum):
    CENTER = "CENTER"
    HOME = "HOME"


class AppraisalStatus(str, Enum):
    DRAFT = "DRAFT"
    APPRAISED = "APPRAISED"
    OFFERED = "OFFERED"
    EXPIRED = "EXPIRED"
    REAPPRAISED = "REAPPRAISED"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"


class ApplicationStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    CONDITIONALLY_APPROVED = "CONDITIONALLY_APPROVED"
    CONTRACT_PENDING = "CONTRACT_PENDING"
    FUNDED = "FUNDED"
    DECLINED = "DECLINED"


class BatchStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    IN_PRODUCTION = "IN_PRODUCTION"
    DELAYED = "DELAYED"
    COMPLETED = "COMPLETED"


class UnitStatus(str, Enum):
    UNASSIGNED = "UNASSIGNED"
    ALLOCATED = "ALLOCATED"
    IN_TRANSIT = "IN_TRANSIT"
    ARRIVED = "ARRIVED"
    RELEASED = "RELEASED"


class CenterKind(str, Enum):
    DELIVERY_CENTER = "DELIVERY_CENTER"
    GALLERY = "GALLERY"
    SERVICE_CENTER = "SERVICE_CENTER"
    PARTS_HUB = "PARTS_HUB"


class CenterStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    RETIRED = "RETIRED"


class VehicleStatus(str, Enum):
    IN_SERVICE = "IN_SERVICE"
    SERVICE_HOLD = "SERVICE_HOLD"
    RETIRED = "RETIRED"


class ServiceHoldState(str, Enum):
    NONE = "NONE"
    PARTS_HOLD = "PARTS_HOLD"
    AWAITING_PARTS_SHIPMENT = "AWAITING_PARTS_SHIPMENT"


class Severity(str, Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class TriageOutcome(str, Enum):
    PENDING = "PENDING"
    MOBILE_REQUIRED = "MOBILE_REQUIRED"
    CENTER_REQUIRED = "CENTER_REQUIRED"
    OTA_RESOLVABLE = "OTA_RESOLVABLE"
    NO_ACTION = "NO_ACTION"


class ServiceAppointmentStatus(str, Enum):
    TRIAGED = "TRIAGED"
    CENTER_SCHEDULED = "CENTER_SCHEDULED"
    MOBILE_DISPATCHED = "MOBILE_DISPATCHED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class VisitStatus(str, Enum):
    DRAFT = "DRAFT"
    PARTS_RESERVED = "PARTS_RESERVED"
    PARTS_SHIPPED = "PARTS_SHIPPED"
    EN_ROUTE = "EN_ROUTE"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    RESCHEDULED = "RESCHEDULED"
    CANCELLED = "CANCELLED"


class EntitlementSource(str, Enum):
    FACTORY_OPTION = "FACTORY_OPTION"
    PURCHASE = "PURCHASE"
    TRIAL = "TRIAL"
    TRANSFER = "TRANSFER"


class EntitlementStatus(str, Enum):
    ACTIVE = "ACTIVE"
    EXPIRED = "EXPIRED"
    REVOKED = "REVOKED"


class IssueNoteStatus(str, Enum):
    OPEN = "OPEN"
    RESOLVED = "RESOLVED"
    WAIVED = "WAIVED"


class LedgerEntryType(str, Enum):
    ORDER_FEE_PAYMENT = "ORDER_FEE_PAYMENT"
    ORDER_FEE_REFUND = "ORDER_FEE_REFUND"
    TRADE_IN_CREDIT = "TRADE_IN_CREDIT"
    TRADE_IN_CREDIT_REVERSAL = "TRADE_IN_CREDIT_REVERSAL"
    DELIVERY_FEE_CHARGE = "DELIVERY_FEE_CHARGE"
    DELIVERY_FEE_WAIVER = "DELIVERY_FEE_WAIVER"


# ─── Entity TypedDicts (common_fields: true) ──────────

class Buyer(TypedDict):
    id: str
    full_name: str
    email: str
    residency_state_code: str
    credit_band: str
    order_credit_balance_cents: int
    identity_verified: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class StateJurisdiction(TypedDict):
    id: str
    state_code: str
    direct_sales_permitted: bool
    gallery_only_required: bool
    out_of_state_delivery_required: bool
    cooling_off_days: int
    doc_fee_cap_cents: int
    mobile_service_permitted: bool
    delivery_buffer_minutes: int
    allocation_window_days: int
    transport_lead_days: int
    status: str
    created_at: str
    updated_at: str
    version: int


class VehicleConfiguration(TypedDict):
    id: str
    model_code: str
    base_price_cents: int
    configured_price_cents: int
    option_count: int
    status: str
    created_at: str
    updated_at: str
    version: int


class ConfigurationOption(TypedDict):
    id: str
    configuration_id: str
    option_sku: str
    option_category: str
    is_software_entitlement: bool
    price_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class VehicleOrder(TypedDict):
    id: str
    buyer_id: str
    configuration_id: str
    jurisdiction_id: str
    delivery_center_id: str
    order_fee_cents: int
    order_fee_paid_cents: int
    placed_at: Optional[str]
    configuration_lock_deadline: Optional[str]
    order_total_due_cents: int
    delivery_readiness_posture: str
    estimate_shift_days_cumulative: int
    issue_note_count: int
    status: str
    created_at: str
    updated_at: str
    version: int


class TradeInAppraisal(TypedDict):
    id: str
    order_id: str
    trade_vin: str
    mileage: int
    gross_offer_cents: int
    reconditioning_estimate_cents: int
    offer_valid_until: str
    net_credit_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class FinancingApplication(TypedDict):
    id: str
    order_id: str
    buyer_id: str
    term_months: int
    down_payment_cents: int
    include_trade_in_credit: bool
    credit_band: Optional[str]
    apr_bps: Optional[int]
    amount_financed_cents: int
    monthly_payment_cents: Optional[int]
    decision_at: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class ProductionBatch(TypedDict):
    id: str
    factory_code: str
    model_code: str
    unit_capacity: int
    allocated_unit_count: int
    unallocated_unit_count: int
    planned_completion_at: str
    delay_days: int
    status: str
    created_at: str
    updated_at: str
    version: int


class AllocationUnit(TypedDict):
    id: str
    batch_id: str
    order_id: Optional[str]
    vin: str
    allocated_at: Optional[str]
    transport_eta: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class DeliveryEstimate(TypedDict):
    id: str
    order_id: str
    prior_estimate_id: Optional[str]
    window_start: str
    window_end: str
    basis_equipment_at: str
    shift_days: int
    estimate_state: str
    notification_state: str
    created_at: str
    updated_at: str
    version: int


class DeliveryCenter(TypedDict):
    id: str
    center_name: str
    center_kind: str
    state_code: str
    home_delivery_radius_miles: int
    bay_count: int
    booked_slot_count: int
    van_count: int
    status: str
    created_at: str
    updated_at: str
    version: int


class DeliveryAppointment(TypedDict):
    id: str
    order_id: str
    delivery_center_id: str
    delivery_mode: str
    scheduled_start: str
    scheduled_end: str
    buffer_minutes: int
    acceptance_inspection_result: str
    documented_issue_count: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Vehicle(TypedDict):
    id: str
    order_id: str
    vin: str
    delivered_at: Optional[str]
    odometer_miles: int
    software_version: str
    service_hold_state: str
    status: str
    created_at: str
    updated_at: str
    version: int


class RemoteDiagnosticReport(TypedDict):
    id: str
    vehicle_id: str
    fault_code: str
    severity: str
    is_driveable: bool
    triage_outcome: str
    parts_required: bool
    reported_at: str
    created_at: str
    updated_at: str
    version: int


class ServiceAppointment(TypedDict):
    id: str
    vehicle_id: str
    diagnostic_report_id: str
    service_center_id: str
    scheduled_start: str
    scheduled_end: str
    is_warranty_covered: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class MobileServiceVisit(TypedDict):
    id: str
    vehicle_id: str
    service_appointment_id: str
    parts_hub_id: str
    van_code: str
    visit_start: str
    visit_end: str
    labor_hours: float
    parts_cost_cents: int
    parts_pre_shipped_at: Optional[str]
    visit_cost_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class SoftwareEntitlement(TypedDict):
    id: str
    vehicle_id: str
    feature_code: str
    entitlement_source: str
    price_cents: int
    trial_days: int
    bundle_discount_bps: int
    payable_cents: int
    bundle_net_cents: int
    effective_at: str
    expires_at: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class VehicleIssueNote(TypedDict):
    id: str
    order_id: str
    vehicle_id: str
    issue_code: str
    observed_mileage: int
    blocked_handover: bool
    status: str
    created_at: str
    updated_at: str
    version: int


# ─── Append-only entity (common_fields: false) ────────

class OrderFeeLedgerEntry(TypedDict):
    """Append-only ledger fact: only `id` and `created_at`, never mutated."""
    id: str
    order_id: str
    buyer_id: str
    entry_type: str
    amount_cents: int
    reason_code: str
    created_at: str


__all__ = [name for name in dir() if not name.startswith("_")]