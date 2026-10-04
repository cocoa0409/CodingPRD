"""Domain types: entity TypedDicts, status enums, role enum.

Field nullability follows the PRD: fields documented as "null until ..." or
"null otherwise" are declared Optional.  CaseReassignment and DocketReview are
immutable ledger-style records: they carry only ``id`` and ``created_at`` of
the standard system fields (no ``updated_at``, no ``version``).
"""

from enum import Enum
from typing import List, Optional, TypedDict


# ─── Roles ────────────────────────────────────────────────────────────────


class UserRole(str, Enum):
    COURT_ADMINISTRATOR = "CourtAdministrator"
    IMMIGRATION_JUDGE = "ImmigrationJudge"
    BOARD_MEMBER = "BoardMember"


# ─── Enumerations ─────────────────────────────────────────────────────────


class CustodyStatus(str, Enum):
    DETAINED = "DETAINED"
    NON_DETAINED = "NON_DETAINED"


class RepresentationStatus(str, Enum):
    PRO_SE = "PRO_SE"
    COUNSEL_RETAINED = "COUNSEL_RETAINED"
    PRO_BONO = "PRO_BONO"


class CaseStatus(str, Enum):
    FILED = "FILED"
    CALENDAR = "CALENDAR"
    MERITS = "MERITS"
    DECIDED = "DECIDED"
    APPEALED = "APPEALED"
    IN_ABSENTIA = "IN_ABSENTIA"
    ADMIN_CLOSED = "ADMIN_CLOSED"
    COMPLETED = "COMPLETED"


class HearingType(str, Enum):
    MASTER_CALENDAR = "MASTER_CALENDAR"
    INDIVIDUAL_MERITS = "INDIVIDUAL_MERITS"


class HearingStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    COMPLETED = "COMPLETED"
    CONTINUED = "CONTINUED"
    NO_SHOW = "NO_SHOW"
    CANCELLED = "CANCELLED"


class ServiceMethod(str, Enum):
    MAIL = "MAIL"
    PERSONAL_SERVICE = "PERSONAL_SERVICE"
    ELECTRONIC = "ELECTRONIC"


class NoticeStatus(str, Enum):
    SERVED = "SERVED"
    DEFECTIVE = "DEFECTIVE"


class ContinuanceReason(str, Enum):
    ATTORNEY_REPRESENTATION = "ATTORNEY_REPRESENTATION"
    EVIDENCE_GATHERING = "EVIDENCE_GATHERING"
    PENDING_APPLICATION = "PENDING_APPLICATION"
    OTHER = "OTHER"


class ContinuanceStatus(str, Enum):
    PENDING = "PENDING"
    GRANTED = "GRANTED"
    DENIED = "DENIED"


class VenueMotionStatus(str, Enum):
    PENDING = "PENDING"
    GRANTED = "GRANTED"
    DENIED = "DENIED"


class RulingDecision(str, Enum):
    """Judge-side decision payload for continuances / venue motions / reopen motions."""

    GRANTED = "GRANTED"
    DENIED = "DENIED"


class DecisionOutcome(str, Enum):
    GRANT_RELIEF = "GRANT_RELIEF"
    REMOVAL = "REMOVAL"
    TERMINATION = "TERMINATION"
    IN_ABSENTIA_REMOVAL = "IN_ABSENTIA_REMOVAL"


class DecisionStatus(str, Enum):
    ISSUED = "ISSUED"
    APPEAL_PENDING = "APPEAL_PENDING"
    FINAL = "FINAL"
    REMANDED = "REMANDED"
    RESCINDED = "RESCINDED"


class AppealStatus(str, Enum):
    FILED = "FILED"
    AFFIRMED = "AFFIRMED"
    REMANDED = "REMANDED"
    DISMISSED = "DISMISSED"


class AppealRuling(str, Enum):
    AFFIRMED = "AFFIRMED"
    REMANDED = "REMANDED"
    DISMISSED = "DISMISSED"


