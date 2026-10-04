"""Domain types: entity TypedDicts, status enums, role enum.

Every one of the twelve persisted resources in this domain carries the full
system field set (id, created_at, updated_at, version) — see PRD §2.4.
"""
from enum import Enum
from typing import TypedDict, Optional, List


class UserRole(str, Enum):
    PLATFORM_OPS = "PlatformOps"
    PROGRAMMING_MANAGER = "ProgrammingManager"
    DISTRIBUTOR = "Distributor"
    EXHIBITOR = "Exhibitor"
    THEATER = "Theater"
    FINANCE_OPS = "FinanceOps"
    CONTENT_OFFICER = "ContentOfficer"


class DistributorStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class CircuitStatus(str, Enum):
    PENDING = "PENDING"
    ACCREDITED = "ACCREDITED"
    SUSPENDED = "SUSPENDED"


class TheaterStatus(str, Enum):
    ACTIVE = "ACTIVE"
    DARK = "DARK"
    SUSPENDED = "SUSPENDED"


class TitleStatus(str, Enum):
    DRAFT = "DRAFT"
    BOOKABLE = "BOOKABLE"
    CLEARED = "CLEARED"
    RIGHTS_EXPIRED = "RIGHTS_EXPIRED"
    WITHDRAWN = "WITHDRAWN"
    ARCHIVED = "ARCHIVED"


class BookingStatus(str, Enum):
    DRAFT = "DRAFT"
    PENDING_APPROVAL = "PENDING_APPROVAL"
    COUNTERED = "COUNTERED"
    APPROVED = "APPROVED"
    ON_SALE = "ON_SALE"
    ON_HOLD = "ON_HOLD"
    CONFIRMED = "CONFIRMED"
    CANCELLED = "CANCELLED"
    SETTLED = "SETTLED"
    TERMINAL = "TERMINAL"


class SettlementStatus(str, Enum):
    OPEN = "OPEN"
    CLOSED = "CLOSED"
    REOPENED = "REOPENED"


class ContentDeliveryStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    DELIVERED = "DELIVERED"
    VERIFIED = "VERIFIED"
    FAILED = "FAILED"


class ScreeningState(str, Enum):
    SCHEDULED = "SCHEDULED"
    SCREENED = "SCREENED"
    SKIPPED_INCOMPLETE = "SKIPPED_INCOMPLETE"
    SKIPPED_CANCELLED = "SKIPPED_CANCELLED"
    VOID = "VOID"


class FeedEventState(str, Enum):
    DETECTED = "DETECTED"
    CONFIRMED = "CONFIRMED"
    VOIDED = "VOIDED"
    RESOLVED = "RESOLVED"


class ExhibitState(str, Enum):
    PROPOSED = "PROPOSED"
    COMMITTED = "COMMITTED"
    RELEASED = "RELEASED"


class IssuanceStatus(str, Enum):
    PENDING = "PENDING"
    ISSUED = "ISSUED"
    REVOKED = "REVOKED"


class ValidityState(str, Enum):
    NOT_YET_VALID = "NOT_YET_VALID"
    VALID = "VALID"
    EXPIRED = "EXPIRED"


class CreditRating(str, Enum):
    A = "A"
    B = "B"
    C = "C"


class SettlementTerms(str, Enum):
    NET_30 = "NET_30"
    NET_60 = "NET_60"
    GROSS_ON_GROSS = "GROSS_ON_GROSS"
    FOUR_WALL = "FOUR_WALL"


class ContentType(str, Enum):
    CONCERT = "CONCERT"
    ANNIVERSARY = "ANNIVERSARY"
    FAITH = "FAITH"
    LIVE_BROADCAST = "LIVE_BROADCAST"
    SPECIAL = "SPECIAL"


class DeliveryMethod(str, Enum):
    SATELLITE = "SATELLITE"
    FILE = "FILE"
    BOTH = "BOTH"


class FailureType(str, Enum):
    FEED_LOSS = "FEED_LOSS"
    CONTENT_FAILURE = "CONTENT_FAILURE"
    SATELLITE_OUTAGE = "SATELLITE_OUTAGE"
    KEY_FAILURE = "KEY_FAILURE"


class EncoreWindowStatus(str, Enum):
    DRAFT = "DRAFT"
    SCHEDULED = "SCHEDULED"
    WITHDRAWN = "WITHDRAWN"
    EXPIRED = "EXPIRED"


