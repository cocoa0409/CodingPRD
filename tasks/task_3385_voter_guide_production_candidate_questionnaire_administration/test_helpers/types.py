"""Domain types: entity TypedDicts, status enums, role enum (PRD §2-§4).

Every resource carries the four common properties of PRD §2.5 (id,
created_at, updated_at, version); there are no append-only resources in this
domain, so every TypedDict below includes all four.
"""
from enum import Enum
from typing import Any, Dict, List, Optional, TypedDict


class UserRole(str, Enum):
    LEAGUE_ADMIN = "LeagueAdmin"
    CHAPTER_COORDINATOR = "ChapterCoordinator"
    QUESTIONNAIRE_EDITOR = "QuestionnaireEditor"
    NEUTRALITY_REVIEWER = "NeutralityReviewer"
    FORUM_MODERATOR = "ForumModerator"
    CANDIDATE = "Candidate"
    PUBLIC_USER = "PublicUser"


class ElectionCycleStatus(str, Enum):
    DRAFT = "DRAFT"
    OPEN = "OPEN"
    PUBLISHED = "PUBLISHED"
    ARCHIVED = "ARCHIVED"


class ContestKind(str, Enum):
    CANDIDATE_RACE = "CANDIDATE_RACE"
    BALLOT_MEASURE = "BALLOT_MEASURE"


class ContestStatus(str, Enum):
    FILING_OPEN = "FILING_OPEN"
    QUESTIONNAIRE_PHASE = "QUESTIONNAIRE_PHASE"
    GUIDE_READY = "GUIDE_READY"
    LOCKED = "LOCKED"


class WordCountPolicy(str, Enum):
    STRICT = "STRICT"
    LENIENT = "LENIENT"


class ReadingLevelMetric(str, Enum):
    FLESCH_KINCAID = "FLESCH_KINCAID"
    SMOG = "SMOG"


class FilingStatus(str, Enum):
    FILED = "FILED"
    VERIFIED = "VERIFIED"
    WITHDRAWN = "WITHDRAWN"
    DISQUALIFIED = "DISQUALIFIED"


class QuestionnaireStatus(str, Enum):
    DRAFT = "DRAFT"
    ISSUED = "ISSUED"
    CLOSED = "CLOSED"
    PINNED = "PINNED"


class ResponseStatus(str, Enum):
    INVITED = "INVITED"
    SUBMITTED = "SUBMITTED"
    OVER_LIMIT_RETURNED = "OVER_LIMIT_RETURNED"
    NONRESPONSE_MARKED = "NONRESPONSE_MARKED"
    LATE_UNPUBLISHED = "LATE_UNPUBLISHED"
    WITHDRAWN_HIDDEN = "WITHDRAWN_HIDDEN"


class PublishedIndicator(str, Enum):
    PENDING = "PENDING"
    PUBLISHED_UNEDITED = "PUBLISHED_UNEDITED"
    DID_NOT_RESPOND = "DID_NOT_RESPOND"
    LATE = "LATE"
    WITHDRAWN = "WITHDRAWN"


class MeasureStatus(str, Enum):
    DRAFTING = "DRAFTING"
    IN_NEUTRALITY_REVIEW = "IN_NEUTRALITY_REVIEW"
    REMANDED = "REMANDED"
    APPROVED_FOR_GUIDE = "APPROVED_FOR_GUIDE"


class ArgumentSide(str, Enum):
    PRO = "PRO"
    CON = "CON"


class ArgumentStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"


class ReviewVerdict(str, Enum):
    NEUTRAL = "NEUTRAL"
    LOADED_LANGUAGE = "LOADED_LANGUAGE"
    UNBALANCED = "UNBALANCED"


class LanguageCode(str, Enum):
    EN = "EN"
    ES = "ES"
    ZH = "ZH"
    VI = "VI"
    TL = "TL"


class Channel(str, Enum):
    PRINT = "PRINT"
    WEB = "WEB"
    PARTNER = "PARTNER"


class AccessibilityFormat(str, Enum):
    STANDARD = "STANDARD"
    LARGE_PRINT = "LARGE_PRINT"
    SCREEN_READER = "SCREEN_READER"


class EditionStatus(str, Enum):
    ASSEMBLING = "ASSEMBLING"
    READY = "READY"
    DISTRIBUTED = "DISTRIBUTED"
    RETIRED = "RETIRED"


class ForumStatus(str, Enum):
    PLANNED = "PLANNED"
    CONFIRMED = "CONFIRMED"
    HELD = "HELD"
    CANCELLED = "CANCELLED"


class QuestionSource(str, Enum):
    PUBLIC_SUBMISSION = "PUBLIC_SUBMISSION"
    MODERATOR_AUTHORED = "MODERATOR_AUTHORED"


class QuestionStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    SELECTED = "SELECTED"
    REJECTED = "REJECTED"


