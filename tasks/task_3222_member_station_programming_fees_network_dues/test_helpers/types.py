"""Domain types: entity TypedDicts, status enums, role enum.

Entities declared with full common fields carry ``id``, ``created_at``,
``updated_at`` and ``version``. The three deliberately lighter entities
(``ProgrammingFeeSchedule``, ``AudienceReport`` and
``DuesVoteEligibilityProjection``) carry only ``id`` and ``created_at``.
"""
from enum import Enum
from typing import TypedDict, Optional, List


class EligibilityStatus(str, Enum):
    APPLICANT = "APPLICANT"
    UNDER_REVIEW = "UNDER_REVIEW"
    DEFICIENT = "DEFICIENT"
    REMEDIATION_SUBMITTED = "REMEDIATION_SUBMITTED"
    ELIGIBLE = "ELIGIBLE"
    PROBATION = "PROBATION"
    SUSPENDED = "SUSPENDED"
    WITHDRAWN = "WITHDRAWN"


class MembershipClass(str, Enum):
    CLASS_A = "CLASS_A"
    CLASS_B = "CLASS_B"
    CLASS_C = "CLASS_C"
    CLASS_D = "CLASS_D"


class BoardRegion(str, Enum):
    REGION_NORTHEAST = "REGION_NORTHEAST"
    REGION_SOUTH = "REGION_SOUTH"
    REGION_MIDWEST = "REGION_MIDWEST"
    REGION_WEST = "REGION_WEST"


class CarriageAgreementStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    UNDER_REVIEW = "UNDER_REVIEW"
    CLEARED = "CLEARED"
    CARRIED = "CARRIED"
    ACTIVE = "ACTIVE"
    EMBARGOED = "EMBARGOED"
    EXPIRED = "EXPIRED"
    TERMINATED = "TERMINATED"


class BroadcastWindowStatus(str, Enum):
    DRAFT = "DRAFT"
    PENDING_CLEARANCE = "PENDING_CLEARANCE"
    CLEARED = "CLEARED"
    REJECTED = "REJECTED"
    SCHEDULED = "SCHEDULED"
    BROADCAST = "BROADCAST"
    MISSED = "MISSED"
    VIOLATED = "VIOLATED"


class FeedStatus(str, Enum):
    PLANNED = "PLANNED"
    ONLINE = "ONLINE"
    CROWDED = "CROWDED"
    MAINTENANCE = "MAINTENANCE"
    OFFLINE = "OFFLINE"
    SUSPENDED = "SUSPENDED"


class UplinkSlotStatus(str, Enum):
    RESERVED = "RESERVED"
    SCHEDULED = "SCHEDULED"
    PREEMPTED = "PREEMPTED"
    CANCELLED = "CANCELLED"
    RELEASED = "RELEASED"
    AIRED = "AIRED"


class UnderwritingAgreementStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    COMPLIANCE_REVIEW = "COMPLIANCE_REVIEW"
    APPROVED = "APPROVED"
    SCHEDULED = "SCHEDULED"
    AIRING = "AIRING"
    AIRING_COMPLETE = "AIRING_COMPLETE"
    REJECTED = "REJECTED"
    NO_AIRED = "NO_AIRED"


class AirplayStatus(str, Enum):
    NOT_SCHEDULED = "NOT_SCHEDULED"
    SLOTTED = "SLOTTED"
    PARTIALLY_AIRED = "PARTIALLY_AIRED"
    FULLY_AIRED = "FULLY_AIRED"
    AIRING_BLOCKED = "AIRING_BLOCKED"


class ContributionStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    SHORTLISTED = "SHORTLISTED"
    LICENSED = "LICENSED"
    USED = "USED"
    WITHDRAWN = "WITHDRAWN"
    REJECTED = "REJECTED"


class DriveStatus(str, Enum):
    PLANNED = "PLANNED"
    ACTIVE = "ACTIVE"
    CLOSED = "CLOSED"
    REPORTED = "REPORTED"
    SETTLED = "SETTLED"
    CANCELLED = "CANCELLED"


