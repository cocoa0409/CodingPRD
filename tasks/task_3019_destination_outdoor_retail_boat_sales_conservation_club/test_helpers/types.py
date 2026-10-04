"""Domain types: entity TypedDicts, status enums, role enum.

Every persisted resource in this API is a full common-field resource, so each
TypedDict carries ``id``, ``created_at``, ``updated_at`` and ``version``.
"""
from enum import Enum
from typing import Optional, TypedDict


class UserRole(str, Enum):
    ANONYMOUS = "Anonymous"
    MEMBER = "Member"
    ATTRACTION_HOST = "AttractionHost"
    EVENTS_COORDINATOR = "EventsCoordinator"
    DEAL_DESK_CLERK = "DealDeskClerk"
    SERVICE_WRITER = "ServiceWriter"
    SERVICE_TECHNICIAN = "ServiceTechnician"
    RECEIVING_MANAGER = "ReceivingManager"
    PERMIT_CLERK = "PermitClerk"
    REMIT_ADMIN = "RemitAdmin"
    AGENCY_OPERATOR = "AgencyOperator"
    TITLE_CLERK = "TitleClerk"
    CREDIT_UNDERWRITER = "CreditUnderwriter"
    CREDIT_OFFICER = "CreditOfficer"
    CLUB_CARD_SPECIALIST = "ClubCardSpecialist"
    FINANCE_ADMIN = "FinanceAdmin"
    STORE_MANAGER = "StoreManager"
    PLATFORM_ADMIN = "PlatformAdmin"


class StorePosture(str, Enum):
    OPEN = "OPEN"
    RESTRICTED = "RESTRICTED"
    FROZEN = "FROZEN"


class AttractionStatus(str, Enum):
    PLANNED = "PLANNED"
    OPEN = "OPEN"
    RESTRICTED = "RESTRICTED"
    CLOSED = "CLOSED"


class AttractionSessionStatus(str, Enum):
    REQUESTED = "REQUESTED"
    CONFIRMED = "CONFIRMED"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    NO_SHOW = "NO_SHOW"
    CANCELLED = "CANCELLED"


class BoatUnitStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    DEAL_PENDING = "DEAL_PENDING"
    SOLD = "SOLD"


class DealStage(str, Enum):
    QUOTED = "QUOTED"
    CONTRACTED = "CONTRACTED"
    DELIVERED = "DELIVERED"
    SETTLED = "SETTLED"


class FundingStatus(str, Enum):
    UNFUNDED = "UNFUNDED"
    PENDING = "PENDING"
    FUNDED = "FUNDED"
    REFUNDED = "REFUNDED"


class TitleStatus(str, Enum):
    NOT_STARTED = "NOT_STARTED"
    FILED = "FILED"
    ISSUED = "ISSUED"
    REJECTED = "REJECTED"


class RiggingStatus(str, Enum):
    NOT_STARTED = "NOT_STARTED"
    SCHEDULED = "SCHEDULED"
    COMPLETE = "COMPLETE"


class PermitSaleStatus(str, Enum):
    ISSUED = "ISSUED"
    VOIDED = "VOIDED"
    REMITTED = "REMITTED"
    CORRECTED = "CORRECTED"


class RemitBatchStatus(str, Enum):
    OPEN = "OPEN"
    SEALED = "SEALED"
    TRANSMITTED = "TRANSMITTED"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"
    CORRECTED = "CORRECTED"


class ClubCardStatus(str, Enum):
    NONE = "NONE"
    PENDING = "PENDING"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class ClubTier(str, Enum):
    BASE = "BASE"
    SILVER = "SILVER"
    GOLD = "GOLD"
    PATRON = "PATRON"


class PointEventKind(str, Enum):
    AWARD = "AWARD"
    REDEEM = "REDEEM"
    REVERSAL = "REVERSAL"
    ADJUST = "ADJUST"


class ServiceOrderStatus(str, Enum):
    INTAKE = "INTAKE"
    SCHEDULED = "SCHEDULED"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    DELIVERED = "DELIVERED"
    CANCELLED = "CANCELLED"


class ServiceIntakeStatus(str, Enum):
    INTAKE_QUOTED = "INTAKE_QUOTED"
    PERMIT_VERIFIED = "PERMIT_VERIFIED"
    MATERIALS_ORDERED = "MATERIALS_ORDERED"
    CURING = "CURING"
    READY_FOR_PICKUP = "READY_FOR_PICKUP"
    RELEASED = "RELEASED"
    ABANDONED = "ABANDONED"


class FulfillmentStatus(str, Enum):
    READY_FOR_RELEASE = "READY_FOR_RELEASE"
    RELEASED = "RELEASED"
    CANCELLED = "CANCELLED"


class BayBookingStatus(str, Enum):
    RESERVED = "RESERVED"
    CHECKED_IN = "CHECKED_IN"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class WaiverStatus(str, Enum):
    SIGNED = "SIGNED"
    SUPERSEDED = "SUPERSEDED"
    EXPIRED = "EXPIRED"


class Store(TypedDict):
    id: str
    name: str
    state_code: str
    dealer_license_no: str
    dwell_capacity_minutes: int
    dwell_committed_minutes: int
    dwell_free_minutes: int
    attraction_posture: str
    remit_ledger_cents: int
    permit_remit_epoch: int
    load_bays_total: int
    created_at: str
    updated_at: str
    version: int


