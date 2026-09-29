"""Domain types for the Destination Sales & Convention Attraction API.

Entity TypedDicts, status enums and the role enum, all named exactly as the
PRD names them.  Resource kinds the PRD declares append-only (support letters,
incentive decisions, economic impact estimates, nightly pickup records and
lodging tax receipts) carry only ``id`` and ``created_at`` -- never
``updated_at`` and never ``version``.
"""
from enum import Enum
from typing import Any, Dict, List, Optional, TypedDict


class UserRole(str, Enum):
    BUREAU_ADMIN = "BureauAdmin"
    SALES_MANAGER = "SalesManager"
    HOTEL_PARTNER = "HotelPartner"
    CENTER_SCHEDULER = "CenterScheduler"
    MEETING_PLANNER = "MeetingPlanner"
    INCENTIVE_APPROVER = "IncentiveApprover"
    SERVICES_MANAGER = "ServicesManager"
    BOARD_ANALYST = "BoardAnalyst"


ALL_ROLES: List[str] = [r.value for r in UserRole]


class PlannerTier(str, Enum):
    TIER_A = "TIER_A"
    TIER_B = "TIER_B"
    TIER_C = "TIER_C"


class EngagementStatus(str, Enum):
    PROSPECT = "PROSPECT"
    ENGAGED = "ENGAGED"


class ParticipationStatus(str, Enum):
    PARTICIPATING = "PARTICIPATING"
    SUSPENDED = "SUSPENDED"


class HallStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    UNDER_RENOVATION = "UNDER_RENOVATION"


class SalesStage(str, Enum):
    LEAD = "LEAD"
    QUALIFIED = "QUALIFIED"
    BIDDING = "BIDDING"
    DEFINITE = "DEFINITE"
    SERVICED = "SERVICED"
    LOST = "LOST"


class HoldPosture(str, Enum):
    NONE = "NONE"
    TENTATIVE = "TENTATIVE"
    CHALLENGED = "CHALLENGED"
    CONFIRMED = "CONFIRMED"
    RELEASED = "RELEASED"


class LostReason(str, Enum):
    RATE_TOO_HIGH = "RATE_TOO_HIGH"
    DATES_UNAVAILABLE = "DATES_UNAVAILABLE"
    SPACE_UNAVAILABLE = "SPACE_UNAVAILABLE"
    LOST_TO_COMPETITOR = "LOST_TO_COMPETITOR"
    PLANNER_DECLINED_BID = "PLANNER_DECLINED_BID"
    INSUFFICIENT_INCENTIVE = "INSUFFICIENT_INCENTIVE"
    REVISION_LIMIT_REACHED = "REVISION_LIMIT_REACHED"


class SpaceHoldStatus(str, Enum):
    HELD = "HELD"
    CHALLENGED = "CHALLENGED"
    CONFIRMED = "CONFIRMED"
    RELEASED = "RELEASED"
    EXPIRED = "EXPIRED"


class HoldRank(str, Enum):
    FIRST = "FIRST"
    SECOND = "SECOND"


class ReleaseReason(str, Enum):
    SCHEDULER_RELEASE = "SCHEDULER_RELEASE"
    CHALLENGE_LAPSED = "CHALLENGE_LAPSED"
    OPPORTUNITY_LOST = "OPPORTUNITY_LOST"
    SUPERSEDED_BY_CONFIRMED = "SUPERSEDED_BY_CONFIRMED"
    HOLD_EXPIRED = "HOLD_EXPIRED"
    EVENT_SERVICED = "EVENT_SERVICED"


class CommitmentStatus(str, Enum):
    INVITED = "INVITED"
    OFFERED = "OFFERED"
    COMMITTED = "COMMITTED"
    WITHDRAWN = "WITHDRAWN"
    RELEASED = "RELEASED"


class WithdrawReason(str, Enum):
    PROPERTY_SOLD_OUT = "PROPERTY_SOLD_OUT"
    RATE_DISPUTE = "RATE_DISPUTE"
    INVITE_DECLINED = "INVITE_DECLINED"
    OPPORTUNITY_LOST = "OPPORTUNITY_LOST"
    EVENT_SERVICED = "EVENT_SERVICED"


