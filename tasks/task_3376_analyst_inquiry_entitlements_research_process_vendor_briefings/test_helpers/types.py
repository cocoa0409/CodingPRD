"""Domain types: entity TypedDicts, status enums, role enum.

Every entity in this API carries `id`, `created_at`, `updated_at` and
`version`; lifecycle instants are null until stamped.
"""
from enum import Enum
from typing import List, Optional, TypedDict


# ─── Roles ────────────────────────────────────────────

class UserRole(str, Enum):
    PLATFORM_ADMIN = "PlatformAdmin"
    CLIENT_ADMIN = "ClientAdmin"
    SEAT_HOLDER = "SeatHolder"
    ANALYST = "Analyst"
    RESEARCH_DIRECTOR = "ResearchDirector"
    COMPLIANCE_OFFICER = "ComplianceOfficer"
    VENDOR_REP = "VendorRep"
    EVENT_PROGRAMMER = "EventProgrammer"
    SALES_REP = "SalesRep"


# ─── Enumerations ─────────────────────────────────────

class Region(str, Enum):
    NA = "NA"
    EMEA = "EMEA"
    APAC = "APAC"


class ContractStatus(str, Enum):
    ACTIVE = "ACTIVE"
    RENEWAL_REVIEW = "RENEWAL_REVIEW"
    RENEWED = "RENEWED"
    CHURNED = "CHURNED"


class RenewalPosture(str, Enum):
    HEALTHY = "HEALTHY"
    WATCH = "WATCH"
    AT_RISK = "AT_RISK"


class ReprintTier(str, Enum):
    NONE = "NONE"
    STANDARD = "STANDARD"
    PREMIUM = "PREMIUM"


class ResearchRole(str, Enum):
    EXECUTIVE_VIEWER = "EXECUTIVE_VIEWER"
    PRACTITIONER = "PRACTITIONER"
    ARCHITECT = "ARCHITECT"
    STRATEGIST = "STRATEGIST"


class SeatKind(str, Enum):
    NAMED = "NAMED"
    SHARED = "SHARED"


class SeatStatus(str, Enum):
    PROVISIONED = "PROVISIONED"
    ACTIVE = "ACTIVE"
    REVOKED = "REVOKED"


class PracticeArea(str, Enum):
    CIO_TECH = "CIO_TECH"
    DATA_ANALYTICS = "DATA_ANALYTICS"
    SECURITY = "SECURITY"
    ERP_FINANCE = "ERP_FINANCE"


class Seniority(str, Enum):
    ASSOCIATE = "ASSOCIATE"
    SENIOR = "SENIOR"
    VP = "VP"
    DISTINGUISHED = "DISTINGUISHED"


class AnalystStatus(str, Enum):
    ACTIVE = "ACTIVE"
    ON_LEAVE = "ON_LEAVE"
    EMERITUS = "EMERITUS"


class IntegrityFlag(str, Enum):
    CLEAR = "CLEAR"
    CONFLICT_REVIEW = "CONFLICT_REVIEW"
    CONFLICT_BLOCKED = "CONFLICT_BLOCKED"


class InquiryStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    ROUTED = "ROUTED"
    SCHEDULED = "SCHEDULED"
    IN_PREP = "IN_PREP"
    COMPLETED = "COMPLETED"
    NO_SHOW = "NO_SHOW"
    CANCELLED = "CANCELLED"


class DocType(str, Enum):
    MARKET_GUIDE = "MARKET_GUIDE"
    COMPARATIVE_MATRIX = "COMPARATIVE_MATRIX"
    HYPE_PROFILE = "HYPE_PROFILE"
    CRITICAL_CAPABILITIES = "CRITICAL_CAPABILITIES"


class EditorialStatus(str, Enum):
    DRAFT = "DRAFT"
    PEER_REVIEW = "PEER_REVIEW"
    FACT_CHECK = "FACT_CHECK"
    CLEARED = "CLEARED"
    PUBLISHED = "PUBLISHED"
    REVISED = "REVISED"