class MotionBasis(str, Enum):
    NOTICE_DEFECTIVE = "NOTICE_DEFECTIVE"
    EXCEPTIONAL_CIRCUMSTANCES = "EXCEPTIONAL_CIRCUMSTANCES"


class MotionStatus(str, Enum):
    FILED = "FILED"
    GRANTED = "GRANTED"
    DENIED = "DENIED"


REASSIGNMENT_REASON = "BACKLOG_REBALANCE"


# ─── Entity bodies (standard system fields: id/created_at/updated_at/version) ──


class Court(TypedDict):
    id: str
    court_code: str
    name: str
    city: str
    annual_completion_goal: int
    detained_daily_hearing_capacity: int
    pending_case_count: int
    completions_ytd: int
    is_backlog_critical: bool
    created_at: str
    updated_at: str
    version: int


class Judge(TypedDict):
    id: str
    court_id: str
    full_name: str
    max_pending_cases: int
    pending_case_load: int
    created_at: str
    updated_at: str
    version: int


class Interpreter(TypedDict):
    id: str
    court_id: str
    full_name: str
    language_codes: List[str]
    daily_hearing_cap: int
    created_at: str
    updated_at: str
    version: int


class LegalOrientationProgram(TypedDict):
    id: str
    court_id: str
    program_name: str
    coverage_pct: int
    active: bool
    created_at: str
    updated_at: str
    version: int


class Case(TypedDict):
    id: str
    court_id: str
    case_number: str
    respondent_full_name: str
    custody_status: str
    primary_language_code: str
    representation_status: str
    interpreter_required: bool
    assigned_judge_id: Optional[str]
    status: str
    filed_at: str
    completed_at: Optional[str]
    target_completion_date: str
    days_pending_calendar: int
    days_pending_court: int
    is_past_goal: bool
    continuance_count: int
    priority_score: int
    created_at: str
    updated_at: str
    version: int


class Hearing(TypedDict):
    id: str
    case_id: str
    hearing_type: str
    scheduled_start: str
    duration_minutes: int
    scheduled_end: str
    is_remote: bool
    judge_id: Optional[str]
    interpreter_id: Optional[str]
    supersedes_hearing_id: Optional[str]
    auto_created: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class HearingNotice(TypedDict):
    id: str
    hearing_id: str
    service_method: str
    served_at: str
    status: str
    created_at: str
    updated_at: str
    version: int


class ContinuanceRequest(TypedDict):
    id: str
    case_id: str
    hearing_id: str
    reason_code: str
    is_first_for_case: bool
    status: str
    decided_by_judge_id: Optional[str]
    decided_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ChangeOfVenueMotion(TypedDict):
    id: str
    case_id: str
    destination_court_id: str
    reason: str
    status: str
    decided_by_judge_id: Optional[str]
    decided_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class CaseReassignment(TypedDict):
    """Immutable ledger record: only id + created_at of the system fields."""

    id: str
    case_id: str
    from_court_id: str
    to_court_id: str
    reason: str
    executed_at: str
    created_at: str


class Decision(TypedDict):
    id: str
    case_id: str
    judge_id: str
    outcome: str
    source_hearing_id: Optional[str]
    issued_at: str
    appeal_deadline: str
    reopen_deadline: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class Appeal(TypedDict):
    id: str
    decision_id: str
    case_id: str
    grounds: Optional[str]
    filed_at: str
    status: str
    remand_instructions: Optional[str]
    decided_by_board_member_id: Optional[str]
    decided_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class MotionToReopen(TypedDict):
    id: str
    case_id: str
    decision_id: str
    basis: str
    filed_at: str
    status: str
    decided_by_judge_id: Optional[str]
    decided_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class DocketReview(TypedDict):
    """Immutable checkpoint snapshot: only id + created_at of the system fields."""

    id: str
    court_id: str
    run_index: int
    computed_at: str
    pending_case_count: int
    completions_ytd: int
    representation_rate_pct: float
    pace_ratio_calendar: float
    pace_ratio_hearing_day: float
    is_backlog_critical: bool
    is_on_pace: bool
    cases_finalized_by_lapse: int
    created_at: str
