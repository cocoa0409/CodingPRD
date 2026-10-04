"""Domain types: entity TypedDicts, status enums, action enums, role enum.

All entities carry the four system-managed common fields (id, created_at,
updated_at, version) per PRD section on resource identity; domain datetimes
render exactly as the logical clock reads.
"""
from enum import Enum
from typing import Any, Dict, List, Optional, TypedDict


# ---------------------------------------------------------------------------
# Roles (PRD: X-User-Role is one of four roles)
# ---------------------------------------------------------------------------

class UserRole(str, Enum):
    AUCTION_ADMIN = "AuctionAdmin"
    BIDDER = "Bidder"
    INCUMBENT_OPERATOR = "IncumbentOperator"
    TRANSFER_REVIEWER = "TransferReviewer"


# ---------------------------------------------------------------------------
# Status enums
# ---------------------------------------------------------------------------

class BandPlanStatus(str, Enum):
    DRAFT = "DRAFT"
    PUBLISHED = "PUBLISHED"


class AuctionStatus(str, Enum):
    DRAFT = "DRAFT"
    APPLICATION_OPEN = "APPLICATION_OPEN"
    QUIET_PERIOD = "QUIET_PERIOD"
    CLOCK_ACTIVE = "CLOCK_ACTIVE"
    CLOCK_PAUSED = "CLOCK_PAUSED"
    ASSIGNMENT_PHASE = "ASSIGNMENT_PHASE"
    CLOSED = "CLOSED"


class ApplicantStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    UNDER_REVIEW = "UNDER_REVIEW"
    NEEDS_CORRECTION = "NEEDS_CORRECTION"
    QUALIFIED = "QUALIFIED"
    REJECTED = "REJECTED"
    DISQUALIFIED = "DISQUALIFIED"
    WITHDRAWN = "WITHDRAWN"


class ClockRoundStatus(str, Enum):
    OPEN = "OPEN"
    CLOSED = "CLOSED"


class BidStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    PROCESSED = "PROCESSED"
    VOIDED = "VOIDED"


class AssignmentBidStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    APPLIED = "APPLIED"


class LicenseStatus(str, Enum):
    PENDING_PAYMENT = "PENDING_PAYMENT"
    ACTIVE = "ACTIVE"
    RENEWAL_REVIEW = "RENEWAL_REVIEW"
    TERMINATED = "TERMINATED"
    CANCELLED = "CANCELLED"


class MilestoneType(str, Enum):
    INTERIM = "INTERIM"
    FINAL = "FINAL"


class BuildoutMilestoneStatus(str, Enum):
    PENDING = "PENDING"
    FILED = "FILED"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"
    MISSED = "MISSED"


class TransferType(str, Enum):
    FULL_ASSIGNMENT = "FULL_ASSIGNMENT"
    LEASE = "LEASE"


class TransferStatus(str, Enum):
    FILED = "FILED"
    UNDER_REVIEW = "UNDER_REVIEW"
    INFO_REQUESTED = "INFO_REQUESTED"
    APPROVED = "APPROVED"
    DENIED = "DENIED"
    WITHDRAWN = "WITHDRAWN"


class IncumbentStatus(str, Enum):
    NOTIFIED = "NOTIFIED"
    PLAN_SUBMITTED = "PLAN_SUBMITTED"
    DISPUTED = "DISPUTED"
    RELOCATING = "RELOCATING"
    CLEARED = "CLEARED"


class RenewalStatus(str, Enum):
    FILED = "FILED"
    UNDER_REVIEW = "UNDER_REVIEW"
    GRANTED = "GRANTED"
    DENIED = "DENIED"


class BlockCategory(str, Enum):
    CATEGORY_A = "CATEGORY_A"
    CATEGORY_B = "CATEGORY_B"
    CATEGORY_C = "CATEGORY_C"
    CATEGORY_D = "CATEGORY_D"


# ---------------------------------------------------------------------------
# Action enums for multiplexed driver endpoints
# ---------------------------------------------------------------------------

class AuctionPhaseAction(str, Enum):
    OPEN_APPLICATIONS = "OPEN_APPLICATIONS"
    BEGIN_QUIET_PERIOD = "BEGIN_QUIET_PERIOD"
    POSTPONE = "POSTPONE"
    START_CLOCK = "START_CLOCK"
    PAUSE_CLOCK = "PAUSE_CLOCK"
    RESUME_CLOCK = "RESUME_CLOCK"
    COMPLETE_ASSIGNMENT = "COMPLETE_ASSIGNMENT"


class ApplicantReviewAction(str, Enum):
    START_REVIEW = "START_REVIEW"
    QUALIFY = "QUALIFY"
    REJECT = "REJECT"
    REQUEST_CORRECTION = "REQUEST_CORRECTION"
    DISQUALIFY = "DISQUALIFY"


class MilestoneDecision(str, Enum):
    ACCEPT = "ACCEPT"
    REJECT = "REJECT"


