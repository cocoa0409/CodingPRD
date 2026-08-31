"""Domain types for the Athlete Endorsement Booking API.

Entity shapes, status enums and the caller-role enum, all named exactly as the
PRD names them.
"""
from enum import Enum
from typing import List, Optional, TypedDict


class UserRole(str, Enum):
    TALENT_AGENT = "TalentAgent"
    BRAND_REP = "BrandRep"
    ATHLETE = "Athlete"
    COMPLIANCE_OFFICER = "ComplianceOfficer"
    FINANCE_MANAGER = "FinanceManager"


class AthleteStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    RETIRED = "RETIRED"


class MarketTier(str, Enum):
    GLOBAL = "GLOBAL"
    NATIONAL = "NATIONAL"
    REGIONAL = "REGIONAL"


class EndorsementCategory(str, Enum):
    BEVERAGE = "BEVERAGE"
    FOOTWEAR = "FOOTWEAR"
    FINANCIAL = "FINANCIAL"
    AUTOMOTIVE = "AUTOMOTIVE"
    GAMING = "GAMING"
    NUTRITION = "NUTRITION"


class Territory(str, Enum):
    DOMESTIC = "DOMESTIC"
    NORTH_AMERICA = "NORTH_AMERICA"
    GLOBAL = "GLOBAL"


class UsageRightsTier(str, Enum):
    SOCIAL_ONLY = "SOCIAL_ONLY"
    BROADCAST = "BROADCAST"
    PERPETUAL = "PERPETUAL"


class MoralsClauseTier(str, Enum):
    TIER_A = "TIER_A"
    TIER_B = "TIER_B"
    TIER_C = "TIER_C"


class OpportunityStatus(str, Enum):
    INTAKE = "INTAKE"
    SCREENED = "SCREENED"
    REJECTED_FIT = "REJECTED_FIT"
    CONTRACTED = "CONTRACTED"
    CLOSED_LOST = "CLOSED_LOST"


class TermSheetStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    COUNTERED = "COUNTERED"
    ACCEPTED = "ACCEPTED"
    WITHDRAWN = "WITHDRAWN"
    EXPIRED = "EXPIRED"


class ContractStatus(str, Enum):
    PENDING_COUNTERSIGN = "PENDING_COUNTERSIGN"
    ACTIVE = "ACTIVE"
    COMPLETED = "COMPLETED"
    TERMINATED = "TERMINATED"


class SettlementStatus(str, Enum):
    UNBILLED = "UNBILLED"
    BILLABLE = "BILLABLE"
    INVOICED = "INVOICED"
    SETTLED = "SETTLED"


class ExclusivityGrantStatus(str, Enum):
    PENDING = "PENDING"
    ACTIVE = "ACTIVE"
    RELEASED = "RELEASED"


class BookingStatus(str, Enum):
    HOLD = "HOLD"
    CONFIRMED = "CONFIRMED"
    COMPLETED = "COMPLETED"
    NO_SHOW = "NO_SHOW"
    CANCELLED = "CANCELLED"


class BookingOutcome(str, Enum):
    COMPLETED = "COMPLETED"
    NO_SHOW = "NO_SHOW"


class DeliverableType(str, Enum):
    SOCIAL_POST = "SOCIAL_POST"
    APPEARANCE = "APPEARANCE"
    SHOOT = "SHOOT"


class DeliverableStatus(str, Enum):
    PENDING = "PENDING"
    SUBMITTED = "SUBMITTED"
    REVISION_REQUESTED = "REVISION_REQUESTED"
    APPROVED = "APPROVED"
    VOIDED = "VOIDED"


class ReviewDecision(str, Enum):
    APPROVE = "APPROVE"
    REQUEST_REVISION = "REQUEST_REVISION"


class DisclosurePlatform(str, Enum):
    INSTAGRAM = "INSTAGRAM"
    X = "X"
    TIKTOK = "TIKTOK"
    YOUTUBE = "YOUTUBE"
    BROADCAST = "BROADCAST"


class DisclosureStatus(str, Enum):
    PENDING_REVIEW = "PENDING_REVIEW"
    COMPLIANT = "COMPLIANT"
    NON_COMPLIANT = "NON_COMPLIANT"


class PayoutStatus(str, Enum):
    DRAFT = "DRAFT"
    DISBURSED = "DISBURSED"
    VOIDED = "VOIDED"


class RenewalStatus(str, Enum):
    OPEN = "OPEN"
    EXERCISED = "EXERCISED"
    DECLINED = "DECLINED"
    LAPSED = "LAPSED"


class RenewalDecision(str, Enum):
    EXERCISE = "EXERCISE"
    DECLINE = "DECLINE"


class BonusTier(str, Enum):
    TIER_1 = "TIER_1"
    TIER_2 = "TIER_2"
    TIER_3 = "TIER_3"
    NONE = "NONE"


class LedgerEntryType(str, Enum):
    TRAVEL_ACCRUAL = "TRAVEL_ACCRUAL"
    REVERSAL = "REVERSAL"
    PENALTY = "PENALTY"
    BONUS = "BONUS"
    DISBURSEMENT = "DISBURSEMENT"