class BidPackageStatus(str, Enum):
    DRAFT = "DRAFT"
    INCENTIVE_PENDING = "INCENTIVE_PENDING"
    APPROVED = "APPROVED"
    SUBMITTED = "SUBMITTED"
    ACCEPTED = "ACCEPTED"
    DECLINED = "DECLINED"


class PlannerResponse(str, Enum):
    ACCEPTED = "ACCEPTED"
    DECLINED = "DECLINED"
    REVISION_REQUESTED = "REVISION_REQUESTED"


class DeclineReason(str, Enum):
    RATE_TOO_HIGH = "RATE_TOO_HIGH"
    INSUFFICIENT_INCENTIVE = "INSUFFICIENT_INCENTIVE"
    LOST_TO_COMPETITOR = "LOST_TO_COMPETITOR"
    REVISION_LIMIT_REACHED = "REVISION_LIMIT_REACHED"


class LetterType(str, Enum):
    MAYOR = "MAYOR"
    CHAMBER = "CHAMBER"
    UNIVERSITY = "UNIVERSITY"
    INDUSTRY_PARTNER = "INDUSTRY_PARTNER"
    CONVENTION_CENTER = "CONVENTION_CENTER"


class FundPosture(str, Enum):
    OPEN = "OPEN"
    CONSTRAINED = "CONSTRAINED"
    EXHAUSTED = "EXHAUSTED"


class DecisionVerdict(str, Enum):
    APPROVED = "APPROVED"
    REDUCED = "REDUCED"
    REJECTED = "REJECTED"


class EstimateVariant(str, Enum):
    PROVISIONAL = "PROVISIONAL"
    FINAL = "FINAL"


class ServicingCategory(str, Enum):
    HOUSING = "HOUSING"
    TRANSPORTATION = "TRANSPORTATION"
    VOLUNTEER = "VOLUNTEER"


class ServicingStatus(str, Enum):
    REQUESTED = "REQUESTED"
    SCHEDULED = "SCHEDULED"
    DELIVERED = "DELIVERED"
    CANCELLED = "CANCELLED"


class BoardReportStatus(str, Enum):
    DRAFT = "DRAFT"
    PUBLISHED = "PUBLISHED"


# --- Entities carrying id + created_at + updated_at + version ---------------

class MeetingPlanner(TypedDict, total=False):
    id: str
    org_name: str
    contact_email: str
    legacy_definite_count: int
    legacy_definite_room_nights: int
    definite_count: int
    lost_count: int
    lifetime_definite_room_nights: int
    relationship_score_lifetime: int
    relationship_score_rolling_24m: int
    tier: str
    engagement_status: str
    last_touch_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Hotel(TypedDict, total=False):
    id: str
    name: str
    committable_rooms: int
    walk_distance_blocks: int
    participation_status: str
    committed_peak_rooms: int
    committed_room_nights: int
    pickup_room_nights: int
    created_at: str
    updated_at: str
    version: int


class CenterHall(TypedDict, total=False):
    id: str
    name: str
    exhibit_sqft: int
    capacity_persons: int
    turnaround_hours: int
    hall_status: str
    confirmed_hold_count: int
    created_at: str
    updated_at: str
    version: int


class Opportunity(TypedDict, total=False):
    id: str
    planner_id: str
    supersedes_opportunity_id: Optional[str]
    event_name: str
    arrival_date: str
    departure_date: str
    event_nights: int
    peak_rooms_requested: int
    total_room_nights_requested: int
    attendance_estimate: int
    exhibit_sqft_requested: int
    rate_ceiling_amount: float
    sales_stage: str
    hold_posture: str
    committed_peak_rooms: int
    block_coverage_pct: float
    citywide_cutoff_days_before_arrival: int
    cutoff_alignment_spread_days: int
    definite_room_nights: int
    definite_at: Optional[str]
    lost_reason: Optional[str]
    attrition_settlement_amount: float
    created_at: str
    updated_at: str
    version: int


