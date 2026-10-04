"""Domain types for the digital freight matching platform.

Entity TypedDicts follow the PRD's common-field convention: entities that carry
the common field set expose id/created_at/updated_at/version, while the two
append-only observational records carry only id and created_at.
"""
from enum import Enum
from typing import TypedDict, Optional, List


# --------------------------------------------------------------------------
# Status enums
# --------------------------------------------------------------------------
class ShipperStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class CarrierStatus(str, Enum):
    PENDING = "PENDING"
    AUTHORITY_VERIFIED = "AUTHORITY_VERIFIED"
    INSURANCE_ON_FILE = "INSURANCE_ON_FILE"
    VERIFIED = "VERIFIED"
    SUSPENDED = "SUSPENDED"


class OperatingAuthorityStatus(str, Enum):
    NONE = "NONE"
    PENDING = "PENDING"
    ACTIVE = "ACTIVE"
    REVOKED = "REVOKED"


class EquipmentType(str, Enum):
    DRY_VAN = "DRY_VAN"
    REEFER = "REEFER"
    FLATBED = "FLATBED"


class EquipmentStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    ASSIGNED = "ASSIGNED"
    IN_SHOP = "IN_SHOP"


class FacilityStatus(str, Enum):
    ACTIVE = "ACTIVE"
    CLOSED = "CLOSED"


class LaneContractStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    EXPIRED = "EXPIRED"


class PricingMode(str, Enum):
    SPOT = "SPOT"
    CONTRACT = "CONTRACT"


class MarketBand(str, Enum):
    OPEN = "OPEN"
    BALANCED = "BALANCED"
    TIGHT = "TIGHT"


class Commodity(str, Enum):
    GENERAL = "GENERAL"
    TEMPERATURE_CONTROLLED = "TEMPERATURE_CONTROLLED"
    HAZMAT = "HAZMAT"
    HIGH_VALUE = "HIGH_VALUE"


class LoadStatus(str, Enum):
    DRAFT = "DRAFT"
    POSTED = "POSTED"
    UNCOVERED = "UNCOVERED"
    BOOKED = "BOOKED"
    IN_TRANSIT = "IN_TRANSIT"
    DELIVERED = "DELIVERED"
    INVOICED = "INVOICED"
    PAID = "PAID"
    CANCELLED = "CANCELLED"
    VOIDED = "VOIDED"


TERMINAL_LOAD_STATUSES = {"PAID", "CANCELLED", "VOIDED"}


class QuoteKind(str, Enum):
    INITIAL = "INITIAL"
    REPRICED = "REPRICED"


class QuoteStatus(str, Enum):
    ACTIVE = "ACTIVE"
    VIEWED = "VIEWED"
    DECLINED = "DECLINED"
    ACCEPTED = "ACCEPTED"
    SUPERSEDED = "SUPERSEDED"
    EXPIRED = "EXPIRED"


class BookingStatus(str, Enum):
    PENDING_APPOINTMENT = "PENDING_APPOINTMENT"
    IN_TRANSIT = "IN_TRANSIT"
    DELIVERED = "DELIVERED"
    SETTLED = "SETTLED"
    CANCELLED = "CANCELLED"


class SlotKind(str, Enum):
    PICKUP = "PICKUP"
    DELIVERY = "DELIVERY"


class AppointmentStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    MISSED = "MISSED"
    CANCELLED = "CANCELLED"


class DetentionStatus(str, Enum):
    OPEN = "OPEN"
    CLOSED = "CLOSED"
    WAIVED = "WAIVED"


class ReportedStatus(str, Enum):
    EN_ROUTE_PICKUP = "EN_ROUTE_PICKUP"
    AT_PICKUP = "AT_PICKUP"
    IN_TRANSIT = "IN_TRANSIT"
    AT_DELIVERY = "AT_DELIVERY"
    DELIVERED = "DELIVERED"


STATUS_RANK = {
    "EN_ROUTE_PICKUP": 1,
    "AT_PICKUP": 2,
    "IN_TRANSIT": 3,
    "AT_DELIVERY": 4,
    "DELIVERED": 5,
}


class ClaimStatus(str, Enum):
    FILED = "FILED"
    UNDER_REVIEW = "UNDER_REVIEW"
    INFO_REQUESTED = "INFO_REQUESTED"
    APPROVED = "APPROVED"
    DENIED = "DENIED"
    ESCALATED = "ESCALATED"
    SETTLED = "SETTLED"


class FiledByRole(str, Enum):
    SHIPPER = "SHIPPER"
    CARRIER = "CARRIER"


class SettlementStatus(str, Enum):
    ACCRUED = "ACCRUED"
    READY = "READY"
    PAID = "PAID"
    CLAWED_BACK = "CLAWED_BACK"
    REVERSED = "REVERSED"


class PayoutMode(str, Enum):
    TERMS = "TERMS"
    QUICK_PAY = "QUICK_PAY"


class UserRole(str, Enum):
    ANONYMOUS = "Anonymous"
    SHIPPER = "Shipper"
    CARRIER = "Carrier"
    COMPLIANCE_REVIEWER = "ComplianceReviewer"
    CLAIMS_ADJUSTER = "ClaimsAdjuster"
    PLATFORM_ADMIN = "PlatformAdmin"


DECLARED_ROLES = [r.value for r in UserRole]


