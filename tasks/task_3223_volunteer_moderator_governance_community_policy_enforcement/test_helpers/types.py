"""Domain types for the volunteer moderation governance API.

Entity TypedDicts, status enums and the role enum. Entities whose rows carry
server-managed identity only (the protest approval join record) omit
``updated_at`` and ``version``.
"""
from enum import Enum
from typing import Any, List, Optional, TypedDict


class UserRole(str, Enum):
    ACCOUNT = "Account"
    MODERATOR = "Moderator"
    PLATFORM_ADMIN = "PlatformAdmin"
    ANONYMOUS = "Anonymous"
    CONTENT_REVIEWER = "ContentReviewer"
    SUCCESSION_AUDITOR = "SuccessionAuditor"


class CommunityState(str, Enum):
    ACTIVE = "ACTIVE"
    PROTEST_RESTRICTED = "PROTEST_RESTRICTED"
    RESTRICTED = "RESTRICTED"
    INSTITUTION_NEGOTIATION = "INSTITUTION_NEGOTIATION"
    QUARANTINED = "QUARANTINED"
    ARCHIVED = "ARCHIVED"


class RuleStatus(str, Enum):
    ACTIVE = "ACTIVE"
    RETIRED = "RETIRED"


class ModeratorStatus(str, Enum):
    ACTIVE = "ACTIVE"
    REMOVED_FOR_INACTIVITY = "REMOVED_FOR_INACTIVITY"
    RESIGNED = "RESIGNED"
    DEMOTED = "DEMOTED"


class ModeratorRole(str, Enum):
    TOP_MODERATOR = "TOP_MODERATOR"
    REGULAR_MODERATOR = "REGULAR_MODERATOR"


class RemovalReasonCode(str, Enum):
    INACTIVITY = "INACTIVITY"
    RESIGNATION = "RESIGNATION"
    TOP_DISPUTE_LOSS = "TOP_DISPUTE_LOSS"
    ADMIN_ARCHIVAL = "ADMIN_ARCHIVAL"


class SuccessionState(str, Enum):
    PENDING_HANDOVER = "PENDING_HANDOVER"
    DISCUSSION = "DISCUSSION"
    HANDOVER_BLOCKED = "HANDOVER_BLOCKED"
    COMPLETED = "COMPLETED"


class SuccessionCompletionReason(str, Enum):
    HANDOVER_ACCEPTED = "HANDOVER_ACCEPTED"
    ALL_MODERATORS_INACTIVE = "ALL_MODERATORS_INACTIVE"
    PREVENTED_BY_DISPUTE = "PREVENTED_BY_DISPUTE"


class PostStatus(str, Enum):
    PUBLISHED = "PUBLISHED"
    REMOVED = "REMOVED"
    LOCKED = "LOCKED"


class PostType(str, Enum):
    TEXT = "TEXT"
    LINK = "LINK"
    IMAGE = "IMAGE"
    CROSSPOST = "CROSSPOST"


class ReportStatus(str, Enum):
    OPEN = "OPEN"
    RESOLVED = "RESOLVED"
    RESOLVED_LOCKED = "RESOLVED_LOCKED"
    DISMISSED = "DISMISSED"


class ReportReasonCode(str, Enum):
    SPAM = "SPAM"
    HARASSMENT = "HARASSMENT"
    HATE_SPEECH = "HATE_SPEECH"
    VIOLENCE = "VIOLENCE"
    MINOR_SAFETY = "MINOR_SAFETY"
    BRIGADING = "BRIGADING"
    VOTE_MANIPULATION = "VOTE_MANIPULATION"
    IMPERSONATION = "IMPERSONATION"


class ContentSourceType(str, Enum):
    POST = "POST"
    COMMENT = "COMMENT"
    ACCOUNT = "ACCOUNT"


class BacklogStatus(str, Enum):
    OPEN = "OPEN"
    CONSUMED = "CONSUMED"
    DISMISSED = "DISMISSED"


