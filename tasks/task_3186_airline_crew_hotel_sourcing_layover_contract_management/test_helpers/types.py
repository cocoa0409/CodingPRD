"""Domain types: entity TypedDicts, status enums, role enum."""
from enum import Enum
from typing import TypedDict, Optional, List, Any


class CrewType(str, Enum):
    PILOT = "PILOT"
    FLIGHT_ATTENDANT = "FLIGHT_ATTENDANT"


class VendorStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    BLACKLISTED = "BLACKLISTED"


class RfpCycleStatus(str, Enum):
    DRAFT = "DRAFT"
    OPEN = "OPEN"
    EVALUATION = "EVALUATION"
    NEGOTIATION = "NEGOTIATION"
    AWARDED = "AWARDED"
    CANCELLED = "CANCELLED"


class RfpProposalStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    UNDER_REVIEW = "UNDER_REVIEW"
    SHORTLISTED = "SHORTLISTED"
    REJECTED = "REJECTED"
    ACCEPTED = "ACCEPTED"
    WITHDRAWN = "WITHDRAWN"


class ContractStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    TERMINATED = "TERMINATED"
    EXPIRED = "EXPIRED"


class LayoverStatus(str, Enum):
    PLANNED = "PLANNED"
    CONFIRMED = "CONFIRMED"
    SURGED = "SURGED"
    CANCELLED = "CANCELLED"
    COMPLETED = "COMPLETED"


class AllocationKind(str, Enum):
    CONTRACTED = "CONTRACTED"
    DISTRESSED = "DISTRESSED"


class AllocationStatus(str, Enum):
    HELD = "HELD"
    CONFIRMED = "CONFIRMED"
    CHECKED_IN = "CHECKED_IN"
    RELEASED = "RELEASED"
    CANCELLED = "CANCELLED"
    NO_SHOW = "NO_SHOW"


class TripDirection(str, Enum):
    AIRPORT_TO_HOTEL = "AIRPORT_TO_HOTEL"
    HOTEL_TO_AIRPORT = "HOTEL_TO_AIRPORT"


class TripStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    DISPATCHED = "DISPATCHED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"
    MISSED = "MISSED"


class AuditStatus(str, Enum):
    OPEN = "OPEN"
    IN_PROGRESS = "IN_PROGRESS"
    CLOSED_PASS = "CLOSED_PASS"
    CLOSED_FAIL = "CLOSED_FAIL"


class AuditSeverity(str, Enum):
    MINOR = "MINOR"
    MAJOR = "MAJOR"
    CRITICAL = "CRITICAL"


class InvoiceStatus(str, Enum):
    RECEIVED = "RECEIVED"
    RECONCILED = "RECONCILED"
    APPROVED = "APPROVED"
    DISPUTED = "DISPUTED"
    PAID = "PAID"
    REJECTED = "REJECTED"


class MinRoomStandard(str, Enum):
    STANDARD = "STANDARD"
    PREMIUM = "PREMIUM"
    SUITE = "SUITE"


class QuietRoomStandard(str, Enum):
    BASIC = "BASIC"
    ENHANCED = "ENHANCED"
    PREMIUM = "PREMIUM"


class FeedbackCategory(str, Enum):
    NOISE = "NOISE"
    SECURITY = "SECURITY"
    CLEANLINESS = "CLEANLINESS"
    TRANSPORT = "TRANSPORT"
    OTHER = "OTHER"


class UserRole(str, Enum):
    PLATFORM_ADMIN = "PlatformAdmin"
    SOURCING_MANAGER = "SourcingManager"
    CREW_OPS = "CrewOps"
    FINANCE_ANALYST = "FinanceAnalyst"
    CREW_AUDITOR = "CrewAuditor"
    HOTEL_VENDOR_REP = "HotelVendorRep"


class Station(TypedDict, total=False):
    id: str
    code: str
    name: str
    timezone: str
    min_rest_hours: int
    transport_time_minutes: int
    room_availability_commitment: int
    created_at: str
    updated_at: str
    version: int


class UnionAgreement(TypedDict, total=False):
    id: str
    name: str
    crew_type: str
    min_rest_hours: int
    quiet_room_required: bool
    min_room_standard: str
    blackout_protection_required: bool
    max_invoice_variance_pct: float
    created_at: str
    updated_at: str
    version: int


class HotelVendor(TypedDict, total=False):
    id: str
    name: str
    contact_email: str
    status: str
    security_certified: bool
    quiet_rooms_count: int
    created_at: str
    updated_at: str
    version: int


class RfpCycle(TypedDict, total=False):
    id: str
    station_id: str
    title: str
    status: str
    response_deadline: str
    target_room_count: int
    budget_cap_cents: int
    negotiation_round: int
    created_at: str
    updated_at: str
    version: int


class RfpProposal(TypedDict, total=False):
    id: str
    rfp_cycle_id: str
    vendor_id: str
    offered_room_count: int
    offered_rate_cents: int
    current_rate_cents: int
    status: str
    quiet_room_commitment: int
    blackout_dates: List[str]
    created_at: str
    updated_at: str
    version: int


class Contract(TypedDict, total=False):
    id: str
    rfp_cycle_id: str
    station_id: str
    vendor_id: str
    proposal_id: str
    status: str
    room_block_size: int
    negotiated_rate_cents: int
    start_date: str
    end_date: str
    late_cancel_hours: int
    quiet_room_standard: str
    security_requirements: List[str]
    blackout_dates: List[str]
    blackout_protection: bool
    remediation_deadline: Optional[str]
    total_contract_value_cents: int
    created_at: str
    updated_at: str
    version: int


class CrewLayoverRequirement(TypedDict, total=False):
    id: str
    station_id: str
    crew_type: str
    crew_count: int
    arrival_time: str
    departure_time: str
    required_rest_hours: int
    status: str
    is_irregular_ops: bool
    rest_compliant: bool
    created_at: str
    updated_at: str
    version: int


class RoomAllocation(TypedDict, total=False):
    id: str
    layover_requirement_id: str
    contract_id: Optional[str]
    vendor_id: Optional[str]
    kind: str
    status: str
    rooms_held: int
    nightly_rate_cents: int
    blackout_rate_cents: Optional[int]
    stay_date: str
    distressed_cost_cents: Optional[int]
    created_at: str
    updated_at: str
    version: int


class TransportTrip(TypedDict, total=False):
    id: str
    layover_requirement_id: str
    contract_id: Optional[str]
    direction: str
    pickup_time: str
    status: str
    vehicle_capacity: int
    created_at: str
    updated_at: str
    version: int


# Append-only (common_fields: false): carries ONLY id + created_at
class CrewFeedback(TypedDict, total=False):
    id: str
    contract_id: str
    layover_requirement_id: str
    crew_type: str
    rating: int
    category: str
    comment: str
    created_at: str


class Audit(TypedDict, total=False):
    id: str
    contract_id: str
    auditor_id: str
    status: str
    severity: str
    findings: str
    opened_at: str
    created_at: str
    updated_at: str
    version: int


class Invoice(TypedDict, total=False):
    id: str
    contract_id: str
    billing_period_start: str
    billing_period_end: str
    status: str
    billed_room_nights: int
    billed_amount_cents: int
    reconciled_room_nights: int
    reconciled_amount_cents: int
    variance_pct: float
    created_at: str
    updated_at: str
    version: int
