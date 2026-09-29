"""Domain types for the Government Affairs & Political Committee Administration API.

Status enums, role enum and entity shapes as described in the PRD.
"""
from enum import Enum
from typing import List, Optional, TypedDict


class UserRole(str, Enum):
    ASSOCIATION_ADMIN = "AssociationAdmin"
    GOV_AFFAIRS_DIRECTOR = "GovAffairsDirector"
    COMPLIANCE_OFFICER = "ComplianceOfficer"
    BOARD_TRUSTEE = "BoardTrustee"
    MEMBER_DELEGATE = "MemberDelegate"


class JurisdictionCode(str, Enum):
    FEDERAL = "FEDERAL"
    STATE_CA = "STATE_CA"
    STATE_NY = "STATE_NY"


class CommitteeScope(str, Enum):
    FEDERAL = "FEDERAL"
    STATE_CA = "STATE_CA"
    STATE_NY = "STATE_NY"
    MULTI = "MULTI"


class ReportingCadence(str, Enum):
    QUARTERLY = "QUARTERLY"
    SEMIANNUAL = "SEMIANNUAL"


class NoticeMethod(str, Enum):
    RATIO = "RATIO"
    FLAT_FLOOR = "FLAT_FLOOR"


class MembershipTier(str, Enum):
    ASSOCIATE = "ASSOCIATE"
    FULL = "FULL"
    PREMIER = "PREMIER"


class MemberStatus(str, Enum):
    ACTIVE = "ACTIVE"
    LAPSED = "LAPSED"
    SUSPENDED = "SUSPENDED"


class SeatRole(str, Enum):
    CHAIR = "CHAIR"
    MEMBER = "MEMBER"


class SeatStatus(str, Enum):
    ACTIVE = "ACTIVE"
    DAMPENED = "DAMPENED"


class RosterState(str, Enum):
    FORMING = "FORMING"
    IMPAIRED = "IMPAIRED"
    QUORATE = "QUORATE"


class PositionStatus(str, Enum):
    DRAFT = "DRAFT"
    BALLOTING = "BALLOTING"
    CONSENSUS_REACHED = "CONSENSUS_REACHED"
    RECONSIDERATION = "RECONSIDERATION"
    FAILED_CONSENSUS = "FAILED_CONSENSUS"
    ADOPTED = "ADOPTED"


class TallyOutcome(str, Enum):
    NONE = "NONE"
    NO_QUORUM = "NO_QUORUM"
    CONSENSUS = "CONSENSUS"
    DISSENSUS = "DISSENSUS"


class BallotChoice(str, Enum):
    SUPPORT = "SUPPORT"
    OPPOSE = "OPPOSE"
    ABSTAIN = "ABSTAIN"


class BallotStatus(str, Enum):
    CAST = "CAST"
    SUPERSEDED = "SUPERSEDED"


class DissentStatus(str, Enum):
    NONE = "NONE"
    FILED = "FILED"
    WITHDRAWN = "WITHDRAWN"
    RECORDED = "RECORDED"


class RegistrationStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    AMENDMENT_PENDING = "AMENDMENT_PENDING"
    TERMINATED = "TERMINATED"


class ActivityKind(str, Enum):
    DIRECT_LOBBYING = "DIRECT_LOBBYING"
    COALITION_CONTRIBUTION = "COALITION_CONTRIBUTION"
    THIRD_PARTY_ADVOCACY = "THIRD_PARTY_ADVOCACY"
    GRASSROOTS_SUPPORT = "GRASSROOTS_SUPPORT"


class ActivityStatus(str, Enum):
    LOGGED = "LOGGED"
    VOIDED = "VOIDED"


class ReportStatus(str, Enum):
    OPEN = "OPEN"
    CERTIFIED = "CERTIFIED"
    SUPERSEDED = "SUPERSEDED"


class ReportBasis(str, Enum):
    METHOD_A = "METHOD_A"
    METHOD_B = "METHOD_B"


class CampaignStatus(str, Enum):
    PLANNED = "PLANNED"
    LIVE = "LIVE"
    CLOSED = "CLOSED"


class AlertStatus(str, Enum):
    DISPATCHED = "DISPATCHED"
    NO_MATCH = "NO_MATCH"


class Chamber(str, Enum):
    US_HOUSE = "US_HOUSE"
    US_SENATE = "US_SENATE"
    STATE_ASSEMBLY = "STATE_ASSEMBLY"


class PriorApprovalStatus(str, Enum):
    REQUESTED = "REQUESTED"
    GRANTED = "GRANTED"
    REVOKED = "REVOKED"
    EXPIRED = "EXPIRED"


class FundPosture(str, Enum):
    OPEN = "OPEN"
    RESTRICTED = "RESTRICTED"


class Incumbency(str, Enum):
    INCUMBENT = "INCUMBENT"
    CHALLENGER = "CHALLENGER"
    OPEN_SEAT = "OPEN_SEAT"


class ContributionStatus(str, Enum):
    PENDING_BOARD = "PENDING_BOARD"
    SUSPENDED = "SUSPENDED"
    BOARD_APPROVED = "BOARD_APPROVED"
    DISBURSED = "DISBURSED"
    VOIDED = "VOIDED"


