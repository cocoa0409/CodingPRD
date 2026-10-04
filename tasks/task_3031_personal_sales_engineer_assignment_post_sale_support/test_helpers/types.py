"""Domain types: entity TypedDicts, status enums, role enum.

Field names are PRD-exact. Every entity in this service declares the universal
pair ``created_at`` / ``updated_at`` plus the integer ``version`` (PRD 2.8,
"Every entity in this API declares both `updated_at` and `version`").
"""
from enum import Enum
from typing import TypedDict


class UserRole(str, Enum):
    PLATFORM_ADMIN = "PlatformAdmin"
    SALES_ENGINEER_OPS = "SalesEngineerOps"
    ENGINEER = "Engineer"
    SETUP_TECHNICIAN = "SetupTechnician"
    SUPPORT_AGENT = "SupportAgent"
    SERVICE_DEPARTMENT = "ServiceDepartment"
    ANONYMOUS = "Anonymous"


class ProductFamily(str, Enum):
    GUITAR = "GUITAR"
    AMPLIFIER = "AMPLIFIER"
    INTERFACE = "INTERFACE"
    MICROPHONE = "MICROPHONE"
    EFFECT_PEDAL = "EFFECT_PEDAL"
    ACCESSORY = "ACCESSORY"


class Region(str, Enum):
    MIDWEST = "MIDWEST"
    SOUTH = "SOUTH"
    WEST = "WEST"
    EAST = "EAST"


class EngineerStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    OFFBOARDED = "OFFBOARDED"


class SeniorityTier(str, Enum):
    TIER_1 = "TIER_1"
    TIER_2 = "TIER_2"
    TIER_3 = "TIER_3"


class CustomerStatus(str, Enum):
    PENDING = "PENDING"
    ACTIVE = "ACTIVE"
    CLOSED = "CLOSED"


class AccountTier(str, Enum):
    STANDARD = "STANDARD"
    PREMIUM = "PREMIUM"
    STUDIO = "STUDIO"


class Entitlement(str, Enum):
    NONE = "NONE"
    BASIC = "BASIC"
    EXTENDED = "EXTENDED"


class AssignmentStatus(str, Enum):
    PENDING_ACCEPT = "PENDING_ACCEPT"
    ACTIVE = "ACTIVE"
    ENDED = "ENDED"


class AssignmentReason(str, Enum):
    NEW_ACCOUNT = "NEW_ACCOUNT"
    PERMANENT_TRANSFER = "PERMANENT_TRANSFER"
    REGION_CHANGE = "REGION_CHANGE"
    TEMPORARY_COVERAGE = "TEMPORARY_COVERAGE"


class PackageType(str, Enum):
    SYSTEM_PACKAGE = "SYSTEM_PACKAGE"
    INSTRUMENT_ONLY = "INSTRUMENT_ONLY"
    ACCESSORY_ONLY = "ACCESSORY_ONLY"


class QuoteStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    RESERVED = "RESERVED"
    REJECTED = "REJECTED"
    CANCELLED = "CANCELLED"


class SetupStatus(str, Enum):
    PENDING_SETUP = "PENDING_SETUP"
    IN_SETUP = "IN_SETUP"
    SETUP_COMPLETE = "SETUP_COMPLETE"
    INSPECTED = "INSPECTED"
    SHIPPED = "SHIPPED"


class InspectionVerdict(str, Enum):
    PASS = "PASS"
    CONDITIONAL = "CONDITIONAL"
    FAIL = "FAIL"


class WarrantyPlanStatus(str, Enum):
    PENDING = "PENDING"
    ACTIVE = "ACTIVE"
    CLAIM_OPEN = "CLAIM_OPEN"
    REPAIR_IN_PROGRESS = "REPAIR_IN_PROGRESS"
    EXPIRED = "EXPIRED"
    VOIDED = "VOIDED"


class WarrantyClaimStatus(str, Enum):
    PENDING_ROUTING = "PENDING_ROUTING"
    ROUTED = "ROUTED"
    CLOSED = "CLOSED"


class ServiceCenterStatus(str, Enum):
    OPEN = "OPEN"
    SUSPENDED = "SUSPENDED"


class TicketStatus(str, Enum):
    OPEN = "OPEN"
    IN_TRIAGE = "IN_TRIAGE"
    ESCALATED = "ESCALATED"
    RESOLVED = "RESOLVED"


class TicketChannel(str, Enum):
    PHONE = "PHONE"
    EMAIL = "EMAIL"
    CHAT = "CHAT"


class LedgerEventType(str, Enum):
    SERVICE_DEPARTMENT_ESCALATION = "SERVICE_DEPARTMENT_ESCALATION"
    ESCALATION_WITHDRAWN = "ESCALATION_WITHDRAWN"


class BackorderStatus(str, Enum):
    PREORDER_PENDING = "PREORDER_PENDING"
    ALLOCATION_SWEEP = "ALLOCATION_SWEEP"
    PARTIALLY_FILLED = "PARTIALLY_FILLED"
    BOARD_FILLED = "BOARD_FILLED"
    RECEIVING = "RECEIVING"
    SHIPPED = "SHIPPED"
    CANCELLED = "CANCELLED"


