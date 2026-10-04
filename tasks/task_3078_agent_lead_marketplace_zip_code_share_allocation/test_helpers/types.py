"""Domain types: entity TypedDicts, status enums, role enum (PRD §2.1, §2.10, §3)."""
from enum import Enum
from typing import List, Optional, TypedDict


class UserRole(str, Enum):
    AGENT = "Agent"
    BROKERAGE_USER = "BrokerageUser"
    MARKETPLACE_OPS = "MarketplaceOps"
    PLATFORM_ADMIN = "PlatformAdmin"


class MarketStatus(str, Enum):
    OPEN = "OPEN"
    SUSPENDED = "SUSPENDED"


class ParticipationAgreement(str, Enum):
    IDX_FULL = "IDX_FULL"
    IDX_LIMITED = "IDX_LIMITED"
    NON_PARTICIPATING = "NON_PARTICIPATING"


class BrokerageStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class AgentStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    DEACTIVATED = "DEACTIVATED"


class PerformanceTier(str, Enum):
    UNRATED = "UNRATED"
    HIGH = "HIGH"
    STANDARD = "STANDARD"
    LOW = "LOW"
    INELIGIBLE = "INELIGIBLE"


class TeamStatus(str, Enum):
    ACTIVE = "ACTIVE"
    DISSOLVED = "DISSOLVED"


class MembershipStatus(str, Enum):
    ACTIVE = "ACTIVE"
    REMOVED = "REMOVED"


class DistributionMode(str, Enum):
    WEIGHTED_DEFICIT = "WEIGHTED_DEFICIT"
    MANUAL = "MANUAL"


class OrderStatus(str, Enum):
    PENDING_PAYMENT = "PENDING_PAYMENT"
    ACTIVE = "ACTIVE"
    PAUSED = "PAUSED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"
    PAYMENT_FAILED = "PAYMENT_FAILED"


class PaymentStatus(str, Enum):
    SUCCEEDED = "SUCCEEDED"
    DECLINED = "DECLINED"


class LeadStatus(str, Enum):
    NEW = "NEW"
    ROUTED = "ROUTED"
    UNASSIGNED = "UNASSIGNED"
    ASSIGNED = "ASSIGNED"
    LIVE_CONNECTED = "LIVE_CONNECTED"
    CLOSED_CONVERTED = "CLOSED_CONVERTED"
    CLOSED_LOST = "CLOSED_LOST"
    REJECTED_DUPLICATE = "REJECTED_DUPLICATE"


class AssignmentStatus(str, Enum):
    OFFERED = "OFFERED"
    ACCEPTED = "ACCEPTED"
    EXPIRED = "EXPIRED"
    CANCELLED = "CANCELLED"


class ConnectionStatus(str, Enum):
    REQUESTED = "REQUESTED"
    BRIDGING = "BRIDGING"
    COMPLETED = "COMPLETED"
    NO_ANSWER = "NO_ANSWER"
    DROPPED = "DROPPED"
    REJECTED_DUPLICATE = "REJECTED_DUPLICATE"


class RecordingStatus(str, Enum):
    STORED = "STORED"
    PURGED = "PURGED"


class ClaimStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


class ClaimType(str, Enum):
    INVALID = "INVALID"
    DUPLICATE = "DUPLICATE"


class ListingStatus(str, Enum):
    PENDING_REVIEW = "PENDING_REVIEW"
    ACTIVE = "ACTIVE"
    REJECTED = "REJECTED"
    WITHDRAWN = "WITHDRAWN"


class SourceFeed(str, Enum):
    MLS = "MLS"
    BROKER_DIRECT = "BROKER_DIRECT"


class DisputeStatus(str, Enum):
    OPEN = "OPEN"
    RESOLVED = "RESOLVED"
    REJECTED = "REJECTED"


class DisputeType(str, Enum):
    LISTING_DISPLAY = "LISTING_DISPLAY"
    LEAD_ATTRIBUTION = "LEAD_ATTRIBUTION"


# --- entities carrying id + created_at + updated_at + version (PRD §2.10) ---

class Market(TypedDict, total=False):
    id: str
    zip_code: str
    state_code: str
    participation_agreement: str
    base_lead_price_cents: int
    market_status: str
    allocated_bps: int
    available_bps: int
    current_unit_price_cents: int
    created_at: str
    updated_at: str
    version: int


