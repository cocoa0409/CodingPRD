"""Domain types for the Fair Grandstand Entertainment Booking API.

Status enums, enumerated payload vocabularies and entity TypedDicts, all named
exactly as the PRD names them. The three append-only record types the PRD
describes in §2.5 -- the negotiation round, the ticket sale batch and the
contingency action -- carry only ``id`` and ``created_at``, so their TypedDicts
deliberately omit ``updated_at`` and ``version``.
"""

from enum import Enum
from typing import Optional, TypedDict


# ---------------------------------------------------------------------------
# Roles
# ---------------------------------------------------------------------------
class UserRole(str, Enum):
    TALENT_BUYER = "TalentBuyer"
    TALENT_AGENT = "TalentAgent"
    FAIR_OPERATIONS_DIRECTOR = "FairOperationsDirector"
    PRODUCTION_MANAGER = "ProductionManager"
    BOX_OFFICE_MANAGER = "BoxOfficeManager"
    SPONSORSHIP_DIRECTOR = "SponsorshipDirector"
    SETTLEMENT_CONTROLLER = "SettlementController"


ALL_ROLES = [role.value for role in UserRole]


# ---------------------------------------------------------------------------
# Status enums
# ---------------------------------------------------------------------------
class OfferStatus(str, Enum):
    DRAFT = "DRAFT"
    SENT = "SENT"
    COUNTERED = "COUNTERED"
    ACCEPTED = "ACCEPTED"
    DECLINED = "DECLINED"
    WITHDRAWN = "WITHDRAWN"
    EXPIRED = "EXPIRED"


class BookingStatus(str, Enum):
    DATE_HELD = "DATE_HELD"
    ANNOUNCED = "ANNOUNCED"
    PERFORMED = "PERFORMED"
    CANCELLED = "CANCELLED"
    POSTPONED = "POSTPONED"


class TicketingStatus(str, Enum):
    SCALED_PENDING = "SCALED_PENDING"
    SCALED = "SCALED"
    ON_SALE = "ON_SALE"
    SALES_CLOSED = "SALES_CLOSED"
    REFUNDING = "REFUNDING"
    REFUNDED = "REFUNDED"


class BookingPosture(str, Enum):
    OPEN = "OPEN"
    SATURATED = "SATURATED"


class ProductionAdvanceStatus(str, Enum):
    ADVANCE_PENDING = "ADVANCE_PENDING"
    ADVANCE_IN_REVIEW = "ADVANCE_IN_REVIEW"
    ADVANCE_COMPLETE = "ADVANCE_COMPLETE"
    ADVANCE_BLOCKED = "ADVANCE_BLOCKED"
    ADVANCE_CANCELLED = "ADVANCE_CANCELLED"


class BlockedReasonCode(str, Enum):
    DENIED_CRITICAL_ITEM = "DENIED_CRITICAL_ITEM"
    MISSING_STAGE_PLOT = "MISSING_STAGE_PLOT"


class RiderItemStatus(str, Enum):
    REQUESTED = "REQUESTED"
    APPROVED = "APPROVED"
    DENIED = "DENIED"
    SUBSTITUTED = "SUBSTITUTED"
    VOIDED = "VOIDED"


class RiderDecision(str, Enum):
    APPROVED = "APPROVED"
    DENIED = "DENIED"
    SUBSTITUTED = "SUBSTITUTED"


class RiderCategory(str, Enum):
    STAGING = "STAGING"
    SOUND = "SOUND"
    LIGHTING = "LIGHTING"
    HOSPITALITY = "HOSPITALITY"


class TicketScaleStatus(str, Enum):
    ON_SALE_ELIGIBLE = "ON_SALE_ELIGIBLE"
    REFUND_DUE = "REFUND_DUE"
    CLOSED = "CLOSED"


class SponsorshipActivationStatus(str, Enum):
    PROPOSED = "PROPOSED"
    CONFIRMED = "CONFIRMED"
    FULFILLED = "FULFILLED"
    CANCELLED = "CANCELLED"


class SettlementStatus(str, Enum):
    DRAFT = "DRAFT"
    PENDING_APPROVAL = "PENDING_APPROVAL"
    APPROVED = "APPROVED"


# ---------------------------------------------------------------------------
# Enumerated payload vocabularies
# ---------------------------------------------------------------------------
class Genre(str, Enum):
    COUNTRY = "COUNTRY"
    ROCK = "ROCK"
    HIP_HOP = "HIP_HOP"
    LATIN = "LATIN"
    CHRISTIAN = "CHRISTIAN"
    COMEDY = "COMEDY"
    TRIBUTE = "TRIBUTE"


