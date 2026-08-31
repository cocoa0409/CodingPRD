"""Domain types for the antitrust competition compliance service.

Status enumerations, role names and entity shapes exactly as the PRD names
them. Every one of the sixteen resource types carries the four common
properties (`id`, `created_at`, `updated_at`, `version`).
"""
from enum import Enum
from typing import List, Optional, TypedDict


# ─── Roles ────────────────────────────────────────────────────────────────

class UserRole(str, Enum):
    COMPLIANCE_ADMIN = "ComplianceAdmin"
    ANTITRUST_COUNSEL = "AntitrustCounsel"
    BUSINESS_LEAD = "BusinessLead"
    EMPLOYEE = "Employee"


# ─── Business unit ────────────────────────────────────────────────────────

class RiskBand(str, Enum):
    LOW = "LOW"
    MODERATE = "MODERATE"
    HIGH = "HIGH"
    SEVERE = "SEVERE"


class Posture(str, Enum):
    OPEN = "OPEN"
    RESTRICTED = "RESTRICTED"
    FROZEN = "FROZEN"


# ─── Employee ─────────────────────────────────────────────────────────────

class RoleCategory(str, Enum):
    SALES = "SALES"
    PRICING = "PRICING"
    LEGAL = "LEGAL"
    OTHER = "OTHER"


class ClearanceStatus(str, Enum):
    NONE = "NONE"
    GRANTED = "GRANTED"
    SUSPENDED = "SUSPENDED"
    REVOKED = "REVOKED"


class TrainingStatus(str, Enum):
    NONE = "NONE"
    CURRENT = "CURRENT"
    EXPIRED = "EXPIRED"


class TrainingAssignmentStatus(str, Enum):
    ASSIGNED = "ASSIGNED"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    EXPIRED = "EXPIRED"
    WAIVED = "WAIVED"


# ─── Trade association and participation ──────────────────────────────────

class ApprovalTier(str, Enum):
    TIER_1_LOW = "TIER_1_LOW"
    TIER_2_MEDIUM = "TIER_2_MEDIUM"
    TIER_3_HIGH = "TIER_3_HIGH"


class AssociationStatus(str, Enum):
    PROPOSED = "PROPOSED"
    APPROVED = "APPROVED"
    PROHIBITED = "PROHIBITED"


class ParticipationStatus(str, Enum):
    DRAFT = "DRAFT"
    APPROVAL_PENDING = "APPROVAL_PENDING"
    PARTIALLY_APPROVED = "PARTIALLY_APPROVED"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    UNDER_REVIEW = "UNDER_REVIEW"
    REJECTED = "REJECTED"
    TERMINATED = "TERMINATED"


class MeetingType(str, Enum):
    BOARD = "BOARD"
    COMMITTEE = "COMMITTEE"
    STANDARDS = "STANDARDS"
    SOCIAL = "SOCIAL"


class AttendanceStatus(str, Enum):
    PLANNED = "PLANNED"
    ATTENDED = "ATTENDED"
    MINUTES_SUBMITTED = "MINUTES_SUBMITTED"
    MINUTES_REVIEWED = "MINUTES_REVIEWED"
    FLAGGED = "FLAGGED"
    CANCELLED = "CANCELLED"


class MinutesVerdict(str, Enum):
    CLEAN = "CLEAN"
    CONCERN = "CONCERN"
    VIOLATION = "VIOLATION"


class MinutesFinding(str, Enum):
    PRICING_DISCUSSION = "PRICING_DISCUSSION"
    CAPACITY_DISCUSSION = "CAPACITY_DISCUSSION"
    CUSTOMER_ALLOCATION = "CUSTOMER_ALLOCATION"
    BID_COORDINATION = "BID_COORDINATION"
    MARKET_DATA_AGGREGATE = "MARKET_DATA_AGGREGATE"
    NONE = "NONE"


# ─── Competitor contact ───────────────────────────────────────────────────

class ContactChannel(str, Enum):
    IN_PERSON_UNSTRUCTURED = "IN_PERSON_UNSTRUCTURED"
    TRADE_SHOW = "TRADE_SHOW"
    PHONE = "PHONE"
    EMAIL = "EMAIL"
    WRITTEN_FORMAL = "WRITTEN_FORMAL"