class EmbargoStatus(str, Enum):
    EMBARGOED = "EMBARGOED"
    RELEASED = "RELEASED"


class PeerVerdict(str, Enum):
    NOT_ASSIGNED = "NOT_ASSIGNED"
    PENDING = "PENDING"
    APPROVE = "APPROVE"
    REVISE = "REVISE"


class VendorStatus(str, Enum):
    ACTIVE = "ACTIVE"


class EmployeeCountBand(str, Enum):
    SMB = "SMB"
    MIDMARKET = "MIDMARKET"
    ENTERPRISE = "ENTERPRISE"


class InclusionStatus(str, Enum):
    PROPOSED = "PROPOSED"
    UNDER_EVALUATION = "UNDER_EVALUATION"
    INCLUDED = "INCLUDED"
    EXCLUDED = "EXCLUDED"
    UNDER_APPEAL = "UNDER_APPEAL"
    APPEAL_UPHELD = "APPEAL_UPHELD"
    APPEAL_DENIED = "APPEAL_DENIED"
    SUPERSEDED = "SUPERSEDED"


class FactCheckStatus(str, Enum):
    NOT_STARTED = "NOT_STARTED"
    REQUESTED = "REQUESTED"
    VENDOR_RESPONDED = "VENDOR_RESPONDED"
    ADJUDICATED = "ADJUDICATED"
    DISPUTED = "DISPUTED"
    LAPSED = "LAPSED"


class PermittedMarketingUse(str, Enum):
    NO_USE = "NO_USE"
    INTERNAL_ONLY = "INTERNAL_ONLY"
    SOCIAL_SNIPPET = "SOCIAL_SNIPPET"
    FULL_REPRINT = "FULL_REPRINT"


class BriefingStatus(str, Enum):
    REQUESTED = "REQUESTED"
    SCREENED = "SCREENED"
    SCHEDULED = "SCHEDULED"
    HELD = "HELD"
    DECLINED = "DECLINED"
    REVOKED_BY_SEPARATION = "REVOKED_BY_SEPARATION"


class SeparationCheckResult(str, Enum):
    PENDING = "PENDING"
    PASS = "PASS"
    FAIL_SALES_RELATIONSHIP = "FAIL_SALES_RELATIONSHIP"


class RelationshipType(str, Enum):
    SPONSORSHIP = "SPONSORSHIP"
    PAID_ADVISORY = "PAID_ADVISORY"
    SPEAKING_FEE = "SPEAKING_FEE"


class SalesRelationshipStatus(str, Enum):
    ACTIVE = "ACTIVE"
    TERMINATED = "TERMINATED"


class EventStatus(str, Enum):
    DRAFT = "DRAFT"
    PROGRAMMING = "PROGRAMMING"
    AGENDA_LOCKED = "AGENDA_LOCKED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class SessionKind(str, Enum):
    RESEARCH_SESSION = "RESEARCH_SESSION"
    SPONSOR_KEYNOTE = "SPONSOR_KEYNOTE"


class SponsorshipTier(str, Enum):
    PLATINUM = "PLATINUM"
    GOLD = "GOLD"
    SILVER = "SILVER"


class SponsorshipStatus(str, Enum):
    PENDING = "PENDING"
    ACTIVE = "ACTIVE"
    CANCELLED = "CANCELLED"


# ─── Entities ─────────────────────────────────────────

class ClientAccount(TypedDict):
    id: str
    legal_name: str
    industry: str
    region: str
    contract_status: str
    contract_start_utc: str
    contract_end_utc: str
    seat_count_contracted: int
    inquiry_allowance_total: int
    reprint_tier: str
    active_seat_count: int
    provisioned_seat_count: int
    revoked_seat_count: int
    consumed_inquiry_units: int
    reserved_inquiry_units: int
    remaining_reserved_units: int
    remaining_consumed_units: int
    utilization_score: float
    utilization_score_active_weighted: float
    renewal_posture: str
    renewal_decided_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Seat(TypedDict):
    id: str
    client_account_id: str
    seat_email: str
    research_role: str
    seat_kind: str
    status: str
    activated_at: Optional[str]
    revoked_at: Optional[str]
    entitlement_document_types: List[str]
    entitlement_override_types: List[str]
    last_inquiry_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Analyst(TypedDict):
    id: str
    full_name: str
    practice_area: str
    topic_routes: List[str]
    seniority: str
    status: str
    open_inquiry_count: int
    integrity_flag: str
    conflicted_vendor_ids: List[str]
    inquiries_completed_total: int
    created_at: str
    updated_at: str
    version: int