class Member(TypedDict):
    id: str
    store_id: str
    email: str
    full_name: str
    club_card_status: str
    points_balance: int
    points_lifetime_earned: int
    club_tier: str
    redeemable_points: int
    conservation_match_cents: int
    donation_opt_in: bool
    created_at: str
    updated_at: str
    version: int


class Attraction(TypedDict):
    id: str
    store_id: str
    attraction_type: str
    capacity_units: int
    dwell_cost_minutes: int
    requires_waiver: bool
    in_use_units: int
    status: str
    created_at: str
    updated_at: str
    version: int


class AttractionSession(TypedDict):
    id: str
    store_id: str
    attraction_id: str
    member_id: str
    waiver_id: Optional[str]
    session_kind: str
    party_size: int
    lane_no: Optional[int]
    slot_start_utc: str
    slot_end_utc: str
    dwell_charge_minutes: int
    overrun_minutes: int
    no_show_strikes: int
    status: str
    created_at: str
    updated_at: str
    version: int


class BoatUnit(TypedDict):
    id: str
    store_id: str
    stock_no: str
    model_name: str
    unit_price_cents: int
    motor_price_cents: int
    trailer_price_cents: int
    unit_condition: str
    prior_title_no: Optional[str]
    hull_id_no: str
    status: str
    created_at: str
    updated_at: str
    version: int


class TradeInAppraisal(TypedDict):
    id: str
    store_id: str
    member_id: str
    boat_unit_id: str
    offer_amount_cents: int
    accepted_credit_cents: int
    appraised_at_utc: str
    status: str
    created_at: str
    updated_at: str
    version: int


class ServiceOrder(TypedDict):
    id: str
    store_id: str
    boat_unit_id: str
    deal_id: Optional[str]
    boat_deal_id: Optional[str]
    order_kind: str
    promised_lead_days: int
    started_at_utc: Optional[str]
    completed_at_utc: Optional[str]
    actual_lead_days: int
    is_late: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class TitleFiling(TypedDict):
    id: str
    store_id: str
    boat_unit_id: str
    filing_kind: str
    state_code: str
    agency_reference: Optional[str]
    filed_at_utc: Optional[str]
    acknowledged_at_utc: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class BoatDeal(TypedDict):
    id: str
    store_id: str
    member_id: str
    boat_unit_id: str
    trade_in_appraisal_id: Optional[str]
    deal_stage: str
    funding_status: str
    title_status: str
    title_filing_id: Optional[str]
    rigging_status: str
    contract_price_cents: int
    total_fee_cents: int
    balance_due_cents: int
    deposit_cents: int
    funded_amount_cents: int
    points_awarded: int
    settlement_variance_cents: int
    created_at: str
    updated_at: str
    version: int


class PermitSale(TypedDict):
    id: str
    store_id: str
    member_id: str
    permit_type: str
    residency_class: str
    term_days: int
    land_access_units: int
    agent_user_id: str
    issuer_admin_user_id: str
    remitter_admin_user_id: Optional[str]
    fee_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class PermitRemitBatch(TypedDict):
    id: str
    store_id: str
    window_start_utc: str
    window_end_utc: str
    gross_fee_cents: int
    interpretative_gross_cents: int
    remit_variance_cents: int
    agency_ack_no: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class ClubCardApplication(TypedDict):
    id: str
    store_id: str
    member_id: str
    card_product: str
    donation_match_bps: int
    underwriter_user_id: str
    decision_user_id: Optional[str]
    decision_reason: Optional[str]
    credit_limit_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class PointEvent(TypedDict):
    id: str
    member_id: str
    store_id: str
    boat_deal_id: Optional[str]
    event_kind: str
    points_delta: int
    donation_match_cents: int
    created_seq: int
    created_at: str
    updated_at: str
    version: int


class EventOffering(TypedDict):
    id: str
    store_id: str
    attraction_id: Optional[str]
    offering_kind: str
    title: str
    starts_at_utc: str
    ends_at_utc: str
    registration_cap: int
    confirmed_count: int
    dwell_charge_minutes: int
    status: str
    created_at: str
    updated_at: str
    version: int


class EventRegistration(TypedDict):
    id: str
    store_id: str
    event_offering_id: str
    member_id: str
    seats: int
    attendance_marked: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class LoadingBayBooking(TypedDict):
    id: str
    store_id: str
    bay_no: int
    member_id: str
    service_order_id: str
    booked_start_utc: str
    booked_end_utc: str
    status: str
    created_at: str
    updated_at: str
    version: int


class OrderFulfillment(TypedDict):
    id: str
    store_id: str
    member_id: str
    order_kind: str
    pre_service_order_id: str
    booking_id: str
    waiver_id: Optional[str]
    rm_cross_check_code: Optional[str]
    fulfilled_at_utc: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class ServiceIntake(TypedDict):
    id: str
    store_id: str
    member_id: str
    service_order_id: str
    intake_kind: str
    species_code: Optional[str]
    permit_sale_id: Optional[str]
    specimen_quantity: int
    deposit_cents: int
    quoted_lead_days: int
    project_charge_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class LiabilityWaiver(TypedDict):
    id: str
    member_id: str
    store_id: str
    activity_scope: str
    signed_at_utc: str
    waiver_term_days: int
    expires_on: str
    status: str
    created_at: str
    updated_at: str
    version: int


class PaginatedMeta(TypedDict):
    total_count: int
    has_more: bool
    limit: int
    offset: int