class ExposureVariant(str, Enum):
    ROSTER_SNAPSHOT = "ROSTER_SNAPSHOT"
    PIPELINE_PROJECTED = "PIPELINE_PROJECTED"


# ── Entity shapes ────────────────────────────────────────────────────────────
# Every resource below carries id / created_at / updated_at / version, with the
# single documented exception of LedgerEntry.

class Athlete(TypedDict):
    id: str
    full_name: str
    sport: str
    market_tier: str
    base_appearance_rate_cents: int
    commission_pct: float
    home_market: str
    status: str
    active_exclusivity_count: int
    exposure_risk_snapshot_score: int
    no_show_count: int
    created_at: str
    updated_at: str
    version: int


class Brand(TypedDict):
    id: str
    name: str
    category: str
    legal_entity_name: str
    compliance_rating: int
    sanctioned: bool
    sanction_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Opportunity(TypedDict):
    id: str
    brand_id: str
    athlete_id: str
    requested_start_date: str
    requested_end_date: str
    proposed_fee_cents: int
    planned_posts: int
    planned_appearances: int
    planned_shoots: int
    exclusivity_category: str
    exclusivity_months: int
    territory: str
    usage_rights_tier: str
    status: str
    expected_fee_cents: Optional[int]
    brand_fit_score: Optional[int]
    screened_by_user_id: Optional[str]
    screened_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class TermSheet(TypedDict):
    id: str
    opportunity_id: str
    round_number: int
    counter_count: int
    fee_cents: int
    usage_rights_tier: str
    usage_term_months: int
    territory: str
    morals_clause_tier: str
    exclusivity_category: str
    exclusivity_months: int
    appearance_days: int
    provisional_fee_cents: Optional[int]
    offer_expires_at: Optional[str]
    last_counter_morals_tier: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class Engagement(TypedDict):
    id: str
    term_sheet_id: str
    opportunity_id: str
    athlete_id: str
    brand_id: str
    contract_status: str
    settlement_status: str
    base_fee_cents: int
    usage_rights_tier: str
    morals_clause_tier: str
    territory: str
    exclusivity_category: str
    exclusivity_months: int
    term_start_date: str
    term_end_date: str
    provisional_fee_cents: int
    binding_fee_cents: Optional[int]
    accrued_fee_cents: int
    gross_settled_cents: int
    required_deliverable_count: int
    approved_deliverable_count: int
    appearance_days_committed: int
    countersigned_by_user_id: Optional[str]
    countersigned_at: Optional[str]
    terminated_reason_code: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ExclusivityGrant(TypedDict):
    id: str
    athlete_id: str
    engagement_id: str
    category: str
    start_date: str
    end_date: str
    status: str
    released_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class AppearanceBooking(TypedDict):
    id: str
    engagement_id: str
    city: str
    start_at: str
    end_at: str
    travel_buffer_hours: int
    travel_cost_cents: int
    travel_days: int
    status: str
    outcome: Optional[str]
    cancel_reason_code: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ProductionSlot(TypedDict):
    id: str
    name: str
    capacity: int
    window_start_at: str
    window_end_at: str
    reserved_count: int
    created_at: str
    updated_at: str
    version: int


class Deliverable(TypedDict):
    id: str
    engagement_id: str
    type: str
    due_date: str
    booking_id: Optional[str]
    production_slot_id: Optional[str]
    shoot_start_at: Optional[str]
    shoot_end_at: Optional[str]
    disclosure_required: bool
    asset_url: Optional[str]
    weight: int
    line_value_cents: Optional[int]
    revision_count: int
    status: str
    created_at: str
    updated_at: str
    version: int


class DisclosureRecord(TypedDict):
    id: str
    deliverable_id: str
    platform: str
    disclosure_tag: str
    posted_at: str
    ruled_by_user_id: Optional[str]
    finding_note: Optional[str]
    remediation_count: int
    status: str
    created_at: str
    updated_at: str
    version: int


class PayoutStatement(TypedDict):
    id: str
    engagement_id: str
    line_count: int
    gross_amount_cents: int
    agency_commission_cents: int
    penalty_cents: int
    athlete_net_cents: int
    status: str
    disbursed_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class RenewalOption(TypedDict):
    id: str
    engagement_id: str
    option_deadline_date: str
    proposed_base_fee_cents: int
    base_value_cents: int
    approval_rate: float
    bonus_tier: str
    bonus_cents: int
    total_engagement_value_cents: int
    renewal_fee_cents: int
    status: str
    decided_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class LedgerEntry(TypedDict):
    """Immutable append-only money movement: id + created_at only."""
    id: str
    engagement_id: str
    entry_type: str
    amount_cents: int
    memo: str
    source_entity: str
    source_id: str
    created_at: str


class ExposureSummary(TypedDict):
    athlete_id: str
    variant: str
    category_load: int
    morals_exposure: int
    noncompliance_hits: int
    score: int