class AudienceSegment(str, Enum):
    FAMILY = "FAMILY"
    YOUNG_ADULT = "YOUNG_ADULT"
    ADULT_45_PLUS = "ADULT_45_PLUS"
    TEEN = "TEEN"


class DealType(str, Enum):
    VERSUS = "VERSUS"
    GUARANTEE_PLUS_BACKEND = "GUARANTEE_PLUS_BACKEND"


class StrategyBasis(str, Enum):
    ATTENDANCE_WEIGHTED = "ATTENDANCE_WEIGHTED"
    REVENUE_WEIGHTED = "REVENUE_WEIGHTED"


class SeatingType(str, Enum):
    RESERVED = "RESERVED"
    GENERAL_ADMISSION = "GENERAL_ADMISSION"


class BatchKind(str, Enum):
    SALE = "SALE"
    REFUND = "REFUND"


class SalesChannel(str, Enum):
    ONLINE = "ONLINE"
    BOX_OFFICE = "BOX_OFFICE"
    PHONE = "PHONE"
    COMP = "COMP"


class SponsorCategory(str, Enum):
    BEVERAGE = "BEVERAGE"
    AUTOMOTIVE = "AUTOMOTIVE"
    TELECOM = "TELECOM"
    AGRIBUSINESS = "AGRIBUSINESS"
    FINANCIAL = "FINANCIAL"
    QSR = "QSR"


class ExclusivityTier(str, Enum):
    PRESENTING = "PRESENTING"
    SUPPORTING = "SUPPORTING"


class SponsorshipRights(str, Enum):
    STAGE_NAMING = "STAGE_NAMING"
    PRESENTING = "PRESENTING"
    SAMPLING = "SAMPLING"
    SIGNAGE = "SIGNAGE"


class ContingencyActionType(str, Enum):
    CANCEL = "CANCEL"
    POSTPONE = "POSTPONE"


class ContingencyReasonCode(str, Enum):
    SEVERE_WEATHER = "SEVERE_WEATHER"
    LIGHTNING_HOLD = "LIGHTNING_HOLD"
    ARTIST_ILLNESS = "ARTIST_ILLNESS"
    PRODUCTION_FAILURE = "PRODUCTION_FAILURE"


class RefundPolicy(str, Enum):
    FULL_REFUND = "FULL_REFUND"
    RAIN_CHECK = "RAIN_CHECK"
    NO_REFUND_AFTER_DOORS = "NO_REFUND_AFTER_DOORS"


class SettlementBasis(str, Enum):
    PROVISIONAL = "PROVISIONAL"
    FINAL = "FINAL"


class MerchSeller(str, Enum):
    ARTIST = "ARTIST"
    VENUE = "VENUE"


class RejectionReasonCode(str, Enum):
    GROSS_MISMATCH = "GROSS_MISMATCH"
    EXPENSE_UNSUPPORTED = "EXPENSE_UNSUPPORTED"
    MERCH_MISSING = "MERCH_MISSING"


class ProposedBy(str, Enum):
    BUYER = "BUYER"
    AGENT = "AGENT"


# ---------------------------------------------------------------------------
# Entities that carry id + created_at + updated_at + version
# ---------------------------------------------------------------------------
class FairEdition(TypedDict):
    id: str
    year: int
    name: str
    run_start_date: str
    run_end_date: str
    gate_admission_price_cents: int
    talent_budget_cap_cents: int
    refund_reserve_cents: int
    max_shows_per_day: int
    curfew_utc_time: str
    strategy_basis: str
    committed_guarantee_total_cents: int
    refund_liability_committed_cents: int
    open_stage_count: int
    created_at: str
    updated_at: str
    version: int


class Stage(TypedDict):
    id: str
    fair_edition_id: str
    name: str
    reserved_seat_capacity: int
    ga_capacity: int
    changeover_buffer_minutes: int
    slot_soft_cap: int
    held_show_count: int
    booking_posture: str
    created_at: str
    updated_at: str
    version: int


class TalentAgent(TypedDict):
    id: str
    user_id: str
    agency_name: str
    contact_email: str
    roster_artist_count: int
    created_at: str
    updated_at: str
    version: int


class Artist(TypedDict):
    id: str
    agent_id: str
    name: str
    genre: str
    audience_segment: str
    base_draw_score: float
    prior_year_paid_attendance: int
    prior_year_net_revenue_cents: int
    draw_score_next_year: Optional[float]
    created_at: str
    updated_at: str
    version: int


