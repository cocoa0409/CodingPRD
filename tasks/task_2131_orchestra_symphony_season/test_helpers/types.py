"""Domain types for the Orchestra Symphony Season API.

Status enums, role enum and entity TypedDicts. Every persisted resource in this
system carries `id`, `created_at`, `updated_at` and `version` (PRD 2.4), so every
TypedDict below lists all four.
"""

from enum import Enum
from typing import List, Optional, TypedDict


# --------------------------------------------------------------------------
# Roles
# --------------------------------------------------------------------------
class UserRole(str, Enum):
    ARTISTIC_ADMIN = "ArtisticAdmin"
    ORCHESTRA_MANAGER = "OrchestraManager"
    BOX_OFFICE_AGENT = "BoxOfficeAgent"
    PATRON = "Patron"
    MUSICIAN = "Musician"
    GUEST_ARTIST = "GuestArtist"
    ADVERTISING_SALES = "AdvertisingSales"


ALL_ROLES = [r.value for r in UserRole]


# --------------------------------------------------------------------------
# Status enums
# --------------------------------------------------------------------------
class SeasonStatus(str, Enum):
    PLANNING = "PLANNING"
    RENEWAL_WINDOW = "RENEWAL_WINDOW"
    SINGLE_ON_SALE = "SINGLE_ON_SALE"
    IN_PROGRESS = "IN_PROGRESS"
    CLOSED = "CLOSED"


class ProgrammingStatus(str, Enum):
    DRAFT = "DRAFT"
    PROGRAMMED = "PROGRAMMED"
    LOCKED = "LOCKED"


class SaleStatus(str, Enum):
    UNANNOUNCED = "UNANNOUNCED"
    RENEWAL_ONLY = "RENEWAL_ONLY"
    PUBLIC_ONSALE = "PUBLIC_ONSALE"
    SALES_CLOSED = "SALES_CLOSED"


class PerformanceStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    PERFORMED = "PERFORMED"
    CANCELLED = "CANCELLED"


class ReadinessPosture(str, Enum):
    READY = "READY"
    AT_RISK = "AT_RISK"
    BLOCKED = "BLOCKED"


class DemandBand(str, Enum):
    LOW = "LOW"
    MODERATE = "MODERATE"
    HIGH = "HIGH"
    PEAK = "PEAK"


class ContractStatus(str, Enum):
    OFFERED = "OFFERED"
    COUNTERED = "COUNTERED"
    SIGNED = "SIGNED"
    WITHDRAWN = "WITHDRAWN"


class ContractRoleType(str, Enum):
    SOLOIST = "SOLOIST"
    CONDUCTOR = "CONDUCTOR"


class ServiceStatus(str, Enum):
    DRAFT = "DRAFT"
    PUBLISHED = "PUBLISHED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class ServiceType(str, Enum):
    REHEARSAL = "REHEARSAL"
    DRESS_REHEARSAL = "DRESS_REHEARSAL"
    PERFORMANCE = "PERFORMANCE"


class ComplianceStatus(str, Enum):
    COMPLIANT = "COMPLIANT"
    UNDERSTAFFED = "UNDERSTAFFED"


class EngagementStatus(str, Enum):
    CONFIRMED = "CONFIRMED"
    DECLINED = "DECLINED"
    SETTLED = "SETTLED"
    VOIDED = "VOIDED"


class Instrument(str, Enum):
    VIOLIN = "VIOLIN"
    VIOLA = "VIOLA"
    CELLO = "CELLO"
    BASS = "BASS"
    FLUTE = "FLUTE"
    OBOE = "OBOE"
    CLARINET = "CLARINET"
    BASSOON = "BASSOON"
    HORN = "HORN"
    TRUMPET = "TRUMPET"
    TROMBONE = "TROMBONE"
    PERCUSSION = "PERCUSSION"
    HARP = "HARP"


class DonorLevel(str, Enum):
    NONE = "NONE"
    FRIEND = "FRIEND"
    SUSTAINER = "SUSTAINER"
    BENEFACTOR = "BENEFACTOR"
    LAUREATE = "LAUREATE"


class PackageType(str, Enum):
    NEW = "NEW"
    RENEWAL = "RENEWAL"


class PackageStatus(str, Enum):
    PENDING_PAYMENT = "PENDING_PAYMENT"
    ACTIVE = "ACTIVE"
    LAPSED = "LAPSED"
    EXPIRED = "EXPIRED"


class TicketOrderStatus(str, Enum):
    HELD = "HELD"
    PAID = "PAID"
    EXPIRED = "EXPIRED"
    REFUNDED = "REFUNDED"


class AdSize(str, Enum):
    FULL_PAGE = "FULL_PAGE"
    HALF_PAGE = "HALF_PAGE"
    QUARTER_PAGE = "QUARTER_PAGE"


class AdPlacement(str, Enum):
    BACK_COVER = "BACK_COVER"
    INSIDE_FRONT_COVER = "INSIDE_FRONT_COVER"
    RUN_OF_BOOK = "RUN_OF_BOOK"


class AdBookingStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


# --------------------------------------------------------------------------
# Entity shapes
# --------------------------------------------------------------------------
class Season(TypedDict):
    id: str
    name: str
    fiscal_year: int
    renewal_deadline_utc: str
    base_ticket_price_cents: int
    loyalty_discount_bp: int
    status: str
    ops_run_index: int
    concerts_programmed_count: int
    concerts_cancelled_count: int
    program_book_revenue_cents: int
    created_at: str
    updated_at: str
    version: int


class Venue(TypedDict):
    id: str
    name: str
    changeover_buffer_minutes: int
    total_capacity: int
    created_at: str
    updated_at: str
    version: int


class SeatSection(TypedDict):
    id: str
    venue_id: str
    name: str
    capacity: int
    price_multiplier_bp: int
    donor_priority_rank: int
    min_renewal_priority_score: int
    created_at: str
    updated_at: str
    version: int


class SectionInventoryElement(TypedDict):
    seat_section_id: str
    capacity: int
    held_count: int
    sold_count: int
    available_count: int
    fill_bp: int
    demand_band: str


class Concert(TypedDict):
    id: str
    season_id: str
    venue_id: str
    title: str
    performance_start_utc: str
    performance_end_utc: str
    program_minutes: int
    programming_status: str
    sale_status: str
    performance_status: str
    readiness_posture: str
    section_inventory: List[SectionInventoryElement]
    seats_held_count: int
    seats_sold_count: int
    substitution_count: int
    gross_ticket_revenue_cents: int
    created_at: str
    updated_at: str
    version: int


class GuestArtistContract(TypedDict):
    id: str
    concert_id: str
    artist_name: str
    role_type: str
    offered_fee_cents: int
    countered_fee_cents: Optional[int]
    agreed_fee_cents: Optional[int]
    negotiation_round: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Musician(TypedDict):
    id: str
    full_name: str
    instrument: str
    is_principal: bool
    overscale_bp: int
    services_charged_ytd: int
    ytd_earnings_cents: int
    created_at: str
    updated_at: str
    version: int


class UnionAgreement(TypedDict):
    id: str
    season_id: str
    scale_service_fee_cents: int
    max_service_minutes: int
    overtime_rate_cents_per_minute: int
    min_rest_minutes_between_services: int
    max_services_per_day: int
    doubling_premium_bp: int
    mandatory_break_minutes: int
    principal_premium_bp: int
    created_at: str
    updated_at: str
    version: int


class RehearsalService(TypedDict):
    id: str
    concert_id: str
    venue_id: str
    service_type: str
    scheduled_start_utc: str
    scheduled_end_utc: str
    break_minutes: int
    minimum_complement: int
    actual_start_utc: Optional[str]
    actual_end_utc: Optional[str]
    status: str
    confirmed_engagement_count: int
    compliance_status: str
    provisional_service_cost_cents: int
    final_service_cost_cents: Optional[int]
    created_at: str
    updated_at: str
    version: int


class MusicianEngagement(TypedDict):
    id: str
    service_id: str
    musician_id: str
    doubling_count: int
    status: str
    provisional_pay_cents: Optional[int]
    final_pay_cents: Optional[int]
    overtime_minutes: int
    created_at: str
    updated_at: str
    version: int


class Patron(TypedDict):
    id: str
    full_name: str
    email: str
    subscriber_since_year: Optional[int]
    lifetime_donation_cents: int
    donor_level: str
    consecutive_renewal_years: int
    renewal_priority_score: int
    credit_balance_cents: int
    lifetime_cash_in_cents: int
    created_at: str
    updated_at: str
    version: int


class SubscriptionPackage(TypedDict):
    id: str
    patron_id: str
    season_id: str
    seat_section_id: str
    prior_package_id: Optional[str]
    seat_count: int
    concert_ids: List[str]
    package_type: str
    status: str
    locked_unit_price_cents: int
    price_cents: int
    fulfilled_concert_count: int
    created_at: str
    updated_at: str
    version: int


class TicketOrder(TypedDict):
    id: str
    concert_id: str
    patron_id: str
    seat_section_id: str
    seat_count: int
    status: str
    quoted_unit_price_cents: int
    amount_due_cents: int
    amount_paid_cents: int
    credit_applied_cents: int
    demand_band_at_hold: str
    hold_expires_at_ops_run: int
    created_at: str
    updated_at: str
    version: int


class AdBooking(TypedDict):
    id: str
    season_id: str
    advertiser_name: str
    ad_size: str
    placement: str
    insertion_count: int
    status: str
    ad_subtotal_cents: Optional[int]
    volume_discount_bp: Optional[int]
    placement_fee_cents: Optional[int]
    invoice_total_cents: Optional[int]
    created_at: str
    updated_at: str
    version: int


class PriceQuote(TypedDict):
    unit_price_cents: int
    demand_band: str
    fill_bp: int
    donor_discount_bp: int
    seat_count: int
    amount_due_cents: int
