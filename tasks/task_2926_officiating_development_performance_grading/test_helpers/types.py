"""Domain types for the Officiating Development & Grading API.

Status enums, role enum and entity TypedDicts, all named exactly as the PRD
names them.
"""
from enum import Enum
from typing import List, Optional, TypedDict


# ─── Roles ────────────────────────────────────────────

class UserRole(str, Enum):
    OFFICIATING_DIRECTOR = "OfficiatingDirector"
    CREW_SCHEDULER = "CrewScheduler"
    GRADING_SUPERVISOR = "GradingSupervisor"
    OFFICIAL = "Official"
    FIELD_EVALUATOR = "FieldEvaluator"
    REPLAY_OFFICIAL = "ReplayOfficial"
    TRAINING_COORDINATOR = "TrainingCoordinator"
    COMMUNICATIONS_OFFICER = "CommunicationsOfficer"


ALL_ROLE_NAMES: List[str] = [r.value for r in UserRole]


# ─── Enumerations ─────────────────────────────────────

class SeasonProgramStatus(str, Enum):
    CONFIGURING = "CONFIGURING"
    OPEN = "OPEN"
    POSTSEASON_LOCKED = "POSTSEASON_LOCKED"


class OfficialStatus(str, Enum):
    CANDIDATE = "CANDIDATE"
    ACTIVE = "ACTIVE"
    PROBATION = "PROBATION"
    SUSPENDED = "SUSPENDED"
    RELEASED = "RELEASED"


class OfficialPosition(str, Enum):
    REFEREE = "REFEREE"
    UMPIRE = "UMPIRE"
    DOWN_JUDGE = "DOWN_JUDGE"


class OfficialTier(str, Enum):
    TIER_3 = "TIER_3"
    TIER_2 = "TIER_2"
    TIER_1 = "TIER_1"


class TrainingRecordType(str, Enum):
    RULES_CLINIC = "RULES_CLINIC"
    PHYSICAL_TEST = "PHYSICAL_TEST"
    RULES_EXAM = "RULES_EXAM"


class ApplicationStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    SCREENED = "SCREENED"
    COMMITTEE_REVIEW = "COMMITTEE_REVIEW"
    RETURNED_FOR_TAPE = "RETURNED_FOR_TAPE"
    APPROVED = "APPROVED"
    DENIED = "DENIED"


class ApplicationDecisionOutcome(str, Enum):
    APPROVED = "APPROVED"
    DENIED = "DENIED"


class GameStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    IN_PROGRESS = "IN_PROGRESS"
    PLAYED = "PLAYED"
    FINALIZED = "FINALIZED"


class CrewPosture(str, Enum):
    UNDERSTAFFED = "UNDERSTAFFED"
    STAFFED = "STAFFED"
    LOCKED = "LOCKED"


class CrewStrengthVariant(str, Enum):
    PROJECTED = "PROJECTED"
    REALIZED = "REALIZED"


class AssignmentStatus(str, Enum):
    PROPOSED = "PROPOSED"
    CONFIRMED = "CONFIRMED"
    COMPLETED = "COMPLETED"
    WITHDRAWN = "WITHDRAWN"
    SUPERSEDED = "SUPERSEDED"
    VOIDED = "VOIDED"


class CallCategory(str, Enum):
    HOLDING = "HOLDING"
    PASS_INTERFERENCE = "PASS_INTERFERENCE"
    ROUGHING_PASSER = "ROUGHING_PASSER"
    FALSE_START = "FALSE_START"


class GradeCode(str, Enum):
    CORRECT = "CORRECT"
    INCORRECT_CALL = "INCORRECT_CALL"
    MISSED_CALL = "MISSED_CALL"
    INADVERTENT_WHISTLE = "INADVERTENT_WHISTLE"


