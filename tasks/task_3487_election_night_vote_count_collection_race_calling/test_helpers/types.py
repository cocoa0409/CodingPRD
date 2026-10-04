"""Domain types: entity TypedDicts, status enums, role enum.

Field sets follow the PRD's resource model: events, counties, contests,
stringers, assignments, vote reports, race calls, recount cases, coverage
decisions, and media customers carry id + created_at + updated_at + version;
county links, candidates, feed sources, result deliveries, and media invoices
carry only id + created_at.
"""
from enum import Enum
from typing import TypedDict, Optional, List


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class UserRole(str, Enum):
    ELECTION_OPS_ADMIN = "ElectionOpsAdmin"
    COVERAGE_PLANNER = "CoveragePlanner"
    STRINGER_COORDINATOR = "StringerCoordinator"
    STRINGER = "Stringer"
    FEED_OPERATOR = "FeedOperator"
    TABULATION_CLERK = "TabulationClerk"
    DECISION_ANALYST = "DecisionAnalyst"
    DECISION_DESK_CHIEF = "DecisionDeskChief"
    RECOUNT_OFFICER = "RecountOfficer"
    MEDIA_CUSTOMER = "MediaCustomer"


class EventType(str, Enum):
    GENERAL = "GENERAL"
    PRIMARY = "PRIMARY"
    SPECIAL = "SPECIAL"
    RUNOFF = "RUNOFF"


class EventPosture(str, Enum):
    SETUP = "SETUP"
    CANDIDATES_LOCKED = "CANDIDATES_LOCKED"
    LIVE = "LIVE"
    TABULATION = "TABULATION"
    CERTIFICATION = "CERTIFICATION"
    ARCHIVED = "ARCHIVED"


class StringerSelectionMode(str, Enum):
    CAREER = "CAREER"
    RECENT_FORM = "RECENT_FORM"


class CountyStatus(str, Enum):
    PENDING = "PENDING"
    REPORTING = "REPORTING"
    COMPLETE = "COMPLETE"


class ContestType(str, Enum):
    FEDERAL_EXEC = "FEDERAL_EXEC"
    FEDERAL_SENATE = "FEDERAL_SENATE"
    FEDERAL_HOUSE = "FEDERAL_HOUSE"
    STATE = "STATE"
    BALLOT_MEASURE = "BALLOT_MEASURE"


class TabulationStatus(str, Enum):
    AWAITING = "AWAITING"
    REPORTING = "REPORTING"
    COMPLETE = "COMPLETE"


class CallStatus(str, Enum):
    UNCALLED = "UNCALLED"
    CALLED = "CALLED"


class Party(str, Enum):
    DEM = "DEM"
    REP = "REP"
    IND = "IND"
    LIB = "LIB"
    GRN = "GRN"
    OTHER = "OTHER"


class PriorityTier(str, Enum):
    PRIMARY = "PRIMARY"
    SECONDARY = "SECONDARY"


class AssignmentStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    ACTIVE = "ACTIVE"
    RELEASED = "RELEASED"
    NO_SHOW = "NO_SHOW"


class ReportSource(str, Enum):
    STRINGER = "STRINGER"
    FEED = "FEED"


class VoteReportStatus(str, Enum):
    RECEIVED = "RECEIVED"
    FLAGGED = "FLAGGED"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"
    VOIDED = "VOIDED"


class ReviewDecision(str, Enum):
    ACCEPT = "ACCEPT"
    REJECT = "REJECT"
    VOID = "VOID"


class RaceCallStatus(str, Enum):
    PROPOSED = "PROPOSED"
    PUBLISHED = "PUBLISHED"
    RETRACTED = "RETRACTED"


class CallAction(str, Enum):
    PUBLISH = "PUBLISH"
    RETRACT = "RETRACT"


class RecountCaseStatus(str, Enum):
    FILED = "FILED"
    ACTIVE = "ACTIVE"
    DISMISSED = "DISMISSED"
    RESOLVED_CONFIRMED = "RESOLVED_CONFIRMED"
    RESOLVED_OVERTURNED = "RESOLVED_OVERTURNED"


class RecountAction(str, Enum):
    ACTIVATE = "ACTIVATE"
    DISMISS = "DISMISS"
    RESOLVE = "RESOLVE"


class RecountOutcome(str, Enum):
    CONFIRMED = "CONFIRMED"
    OVERTURNED = "OVERTURNED"


class CoverageDecisionStatus(str, Enum):
    PROPOSED = "PROPOSED"
    APPROVED = "APPROVED"
    DECLINED = "DECLINED"
    FUNDED = "FUNDED"


class CoverageReview(str, Enum):
    APPROVE = "APPROVE"
    DECLINE = "DECLINE"
    FUND = "FUND"


class AssignmentAction(str, Enum):
    RELEASE = "RELEASE"
    NO_SHOW = "NO_SHOW"
    REDEPLOY = "REDEPLOY"