class DecisionOutcome(str, Enum):
    KEEP = "KEEP"
    REMOVE = "REMOVE"
    LOCK = "LOCK"
    REPORT_REJECTED = "REPORT_REJECTED"
    WARNING_ISSUED = "WARNING_ISSUED"
    MUTE_ISSUED = "MUTE_ISSUED"
    BAN_ISSUED = "BAN_ISSUED"


class DecisionStatus(str, Enum):
    RECORDED = "RECORDED"
    AUDITED = "AUDITED"
    REVISED = "REVISED"
    SETTLED = "SETTLED"


class LegitimacyBand(str, Enum):
    LOW = "LOW"
    MID = "MID"
    HIGH = "HIGH"


class SanctionStatus(str, Enum):
    ACTIVE = "ACTIVE"
    LIFTED = "LIFTED"


class ClusterStatus(str, Enum):
    DETECTED = "DETECTED"
    ESCALATED = "ESCALATED"
    DISMISSED = "DISMISSED"


class AppealState(str, Enum):
    FILED = "FILED"
    SUBMITTED = "SUBMITTED"
    UNDER_WATCH = "UNDER_WATCH"
    GRANTED = "GRANTED"
    DENIED = "DENIED"


class AppealGroundCode(str, Enum):
    ANALYSIS_ERROR = "ANALYSIS_ERROR"
    MODERATOR_MISCONDUCT = "MODERATOR_MISCONDUCT"


class AppealDecisionReasonCode(str, Enum):
    ANALYSIS_ERROR_CONFIRMED = "ANALYSIS_ERROR_CONFIRMED"
    MISCONDUCT_CONFIRMED = "MISCONDUCT_CONFIRMED"
    MISAPPLICATION_CONFIRMED = "MISAPPLICATION_CONFIRMED"
    NO_NEW_EVIDENCE = "NO_NEW_EVIDENCE"


class ProtestAccessMode(str, Enum):
    READ_ONLY = "READ_ONLY"
    RESTRICTED = "RESTRICTED"
    PRIVATE = "PRIVATE"


class ProtestStatus(str, Enum):
    REQUESTED = "REQUESTED"
    COORDINATED = "COORDINATED"
    ENDED = "ENDED"


class AccountState(str, Enum):
    HONORED = "HONORED"
    WARNED = "WARNED"
    MUTED = "MUTED"
    BANNED = "BANNED"


# --- entities carrying id + created_at + updated_at + version ----------------

class Community(TypedDict):
    id: str
    name: str
    description: str
    is_over_18: bool
    state: str
    enforcement_tier: int
    health_index: float
    open_report_weight: float
    inactive_moderator_count: int
    active_top_moderator_count: int
    active_moderator_count: int
    active_rule_count: int
    applying_sanction_count: int
    quarantine_approval_count: int
    quarantine_reinstatement_count: int
    restricted_since_utc: Optional[str]
    protest_exemption_until_utc: Optional[str]
    created_at: str
    updated_at: str
    version: int


class CommunityRule(TypedDict):
    id: str
    community_id: str
    rule_code: str
    rule_text: str
    rule_band: int
    is_sitewide_floor: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class Moderator(TypedDict):
    id: str
    community_id: str
    moderator_account_id: str
    display_name: str
    moderator_role: str
    is_top_moderator: bool
    top_rank: int
    last_moderation_action_at_utc: Optional[str]
    inactivity_basis_utc: Optional[str]
    status: str
    moderator_version: int
    promoted_at_utc: Optional[str]
    removal_reason_code: Optional[str]
    created_at: str
    updated_at: str
    version: int


class TeamSuccession(TypedDict):
    id: str
    community_id: str
    state: str
    initiated_at_utc: str
    previous_state: str
    discussion_round_count: int
    handover_deadline_utc: str
    blocked_by_moderator_id: Optional[str]
    completion_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Post(TypedDict):
    id: str
    community_id: str
    author_account_id: str
    title: str
    body: str
    post_type: str
    is_over_18: bool
    status: str
    removal_count: int
    created_at: str
    updated_at: str
    version: int