class Member(TypedDict):
    id: str
    legal_name: str
    membership_tier: str
    home_jurisdiction_code: str
    home_district_code: str
    notice_method: str
    annual_dues_cents: int
    dues_year: int
    restricted_class_size: int
    status: str
    advocacy_optout: bool
    engagement_score: int
    recorded_dissent_count: int
    pac_solicitable: bool
    created_at: str
    updated_at: str
    version: int


class PolicyCommittee(TypedDict):
    id: str
    name: str
    jurisdiction_scope: str
    quorum_threshold_pct: float
    consensus_threshold_pct: float
    seat_count: int
    total_voting_weight: int
    roster_state: str
    created_at: str
    updated_at: str
    version: int


class CommitteeSeat(TypedDict):
    id: str
    committee_id: str
    member_id: str
    seat_role: str
    voting_weight: int
    dissent_strikes: int
    status: str
    created_at: str
    updated_at: str
    version: int


class PolicyPosition(TypedDict):
    id: str
    committee_id: str
    title: str
    jurisdiction_code: str
    summary: str
    status: str
    round_number: int
    ballot_deadline_date: Optional[str]
    support_weight: int
    oppose_weight: int
    abstain_weight: int
    quorum_pct: float
    consensus_pct: float
    last_tally_outcome: str
    dissent_register_count: int
    adopted_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class PositionVote(TypedDict):
    id: str
    position_id: str
    member_id: str
    round_number: int
    ballot: str
    weight_snapshot: int
    ballot_status: str
    dissent_status: str
    dissent_statement: Optional[str]
    created_at: str
    updated_at: str
    version: int


class LobbyingRegistration(TypedDict):
    id: str
    jurisdiction_code: str
    registrant_name: str
    coverage_start_date: str
    coverage_end_date: str
    status: str
    amendment_round: int
    filed_at: Optional[str]
    terminated_at: Optional[str]
    ytd_reportable_cents: int
    ytd_reportable_hours: float
    created_at: str
    updated_at: str
    version: int


class LobbyingActivity(TypedDict):
    id: str
    registration_id: str
    position_id: str
    activity_kind: str
    activity_date: str
    hours: float
    expenditure_cents: int
    coalition_partner_name: Optional[str]
    staff_cost_cents: int
    third_party_disclosure_required: bool
    status: str
    void_reason: Optional[str]
    logged_at: str
    created_at: str
    updated_at: str
    version: int


class ExpenditureReport(TypedDict):
    id: str
    registration_id: str
    period_code: str
    period_start_date: str
    period_end_date: str
    due_date: str
    basis: str
    method_a_total_cents: int
    method_b_total_cents: int
    filed_total_cents: int
    included_activity_count: int
    status: str
    created_by_user_id: str
    certified_by_user_id: Optional[str]
    certified_at: Optional[str]
    late: bool
    created_at: str
    updated_at: str
    version: int


class GrassrootsCampaign(TypedDict):
    id: str
    position_id: str
    name: str
    target_jurisdiction_code: str
    status: str
    alert_count: int
    matched_member_total: int
    unmatched_alert_count: int
    cumulative_cost_cents: int
    disclosure_required: bool
    last_alert_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ActionAlert(TypedDict):
    """An alert is an immutable dispatch record: it carries only id and created_at."""
    id: str
    campaign_id: str
    target_district_code: str
    target_chamber: str
    message_subject: str
    unit_cost_cents: int
    matched_member_ids: List[str]
    matched_member_count: int
    cost_cents: int
    status: str
    dispatched_at: str
    created_at: str


class PriorApproval(TypedDict):
    id: str
    member_id: str
    calendar_year: int
    solicitable_class_size: int
    effective_date: str
    expires_at_date: str
    status: str
    authorized_by_name: Optional[str]
    granted_at: Optional[str]
    granted_by_user_id: Optional[str]
    revoked_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Candidate(TypedDict):
    id: str
    name: str
    office: str
    jurisdiction_code: str
    district_code: str
    election_cycle: str
    incumbency: str
    voting_alignment_pct: float
    committee_relevance_score: int
    latest_support_score: float
    pending_support_cents: int
    committed_support_cents: int
    disbursed_support_cents: int
    created_at: str
    updated_at: str
    version: int


class SegregatedFund(TypedDict):
    id: str
    name: str
    fund_year: int
    jurisdiction_code: str
    min_reserve_cents: int
    receipts_total_cents: int
    committed_balance_cents: int
    disbursed_total_cents: int
    filing_fee_accrued_cents: int
    available_balance_cents: int
    filings_completed_count: int
    last_filed_period_code: Optional[str]
    posture: str
    created_at: str
    updated_at: str
    version: int


class PacContribution(TypedDict):
    id: str
    fund_id: str
    candidate_id: str
    amount_cents: int
    memo: Optional[str]
    support_score: float
    max_allowed_cents: int
    status: str
    proposed_by_user_id: str
    board_approved_by_user_id: Optional[str]
    disbursed_at: Optional[str]
    voided_at: Optional[str]
    void_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class DeductibilityNotice(TypedDict):
    """Computed read, returned inline rather than stored."""
    member_id: str
    dues_year: int
    notice_method: str
    ratio_pct: float
    nondeductible_pct: float
    nondeductible_amount_cents: int
    deductible_amount_cents: int
    lobbying_spend_cents: int