class TransferReviewAction(str, Enum):
    BEGIN_REVIEW = "BEGIN_REVIEW"
    REQUEST_INFO = "REQUEST_INFO"
    PROVIDE_INFO = "PROVIDE_INFO"
    APPROVE = "APPROVE"
    DENY = "DENY"


class IncumbentTransitionAction(str, Enum):
    SUBMIT_PLAN = "SUBMIT_PLAN"
    DISPUTE = "DISPUTE"
    RESUBMIT_PLAN = "RESUBMIT_PLAN"
    BEGIN_RELOCATION = "BEGIN_RELOCATION"
    CONFIRM_CLEARED = "CONFIRM_CLEARED"


class RenewalDecision(str, Enum):
    GRANT = "GRANT"
    DENY = "DENY"


# ---------------------------------------------------------------------------
# Sub-structures
# ---------------------------------------------------------------------------

class OwnershipInterest(TypedDict):
    holder_name: str
    stake_pct: float
    holder_annual_revenue_cents: int


class ProductPrice(TypedDict):
    area_code: str
    category: str
    price_cents: int


class ProductDemand(TypedDict):
    area_code: str
    category: str
    demand_quantity: int


class SupplyEntry(TypedDict):
    area_code: str
    category: str
    available: int


class RelocationShare(TypedDict):
    license_id: str
    amount_cents: int


# ---------------------------------------------------------------------------
# Entity TypedDicts (all carry id / created_at / updated_at / version)
# ---------------------------------------------------------------------------

class BandPlan(TypedDict):
    id: str
    band_name: str
    frequency_start_mhz: float
    frequency_end_mhz: float
    technical_rules: str
    status: str
    created_at: str
    updated_at: str
    version: int


class LicenseArea(TypedDict):
    id: str
    band_plan_id: str
    area_code: str
    name: str
    population: int
    created_at: str
    updated_at: str
    version: int


class LicenseBlock(TypedDict):
    id: str
    band_plan_id: str
    category: str
    mhz_size: int
    supply_per_area: int
    price_per_mhz_pop_cents: int
    created_at: str
    updated_at: str
    version: int


class Auction(TypedDict):
    id: str
    band_plan_id: str
    name: str
    application_deadline: str
    status: str
    current_round_number: int
    total_proceeds_cents: int
    forfeited_deposits_cents: int
    available_supply: List[SupplyEntry]
    created_at: str
    updated_at: str
    version: int


class Applicant(TypedDict):
    id: str
    auction_id: str
    legal_name: str
    claims_small_business: bool
    claims_rural_credit: bool
    own_annual_revenue_cents: int
    service_population: int
    ownership_interests: List[OwnershipInterest]
    attributable_revenue_cents: int
    credit_pct: int
    upfront_paid_cents: int
    upfront_held_cents: int
    upfront_refunded_cents: int
    upfront_forfeited_cents: int
    eligibility_units: int
    initial_eligibility_units: int
    status: str
    created_at: str
    updated_at: str
    version: int


class ClockRound(TypedDict):
    id: str
    auction_id: str
    round_number: int
    stage: int
    prices: List[ProductPrice]
    aggregate_demand: List[ProductDemand]
    status: str
    created_at: str
    updated_at: str
    version: int


class Bid(TypedDict):
    id: str
    round_id: str
    bidder_applicant_id: str
    area_code: str
    category: str
    quantity: int
    units_snapshot: int
    status: str
    created_at: str
    updated_at: str
    version: int


class AssignmentBid(TypedDict):
    id: str
    auction_id: str
    bidder_applicant_id: str
    area_code: str
    category: str
    amount_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class License(TypedDict):
    id: str
    auction_id: str
    area_id: str
    area_code: str
    category: str
    frequency_block_index: int
    holder_applicant_id: str
    credit_pct: int
    gross_clock_price_cents: int
    assignment_bid_cents: int
    gross_final_price_cents: int
    provisional_net_price_cents: int
    net_price_cents: int
    credit_amount_cents: int
    paid_cents: int
    grant_date: Optional[str]
    term_end: Optional[str]
    payment_deadline: str
    active_lease_start: Optional[str]
    active_lease_end: Optional[str]
    leased_to_applicant_id: Optional[str]
    relocation_share_owed_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class BuildoutMilestone(TypedDict):
    id: str
    license_id: str
    milestone_type: str
    due_date: str
    required_coverage_pct: int
    covered_population: Optional[int]
    status: str
    created_at: str
    updated_at: str
    version: int


class TransferApplication(TypedDict):
    id: str
    license_id: str
    transferor_applicant_id: str
    transferee_applicant_id: str
    transfer_type: str
    lease_start: Optional[str]
    lease_end: Optional[str]
    unjust_enrichment_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Incumbent(TypedDict):
    id: str
    band_plan_id: str
    area_id: str
    callsign: str
    relocation_cost_cents: int
    transition_window_start: Optional[str]
    transition_window_end: Optional[str]
    shares_proportional: List[RelocationShare]
    shares_equal: List[RelocationShare]
    status: str
    created_at: str
    updated_at: str
    version: int


class RenewalApplication(TypedDict):
    id: str
    license_id: str
    status: str
    created_at: str
    updated_at: str
    version: int