class ImpactBand(str, Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    GAME_CRITICAL = "GAME_CRITICAL"


class GradeStatus(str, Enum):
    DRAFT = "DRAFT"
    POSTED = "POSTED"
    FINAL = "FINAL"


class AppealState(str, Enum):
    NOT_APPEALED = "NOT_APPEALED"
    APPEAL_PENDING = "APPEAL_PENDING"
    APPEAL_RESOLVED = "APPEAL_RESOLVED"


class AppealStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    UNDER_REVIEW = "UNDER_REVIEW"
    UPHELD = "UPHELD"
    OVERTURNED = "OVERTURNED"
    MODIFIED = "MODIFIED"
    WITHDRAWN = "WITHDRAWN"


class AppealOutcome(str, Enum):
    UPHELD = "UPHELD"
    OVERTURNED = "OVERTURNED"
    MODIFIED = "MODIFIED"


class ReplayStationStatus(str, Enum):
    ONLINE = "ONLINE"
    OFFLINE = "OFFLINE"


class ReviewCategory(str, Enum):
    SCORING_PLAY = "SCORING_PLAY"
    TURNOVER = "TURNOVER"
    PLAYER_SAFETY = "PLAYER_SAFETY"
    GAME_ADMIN = "GAME_ADMIN"


class ReviewStatus(str, Enum):
    INITIATED = "INITIATED"
    DECIDED = "DECIDED"
    EXPIRED = "EXPIRED"


class ReplayDecision(str, Enum):
    STANDS = "STANDS"
    CONFIRMED = "CONFIRMED"
    REVERSED = "REVERSED"


class AccuracyVariant(str, Enum):
    PROVISIONAL = "PROVISIONAL"
    FINAL = "FINAL"


class RetentionRecommendation(str, Enum):
    RETAIN = "RETAIN"
    DEVELOP = "DEVELOP"
    RELEASE = "RELEASE"


class ReportType(str, Enum):
    POOL_REPORT = "POOL_REPORT"
    RULES_CLARIFICATION = "RULES_CLARIFICATION"


class ReportStatus(str, Enum):
    DRAFT = "DRAFT"
    PUBLISHED = "PUBLISHED"
    SUPERSEDED = "SUPERSEDED"


class ReasonCategory(str, Enum):
    PERFORMANCE = "PERFORMANCE"
    CONDUCT = "CONDUCT"
    ATTENDANCE = "ATTENDANCE"


class DisciplineSeverity(str, Enum):
    WARNING = "WARNING"
    REMEDIATION = "REMEDIATION"
    SUSPENSION = "SUSPENSION"


class DisciplineStatus(str, Enum):
    OPENED = "OPENED"
    REMEDIATION_ASSIGNED = "REMEDIATION_ASSIGNED"
    REASSESSED = "REASSESSED"
    CLEARED = "CLEARED"
    ESCALATED = "ESCALATED"
    SUPERSEDED = "SUPERSEDED"


class DisciplineResolveOutcome(str, Enum):
    CLEARED = "CLEARED"
    REASSESSED = "REASSESSED"
    ESCALATED = "ESCALATED"


# ─── Entity shapes ────────────────────────────────────
# Resources carrying the full server-managed set: id + created_at +
# updated_at + version.


class SeasonProgram(TypedDict):
    id: str
    season_year: int
    status: str
    accuracy_eligibility_threshold: float
    min_graded_plays_for_eligibility: int
    appeal_credits_per_official: int
    appeal_window_hours: int
    replay_decision_limit_seconds: int
    reviewable_categories: List[str]
    max_team_exposures_per_season: int
    min_rest_hours_between_games: int
    travel_lead_hours: int
    crew_size_required: int
    max_application_returns: int
    physical_test_min_score: float
    exam_min_score: float
    clinic_attendance_required: int
    eligible_official_count: int
    created_at: str
    updated_at: str
    version: int


class Official(TypedDict):
    id: str
    season_program_id: str
    full_name: str
    position: str
    seasons_experience: int
    home_market_code: str
    tier: str
    affiliated_team_code: Optional[str]
    status: str
    preseason_cleared: bool
    open_assignment_count: int
    appeal_credits_remaining: int
    created_at: str
    updated_at: str
    version: int


class AdvancementApplication(TypedDict):
    id: str
    official_id: str
    target_tier: str
    status: str
    return_count: int
    evaluation_average: Optional[float]
    decision_note: Optional[str]
    screened_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Game(TypedDict):
    id: str
    season_program_id: str
    home_team_code: str
    away_team_code: str
    venue_market_code: str
    kickoff_utc: str
    status: str
    crew_posture: str
    confirmed_crew_count: int
    crew_strength_index: float
    crew_strength_variant: str
    created_at: str
    updated_at: str
    version: int


class CrewAssignment(TypedDict):
    id: str
    game_id: str
    official_id: str
    position: str
    status: str
    occupied_from_utc: str
    occupied_until_utc: str
    released_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class PlayGrade(TypedDict):
    id: str
    game_id: str
    official_id: str
    play_ref: str
    call_category: str
    grade_code: str
    impact: str
    error_points: float
    grade_status: str
    appeal_state: str
    graded_by_user_id: str
    posted_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class GradeAppeal(TypedDict):
    id: str
    play_grade_id: str
    basis_note: str
    status: str
    submitted_at: str
    decided_by_user_id: Optional[str]
    decision_note: Optional[str]
    revised_grade_code: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ReplayStation(TypedDict):
    id: str
    station_code: str
    concurrent_capacity: int
    status: str
    active_review_count: int
    created_at: str
    updated_at: str
    version: int


class ReplayReview(TypedDict):
    id: str
    game_id: str
    station_id: str
    play_ref: str
    category: str
    status: str
    decision: Optional[str]
    elapsed_seconds: Optional[int]
    window_open_utc: str
    window_close_utc: str
    created_at: str
    updated_at: str
    version: int


class OfficialSeasonRecord(TypedDict):
    id: str
    official_id: str
    season_program_id: str
    graded_play_count: int
    weighted_error_points: float
    accuracy_index: float
    accuracy_variant: str
    accuracy_eligible: bool
    postseason_eligible: bool
    availability_component: float
    retention_score: float
    retention_recommendation: str
    created_at: str
    updated_at: str
    version: int


class PoolReport(TypedDict):
    id: str
    game_id: str
    play_grade_id: str
    report_type: str
    body: str
    supersedes_id: Optional[str]
    status: str
    published_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class DisciplineAction(TypedDict):
    id: str
    official_id: str
    reason_category: str
    severity: str
    suspension_games: Optional[int]
    status: str
    remediation_cycle_count: int
    remediation_plan: Optional[str]
    resolution_note: Optional[str]
    created_at: str
    updated_at: str
    version: int


# ─── Append-only evidence logs ────────────────────────
# These two resources are never mutated after they are written; they carry
# only id and created_at — no updated_at and no version.


class FieldEvaluation(TypedDict):
    id: str
    application_id: str
    evaluator_user_id: str
    mechanics_score: float
    rules_score: float
    presence_score: float
    composite_score: float
    created_at: str


class TrainingRecord(TypedDict):
    id: str
    official_id: str
    record_type: str
    session_code: str
    score: Optional[float]
    passed: bool
    created_at: str
