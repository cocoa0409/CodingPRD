"""Domain types: entity TypedDicts, status enums, role enum.

Field names mirror the PRD exactly. Entities that carry the full common-field set
(id, created_at, updated_at, version) declare all four; the append-only audit
stream declares only id and created_at.
"""
from enum import Enum
from typing import TypedDict, Optional, List


# --- Enumerations -----------------------------------------------------------

class AgentKind(str, Enum):
    LEAD = "LEAD"
    ASSOCIATE = "ASSOCIATE"


class AgentStatus(str, Enum):
    ACTIVE = "ACTIVE"
    AT_CAPACITY = "AT_CAPACITY"
    ON_LEAVE = "ON_LEAVE"


class OccupancyBand(str, Enum):
    UNDER_TARGET = "UNDER_TARGET"
    NEAR_TARGET = "NEAR_TARGET"
    OVER_TARGET = "OVER_TARGET"


class RatioState(str, Enum):
    UNDER_TARGET = "UNDER_TARGET"
    ON_TARGET = "ON_TARGET"
    OVER_TARGET = "OVER_TARGET"


class LeadCapacityState(str, Enum):
    OPEN = "OPEN"
    AT_CAPACITY = "AT_CAPACITY"
    OVER_TARGET = "OVER_TARGET"


class ClientNeedKind(str, Enum):
    BUY = "BUY"
    SELL = "SELL"


class ClientStatus(str, Enum):
    UNASSIGNED = "UNASSIGNED"
    ASSIGNED = "ASSIGNED"
    IN_TRANSACTION = "IN_TRANSACTION"
    CLOSED = "CLOSED"
    REFERRED = "REFERRED"


class AssignmentMode(str, Enum):
    ASSIGNED_DIRECT = "ASSIGNED_DIRECT"
    REFERRED_PARTNER = "REFERRED_PARTNER"
    UNASSIGNED = "UNASSIGNED"


class AssignmentReason(str, Enum):
    GEOGRAPHY_MATCH = "GEOGRAPHY_MATCH"
    ALL_AT_CAPACITY = "ALL_AT_CAPACITY"
    NO_IN_GEOGRAPHY_AGENT = "NO_IN_GEOGRAPHY_AGENT"
    NO_SATISFACTION_SCORE = "NO_SATISFACTION_SCORE"
    MANUAL_PARTNER = "MANUAL_PARTNER"
    REGION_OCCUPANCY_AT_CAPACITY = "REGION_OCCUPANCY_AT_CAPACITY"


class CoordinationStatus(str, Enum):
    UNASSIGNED = "UNASSIGNED"
    ASSIGNED = "ASSIGNED"
    REVIEW = "REVIEW"
    CLOSED = "CLOSED"
    CANCELLED = "CANCELLED"


class ServiceTier(str, Enum):
    FULL_SERVICE = "FULL_SERVICE"
    LIMITED_SERVICE = "LIMITED_SERVICE"
    MLS_ONLY = "MLS_ONLY"


class ListingStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    UNDER_CONTRACT = "UNDER_CONTRACT"
    CLOSED = "CLOSED"
    WITHDRAWN = "WITHDRAWN"


class TourStatus(str, Enum):
    ACCESS_PENDING = "ACCESS_PENDING"
    CONFIRMED = "CONFIRMED"
    COMPLETED = "COMPLETED"
    CANCELLED_NO_SHOW = "CANCELLED_NO_SHOW"
    CANCELLED = "CANCELLED"


class SurveyResponseStatus(str, Enum):
    DISPATCHED = "DISPATCHED"
    RESPONDED = "RESPONDED"
    EXPIRED_DISPATCH = "EXPIRED_DISPATCH"


class SettlementStatus(str, Enum):
    PENDING = "PENDING"
    COMPUTED = "COMPUTED"
    SETTLED = "SETTLED"


class SplitPolicy(str, Enum):
    SPLIT_25_PARTNER = "SPLIT_25_PARTNER"
    SPLIT_50_PARTNER = "SPLIT_50_PARTNER"