class ProgramStatus(str, Enum):
    DEVELOPMENT = "DEVELOPMENT"
    PRODUCTION = "PRODUCTION"
    SCHEDULED = "SCHEDULED"
    RUNNING = "RUNNING"
    PUBLISHED = "PUBLISHED"
    RESCHEDULED = "RESCHEDULED"
    RETIRED = "RETIRED"


class ProposalStatus(str, Enum):
    DRAFT = "DRAFT"
    OPEN = "OPEN"
    PASSED = "PASSED"
    ENACTED = "ENACTED"
    REJECTED = "REJECTED"
    TABLED = "TABLED"
    ENACTMENT_CLOSED = "ENACTMENT_CLOSED"


class VoteStatus(str, Enum):
    RECORDED = "RECORDED"
    SUPERSEDED = "SUPERSEDED"
    INVALIDATED = "INVALIDATED"


class ElectionStatus(str, Enum):
    OPEN = "OPEN"
    CLOSED = "CLOSED"
    CERTIFIED = "CERTIFIED"
    CONTESTED = "CONTESTED"
    REOPENED = "REOPENED"
    FINALIZED = "FINALIZED"


class CandidateStatus(str, Enum):
    FILED = "FILED"
    QUALIFIED = "QUALIFIED"
    ELECTED = "ELECTED"
    DEFEATED = "DEFEATED"
    LAPSED = "LAPSED"
    WITHDRAWN = "WITHDRAWN"


class SeatStatus(str, Enum):
    VACANT = "VACANT"
    CONTESTED = "CONTESTED"
    HOLDOVER = "HOLDOVER"
    FILLED = "FILLED"
    RECALLED = "RECALLED"


class AssessmentStatus(str, Enum):
    INITIAL = "INITIAL"
    FINALIZED = "FINALIZED"
    SUPERSEDED = "SUPERSEDED"


class UserRole(str, Enum):
    PLATFORM_ADMIN = "PlatformAdmin"
    STATION_MANAGER = "StationManager"
    NETWORK_COMPLIANCE_AUDITOR = "NetworkComplianceAuditor"
    NETWORK_SCHEDULER = "NetworkScheduler"
    NATIONAL_PROGRAM_EDITOR = "NationalProgramEditor"
    UNDERWRITING_COORDINATOR = "UnderwritingCoordinator"
    NETWORK_GOVERNANCE_OFFICER = "NetworkGovernanceOfficer"


# common_fields: true — carries id + created_at + updated_at + version
class MemberStation(TypedDict):
    id: str
    call_sign: str
    licensee_name: str
    state_code: str
    dma_market_rank: int
    dma_households: int
    coverage_population: int
    full_time_staff_count: int
    newsroom_staff_count: int
    annual_local_revenue_cents: int
    board_seat_region: str
    operations_score: float
    membership_class: str
    eligibility_status: str
    dues_arrears_cents: int
    contribution_credit_cents: int
    applied_relief_cents: int
    dues_vote_eligible: bool
    eligible_from: Optional[str]
    last_review_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


# common_fields: false — carries ONLY id + created_at
class ProgrammingFeeSchedule(TypedDict):
    id: str
    schedule_code: str
    fiscal_year: int
    base_fee_cents: int
    revenue_rate_bps: int
    market_tier_1_max_rank: int
    market_tier_2_max_rank: int
    market_tier_3_max_rank: int
    market_size_multiplier_bps: int
    minimum_fee_cents: int
    maximum_fee_cents: int
    annual_adjustment_bps: int
    rounding_mode: str
    effective_from: str
    effective_to: str
    created_at: str


class CarriageAgreement(TypedDict):
    id: str
    program_code: str
    obligation_type: str
    agreement_status: str
    clearance_deadline: str
    exception_liability_cap_cents: int
    exception_liability_cents: int
    clearance_ratio_bps: int
    published_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class BroadcastWindow(TypedDict):
    id: str
    parent_agreement_id: str
    station_id: str
    program_code: str
    window_start: str
    window_end: str
    embargo_until: Optional[str]
    clearance_status: str
    is_cleared: bool
    carriage_exception_liability_cents: int
    rejection_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class DistributionFeed(TypedDict):
    id: str
    feed_code: str
    feed_type: str
    total_capacity_units: int
    # PRD §2.5: a ratio is transmitted as whole basis points (10000 == one
    # whole unit), never as a decimal fraction.
    max_reserved_capacity_ratio: int
    reserved_capacity_units: int
    crowded: bool
    feed_status: str
    created_at: str
    updated_at: str
    version: int


