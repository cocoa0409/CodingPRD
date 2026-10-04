"""Domain types: entity TypedDicts, status enums and the role enum.

Everything here mirrors the vocabulary the PRD uses for the connected-fitness
hardware domain: memberships, household users, devices, hardware orders,
delivery appointments, financing plans, service orders, parts inventory,
class sessions, class enrollments and refurbishment batches.
"""
from enum import Enum
from typing import TypedDict, Optional, List


# ─── Roles ─────────────────────────────────────────────

class UserRole(str, Enum):
    MEMBERSHIP_OWNER = "MembershipOwner"
    SERVICE_TECHNICIAN = "ServiceTechnician"
    INSTRUCTOR = "Instructor"
    PLATFORM_ADMIN = "PlatformAdmin"
    ANONYMOUS = "Anonymous"


# ─── Membership ────────────────────────────────────────

class MembershipStatus(str, Enum):
    PROVISIONAL = "PROVISIONAL"
    ACTIVE = "ACTIVE"
    PAUSED = "PAUSED"
    CANCELLED = "CANCELLED"
    REACTIVATED = "REACTIVATED"
    DELINQUENT = "DELINQUENT"
    TERMINATED = "TERMINATED"


class Posture(str, Enum):
    OPEN = "OPEN"
    RESTRICTED = "RESTRICTED"
    FROZEN = "FROZEN"


class PlanTier(str, Enum):
    PLUS = "PLUS"
    BUSINESS = "BUSINESS"


class FrozenReason(str, Enum):
    FINANCING_DEFAULT = "FINANCING_DEFAULT"
    OWNERSHIP_DISPUTE = "OWNERSHIP_DISPUTE"


class Membership(TypedDict, total=False):
    id: str
    household_name: str
    billing_email: str
    plan_tier: str
    monthly_fee_cents: int
    concurrent_limit_override: Optional[int]
    concurrent_limit_effective: int
    active_user_count: int
    billing_cycle_start_at: str
    paid_through_at: str
    status: str
    posture: str
    pause_started_at: Optional[str]
    accrued_pause_credit_cents: int
    total_streams_observed: int
    unpaid_financing_count: int
    safety_gate_open: bool
    attr_frozen_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


# ─── HouseholdUser ─────────────────────────────────────

class HouseholdUserStatus(str, Enum):
    PENDING_VERIFICATION = "PENDING_VERIFICATION"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    REMOVED = "REMOVED"


class HouseholdUserRole(str, Enum):
    OWNER = "OWNER"
    MEMBER = "MEMBER"


class SuspendedReason(str, Enum):
    EVICTED_BY_CONCURRENCY = "EVICTED_BY_CONCURRENCY"
    MEMBERSHIP_CANCELLED = "MEMBERSHIP_CANCELLED"
    REACTIVATION_UNPAID = "REACTIVATION_UNPAID"


class HouseholdUser(TypedDict, total=False):
    id: str
    membership_id: str
    display_name: str
    email: str
    role: str
    status: str
    streaming_device_serial: Optional[str]
    suspended_reason: Optional[str]
    verification_token: str
    verified: bool
    eviction_count: int
    created_at: str
    updated_at: str
    version: int


# ─── Device ────────────────────────────────────────────

class DeviceActivationStatus(str, Enum):
    UNASSIGNED = "UNASSIGNED"
    DELIVERED = "DELIVERED"
    LINKED = "LINKED"
    ACTIVE = "ACTIVE"
    LOCKED = "LOCKED"
    DECOMMISSIONED = "DECOMMISSIONED"


class HardwareSku(str, Enum):
    BIKE = "BIKE"
    TREAD = "TREAD"
    ROWER = "ROWER"
    REFURB_BIKE = "REFURB_BIKE"
    REFURB_TREAD = "REFURB_TREAD"


class DeviceCondition(str, Enum):
    NEW = "NEW"
    REFURBISHED = "REFURBISHED"


class ProvenanceSource(str, Enum):
    NEW_SALE = "NEW_SALE"
    RESALE = "RESALE"