class LicenseTier(str, Enum):
    BASIC = "BASIC"
    STANDARD = "STANDARD"
    PREMIUM = "PREMIUM"


class ContentType(str, Enum):
    VOTE_UPDATE = "VOTE_UPDATE"
    CALL = "CALL"
    CALL_CREDIT = "CALL_CREDIT"


class DeliveryStatus(str, Enum):
    SENT = "SENT"
    STALE = "STALE"


# ---------------------------------------------------------------------------
# Entity TypedDicts
# ---------------------------------------------------------------------------
# Carries id + created_at + updated_at + version (ten entity types).

class ElectionEvent(TypedDict, total=False):
    id: str
    event_name: str
    event_date: str
    event_type: str
    total_stringer_hour_budget: int
    stringer_selection_mode: str
    posture: str
    created_at: str
    updated_at: str
    version: int


class County(TypedDict, total=False):
    id: str
    event_id: str
    county_fips: str
    county_name: str
    state_code: str
    expected_precincts: int
    expected_vote_total: int
    survey_turnout_estimate: Optional[int]
    historical_dem_share: Optional[float]
    reported_precincts: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Contest(TypedDict, total=False):
    id: str
    event_id: str
    office_name: str
    state_code: str
    contest_type: str
    seats: int
    tabulation_status: str
    call_status: str
    called_candidate_id: Optional[str]
    reported_precincts: int
    total_votes: int
    margin_pct: float
    outstanding_estimate: int
    created_at: str
    updated_at: str
    version: int


class Stringer(TypedDict, total=False):
    id: str
    stringer_name: str
    home_state: str
    no_show_count: int
    accepted_report_count: int
    voided_report_count: int
    reliability_career: int
    reliability_recent_form: int
    created_at: str
    updated_at: str
    version: int


class StringerAssignment(TypedDict, total=False):
    id: str
    event_id: str
    county_id: str
    stringer_id: Optional[str]
    window_start: str
    window_end: str
    status: str
    auto_selected: bool
    created_at: str
    updated_at: str
    version: int


class CandidateVote(TypedDict):
    candidate_id: str
    votes: int


class VoteReport(TypedDict, total=False):
    id: str
    contest_id: str
    county_id: str
    source: str
    submitted_by_stringer_id: Optional[str]
    precincts_reporting: int
    candidate_votes: List[CandidateVote]
    reported_total: int
    deviation_ratio: float
    swing_deviation: Optional[float]
    status: str
    accepted_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class RaceCall(TypedDict, total=False):
    id: str
    contest_id: str
    winner_candidate_id: str
    proposed_by: str
    published_by: Optional[str]
    status: str
    published_at: Optional[str]
    retract_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class RecountCase(TypedDict, total=False):
    id: str
    contest_id: str
    status: str
    filed_margin_pct: float
    resolution_note: Optional[str]
    created_at: str
    updated_at: str
    version: int


class CoverageDecision(TypedDict, total=False):
    id: str
    event_id: str
    contest_id: str
    allocated_stringer_hours: int
    coverage_start: str
    coverage_end: str
    rationale: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class MediaCustomer(TypedDict, total=False):
    id: str
    customer_name: str
    license_tier: str
    licensed_states: List[str]
    created_at: str
    updated_at: str
    version: int


# ---------------------------------------------------------------------------
# Append-only entities: id + created_at only (no updated_at, no version).
# ---------------------------------------------------------------------------

class ContestCounty(TypedDict, total=False):
    id: str
    contest_id: str
    county_id: str
    created_at: str


class Candidate(TypedDict, total=False):
    id: str
    contest_id: str
    candidate_name: str
    party: str
    is_incumbent: bool
    created_at: str


class FeedSource(TypedDict, total=False):
    id: str
    event_id: str
    feed_name: str
    state_codes: List[str]
    priority_tier: str
    created_at: str


class ResultDelivery(TypedDict, total=False):
    id: str
    customer_id: str
    contest_id: str
    content_type: str
    fee_cents: int
    status: str
    delivered_at: str
    created_at: str


class MediaInvoice(TypedDict, total=False):
    id: str
    customer_id: str
    period: str
    delivery_count: int
    total_fee_cents: int
    created_at: str


# ---------------------------------------------------------------------------
# Tabulation board read shape (GET /contests/{id}/tabulation)
# ---------------------------------------------------------------------------

class OutstandingDetail(TypedDict, total=False):
    # PRD §3.5 pins "the per-county `outstanding_detail`" but never the entry
    # key names for the historical/survey/outstanding figures — only the
    # county identity is safe to assume.
    county_id: str


class CandidateTotal(TypedDict, total=False):
    candidate_id: str
    candidate_name: str
    party: str
    votes: int
    rank: int


class TabulationBoard(TypedDict, total=False):
    contest_id: str
    tabulation_status: str
    call_status: str
    reported_precincts: int
    expected_precincts_total: int
    candidate_totals: List[dict]
    total_votes: int
    margin_pct: float
    outstanding_estimate: int
    outstanding_detail: List[dict]