class TopicTag(str, Enum):
    CAPACITY = "CAPACITY"
    BID = "BID"
    CUSTOMER_ALLOCATION = "CUSTOMER_ALLOCATION"
    TERRITORY = "TERRITORY"
    STANDARDS = "STANDARDS"
    BENCHMARKING = "BENCHMARKING"


class ContactStatus(str, Enum):
    LOGGED = "LOGGED"
    UNDER_REVIEW = "UNDER_REVIEW"
    REMEDIATION_REQUIRED = "REMEDIATION_REQUIRED"
    CLEARED = "CLEARED"
    ESCALATED = "ESCALATED"


# ─── Merger control ───────────────────────────────────────────────────────

class ExemptionCode(str, Enum):
    NONE = "NONE"
    ORDINARY_COURSE = "ORDINARY_COURSE"
    FOREIGN_ASSETS = "FOREIGN_ASSETS"
    INVESTMENT_ONLY = "INVESTMENT_ONLY"


class TransactionStatus(str, Enum):
    DRAFT = "DRAFT"
    ANALYZED = "ANALYZED"
    EXEMPT = "EXEMPT"
    FILED = "FILED"
    CLEARED = "CLEARED"


class ValuationVariant(str, Enum):
    SIGNED_DEAL = "SIGNED_DEAL"
    MARKET_VALUE = "MARKET_VALUE"


class Determination(str, Enum):
    EXEMPT = "EXEMPT"
    BELOW_THRESHOLD = "BELOW_THRESHOLD"
    SIZE_OF_PERSON_NOT_MET = "SIZE_OF_PERSON_NOT_MET"
    FILING_REQUIRED = "FILING_REQUIRED"


class AnalysisStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUPERSEDED = "SUPERSEDED"


# ─── Inspection readiness and document hygiene ────────────────────────────

class DrillType(str, Enum):
    DAWN_RAID = "DAWN_RAID"
    DOCUMENT_HOLD = "DOCUMENT_HOLD"
    INTERVIEW = "INTERVIEW"


class DrillStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    ABORTED = "ABORTED"


class DocumentAuditStatus(str, Enum):
    OPEN = "OPEN"
    COMPLETED = "COMPLETED"


# ─── Leniency ─────────────────────────────────────────────────────────────

class MarkerStatus(str, Enum):
    NONE = "NONE"
    MARKER_REQUESTED = "MARKER_REQUESTED"
    MARKER_GRANTED = "MARKER_GRANTED"
    MARKER_DENIED = "MARKER_DENIED"
    MARKER_EXPIRED = "MARKER_EXPIRED"
    PERFECTED = "PERFECTED"


class DisclosureStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"
    WITHDRAWN = "WITHDRAWN"


# ─── Risk assessment ──────────────────────────────────────────────────────

class AssessmentVariant(str, Enum):
    BASELINE = "BASELINE"
    INCIDENT_ADJUSTED = "INCIDENT_ADJUSTED"


class AssessmentStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUPERSEDED = "SUPERSEDED"


# ─── Entity shapes ────────────────────────────────────────────────────────

class BusinessUnit(TypedDict):
    id: str
    name: str
    market_code: str
    market_share_bps: int
    interaction_point_count: int
    competitor_overlap_pct: float
    exposure_budget_points: float
    review_minutes_budget: int
    exposure_points: float
    manual_exposure_adjustment_points: float
    review_minutes_consumed: int
    risk_band: str
    posture: str
    document_violation_count: int
    created_at: str
    updated_at: str
    version: int


class EmployeeProfile(TypedDict):
    id: str
    business_unit_id: str
    full_name: str
    email: str
    role_category: str
    clearance_status: str
    training_status: str
    training_expires_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class TrainingCurriculum(TypedDict):
    id: str
    code: str
    title: str
    target_role_categories: List[str]
    duration_minutes: int
    validity_days: int
    is_mandatory: bool
    created_at: str
    updated_at: str
    version: int


