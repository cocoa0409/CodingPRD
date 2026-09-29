"""Domain types: status enums, role enum and entity shapes declared by the PRD."""

from enum import Enum
from typing import List, Optional, TypedDict


class UserRole(str, Enum):
    LEAGUE_ADMIN = "LeagueAdmin"
    GENERAL_MANAGER = "GeneralManager"
    PLAYER_AGENT = "PlayerAgent"
    SCOUT = "Scout"
    COACHING_STAFF = "CoachingStaff"
    PERFORMANCE_SUPPORT = "PerformanceSupport"
    SPONSORSHIP_MANAGER = "SponsorshipManager"
    FINANCE_OFFICER = "FinanceOfficer"
    OPS_MANAGER = "OpsManager"
    GUARDIAN_REPRESENTATIVE = "GuardianRepresentative"


class PlayerStatus(str, Enum):
    PROSPECT = "PROSPECT"
    TRYOUT_INVITED = "TRYOUT_INVITED"
    TRYOUT_COMPLETED = "TRYOUT_COMPLETED"
    SIGNED = "SIGNED"
    FREE_AGENT = "FREE_AGENT"


class GuardianConsentStatus(str, Enum):
    NOT_REQUIRED = "NOT_REQUIRED"
    REQUIRED = "REQUIRED"
    GRANTED = "GRANTED"


class EducationEnrollmentStatus(str, Enum):
    NOT_ENROLLED = "NOT_ENROLLED"
    ENROLLED_PART_TIME = "ENROLLED_PART_TIME"
    ENROLLED_FULL_TIME = "ENROLLED_FULL_TIME"


class OfferStatus(str, Enum):
    SENT = "SENT"
    COUNTERED = "COUNTERED"
    ACCEPTED = "ACCEPTED"
    DECLINED = "DECLINED"
    EXPIRED = "EXPIRED"
    SUPERSEDED = "SUPERSEDED"


class ContractStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    TERMINATED = "TERMINATED"


class ObligationStatus(str, Enum):
    COMPLIANT = "COMPLIANT"
    WARNED = "WARNED"
    BREACH = "BREACH"


class BlockType(str, Enum):
    SCRIM = "SCRIM"
    REVIEW = "REVIEW"
    INDIVIDUAL = "INDIVIDUAL"
    TRYOUT = "TRYOUT"


class BlockStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    HELD = "HELD"
    CANCELLED = "CANCELLED"


class CancelReason(str, Enum):
    COACH_CANCELLED = "COACH_CANCELLED"
    WELLNESS_HOLD = "WELLNESS_HOLD"
    CONTRACT_SUSPENDED = "CONTRACT_SUSPENDED"


class ExclusivityCategory(str, Enum):
    ENERGY_DRINK = "ENERGY_DRINK"
    PERIPHERALS = "PERIPHERALS"
    APPAREL = "APPAREL"
    BETTING = "BETTING"
    CRYPTO = "CRYPTO"


class DealStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    FULFILLED = "FULFILLED"


class DeliverableType(str, Enum):
    SOCIAL_POST = "SOCIAL_POST"
    STREAM_SEGMENT = "STREAM_SEGMENT"
    APPEARANCE = "APPEARANCE"
    VOD_FEATURE = "VOD_FEATURE"


class AssignmentStatus(str, Enum):
    ASSIGNED = "ASSIGNED"
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    VOIDED = "VOIDED"


class ReviewDecision(str, Enum):
    APPROVE = "APPROVE"
    REJECT = "REJECT"


class DistributionStatus(str, Enum):
    DRAFT = "DRAFT"
    CALCULATED = "CALCULATED"
    APPROVED = "APPROVED"
    VOIDED = "VOIDED"


class AllocationStatus(str, Enum):
    CALCULATED = "CALCULATED"
    APPROVED = "APPROVED"
    VOIDED = "VOIDED"


class MoveType(str, Enum):
    SIGN = "SIGN"
    RELEASE = "RELEASE"
    TRANSFER_OUT = "TRANSFER_OUT"