class VolunteerCapability(str, Enum):
    COORDINATOR = "COORDINATOR"
    EDITOR = "EDITOR"
    REVIEWER = "REVIEWER"
    MODERATOR = "MODERATOR"


class AttestationStatus(str, Enum):
    CURRENT = "CURRENT"
    LAPSED = "LAPSED"


class VolunteerStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class IncidentType(str, Enum):
    PARTISAN_STATEMENT = "PARTISAN_STATEMENT"
    ADVOCACY_ROLE_CONFLICT = "ADVOCACY_ROLE_CONFLICT"
    MODERATOR_BIAS = "MODERATOR_BIAS"
    QUESTIONNAIRE_SLANT = "QUESTIONNAIRE_SLANT"


class IncidentStatus(str, Enum):
    REPORTED = "REPORTED"
    SUBSTANTIATED = "SUBSTANTIATED"
    DISMISSED = "DISMISSED"


class ElectionCycle(TypedDict, total=False):
    id: str
    cycle_name: str
    election_date: str
    status: str
    distributed_edition_count: int
    created_at: str
    updated_at: str
    version: int


class Jurisdiction(TypedDict, total=False):
    id: str
    cycle_id: str
    jurisdiction_name: str
    fips_code: str
    supported_language_codes: List[str]
    reading_level_metric: str
    created_at: str
    updated_at: str
    version: int


class Contest(TypedDict, total=False):
    id: str
    jurisdiction_id: str
    kind: str
    office_name: Optional[str]
    seat_count: int
    vote_for_count: int
    filing_deadline: str
    questionnaire_word_limit: int
    word_count_policy: str
    status: str
    verified_candidate_count: int
    completion_index: float
    created_at: str
    updated_at: str
    version: int


class CandidateFiling(TypedDict, total=False):
    id: str
    contest_id: str
    candidate_name: str
    party_label: str
    filing_reference: str
    status: str
    filed_at: str
    verified_at: Optional[str]
    withdrawal_count: int
    created_at: str
    updated_at: str
    version: int


class Questionnaire(TypedDict, total=False):
    id: str
    contest_id: str
    due_at: str
    questions: List[Dict[str, Any]]
    status: str
    invited_count: int
    submitted_count: int
    nonresponse_count: int
    late_count: int
    created_at: str
    updated_at: str
    version: int


class CandidateResponse(TypedDict, total=False):
    id: str
    questionnaire_id: str
    filing_id: str
    answers: List[Dict[str, Any]]
    status: str
    submitted_at: Optional[str]
    per_answer_word_counts: List[int]
    over_limit_positions: List[int]
    published_indicator: str
    created_at: str
    updated_at: str
    version: int


class BallotMeasure(TypedDict, total=False):
    id: str
    contest_id: str
    measure_title: str
    official_text: str
    explanation_text: str
    drafter_volunteer_id: str
    status: str
    review_round_count: int
    approvals_this_round: int
    pro_word_total: int
    con_word_total: int
    balance_ratio: float
    balance_flag: bool
    grade_fk: float
    grade_smog: float
    created_at: str
    updated_at: str
    version: int


class MeasureArgument(TypedDict, total=False):
    id: str
    measure_id: str
    side: str
    argument_text: str
    author_credit: str
    word_count: int
    status: str
    created_at: str
    updated_at: str
    version: int


class NeutralityReview(TypedDict, total=False):
    id: str
    measure_id: str
    reviewer_volunteer_id: str
    verdict: str
    notes: str
    round_index: int
    created_at: str
    updated_at: str
    version: int


class GuideEdition(TypedDict, total=False):
    id: str
    cycle_id: str
    language_code: str
    channel: str
    accessibility_format: str
    status: str
    snapshot_contest_ids: List[str]
    pinned_questionnaire_versions: Dict[str, int]
    estimated_page_count: int
    print_run_total: int
    allocations: List[Dict[str, Any]]
    unallocated_copies: int
    created_at: str
    updated_at: str
    version: int


class Forum(TypedDict, total=False):
    id: str
    contest_id: str
    scheduled_start: str
    scheduled_end: str
    moderator_volunteer_id: str
    status: str
    eligible_candidate_count: int
    minutes_text: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ForumQuestion(TypedDict, total=False):
    id: str
    forum_id: str
    question_text: str
    source: str
    author_volunteer_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class Volunteer(TypedDict, total=False):
    id: str
    volunteer_name: str
    chapter_code: str
    roles: List[str]
    advocacy_flag: bool
    attestation_status: str
    attestation_expires_at: str
    status: str
    substantiated_incident_count: int
    created_at: str
    updated_at: str
    version: int


class PolicyIncident(TypedDict, total=False):
    id: str
    volunteer_id: str
    incident_type: str
    description: str
    status: str
    corrective_action: Optional[str]
    resolved_at: Optional[str]
    created_at: str
    updated_at: str
    version: int