class ExchangeReason(str, Enum):
    TONE_MISMATCH = "TONE_MISMATCH"
    DEFECT_DOA = "DEFECT_DOA"
    WRONG_MODEL = "WRONG_MODEL"
    CHANGED_MIND = "CHANGED_MIND"


class ExchangeStatus(str, Enum):
    DRAFT = "DRAFT"
    TRIAL_ACTIVE = "TRIAL_ACTIVE"
    RETURN_REQUESTED = "RETURN_REQUESTED"
    EXCHANGED = "EXCHANGED"
    DENIED = "DENIED"
    CANCELLED = "CANCELLED"


class CertificationStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    PASSED = "PASSED"
    FAILED = "FAILED"
    EXPIRED = "EXPIRED"


class Engineer(TypedDict, total=False):
    id: str
    full_name: str
    email: str
    region: str
    status: str
    max_book_size: int
    active_book_size: int
    certified_family_count: int
    seniority_tier: str
    commission_cap_bps: int
    lifetime_commission_cents: int
    created_at: str
    updated_at: str
    version: int


class Customer(TypedDict, total=False):
    id: str
    full_name: str
    email: str
    home_state: str
    account_tier: str
    status: str
    assigned_engineer_id: str
    purchased_instrument_count: int
    lifetime_gear_credit_cents: int
    tech_support_entitlement: str
    created_at: str
    updated_at: str
    version: int


class Assignment(TypedDict, total=False):
    id: str
    customer_id: str
    engineer_id: str
    reason_code: str
    commission_share_bps: int
    effective_until: str
    sequence: int
    assigned_at: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Quote(TypedDict, total=False):
    id: str
    customer_id: str
    engineer_id: str
    package_type: str
    status: str
    bundle_ready: bool
    dependency_closure_size: int
    gross_subtotal_cents: int
    reserved_at: str
    created_at: str
    updated_at: str
    version: int


class QuoteLine(TypedDict, total=False):
    id: str
    quote_id: str
    product_id: str
    product_code: str
    product_family: str
    is_anchor: bool
    unit_price_cents: int
    quantity: int
    requires_line_id: str
    bundle_discount_bps: int
    line_total_cents: int
    created_at: str
    updated_at: str
    version: int


class InstrumentUnit(TypedDict, total=False):
    id: str
    quote_line_id: str
    serial_number: str
    model_code: str
    setup_status: str
    setup_technician_id: str
    action_height_mm: float
    relief_mm: float
    intonation_offset_cents: int
    inspection_overall: str
    modified_since_setup: bool
    shipped_at: str
    created_at: str
    updated_at: str
    version: int


class WarrantyPlan(TypedDict, total=False):
    id: str
    customer_id: str
    instrument_unit_id: str
    term_months: int
    starts_on: str
    expires_on: str
    status: str
    repair_rounds_used: int
    remaining_repair_rounds: int
    created_at: str
    updated_at: str
    version: int


class WarrantyClaim(TypedDict, total=False):
    id: str
    warranty_plan_id: str
    reported_fault: str
    service_center_id: str
    status: str
    routed_at: str
    closed_at: str
    created_at: str
    updated_at: str
    version: int


class ServiceCenter(TypedDict, total=False):
    id: str
    name: str
    region: str
    capacity_slots: int
    open_ticket_count: int
    accepted_families: list
    status: str
    created_at: str
    updated_at: str
    version: int


class SupportTicket(TypedDict, total=False):
    id: str
    customer_id: str
    subject: str
    channel: str
    service_center_id: str
    status: str
    required_entitlement: str
    escalated_at: str
    escalated_by: str
    prior_service_center_id: str
    escalation_seq: int
    escalation_count: int
    created_at: str
    updated_at: str
    version: int


class Product(TypedDict, total=False):
    id: str
    product_code: str
    display_name: str
    product_family: str
    unit_price_cents: int
    required_family: str
    requires_certification: bool
    in_catalog: bool
    created_at: str
    updated_at: str
    version: int


class Backorder(TypedDict, total=False):
    id: str
    quote_line_id: str
    engineer_id: str
    variant_bps: int
    preorder_open_at: str
    units_requested: int
    units_filled: int
    overcommit_estimate_units: int
    alloc_sequence: int
    eta_deadline: str
    status: str
    created_at: str
    updated_at: str
    version: int


class GearExchange(TypedDict, total=False):
    id: str
    quote_line_id: str
    customer_id: str
    reason: str
    trial_start_date: str
    trial_end_date: str
    days_remaining: int
    restocking_fee_bps: int
    restocking_fee_cents: int
    refund_credit_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class CertificationAttempt(TypedDict, total=False):
    id: str
    engineer_id: str
    product_family: str
    score_pct: int
    attempt_index: int
    eligible_to_retake: bool
    certified: bool
    status: str
    assessed_at: str
    expires_at: str
    created_at: str
    updated_at: str
    version: int


class EscalationLedgerEntry(TypedDict, total=False):
    id: str
    support_ticket_id: str
    service_center_id: str
    event_type: str
    escalation_seq: int
    posted_at: str
    created_at: str
    updated_at: str
    version: int