class MoveStatus(str, Enum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    EXECUTED = "EXECUTED"
    REVERSED = "REVERSED"


class MoveDecision(str, Enum):
    APPROVE = "APPROVE"
    REJECT = "REJECT"


# ─── Entity shapes: every resource kind carries id, created_at, updated_at, version ───


class League(TypedDict):
    id: str
    name: str
    season_start_at: str
    season_end_at: str
    roster_lock_at: str
    transfer_window_open_at: str
    transfer_window_close_at: str
    minimum_salary_cents: int
    min_roster_size: int
    max_roster_size: int
    offer_response_window_hours: int
    max_negotiation_rounds: int
    player_association_levy_bp: int
    association_min_prize_split_bp: int
    association_max_streaming_hours_per_week: int
    minor_max_weekly_minutes: int
    adult_max_weekly_minutes: int
    education_reserved_minutes: int
    minor_age_threshold_years: int
    free_agency_cooldown_days: int
    tryout_required_before_offer: bool
    roster_lock_active: bool
    created_at: str
    updated_at: str
    version: int


class Organization(TypedDict):
    id: str
    league_id: str
    name: str
    tax_jurisdiction_code: str
    annual_salary_budget_cents: int
    org_prize_share_bp: int
    committed_salary_cents: int
    uncommitted_salary_cents: int
    active_roster_count: int
    prize_payable_cents: int
    wellness_flag_count: int
    created_at: str
    updated_at: str
    version: int


class Player(TypedDict):
    id: str
    full_name: str
    birth_date: str
    region_code: str
    association_member: bool
    player_status: str
    current_organization_id: Optional[str]
    age_years: int
    is_minor: bool
    guardian_consent_status: str
    guardian_name: Optional[str]
    guardian_email: Optional[str]
    guardian_weekly_cap_minutes: Optional[int]
    education_enrollment_status: str
    free_agency_window_ends_at: Optional[str]
    last_release_organization_id: Optional[str]
    scouted_by_user_id: str
    created_at: str
    updated_at: str
    version: int


class ContractOffer(TypedDict):
    id: str
    organization_id: str
    player_id: str
    supersedes_offer_id: Optional[str]
    offer_status: str
    round_number: int
    base_salary_cents: int
    term_months: int
    prize_split_player_pct_bp: int
    streaming_hours_per_week: int
    signing_bonus_cents: int
    buyout_multiplier_bp: int
    tax_residency_code: str
    counter_base_salary_cents: Optional[int]
    counter_prize_split_player_pct_bp: Optional[int]
    counter_streaming_hours_per_week: Optional[int]
    counter_note: Optional[str]
    decline_note: Optional[str]
    sent_at: str
    expires_at: str
    created_at: str
    updated_at: str
    version: int


class PlayerContract(TypedDict):
    id: str
    offer_id: str
    player_id: str
    organization_id: str
    contract_status: str
    obligation_status: str
    base_salary_cents: int
    term_months: int
    signing_bonus_cents: int
    prize_split_player_pct_bp: int
    streaming_hours_per_week: int
    buyout_multiplier_bp: int
    tax_residency_code: str
    effective_at: str
    ends_at: str
    provisional_cap_charge_cents: int
    final_cap_charge_cents: int
    season_practice_minutes: int
    last_self_reported_load: int
    reported_streaming_minutes_7d: int
    burnout_score: int
    wellness_hold_until: Optional[str]
    suspension_reason: Optional[str]
    signed_by_user_id: str
    created_at: str
    updated_at: str
    version: int


class TeamHouse(TypedDict):
    id: str
    organization_id: str
    name: str
    timezone: str
    turnaround_buffer_minutes: int
    concurrent_seat_capacity: int
    created_at: str
    updated_at: str
    version: int


class PracticeBlock(TypedDict):
    id: str
    organization_id: str
    team_house_id: str
    block_type: str
    starts_at: str
    ends_at: str
    duration_minutes: int
    participant_player_ids: List[str]
    coach_user_id: str
    block_status: str
    cancel_reason: Optional[str]
    coach_note: Optional[str]
    created_at: str
    updated_at: str
    version: int


class SponsorshipDeal(TypedDict):
    id: str
    organization_id: str
    sponsor_name: str
    exclusivity_category: str
    total_fee_cents: int
    deliverable_count_required: int
    starts_at: str
    ends_at: str
    deal_status: str
    assigned_count: int
    approved_count: int
    minor_permitted: bool
    created_at: str
    updated_at: str
    version: int


class DeliverableAssignment(TypedDict):
    id: str
    sponsorship_deal_id: str
    contract_id: str
    deliverable_type: str
    due_at: str
    fee_share_cents: int
    assignment_status: str
    rejection_count: int
    submission_note: Optional[str]
    review_note: Optional[str]
    created_at: str
    updated_at: str
    version: int


class PrizeDistribution(TypedDict):
    id: str
    organization_id: str
    league_id: str
    tournament_name: str
    placement: int
    gross_prize_cents: int
    tournament_end_at: str
    distribution_status: str
    association_levy_cents: int
    org_share_cents: int
    allocated_cents: int
    unallocated_cents: int
    withholding_total_cents: int
    escrow_total_cents: int
    calculated_by_user_id: Optional[str]
    approved_by_user_id: Optional[str]
    void_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class PrizeAllocation(TypedDict):
    id: str
    prize_distribution_id: str
    contract_id: str
    weight_bp: int
    gross_share_cents: int
    withholding_rate_bp: int
    withholding_cents: int
    escrow_holdback_cents: int
    net_cents: int
    allocation_status: str
    created_at: str
    updated_at: str
    version: int


class RosterMove(TypedDict):
    id: str
    organization_id: str
    player_id: str
    contract_id: Optional[str]
    transfer_to_organization_id: Optional[str]
    move_type: str
    move_status: str
    gross_transfer_fee_cents: int
    buyout_credit_cents: int
    commission_tier_bp: int
    agent_commission_cents: int
    net_to_org_cents: int
    released_cap_cents: int
    effective_at: str
    requested_by_user_id: str
    approved_by_user_id: Optional[str]
    decision_note: Optional[str]
    reversal_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int
