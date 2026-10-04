"""Domain types: entity TypedDicts, status enums and role enum.

Only the resources of the audited lifecycle carry ``updated_at`` and ``version``
(PRD §2.4).  ``CourseUnit`` and ``PracticeAttempt`` are deliberately narrower and
carry only ``id`` and ``created_at``.
"""
from enum import Enum
from typing import Optional, TypedDict


class UserRole(str, Enum):
    LEARNER = "Learner"
    CERTIFICATION_PROCTOR = "CertificationProctor"
    PLATFORM_ADMIN = "PlatformAdmin"
    ANONYMOUS = "Anonymous"


class ProgramTier(str, Enum):
    FREE = "FREE"
    PLUS_FAMILY = "PLUS_FAMILY"
    CERTIFICATION_ELITE = "CERTIFICATION_ELITE"


class SubscriptionStatus(str, Enum):
    FREE = "FREE"
    ACTIVE = "ACTIVE"
    IN_GRACE = "IN_GRACE"
    EXPIRED = "EXPIRED"


class MembershipStatus(str, Enum):
    INVITED = "INVITED"
    ACTIVE = "ACTIVE"
    REMOVED = "REMOVED"


class LessonNodeState(str, Enum):
    LOCKED = "LOCKED"
    UNLOCKED = "UNLOCKED"
    BRONZE = "BRONZE"
    SILVER = "SILVER"
    GOLD = "GOLD"
    LEGENDARY = "LEGENDARY"
    DECAYED = "DECAYED"


class AttemptOutcome(str, Enum):
    ACCEPTED = "ACCEPTED"
    REJECTED_LIMIT = "REJECTED_LIMIT"
    REJECTED_DECAY_CAP = "REJECTED_DECAY_CAP"


class StreakStatus(str, Enum):
    EVALUATING = "EVALUATING"
    QUALIFIED = "QUALIFIED"
    FROZEN = "FROZEN"
    BROKEN = "BROKEN"
    REPAIRED = "REPAIRED"


class PlacementStatus(str, Enum):
    CREATED = "CREATED"
    IN_PROGRESS = "IN_PROGRESS"
    SCORED = "SCORED"
    CALIBRATED = "CALIBRATED"
    ABANDONED = "ABANDONED"
    CERTIFIED = "CERTIFIED"


class CefrBand(str, Enum):
    A1 = "A1"
    A2 = "A2"
    B1 = "B1"
    B2 = "B2"
    C1 = "C1"


class LeagueStatus(str, Enum):
    FORMING = "FORMING"
    ACTIVE = "ACTIVE"
    SETTLING = "SETTLING"
    CLOSED = "CLOSED"


class StandingStatus(str, Enum):
    GOOD_STANDING = "GOOD_STANDING"
    FLAGGED = "FLAGGED"
    PROMOTED = "PROMOTED"
    DEMOTED = "DEMOTED"


class SettledOutcome(str, Enum):
    NONE = "NONE"
    PROMOTED = "PROMOTED"
    DEMOTED = "DEMOTED"
    HELD = "HELD"


class ExamStatus(str, Enum):
    PURCHASED = "PURCHASED"
    PROCTORING = "PROCTORING"
    SUBMITTED = "SUBMITTED"
    SCORED = "SCORED"
    REPORTED = "REPORTED"
    VOID = "VOID"
    EXPIRED = "EXPIRED"


class ScoreBand(str, Enum):
    NOT_CERTIFIED = "NOT_CERTIFIED"
    PASS = "PASS"
    STRONG_PASS = "STRONG_PASS"
    DISTINCTION = "DISTINCTION"


class OfferStatus(str, Enum):
    ISSUED = "ISSUED"
    REDEEMED = "REDEEMED"
    EXPIRED = "EXPIRED"
    SUPPRESSED = "SUPPRESSED"


class MilestoneCode(str, Enum):
    STREAK_7 = "STREAK_7"
    STREAK_30 = "STREAK_30"
    PLACEMENT_SKIP = "PLACEMENT_SKIP"
    LEAGUE_PROMOTION = "LEAGUE_PROMOTION"
    HEART_DEPLETION = "HEART_DEPLETION"


# ── Entity shapes ────────────────────────────────────────────────────────────
# common_fields: true — carries id + created_at + updated_at + version

