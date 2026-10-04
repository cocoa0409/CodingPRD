"""Domain types: entity TypedDicts, status enums, role enum."""
from enum import Enum
from typing import TypedDict


class UserRole(str, Enum):
    PLATFORM_ADMIN = "PlatformAdmin"
    COMPLEX_DIRECTOR = "ComplexDirector"
    COMMUNITY_LIAISON = "CommunityLiaison"
    FIELD_COORDINATOR = "FieldCoordinator"
    PITCHING_COORDINATOR = "PitchingCoordinator"
    TRAVEL_COORDINATOR = "TravelCoordinator"
    TEAM_PHYSICIAN = "TeamPhysician"
    ROSTER_MANAGER = "RosterManager"
    MINOR_LEAGUE_COORDINATOR = "MinorLeagueCoordinator"
    ANALYTICS = "Analytics"
    PLAYER = "Player"


class ComplexStatus(str, Enum):
    NORMAL = "NORMAL"
    FIELD_RESTRICTED = "FIELD_RESTRICTED"
    CLOSED = "CLOSED"


class MaintenanceStatus(str, Enum):
    OPEN = "OPEN"
    HALF_FIELD = "HALF_FIELD"
    CLOSED = "CLOSED"


class AgreementStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    TERMINATED = "TERMINATED"


class TicketingStatus(str, Enum):
    NOT_OPEN = "NOT_OPEN"
    ON_SALE = "ON_SALE"
    SOLD_OUT = "SOLD_OUT"
    SUSPENDED = "SUSPENDED"


class SponsorshipStatus(str, Enum):
    UNSETTLED = "UNSETTLED"
    SETTLED = "SETTLED"
    RECOGNIZED = "RECOGNIZED"
    SETTLEMENT_VOIDED = "SETTLEMENT_VOIDED"


class WorkoutGroupStatus(str, Enum):
    FORMING = "FORMING"
    PUBLISHED = "PUBLISHED"
    DISBANDED = "DISBANDED"


class AssignmentStatus(str, Enum):
    PROVISIONAL = "PROVISIONAL"
    ACTIVE = "ACTIVE"
    WITHDRAWN = "WITHDRAWN"


class RosterStatus(str, Enum):
    NRI = "NRI"
    ACTIVE_ROSTER = "ACTIVE_ROSTER"
    OPTIONED_MINORS = "OPTIONED_MINORS"
    DESIGNATED_FOR_ASSIGNMENT = "DESIGNATED_FOR_ASSIGNMENT"
    WAIVER_PENDING = "WAIVER_PENDING"
    WAIVER_CLAIMED = "WAIVER_CLAIMED"
    RELEASED = "RELEASED"
    NRI_RELEASED = "NRI_RELEASED"
    ASSIGNED_AAA = "ASSIGNED_AAA"
    ASSIGNED_AA = "ASSIGNED_AA"


class DecisionStatus(str, Enum):
    DECISION_PENDING = "DECISION_PENDING"
    DECISION_FINALIZED = "DECISION_FINALIZED"
    DECISION_VOIDED = "DECISION_VOIDED"


class ThrowPhase(str, Enum):
    PHASE_1 = "PHASE_1"
    PHASE_2 = "PHASE_2"
    PHASE_3 = "PHASE_3"
    PHASE_4 = "PHASE_4"
    PHASE_LIVE = "PHASE_LIVE"
    SHUTDOWN = "SHUTDOWN"


class GameStatus(str, Enum):
    DRAFT = "DRAFT"
    PUBLISHED = "PUBLISHED"
    PLAYED = "PLAYED"
    CANCELLED = "CANCELLED"


class InvitationStatus(str, Enum):
    ISSUED = "ISSUED"
    ACKNOWLEDGED = "ACKNOWLEDGED"
    ARRIVED = "ARRIVED"
    VISA_BLOCKED = "VISA_BLOCKED"
    NO_SHOW = "NO_SHOW"


# common_fields: true — every PRD entity carries id + created_at + updated_at + version
class Complex(TypedDict):
    id: str
    name: str
    host_city: str
    season_split_track: str
    timezone: str
    facility_capacity_units: int
    posted_occupancy_units: int
    reserved_major_units: int
    reserved_minor_units: int
    maintenance_block_units: int
    field_maintenance_status: str
    facility_posture: str
    contention_flagged: bool
    posture_sweep_index: int
    created_at: str
    updated_at: str
    version: int


class CommunityAgreement(TypedDict):
    id: str
    complex_id: str
    stadium_name: str
    lease_start_date: str
    lease_end_date: str
    annual_rent_cents: int
    sponsorship_minor_league_base_cents: int
    sponsorship_major_league_base_cents: int
    ticket_price_cents: int
    ticket_sellout_capacity: int
    agreement_status: str
    travel_liability_window_count: int
    travel_liability_days: int
    settlement_release_lag_days: int
    created_at: str
    updated_at: str
    version: int