class AuditKind(str, Enum):
    TRANSACTION_CREATED = "TRANSACTION_CREATED"
    TRANSACTION_STATUS_CHANGED = "TRANSACTION_STATUS_CHANGED"
    CLIENT_CAPACITY_RELEASED = "CLIENT_CAPACITY_RELEASED"
    SERVICE_COMMITMENT_BREACH = "SERVICE_COMMITMENT_BREACH"


class UserRole(str, Enum):
    PLATFORM_ADMIN = "PlatformAdmin"
    OPERATIONS_COORDINATOR = "OperationsCoordinator"
    TRANSACTION_COORDINATOR = "TransactionCoordinator"
    LISTING_AGENT = "ListingAgent"
    ASSOCIATE_AGENT = "AssociateAgent"


# --- Entities (full common fields: id, created_at, updated_at, version) -----

class Region(TypedDict, total=False):
    id: str
    name: str
    service_area_codes: List[str]
    traditional_commission_pct: float
    target_client_ratio: float
    agent_count: int
    occupancy_pct: float
    occupancy_band: str
    clients_in_pipeline: int
    referral_count: int
    open_referral_count: int
    enrolment_is_required: bool
    capacity: int
    created_at: str
    updated_at: str
    version: int


class Agent(TypedDict, total=False):
    id: str
    region_id: str
    full_name: str
    agent_kind: str
    home_zip: str
    base_salary_cents: int
    benefits_cents: int
    expense_allowance_cents: int
    satisfaction_score: Optional[float]
    close_rate: float
    bonus_pct: float
    bonus_cents: int
    salary_commitment_cents: int
    open_referral_count: int
    referral_fee_bps: int
    status: str
    created_at: str
    updated_at: str
    version: int


class OpenClientCount(TypedDict, total=False):
    id: str
    agent_id: str
    active_client_count: int
    ratio_state: str
    created_at: str
    updated_at: str
    version: int


class LeadCapacity(TypedDict, total=False):
    id: str
    agent_id: str
    current_state: str
    tours_in_week: int
    associate_capacity_used: int
    close_rate: float
    graded_transactions: int
    trailing_tours: int
    unassigned_tours: int
    created_at: str
    updated_at: str
    version: int


class Client(TypedDict, total=False):
    id: str
    region_id: str
    full_name: str
    email: str
    service_area_code: str
    need_kind: str
    assigned_agent_id: Optional[str]
    assignment_mode: str
    assignment_reason: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class Transaction(TypedDict, total=False):
    id: str
    client_id: str
    lead_agent_id: Optional[str]
    coordination_status: str
    contract_price_cents: int
    closed_at: Optional[str]
    agent_satisfaction_credit: float
    created_at: str
    updated_at: str
    version: int


class ListingAgreement(TypedDict, total=False):
    id: str
    region_id: str
    client_id: str
    list_price_cents: int
    list_fee_rate_pct: float
    service_tier: str
    traditional_listing_fee_cents: int
    partner_referral_fee_cents: int
    gross_listing_fee_cents: int
    savings_amount_cents: int
    savings_pct: float
    final_listing_fee_cents: int
    service_commitment_hours: int
    posted_at: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class Tour(TypedDict, total=False):
    id: str
    lead_agent_id: str
    client_id: str
    listing_agreement_id: Optional[str]
    associate_agent_id: Optional[str]
    scheduled_at: str
    access_instructions: str
    access_code: Optional[str]
    status: str
    feedback_rating: Optional[int]
    feedback_notes: Optional[str]
    tours_next_36_hours: int
    created_at: str
    updated_at: str
    version: int


class Survey(TypedDict, total=False):
    id: str
    transaction_id: str
    agent_id: str
    score: Optional[int]
    response_status: str
    bonus_eligible: bool
    dispatched_at: str
    responded_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class AgentReferral(TypedDict, total=False):
    id: str
    region_id: str
    client_id: str
    partner_name: str
    referral_fee_bps: int
    referral_fee_cents: int
    settlement_status: str
    split_policy: str
    partner_cents: int
    house_cents: int
    settlement_reference: Optional[str]
    created_at: str
    updated_at: str
    version: int


# --- Append-only entity (no updated_at, no version) -------------------------

class ActivityAudit(TypedDict, total=False):
    id: str
    region_id: str
    entity_type: str
    entity_ref_id: str
    kind: str
    detail: str
    created_at: str