class SpaceHold(TypedDict, total=False):
    id: str
    opportunity_id: str
    center_hall_id: str
    challenged_by_space_hold_id: Optional[str]
    move_in_start: str
    move_out_end: str
    hold_rank: str
    status: str
    expires_at: str
    challenge_deadline: Optional[str]
    release_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class RoomBlockCommitment(TypedDict, total=False):
    id: str
    opportunity_id: str
    hotel_id: str
    rooms_peak_invited: int
    rooms_peak_offered: Optional[int]
    rooms_peak_committed: int
    rate_offered_amount: Optional[float]
    cutoff_days_before_arrival: Optional[int]
    cutoff_date: Optional[str]
    offer_round: int
    status: str
    committed_room_nights: int
    picked_up_room_nights: int
    attrition_shortfall_nights: int
    attrition_damages_amount: float
    withdraw_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class BidPackage(TypedDict, total=False):
    id: str
    opportunity_id: str
    round_number: int
    status: str
    prepared_by_user_id: str
    incentive_requested_by_user_id: Optional[str]
    incentive_request_amount: Optional[float]
    incentive_cap_amount: Optional[float]
    service_commitment_codes: List[str]
    support_letter_type_count: int
    approved_incentive_amount: Optional[float]
    admin_fee_amount: Optional[float]
    total_fund_charge_amount: Optional[float]
    tax_payback_ratio: Optional[float]
    submitted_at: Optional[str]
    response_due_at: Optional[str]
    planner_response: Optional[str]
    decline_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class IncentiveFund(TypedDict, total=False):
    id: str
    fiscal_year: int
    budget_amount: float
    lodging_tax_receipts_total: float
    committed_amount: float
    disbursed_amount: float
    uncommitted_amount: float
    posture: str
    created_at: str
    updated_at: str
    version: int


class ServicingOrder(TypedDict, total=False):
    id: str
    opportunity_id: str
    category: str
    requested_units: int
    assigned_units: int
    delivered_units: int
    window_start: str
    window_end: str
    status: str
    created_at: str
    updated_at: str
    version: int


class BoardReport(TypedDict, total=False):
    id: str
    period_start: str
    period_end: str
    definite_opportunity_count: int
    definite_room_nights: int
    lost_opportunity_count: int
    lost_room_nights_by_reason: Dict[str, int]
    incentive_spend_committed_amount: float
    lodging_tax_recognized_amount: float
    cost_per_definite_room_night: Optional[float]
    attrition_recovered_amount: float
    status: str
    published_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


# --- Append-only event records: id + created_at only ------------------------

class SupportLetter(TypedDict, total=False):
    id: str
    bid_package_id: str
    organization_name: str
    letter_type: str
    received_at: str
    created_at: str


class IncentiveDecision(TypedDict, total=False):
    id: str
    bid_package_id: str
    fund_id: str
    decision: str
    requested_amount: float
    approved_amount: float
    admin_fee_amount: float
    total_charge_amount: float
    tax_payback_ratio: Optional[float]
    decided_by_user_id: str
    rationale: str
    created_at: str


class EconomicImpactEstimate(TypedDict, total=False):
    id: str
    opportunity_id: str
    variant: str
    room_nights_basis: int
    lodging_spend_amount: float
    delegate_spend_amount: float
    exhibitor_spend_amount: float
    direct_spend_amount: float
    total_impact_amount: float
    lodging_tax_yield_amount: float
    computed_at: str
    created_at: str


class PickupRecord(TypedDict, total=False):
    id: str
    room_block_commitment_id: str
    night_date: str
    rooms_picked_up: int
    rate_charged_amount: float
    room_night_revenue_amount: float
    created_at: str


class LodgingTaxReceipt(TypedDict, total=False):
    id: str
    fund_id: str
    amount: float
    received_at: str
    created_at: str


APPEND_ONLY_KINDS = (
    "SupportLetter",
    "IncentiveDecision",
    "EconomicImpactEstimate",
    "PickupRecord",
    "LodgingTaxReceipt",
)