class Device(TypedDict, total=False):
    id: str
    membership_id: Optional[str]
    hardware_sku: str
    serial: str
    condition: str
    certifying_device_id: Optional[str]
    provenance_source: Optional[str]
    activation_status: str
    entitlement_lock: bool
    activated_at: Optional[str]
    warranty_expires_at: Optional[str]
    resale_cycle_count: int
    total_workouts: int
    content_access_allowed: bool
    created_at: str
    updated_at: str
    version: int


# ─── HardwareOrder ─────────────────────────────────────

class OrderStatus(str, Enum):
    PLACED = "PLACED"
    DELIVERY_SCHEDULED = "DELIVERY_SCHEDULED"
    DELIVERED = "DELIVERED"
    ACTIVATED = "ACTIVATED"
    CANCELLED = "CANCELLED"


class FinancingMethod(str, Enum):
    FULL_PAYMENT = "FULL_PAYMENT"
    FINANCE_SCHEDULED = "FINANCE_SCHEDULED"


class RefundDisputeStatus(str, Enum):
    NONE = "NONE"
    FILED = "FILED"
    DENIED = "DENIED"
    APPROVED = "APPROVED"


class HardwareOrder(TypedDict, total=False):
    id: str
    membership_id: str
    hardware_sku: str
    subtotal_cents: int
    quote_total_cents: int
    captured_total_cents: Optional[int]
    delivery_fee_cents: int
    stair_carry_fee_cents: int
    assembly_fee_cents: int
    finance_charge_cents: int
    financing_method: str
    status: str
    refund_dispute_status: str
    device_id: Optional[str]
    return_device_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


# ─── DeliveryAppointment ───────────────────────────────

class DeliveryZone(str, Enum):
    METRO = "METRO"
    SUBURBAN = "SUBURBAN"
    RURAL = "RURAL"


class AppointmentStatus(str, Enum):
    REQUESTED = "REQUESTED"
    SCHEDULED = "SCHEDULED"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class CompletionGrade(str, Enum):
    CLEAN = "CLEAN"
    DAMAGED = "DAMAGED"


class DeliveryAppointment(TypedDict, total=False):
    id: str
    device_id: str
    hardware_order_id: str
    start_at: str
    end_at: str
    zone: str
    stair_flights: int
    has_elevator: bool
    delivery_legs: int
    technician_crew_code: str
    status: str
    reschedule_count: int
    completion_grade: Optional[str]
    created_at: str
    updated_at: str
    version: int


# ─── FinancingPlan ─────────────────────────────────────

class FinancingPlanStatus(str, Enum):
    ORIGINATED = "ORIGINATED"
    CURRENT = "CURRENT"
    DELINQUENT = "DELINQUENT"
    DEFAULTED = "DEFAULTED"
    PAID_OFF = "PAID_OFF"


class FinancingPlan(TypedDict, total=False):
    id: str
    membership_id: str
    order_id: str
    principal_cents: int
    term_months: int
    apr_bps: int
    monthly_installment_cents: int
    installments_paid: int
    installments_late: int
    retry_count: int
    status: str
    delinquency_count: int
    safety_disable_latched: bool
    created_at: str
    updated_at: str
    version: int


# ─── ServiceOrder ──────────────────────────────────────

class ServiceOrderStatus(str, Enum):
    DISPATCHED = "DISPATCHED"
    DISPATCH_PENDING_PART = "DISPATCH_PENDING_PART"
    PART_RESERVED = "PART_RESERVED"
    SCHEDULED = "SCHEDULED"
    REPAIR_IN_PROGRESS = "REPAIR_IN_PROGRESS"
    RESOLVED = "RESOLVED"
    CANCELLED = "CANCELLED"


class FaultCode(str, Enum):
    NO_POWER = "NO_POWER"
    BELT_SLIP = "BELT_SLIP"
    SENSOR_FAULT = "SENSOR_FAULT"
    SOFTWARE_CRASH = "SOFTWARE_CRASH"
    FRAME_CRACK = "FRAME_CRACK"


class FaultClass(str, Enum):
    SAFETY_CRITICAL = "SAFETY_CRITICAL"
    COSMETIC = "COSMETIC"


class ServicePriority(str, Enum):
    PRIORITY_SAFETY = "PRIORITY_SAFETY"
    PRIORITY_WARRANTY = "PRIORITY_WARRANTY"
    PRIORITY_STANDARD = "PRIORITY_STANDARD"