class InquiryRequest(TypedDict):
    id: str
    seat_id: str
    analyst_id: Optional[str]
    topic_route: str
    question_summary: str
    preparation_notes: str
    requested_start_utc: str
    duration_minutes: int
    scheduled_start_utc: Optional[str]
    status: str
    units_consumed: int
    note_delivered: bool
    note_reference: str
    routing_attempt_count: int
    declined_analyst_ids: List[str]
    settled_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ResearchDocument(TypedDict):
    id: str
    title: str
    doc_type: str
    practice_area: str
    lead_analyst_id: str
    editorial_status: str
    embargo_status: str
    embargo_days: int
    published_at: Optional[str]
    embargo_until: Optional[str]
    peer_reviewer_analyst_id: str
    peer_verdict: str
    peer_review_round: int
    fact_check_open_count: int
    included_vendor_count: int
    placement_locked: bool
    revision_count: int
    created_at: str
    updated_at: str
    version: int


class Vendor(TypedDict):
    id: str
    vendor_name: str
    hq_region: str
    employee_count_band: str
    status: str
    active_sales_relationship_count: int
    briefing_eligible: bool
    last_briefing_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class DimensionScore(TypedDict):
    dimension: str
    raw_score: float
    weight_pct: float


class VendorInclusion(TypedDict):
    id: str
    document_id: str
    vendor_id: str
    inclusion_status: str
    fact_check_status: str
    dimension_scores: List[DimensionScore]
    weighted_total_score: float
    inclusion_criteria_met_count: int
    criteria_evaluated_at: Optional[str]
    fact_check_round: int
    fact_check_due_utc: Optional[str]
    fact_check_requested_at: Optional[str]
    fact_check_response_at: Optional[str]
    fact_check_late: bool
    reprint_tier: str
    permitted_marketing_use: str
    reprint_copies_authorized: int
    reprint_copies_used: int
    reprint_fee_cents: int
    appeal_filed_at: Optional[str]
    appeal_grounds: str
    appeal_count: int
    appeal_window_closes_at: Optional[str]
    placement_locked: bool
    lead_analyst_conflicted: bool
    created_at: str
    updated_at: str
    version: int


class VendorBriefing(TypedDict):
    id: str
    vendor_id: str
    analyst_id: Optional[str]
    briefing_topic: str
    requested_start_utc: str
    duration_minutes: int
    status: str
    separation_check_result: str
    held_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class SalesRelationship(TypedDict):
    id: str
    analyst_id: str
    vendor_id: str
    relationship_type: str
    annual_value_cents: int
    status: str
    started_at: str
    terminated_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class SessionRow(TypedDict):
    session_title: str
    session_kind: str
    duration_minutes: int
    sponsor_vendor_id: Optional[str]


class ConferenceEvent(TypedDict):
    id: str
    event_name: str
    venue_region: str
    start_utc: str
    end_utc: str
    status: str
    research_session_minutes: int
    sponsor_session_minutes: int
    sponsor_minute_share: float
    sponsorship_revenue_cents: int
    agenda_locked_at: Optional[str]
    sessions: List[SessionRow]
    created_at: str
    updated_at: str
    version: int


class Sponsorship(TypedDict):
    id: str
    conference_event_id: str
    vendor_id: str
    tier: str
    amount_cents: int
    exclusivity_start_utc: str
    exclusivity_end_utc: str
    status: str
    activated_at: Optional[str]
    cancelled_at: Optional[str]
    sponsor_slot_counted: bool
    created_at: str
    updated_at: str
    version: int