class Learner(TypedDict, total=False):
    id: str
    display_name: str
    timezone_id: str
    program_tier: str
    streak_anchor_date: str
    xp_total: int
    gems_balance: int
    leaf_count: int
    hearts_available: Optional[int]
    energy_units: Optional[int]
    energy_anchor_at: str
    created_at: str
    updated_at: str
    version: int


class Subscription(TypedDict, total=False):
    id: str
    learner_id: str
    plan_code: str
    seats_total: int
    seats_used: int
    status: str
    current_period_end: str
    auto_renew: bool
    limits_removed: bool
    created_at: str
    updated_at: str
    version: int


class FamilyMembership(TypedDict, total=False):
    id: str
    subscription_id: str
    member_learner_id: str
    seat_role: str
    status: str
    invited_at: str
    created_at: str
    updated_at: str
    version: int


# common_fields: false — append-only, carries ONLY id + created_at

class CourseUnit(TypedDict, total=False):
    id: str
    unit_index: int
    title: str
    cefr_band: str
    unlock_index: int
    crown_count: int
    total_nodes: int
    created_at: str
    # NO updated_at, NO version


class PracticeAttempt(TypedDict, total=False):
    id: str
    learner_id: str
    lesson_node_id: str
    recorded_at: str
    response_ms: int
    correct: bool
    is_placement_attempt: bool
    outcome: str
    xp_awarded: int
    created_at: str
    # NO updated_at, NO version


class LessonNode(TypedDict, total=False):
    id: str
    unit_id: str
    prerequisite_node_id: Optional[str]
    node_index: int
    state: str
    decay_level: int
    decay_meter: int
    last_reviewed_at: str
    review_due_at: str
    created_at: str
    updated_at: str
    version: int


class StreakState(TypedDict, total=False):
    id: str
    learner_id: str
    current_length: int
    focus_date: str
    freeze_tokens: int
    status: str
    last_qualified_local_date: str
    local_date_offset_days: int
    repair_cost_gems: int
    repair_purchases_this_month: int
    created_at: str
    updated_at: str
    version: int


class PlacementTest(TypedDict, total=False):
    id: str
    learner_id: str
    course_id: str
    status: str
    administered_at: str
    graded_at: str
    total_items: int
    comprehension_score: int
    accuracy_score: int
    calibrated_cefr_band: Optional[str]
    placed_unit_index: int
    free_probe_used: bool
    is_institution_graded: bool
    proctor_user_id: str
    created_at: str
    updated_at: str
    version: int


class League(TypedDict, total=False):
    id: str
    tier: str
    week_start: str
    status: str
    member_count: int
    promotion_cutoff_rank: int
    demotion_cutoff_rank: int
    settled_at: str
    created_at: str
    updated_at: str
    version: int


class LeagueStanding(TypedDict, total=False):
    id: str
    league_id: str
    learner_id: str
    weekly_xp: int
    standing: str
    rank: int
    flag_reason: str
    settled_outcome: str
    created_at: str
    updated_at: str
    version: int


class CertificationExam(TypedDict, total=False):
    id: str
    learner_id: str
    product_code: str
    status: str
    purchased_at: str
    proctored_by_user_id: str
    proctor_started_at: str
    score_band: str
    raw_score: int
    report_id: str
    expires_at: str
    created_at: str
    updated_at: str
    version: int


class EngagementOffer(TypedDict, total=False):
    id: str
    learner_id: str
    milestone_code: str
    discount_pct: int
    status: str
    issued_at: str
    expires_at: str
    scored_tier: str
    created_at: str
    updated_at: str
    version: int


class ScoreReport(TypedDict, total=False):
    id: str
    exam_id: str
    learner_id: str
    institution_name: str
    institution_learner_code: str
    score_band: str
    raw_score: int
    reported_at: str
    created_at: str
    updated_at: str
    version: int


__all__ = [
    "UserRole", "ProgramTier", "SubscriptionStatus", "MembershipStatus",
    "LessonNodeState", "AttemptOutcome", "StreakStatus", "PlacementStatus",
    "CefrBand", "LeagueStatus", "StandingStatus", "SettledOutcome",
    "ExamStatus", "ScoreBand", "OfferStatus", "MilestoneCode",
    "Learner", "Subscription", "FamilyMembership", "CourseUnit",
    "PracticeAttempt", "LessonNode", "StreakState", "PlacementTest",
    "League", "LeagueStanding", "CertificationExam", "EngagementOffer",
    "ScoreReport",
]