class Brokerage(TypedDict, total=False):
    id: str
    legal_name: str
    primary_state: str
    brokerage_status: str
    created_at: str
    updated_at: str
    version: int


class Agent(TypedDict, total=False):
    id: str
    full_name: str
    email: str
    license_number: str
    license_state: str
    brokerage_id: str
    agent_status: str
    performance_tier: str
    rolling_score: int
    official_score: int
    offers_received: int
    offers_accepted: int
    offers_expired: int
    response_seconds_sum: int
    leads_converted: int
    leads_closed_lost: int
    connections_missed: int
    rating_sum: int
    rating_count: int
    created_at: str
    updated_at: str
    version: int


class TeamAccount(TypedDict, total=False):
    id: str
    team_name: str
    lead_agent_id: str
    market_id: str
    distribution_mode: str
    team_status: str
    created_at: str
    updated_at: str
    version: int


class TeamMembership(TypedDict, total=False):
    id: str
    team_id: str
    agent_id: str
    allocation_weight: int
    membership_status: str
    leads_assigned: int
    allocated_charge_cents: int
    created_at: str
    updated_at: str
    version: int


class ShareOrder(TypedDict, total=False):
    id: str
    market_id: str
    buyer_agent_id: str
    team_id: Optional[str]
    share_bps: int
    duration_days: int
    tier: int
    unit_price_cents: int
    deposit_cents: int
    paid_cents: int
    charged_cents: int
    credits_cents: int
    leads_received: int
    leads_charged: int
    leads_credited: int
    order_status: str
    activated_at: Optional[str]
    ends_at: Optional[str]
    completed_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Lead(TypedDict, total=False):
    id: str
    market_id: str
    listing_id: Optional[str]
    consumer_key: str
    listing_agent_id: Optional[str]
    lead_status: str
    share_order_id: Optional[str]
    team_id: Optional[str]
    routing_attempts: int
    accepted_agent_id: Optional[str]
    assigned_at: Optional[str]
    duplicate_of_lead_id: Optional[str]
    routing_note: Optional[str]
    created_at: str
    updated_at: str
    version: int


class LeadAssignment(TypedDict, total=False):
    id: str
    lead_id: str
    share_order_id: str
    candidate_agent_ids: List[str]
    assignment_status: str
    offered_at: str
    expires_at: str
    accepted_by_agent_id: Optional[str]
    accepted_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class LiveConnection(TypedDict, total=False):
    id: str
    lead_id: str
    consumer_key: str
    listing_agent_id: Optional[str]
    agent_id: Optional[str]
    share_order_id: Optional[str]
    connection_status: str
    recording_retention_expires_at: Optional[str]
    duplicate_of_lead_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class CreditClaim(TypedDict, total=False):
    id: str
    lead_id: str
    claimant_agent_id: Optional[str]
    claim_type: str
    reason: str
    claim_status: str
    credit_cents: int
    created_at: str
    updated_at: str
    version: int


class Listing(TypedDict, total=False):
    id: str
    external_ref: str
    market_id: str
    source_feed: str
    brokerage_id: str
    listing_agent_id: str
    listing_status: str
    compliance_note: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Dispute(TypedDict, total=False):
    id: str
    dispute_type: str
    brokerage_id: str
    listing_id: Optional[str]
    lead_id: Optional[str]
    requested_agent_id: Optional[str]
    evidence: str
    dispute_status: str
    resolution: Optional[str]
    resolved_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


# --- append-only resources: id + created_at only (PRD §2.10) ---

class Payment(TypedDict, total=False):
    id: str
    share_order_id: str
    amount_cents: int
    outcome: str
    payment_status: str
    created_at: str


class CallRecording(TypedDict, total=False):
    id: str
    live_connection_id: str
    duration_seconds: int
    consent_given: bool
    recording_status: str
    created_at: str


class Rating(TypedDict, total=False):
    id: str
    lead_id: str
    score: int
    comment: Optional[str]
    created_at: str


class PerformanceSnapshot(TypedDict, total=False):
    id: str
    agent_id: str
    ops_run_seq: int
    window_start_at: Optional[str]
    window_end_at: str
    windowed_score: int
    created_at: str


class OpsRun(TypedDict, total=False):
    id: str
    seq: int
    run_at: str
    sweep_counts: dict
    created_at: str