# --- Entity shapes (all carry the full system field set) --------------------

class Distributor(TypedDict):
    id: str
    distributor_name: str
    contact_email: str
    settlement_currency: str
    guarantee_floor_cents: int
    ticket_price_default_cents: int
    status: str
    bookable_title_count: int
    created_at: str
    updated_at: str
    version: int


class Circuit(TypedDict):
    id: str
    circuit_name: str
    circuit_code: str
    credit_rating: str
    settlement_terms: str
    screen_pool_total: int
    on_sale_lead_days_min: int
    committed_screens_balance: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Theater(TypedDict):
    id: str
    circuit_id: str
    theater_name: str
    city: str
    state_code: str
    timezone: str
    seats_total: int
    screen_count: int
    showtime_buffer_minutes: int
    status: str
    pending_rekey_count: int
    created_at: str
    updated_at: str
    version: int


class Title(TypedDict):
    id: str
    distributor_id: str
    title_name: str
    content_type: str
    is_live: bool
    duration_minutes: int
    rights_start_utc: str
    rights_end_utc: str
    territory_state_codes: List[str]
    max_screen_commitment: int
    ticket_price_cents: Optional[int]
    status: str
    bookable_window_days: int
    booking_count: int
    created_at: str
    updated_at: str
    version: int


class ShowtimePlanElement(TypedDict):
    index: int
    date_utc: str
    start_minute_utc: int
    auditorium: str


class Booking(TypedDict):
    id: str
    title_id: str
    circuit_id: str
    negotiating_user_id: str
    showtime_count: int
    showtime_plan: List[ShowtimePlanElement]
    on_sale_at: str
    guarantee_cents: int
    revenue_share_pct: float
    min_screens: int
    pre_sale_threshold: int
    status: str
    committed_screens_total: int
    guarantee_ceiling_cents: int
    pre_sale_tickets: int
    live_feed_event_count: int
    makegood_credit_cents: int
    settled_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class BookingLine(TypedDict):
    id: str
    booking_id: str
    theater_id: str
    committed_screens: int
    exhibit_state: str
    expected_attendance: int
    sold_tickets: int
    guarantee_applied_cents: int
    credit_issued_cents: int
    created_at: str
    updated_at: str
    version: int


class Screening(TypedDict):
    id: str
    booking_id: str
    theater_id: str
    auditorium: str
    starts_at: str
    ends_at: str
    state: str
    is_encore: bool
    reported_attendance: Optional[int]
    created_at: str
    updated_at: str
    version: int


class EncoreWindow(TypedDict):
    id: str
    booking_id: str
    title_id: str
    window_start_utc: str
    window_end_utc: str
    standard_ticket_price_cents: int
    encore_ticket_price_cents: int
    planned_screen_count: int
    status: str
    derived_encore_price_cents: int
    encore_screening_count: int
    created_at: str
    updated_at: str
    version: int


class ContentDelivery(TypedDict):
    id: str
    booking_id: str
    title_id: str
    delivery_method: str
    content_checksum: str
    scheduled_delivery_utc: str
    delivered_at_utc: Optional[str]
    status: str
    delivered_checksum: Optional[str]
    created_at: str
    updated_at: str
    version: int


class EncryptionKey(TypedDict):
    id: str
    screening_id: str
    title_id: str
    key_ref: Optional[str]
    not_valid_before_utc: str
    not_valid_after_utc: str
    issuance_status: str
    validity_state: str
    revocation_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class FeedEvent(TypedDict):
    id: str
    booking_id: str
    screening_id: Optional[str]
    failure_type: str
    detected_at_utc: str
    outage_minutes: int
    state: str
    resolution_outcome: Optional[str]
    affected_screening_count: int
    created_at: str
    updated_at: str
    version: int


class Settlement(TypedDict):
    id: str
    booking_id: str
    gross_box_office_cents: int
    reported_line_count: int
    topup_paid_cents: int
    adjustment_cents: int
    feed_failure_credit_cents: int
    makegood_credit_cents: int
    distributor_net_cents: int
    exhibitor_net_cents: int
    invariant_drift_cents: int
    status: str
    closed_at_utc: Optional[str]
    created_at: str
    updated_at: str
    version: int