class UplinkSlot(TypedDict):
    id: str
    parent_feed_id: str
    station_id: str
    window_id: str
    slot_start: str
    slot_end: str
    slot_status: str
    priority_rank: int
    created_at: str
    updated_at: str
    version: int


class UnderwritingAgreement(TypedDict):
    id: str
    sponsor_name: str
    station_id: str
    program_code: str
    ack_script_text: str
    consideration_cents: int
    agreement_status: str
    airplay_status: str
    compliance_segment_count: int
    aired_segment_count: int
    disclosure_test_passed: bool
    created_at: str
    updated_at: str
    version: int


class ContentContribution(TypedDict):
    id: str
    station_id: str
    program_id: str
    headline: str
    duration_seconds: int
    contribution_status: str
    last_request_at: Optional[str]
    revision_count: int
    compensation_credit_cents: int
    created_at: str
    updated_at: str
    version: int


class MembershipDrive(TypedDict):
    id: str
    station_id: str
    drive_name: str
    drive_status: str
    pledged_cents: int
    collected_cents: int
    collection_ratio_bps: int
    drive_close_at: str
    drive_deduction_cents: int
    created_at: str
    updated_at: str
    version: int


# common_fields: false — carries ONLY id + created_at
class AudienceReport(TypedDict):
    id: str
    station_id: str
    fiscal_year: int
    cume_persons: int
    nielsen_share_bps: int
    local_content_hours: int
    reported_at: str
    created_at: str


class NationalProgram(TypedDict):
    id: str
    program_code: str
    program_title: str
    strand_type: str
    production_status: str
    clearance_required: bool
    national_premiere_at: str
    publication_cycle: int
    licensed_contribution_count: int
    preliminary_license_credit_cents: int
    created_at: str
    updated_at: str
    version: int


class BoardElection(TypedDict):
    id: str
    board_region: str
    fiscal_year: int
    election_status: str
    cycle_number: int
    seats_available: int
    certification_deadline: str
    created_at: str
    updated_at: str
    version: int


class BoardCandidate(TypedDict):
    id: str
    parent_election_id: str
    station_id: str
    candidate_status: str
    votes_recorded: int
    last_candidacy_cycle: Optional[str]
    nomination_statement: str
    created_at: str
    updated_at: str
    version: int


class BoardSeat(TypedDict):
    id: str
    board_region: str
    station_id: Optional[str]
    seat_status: str
    term_start: Optional[str]
    term_end: str
    board_rank: int
    carried_credit_cents: int
    contribution_deduction_cents: int
    created_at: str
    updated_at: str
    version: int


class DuesStructureProposal(TypedDict):
    id: str
    fiscal_year: int
    proposal_status: str
    current_rate_bps: int
    proposed_base_fee_cents: int
    proposed_revenue_rate_bps: int
    quorum_required_votes: int
    eligible_station_count: int
    yes_votes: int
    no_votes: int
    votes_cast_count: int
    proposal_cycle: int
    effective_from: str
    created_at: str
    updated_at: str
    version: int


class StationVote(TypedDict):
    id: str
    parent_proposal_id: str
    station_id: str
    vote_choice: str
    current_rate_bps: int
    recorded_weight: int
    cast_at: str
    vote_status: str
    superseded_by_vote_id: Optional[str]
    compensated_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ProgrammingFeeAssessment(TypedDict):
    id: str
    station_id: str
    schedule_id: str
    fiscal_year: int
    assessment_status: str
    provisional_fee_cents: int
    final_fee_cents: int
    drive_deduction_cents: int
    allocated_dues_cents: int
    total_pot_cents: int
    created_at: str
    updated_at: str
    version: int


# common_fields: false — carries ONLY id + created_at
class DuesVoteEligibilityProjection(TypedDict):
    id: str
    station_id: str
    fiscal_year: int
    dues_vote_eligible: bool
    eligible_from: Optional[str]
    last_projected_at: Optional[str]
    created_at: str