class Player(TypedDict):
    id: str
    full_name: str
    idp_number: str
    position_code: str
    acquisition_channel: str
    mlb_service_days: int
    minor_league_option_years_used: int
    home_country: str
    home_complex_id: str
    clearance_status: str
    created_at: str
    updated_at: str
    version: int


class PlayerRosterRecord(TypedDict):
    id: str
    player_id: str
    current_roster_status: str
    roster_decision_status: str
    option_eligibility: str
    option_decisions_used: int
    waivers_required: bool
    option_credit_source: str
    last_decision_actor_id: str
    waiver_claim_window_days: int
    split_squad_eligibility: str
    decision_sequence: int
    created_at: str
    updated_at: str
    version: int


class ProgramProfile(TypedDict):
    id: str
    player_id: str
    eligibility_status: str
    rehab_program_phase: str
    active_group_assignment_id: str
    active_rehab_assignment_count: int
    major_group_count: int
    minor_group_count: int
    created_at: str
    updated_at: str
    version: int


class HostCommunityRecord(TypedDict):
    id: str
    agreement_id: str
    ticketing_status: str
    tickets_sold: int
    ticketing_revenue_cents: int
    sponsorship_recorded_cents: int
    sponsorship_revenue_cents: int
    community_ledger_cents: int
    agreement_funded_cents: int
    recognition_funded_cents: int
    ledger_gap_cents: int
    created_at: str
    updated_at: str
    version: int


class Sponsorship(TypedDict):
    id: str
    host_community_record_id: str
    sponsor_name: str
    sponsor_tier: str
    committed_amount_cents: int
    received_amount_cents: int
    fulfillment_completed: bool
    reconciliation_status: str
    created_at: str
    updated_at: str
    version: int


class WorkoutGroup(TypedDict):
    id: str
    complex_id: str
    roster_bucket: str
    group_name: str
    facility_kind: str
    capacity_units: int
    assigned_units: int
    assignment_group_tag: str
    group_status: str
    created_at: str
    updated_at: str
    version: int


class GroupAssignment(TypedDict):
    id: str
    workout_group_id: str
    player_id: str
    roster_bucket: str
    assignment_kind: str
    assignment_status: str
    assigned_at: str
    withdrawal_reason: str
    created_at: str
    updated_at: str
    version: int


class ThrowProgram(TypedDict):
    id: str
    group_assignment_id: str
    player_id: str
    program_phase: str
    target_catch_play_throws: int
    target_bullpen_sessions: int
    cumulative_throws: int
    cumulative_bullpen_sessions: int
    schedule_requirement_throws: int
    requirement_status: str
    created_at: str
    updated_at: str
    version: int


class WorkoutGroupSession(TypedDict):
    id: str
    workout_group_id: str
    session_date: str
    session_end_datetime: str
    session_kind: str
    field_units: int
    session_status: str
    created_at: str
    updated_at: str
    version: int


class ThrowProgramSession(TypedDict):
    id: str
    throw_program_id: str
    logged_at: str
    session_sequence: int
    session_kind: str
    play_catch_throws: int
    session_status: str
    created_at: str
    updated_at: str
    version: int


class CampInvitation(TypedDict):
    id: str
    player_id: str
    invitation_kind: str
    report_current_date: str
    report_final_date: str
    actual_report_date: str
    arrival_band: str
    travel_arrangement_status: str
    invitation_status: str
    invitation_letter_status: str
    domestic_travel: bool
    created_at: str
    updated_at: str
    version: int


class TravelArrangement(TypedDict):
    id: str
    camp_invitation_id: str
    player_id: str
    mode: str
    travel_radius_miles: float
    departure_at: str
    status: str
    travel_cost_cents: int
    reimbursement_status: str
    agreement_funded_cents: int
    reimbursement_cents: int
    funding_source: str
    created_at: str
    updated_at: str
    version: int


class Physical(TypedDict):
    id: str
    player_id: str
    scheduled_visit_date: str
    status: str
    physical_result: str
    performed_at: str
    created_at: str
    updated_at: str
    version: int


class GameSchedule(TypedDict):
    id: str
    complex_id: str
    opponent_name: str
    home_away: str
    game_datetime: str
    travel_radius_miles: float
    duration_units: int
    split_squad: bool
    game_schedule_status: str
    gameday_status: str
    game_interval_start: str
    game_interval_end: str
    created_at: str
    updated_at: str
    version: int


class GameParticipation(TypedDict):
    id: str
    game_schedule_id: str
    player_id: str
    squad_side: str
    participation_status: str
    throw_count: int
    created_at: str
    updated_at: str
    version: int


class SpringTrail(TypedDict):
    id: str
    player_id: str
    trail_level: str
    mapped_at: str
    trail_status: str
    created_at: str
    updated_at: str
    version: int


class MinorLeagueAssignment(TypedDict):
    id: str
    player_id: str
    roster_record_id: str
    assigned_level: str
    affiliate_name: str
    effective_datetime: str
    travel_day_count: int
    break_out_liability_cents: int
    assignment_status: str
    settlement_actor_id: str
    created_at: str
    updated_at: str
    version: int