# --------------------------------------------------------------------------
# Entity TypedDicts
# --------------------------------------------------------------------------
class Shipper(TypedDict):
    id: str
    name: str
    billing_state_code: str
    payment_terms_days: int
    quick_pay_discount_pct: float
    credit_limit_cents: int
    credit_used_cents: int
    credit_available_cents: int
    load_credit_limit: int
    load_credits_committed: int
    load_credits_available: int
    blocked_carrier_ids: List[str]
    breached_pickup_count: int
    last_repriced_lane: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class Carrier(TypedDict):
    id: str
    legal_name: str
    mc_number: str
    dot_number: str
    operating_authority_status: str
    authority_verified_at: Optional[str]
    insurance_expires_at: str
    insurance_liability_limit_cents: int
    cargo_coverage_limit_cents: int
    insurance_attested_at: Optional[str]
    certificate_reference: Optional[str]
    safety_score: float
    equipment_types: List[str]
    claims_clawback_count: int
    operational_risk_score: float
    suspension_reason: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class CarrierEquipment(TypedDict):
    id: str
    carrier_id: str
    equipment_type: str
    unit_number: str
    driver_name: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Facility(TypedDict):
    id: str
    name: str
    state_code: str
    dock_capacity: int
    default_appointment_minutes: int
    free_dwell_minutes: int
    detention_rate_per_hour_cents: int
    docks_committed_today: int
    status: str
    created_at: str
    updated_at: str
    version: int


class LaneContract(TypedDict):
    id: str
    shipper_id: str
    origin_facility_id: str
    destination_facility_id: str
    equipment_type: str
    committed_weekly_volume: int
    committed_rate_cents: int
    accessorial_allowance_cents: int
    start_date: str
    end_date: str
    loads_committed_this_period: int
    period_start: Optional[str]
    contract_carrier_ids: List[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class Load(TypedDict):
    id: str
    shipper_id: str
    origin_facility_id: str
    destination_facility_id: str
    lane_contract_id: Optional[str]
    lane_key: str
    pricing_mode: str
    market_band: str
    equipment_type: str
    commodity: str
    weight_lbs: int
    declared_cargo_value_cents: int
    distance_miles: float
    pickup_window_start: str
    pickup_window_end: str
    delivery_deadline: str
    posted_rate_cents: Optional[int]
    booked_rate_cents: Optional[int]
    reprice_count: int
    repost_count: int
    carrier_id: Optional[str]
    equipment_id: Optional[str]
    accessorial_total_cents: int
    actual_pickup_at: Optional[str]
    pickup_breach_flag: bool
    tracking_status_rank: int
    shipper_version: int
    projected_delay_minutes: int
    status: str
    created_at: str
    updated_at: str
    version: int


class RateQuote(TypedDict):
    id: str
    load_id: str
    quote_kind: str
    base_rate_cents: int
    repriced_rate_cents: Optional[int]
    effective_miles: float
    quoted_cents_per_mile: float
    market_level_cents_per_mile: int
    acceptance_deadline: str
    viewed_carrier_ids: List[str]
    declined_carrier_ids: List[str]
    min_rate_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Booking(TypedDict):
    id: str
    load_id: str
    carrier_id: str
    rate_quote_id: str
    equipment_id: str
    agreed_rate_cents: int
    booked_at: str
    booking_window_start: str
    booking_window_end: str
    appointment_id: str
    contract_lane_draw: bool
    quick_pay_elected: bool
    quick_pay_discount_cents: int
    settled_at: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class AppointmentSlot(TypedDict):
    id: str
    facility_id: str
    load_id: Optional[str]
    carrier_id: str
    slot_kind: str
    dock_position: int
    window_start: str
    window_end: str
    scheduled_date: str
    status: str
    created_at: str
    updated_at: str
    version: int


class DetentionEvent(TypedDict):
    id: str
    appointment_id: str
    facility_id: str
    load_id: str
    carrier_id: str
    arrived_at: str
    departed_at: Optional[str]
    dwell_minutes: int
    billable_detention_minutes: int
    detention_charge_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class TrackingPing(TypedDict):
    """Append-only observational record: id and created_at only."""
    id: str
    load_id: str
    carrier_id: str
    sequence: int
    reported_status: str
    status_rank: int
    location_code: str
    eta_utc: Optional[str]
    recorded_at: str
    created_at: str


class StatusEvent(TypedDict):
    """Append-only observational record: id and created_at only."""
    id: str
    load_id: str
    event_type: str
    source: str
    occurred_at: str
    note: Optional[str]
    created_at: str


class ClaimsCase(TypedDict):
    id: str
    load_id: str
    carrier_id: str
    claimed_amount_cents: int
    damage_description: str
    filed_by_role: str
    liability_limit_cents: int
    price_cap_cents: int
    provisional_liability_cents: int
    approved_amount_cents: int
    review_rounds: int
    escalated: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class CarrierSettlement(TypedDict):
    id: str
    carrier_id: str
    booking_id: str
    load_id: str
    line_haul_cents: int
    accessorial_cents: int
    claims_deduction_cents: int
    gross_payable_cents: int
    quick_pay_discount_cents: int
    net_payable_cents: int
    payout_due_at: Optional[str]
    paid_at: Optional[str]
    reversal_of_settlement_id: Optional[str]
    settlement_status: str
    created_at: str
    updated_at: str
    version: int