class TrainingAssignment(TypedDict):
    id: str
    employee_id: str
    curriculum_id: str
    due_at: str
    status: str
    started_at: Optional[str]
    completed_at: Optional[str]
    expires_at: Optional[str]
    score: Optional[int]
    waiver_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class TradeAssociation(TypedDict):
    id: str
    name: str
    approval_tier: str
    competitor_density_pct: float
    status: str
    created_at: str
    updated_at: str
    version: int


class AssociationParticipation(TypedDict):
    id: str
    business_unit_id: str
    association_id: str
    employee_id: str
    purpose: str
    status: str
    legal_cleared: bool
    business_justified: bool
    legal_cleared_by_user_id: Optional[str]
    business_justification: Optional[str]
    review_load_minutes: int
    review_minutes_reserved: int
    created_at: str
    updated_at: str
    version: int


class AssociationMeeting(TypedDict):
    id: str
    association_id: str
    meeting_type: str
    scheduled_start: str
    scheduled_end: str
    agenda_received: bool
    created_at: str
    updated_at: str
    version: int


class MeetingAttendance(TypedDict):
    id: str
    meeting_id: str
    participation_id: str
    status: str
    occupied_start: str
    occupied_end: str
    minutes_summary: Optional[str]
    topics_discussed: Optional[List[str]]
    minutes_verdict: Optional[str]
    minutes_findings: Optional[List[str]]
    minutes_reviewed_by_user_id: Optional[str]
    exposure_points_assessed: float
    cancellation_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class CompetitorContact(TypedDict):
    id: str
    business_unit_id: str
    employee_id: str
    competitor_name: str
    contact_channel: str
    topic_tags: List[str]
    pricing_topic: bool
    occurred_at: str
    status: str
    exposure_points_charged: float
    band_multiplier_applied: float
    review_opened_by_user_id: Optional[str]
    remediation_instructions: Optional[str]
    remediation_response: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Transaction(TypedDict):
    id: str
    business_unit_id: str
    target_name: str
    deal_value_cents: int
    assumed_liabilities_cents: int
    market_valuation_cents: int
    acquirer_total_assets_cents: int
    target_total_assets_cents: int
    exemption_code: str
    signed_at: str
    status: str
    filed_at: Optional[str]
    waiting_period_end: Optional[str]
    created_at: str
    updated_at: str
    version: int


class HsrAnalysis(TypedDict):
    id: str
    transaction_id: str
    valuation_variant: str
    size_of_transaction_cents: int
    filing_required: bool
    determination: str
    status: str
    analyzed_by_user_id: str
    created_at: str
    updated_at: str
    version: int


class Site(TypedDict):
    id: str
    name: str
    country_code: str
    concurrent_drill_capacity: int
    readiness_score: float
    created_at: str
    updated_at: str
    version: int


class ReadinessDrill(TypedDict):
    id: str
    site_id: str
    drill_type: str
    window_start: str
    window_end: str
    status: str
    score: Optional[int]
    gaps_found: Optional[int]
    abort_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class DocumentAudit(TypedDict):
    id: str
    business_unit_id: str
    sample_size: int
    scope_note: str
    status: str
    violation_count: Optional[int]
    high_risk_phrase_count: Optional[int]
    guideline_score: Optional[float]
    created_at: str
    updated_at: str
    version: int


class LeniencyApplication(TypedDict):
    id: str
    business_unit_id: str
    source_contact_id: Optional[str]
    cartel_code: str
    affected_years: List[dict]
    gravity_pct: Optional[float]
    marker_status: str
    disclosure_status: str
    marker_requested_at: Optional[str]
    marker_granted_at: Optional[str]
    priority_rank: Optional[int]
    estimated_penalty_cents: Optional[int]
    withdrawal_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class RiskAssessment(TypedDict):
    id: str
    business_unit_id: str
    variant: str
    share_component: float
    interaction_component: float
    overlap_component: float
    incident_load: float
    escalated_contact_count: int
    flagged_attendance_count: int
    document_violation_count: int
    market_risk_index: float
    risk_band: str
    status: str
    created_at: str
    updated_at: str
    version: int