class Offer(TypedDict):
    id: str
    fair_edition_id: str
    artist_id: str
    target_stage_id: str
    deal_type: str
    offered_guarantee_cents: int
    backend_split_pct: float
    backend_breakeven_cents: int
    radius_miles: int
    radius_days_before: int
    radius_days_after: int
    radius_waiver_granted: bool
    target_show_date: str
    load_in_start_utc: str
    load_out_end_utc: str
    response_window_hours: int
    status: str
    round_count: int
    countered_guarantee_cents: Optional[int]
    agreed_guarantee_cents: Optional[int]
    sent_at_utc: Optional[str]
    expires_at_utc: Optional[str]
    created_by_user_id: str
    created_at: str
    updated_at: str
    version: int


class ShowBooking(TypedDict):
    id: str
    offer_id: str
    stage_id: str
    postponed_from_booking_id: Optional[str]
    show_date: str
    load_in_start_utc: str
    load_out_end_utc: str
    doors_time_utc: Optional[str]
    booking_status: str
    ticketing_status: str
    agreed_guarantee_cents: int
    agreed_deal_type: str
    agreed_backend_split_pct: float
    agreed_breakeven_cents: int
    gross_potential_cents: int
    sponsorship_revenue_cents: int
    recoupable_production_cost_cents: int
    paid_attendance: int
    refund_liability_cents: int
    announced_at_utc: Optional[str]
    created_at: str
    updated_at: str
    version: int


class TicketScale(TypedDict):
    id: str
    booking_id: str
    seating_type: str
    tier_name: str
    face_price_cents: int
    allotment_seats: int
    bundled_with_gate_admission: bool
    facility_fee_cents: int
    sold_seats: int
    available_seats: int
    scale_gross_potential_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class ProductionAdvance(TypedDict):
    id: str
    booking_id: str
    status: str
    approved_rider_cost_cents: int
    recoupable_rider_cost_cents: int
    denied_item_count: int
    blocked_reason_code: Optional[str]
    created_at: str
    updated_at: str
    version: int


class RiderItem(TypedDict):
    id: str
    production_advance_id: str
    category: str
    description: str
    requested_cost_cents: int
    is_critical: bool
    artist_recoupable: bool
    status: str
    approved_cost_cents: int
    created_at: str
    updated_at: str
    version: int


class Sponsor(TypedDict):
    id: str
    name: str
    category: str
    exclusivity_tier: str
    created_at: str
    updated_at: str
    version: int


class SponsorshipActivation(TypedDict):
    id: str
    sponsor_id: str
    booking_id: str
    rights: str
    base_fee_cents: int
    exclusivity_category: str
    status: str
    net_fee_cents: int
    make_good_credit_cents: int
    created_at: str
    updated_at: str
    version: int


class Settlement(TypedDict):
    id: str
    booking_id: str
    basis: str
    merch_gross_cents: int
    merch_seller: str
    adjusted_gross_cents: int
    sponsorship_offset_cents: int
    base_promoter_expense_cents: int
    provisional_net_pool_cents: int
    artist_payout_cents: int
    production_surcharge_cents: int
    promoter_expense_cents: int
    net_pool_cents: int
    merch_hall_fee_cents: int
    merch_artist_share_cents: int
    total_artist_settlement_cents: int
    status: str
    revision_count: int
    submitted_by_user_id: Optional[str]
    approved_by_user_id: Optional[str]
    rejection_reason_code: Optional[str]
    created_at: str
    updated_at: str
    version: int


# ---------------------------------------------------------------------------
# Append-only history records: id + created_at only, no updated_at, no version
# ---------------------------------------------------------------------------
class OfferRound(TypedDict):
    id: str
    offer_id: str
    round_number: int
    proposed_by: str
    proposed_guarantee_cents: int
    proposed_backend_split_pct: float
    proposed_breakeven_cents: int
    note: Optional[str]
    recorded_at_utc: str
    created_at: str


class TicketSaleBatch(TypedDict):
    id: str
    ticket_scale_id: str
    batch_kind: str
    quantity: int
    channel: str
    recorded_at_utc: str
    counts_toward_paid_attendance: bool
    gross_cents: int
    created_at: str


class ContingencyAction(TypedDict):
    id: str
    booking_id: str
    action_type: str
    reason_code: str
    refund_policy: str
    replacement_show_date: Optional[str]
    decided_at_utc: str
    pre_doors: bool
    refund_liability_cents: int
    created_at: str


APPEND_ONLY_ENTITIES = ("OfferRound", "TicketSaleBatch", "ContingencyAction")
