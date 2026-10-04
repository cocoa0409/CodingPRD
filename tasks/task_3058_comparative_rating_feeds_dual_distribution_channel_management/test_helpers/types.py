"""Domain types: entity TypedDicts, status enums, role enum."""
from enum import Enum
from typing import Optional, TypedDict


class UserRole(str, Enum):
    ANONYMOUS = "Anonymous"
    CARRIER_ADMIN = "CarrierAdmin"
    RATING_MANAGER = "RatingManager"
    UNDERWRITING_REVIEWER = "UnderwritingReviewer"
    AGENT = "Agent"
    CONSUMER = "Consumer"
    COMPARATIVE_RATER = "ComparativeRater"
    SYSTEM = "System"


class ProductStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    WITHDRAWN = "WITHDRAWN"


class PublicationStatus(str, Enum):
    DRAFT = "DRAFT"
    PUBLISHED = "PUBLISHED"
    SUPERSEDED = "SUPERSEDED"
    RECALLED = "RECALLED"


class AgentStatus(str, Enum):
    APPLICANT = "APPLICANT"
    APPOINTED = "APPOINTED"
    SUSPENDED = "SUSPENDED"
    TERMINATED = "TERMINATED"


class AppointmentStatus(str, Enum):
    ACTIVE = "ACTIVE"
    TERMINATED = "TERMINATED"
    EXPIRED = "EXPIRED"


class ScheduleStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUPERSEDED = "SUPERSEDED"
    VOIDED = "VOIDED"


class QuoteStatus(str, Enum):
    DRAFT = "DRAFT"
    QUOTED = "QUOTED"
    REFERRED_TO_AGENT = "REFERRED_TO_AGENT"
    AGENT_QUOTED = "AGENT_QUOTED"
    BOUND = "BOUND"
    EXPIRED = "EXPIRED"
    WITHDRAWN = "WITHDRAWN"


class PolicyStatus(str, Enum):
    IN_FORCE = "IN_FORCE"
    CANCELLED = "CANCELLED"


class ClaimStatus(str, Enum):
    REPORTED = "REPORTED"
    CLOSED = "CLOSED"


class EnrollmentStatus(str, Enum):
    ENROLLED = "ENROLLED"
    PARTICIPATING = "PARTICIPATING"
    SCORED = "SCORED"
    OPTED_OUT = "OPTED_OUT"


class StatementStatus(str, Enum):
    DRAFT = "DRAFT"
    FINALIZED = "FINALIZED"
    PAID = "PAID"
    CLAWED_BACK = "CLAWED_BACK"
    STALE = "STALE"


class PoolStatus(str, Enum):
    OPEN = "OPEN"
    SETTLED = "SETTLED"


class ReviewStatus(str, Enum):
    OPEN = "OPEN"
    FINDINGS_ISSUED = "FINDINGS_ISSUED"
    ACTION_TAKEN = "ACTION_TAKEN"


class PlacementStatus(str, Enum):
    QUOTED = "QUOTED"
    PLACED = "PLACED"
    AOR_TRANSFERRED = "AOR_TRANSFERRED"
    DECLINED = "DECLINED"


class Channel(str, Enum):
    DIRECT = "DIRECT"
    AGENT = "AGENT"


class LineOfBusiness(str, Enum):
    AUTO = "AUTO"
    HOME = "HOME"


class CarrierProduct(TypedDict, total=False):
    id: str
    product_code: str
    line_of_business: str
    state_code: str
    channel_availability: str
    coverage_rates: dict
    direct_discount_pct: float
    agent_load_pct: float
    bundle_credit_pct: float
    min_premium_cents: int
    direct_channel_max_premium_cents: Optional[int]
    bundle_eligible: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class ComparativeRater(TypedDict, total=False):
    id: str
    rater_code: str
    display_name: str
    feed_format_version: str
    accepted_line_of_business: str
    created_at: str
    updated_at: str
    version: int