class Account(TypedDict):
    id: str
    handle: str
    home_community_id: str
    account_state: str
    karma_points: int
    account_sanction_index: float
    created_at: str
    updated_at: str
    version: int


class ContentReport(TypedDict):
    id: str
    community_id: str
    content_source_type: str
    content_source_id: str
    reporter_account_id: str
    report_reason_code: str
    resolution_tier: int
    status: str
    detection_backlog_item_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class AutoDetectionBacklogItem(TypedDict):
    id: str
    community_id: str
    source_type: str
    source_id: str
    subject_account_id: str
    signal_severity_band: int
    detection_confidence: float
    overlap_ratio: float
    published_at_utc: str
    status: str
    legitimacy_score: int
    legitimacy_band: str
    created_at: str
    updated_at: str
    version: int


class ContentDecision(TypedDict):
    id: str
    community_id: str
    auto_detection_backlog_item_id: str
    decision_outcome: str
    decision_confidence: float
    dissection_band: int
    precedent_approval_count: int
    community_health_index_override_present: bool
    overlap_ratio: float
    is_account_wide: bool
    effective_enforcement_tier: int
    community_safety_override: bool
    requires_cross_power_approval: bool
    status: str
    audit_log_ref: str
    created_at: str
    updated_at: str
    version: int


class AccountSanction(TypedDict):
    id: str
    community_id: str
    account_id: str
    decision_id: str
    decision_outcome: str
    status: str
    account_wide_enforcement_counted: bool
    award_points: int
    sanction_date_utc: str
    sanitized_on_utc: Optional[str]
    created_at: str
    updated_at: str
    version: int


class BrigadingCluster(TypedDict):
    id: str
    community_id: str
    internal_link_count: int
    external_link_count: int
    participant_count: int
    legitimate_participant_count: int
    overlap_ratio: float
    signal_severity_band: int
    evidence_complete: bool
    escalation_severity: Optional[int]
    status: str
    detected_at_utc: str
    created_at: str
    updated_at: str
    version: int


class Appeal(TypedDict):
    id: str
    community_id: str
    account_id: str
    sanction_id: str
    ground_code: str
    new_evidence_url: Optional[str]
    sanction_misapplication_present: bool
    state: str
    decision_reason_code: Optional[str]
    filed_at_utc: str
    submitted_at_utc: Optional[str]
    deadline_utc: Optional[str]
    last_referred_at_utc: Optional[str]
    referral_count: int
    created_at: str
    updated_at: str
    version: int


class ProtestEvent(TypedDict):
    id: str
    community_id: str
    requested_access_mode: str
    status: str
    quorum_approval_count: int
    required_quorum_count: int
    distinct_power_count: int
    conflicting_cross_power_account_ids: List[str]
    started_at_utc: Optional[str]
    ended_at_utc: Optional[str]
    exemption_granted_until_utc: Optional[str]
    created_at: str
    updated_at: str
    version: int


# --- append-only join record: id + created_at only ---------------------------

class ProtestApproval(TypedDict):
    id: str
    protest_id: str
    moderator_id: str
    approving_account_id: str
    approved_on_utc: str
    created_at: str


class EscalationRecord(TypedDict):
    rule_id: str
    escalation_note: str
    escalated_at_utc: str


class ModerationAction(TypedDict):
    moderator_id: str
    action_kind: str
    action_at_utc: str


ENTITY_TYPES = {
    "community": Community,
    "rule": CommunityRule,
    "moderator": Moderator,
    "succession": TeamSuccession,
    "post": Post,
    "account": Account,
    "content_report": ContentReport,
    "detection_backlog_item": AutoDetectionBacklogItem,
    "content_decision": ContentDecision,
    "account_sanction": AccountSanction,
    "brigading_cluster": BrigadingCluster,
    "appeal": Appeal,
    "protest": ProtestEvent,
}