class ServiceOrder(TypedDict, total=False):
    id: str
    device_id: str
    order_id: Optional[str]
    reported_fault_code: str
    fault_class: str
    priority: str
    status: str
    part_id: Optional[str]
    reserved_part_qty: int
    diagnosis_note: Optional[str]
    resolved_at: Optional[str]
    failure_before_part: bool
    safety_functions_maintained: bool
    created_at: str
    updated_at: str
    version: int


# ─── PartsInventory ────────────────────────────────────

class PartsInventory(TypedDict, total=False):
    id: str
    part_code: str
    compatible_sku: str
    on_hand_qty: int
    stock_received_qty: int
    reserved_qty: int
    consumed_qty: int
    safety_stock_qty: int
    part_lot_key: str
    created_at: str
    updated_at: str
    version: int


# ─── ClassSession / ClassEnrollment ────────────────────

class SessionStatus(str, Enum):
    DRAFT = "DRAFT"
    PUBLISHED = "PUBLISHED"
    STREAMING = "STREAMING"
    ARCHIVED = "ARCHIVED"
    CANCELLED = "CANCELLED"


class DeliveryMode(str, Enum):
    LIVE = "LIVE"
    ON_DEMAND = "ON_DEMAND"


class Discipline(str, Enum):
    CYCLING = "CYCLING"
    RUNNING = "RUNNING"
    STRENGTH = "STRENGTH"
    YOGA = "YOGA"


class BenchmarkVariant(str, Enum):
    STRICT_BENCHMARK = "STRICT_BENCHMARK"
    INDULGENT_BENCHMARK = "INDULGENT_BENCHMARK"


class ClassSession(TypedDict, total=False):
    id: str
    title: str
    instructor_name: str
    discipline: str
    delivery_mode: str
    starts_at: str
    ends_at: str
    capacity: int
    license_starts_at: str
    license_ends_at: str
    scheduled_status: str
    live_enrollment_count: int
    on_demand_window_ends_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class EnrollmentStatus(str, Enum):
    ENROLLED = "ENROLLED"
    WAITLISTED = "WAITLISTED"
    COMPLETED = "COMPLETED"
    DROPPED = "DROPPED"
    EXPIRED = "EXPIRED"


class CompletionCredit(str, Enum):
    FULL_CREDIT = "FULL_CREDIT"
    PARTIAL_CREDIT = "PARTIAL_CREDIT"


class ClassEnrollment(TypedDict, total=False):
    id: str
    class_session_id: str
    device_id: str
    enroller_user_id: str
    enrolled_at: str
    status: str
    output_points: int
    integrity_points: int
    integrity_flagged: bool
    completion_pct: int
    completion_grade: Optional[str]
    created_at: str
    updated_at: str
    version: int


# ─── RefurbBatch ───────────────────────────────────────

class RefurbStatus(str, Enum):
    INSPECTING = "INSPECTING"
    CERTIFIED = "CERTIFIED"
    LISTED = "LISTED"
    SOLD = "SOLD"


class CertificationGrade(str, Enum):
    A = "A"
    B = "B"
    C = "C"


class RefurbBatch(TypedDict, total=False):
    id: str
    source_device_id: str
    performance_resale_enabled: bool
    certification_grade: str
    inspected_at: str
    status: str
    sold_device_id: Optional[str]
    certification_chain_depth: int
    resale_price_cents: Optional[int]
    library_availability: str
    created_at: str
    updated_at: str
    version: int


class DeliveryQuote(TypedDict, total=False):
    delivery_fee_cents: int
    stair_carry_fee_cents: int
    assembly_fee_cents: int
    quote_total_cents: int


class OpsSweepResult(TypedDict, total=False):
    archived_sessions: int
    expired_enrollments: int
    promoted_waitlisters: int
    terminated_memberships: int
    decommissioned_devices: int


ALL_MEMBERSHIP_STATUSES: List[str] = [s.value for s in MembershipStatus]
ALL_POSTURES: List[str] = [p.value for p in Posture]
ALL_DEVICE_STATUSES: List[str] = [s.value for s in DeviceActivationStatus]