class RateFeedPublication(TypedDict, total=False):
    id: str
    rater_id: str
    product_id: str
    effective_start: str
    effective_end: str
    rate_table_payload: dict
    status: str
    published_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Agent(TypedDict, total=False):
    id: str
    agency_name: str
    principal_name: str
    resident_state_code: str
    status: str
    terminated_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class AgentAppointment(TypedDict, total=False):
    id: str
    agent_id: str
    state_code: str
    line_of_business: str
    effective_start: str
    effective_end: Optional[str]
    status: str
    terminated_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class CommissionSchedule(TypedDict, total=False):
    id: str
    agent_id: str
    line_of_business: str
    effective_start: str
    effective_end: Optional[str]
    tiers: list
    contingent_bonus_eligible: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class Consumer(TypedDict, total=False):
    id: str
    email: str
    full_name: str
    date_of_birth: str
    home_state_code: str
    created_at: str
    updated_at: str
    version: int


class Quote(TypedDict, total=False):
    id: str
    consumer_id: str
    product_id: str
    agent_id: Optional[str]
    channel: str
    coverages: list
    bundled_home_intended: bool
    telematics_opt_in: bool
    status: str
    quoted_premium_cents: Optional[int]
    quoted_at: Optional[str]
    expires_at: Optional[str]
    rate_stale: bool
    referral_snapshot: Optional[dict]
    rate_feed_publication_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Policy(TypedDict, total=False):
    id: str
    quote_id: str
    consumer_id: str
    agent_id: Optional[str]
    product_id: str
    channel: str
    inception_at: str
    term_days: int
    written_premium_cents: int
    status: str
    cancelled_at: Optional[str]
    earned_premium_cents: int
    unearned_premium_cents: int
    per_policy_commission_cents: Optional[int]
    clawback_cents: int
    created_at: str
    updated_at: str
    version: int


class Claim(TypedDict, total=False):
    id: str
    policy_id: str
    claim_type: str
    incurred_amount_cents: int
    status: str
    reported_at: str
    created_at: str
    updated_at: str
    version: int


class TelematicsEnrollment(TypedDict, total=False):
    id: str
    policy_id: str
    channel: str
    status: str
    driving_score: Optional[int]
    upfront_discount_cents: int
    discount_pct_applied: Optional[float]
    adjustment_cents: Optional[int]
    created_at: str
    updated_at: str
    version: int


class CommissionStatement(TypedDict, total=False):
    id: str
    agent_id: str
    period_start: str
    period_end: str
    status: str
    written_premium_cents: int
    commission_cents: int
    clawback_cents: int
    net_payable_cents: int
    line_items: list
    created_at: str
    updated_at: str
    version: int


class ContingentBonusPool(TypedDict, total=False):
    id: str
    year: int
    pool_total_cents: int
    loss_ratio_threshold: float
    growth_threshold_pct: float
    status: str
    settled_at: Optional[str]
    undistributed_cents: Optional[int]
    created_at: str
    updated_at: str
    version: int


class BonusPayout(TypedDict, total=False):
    id: str
    pool_id: str
    agent_id: str
    earned_premium_cents: int
    eligible: bool
    ineligibility_reason: Optional[str]
    payout_cents: int
    created_at: str
    updated_at: str
    version: int


class PortfolioReview(TypedDict, total=False):
    id: str
    agent_id: str
    reason: str
    opened_by_user_id: str
    status: str
    trailing_loss_ratio: float
    earned_premium_trailing_cents: int
    findings: Optional[str]
    action: Optional[str]
    actioned_by_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class BundlePlacement(TypedDict, total=False):
    id: str
    policy_id: str
    agent_id: str
    unaffiliated_carrier_name: str
    home_premium_cents: int
    total_commission_cents: int
    status: str
    transferred_to_agent_id: Optional[str]
    earned_commission_cents: Optional[int]
    transferred_commission_cents: Optional[int]
    created_at: str
    updated_at: str
    version: int
