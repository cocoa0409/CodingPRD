"""Domain types: entity TypedDicts, status enums, role enum."""
from enum import Enum
from typing import TypedDict, Optional, List


class ProgramStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    QUALITY_EMBARGO = "QUALITY_EMBARGO"
    FROZEN = "FROZEN"


class SpecUnitStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    COMPLETE = "COMPLETE"
    REJECTED = "REJECTED"


class PieceStatus(str, Enum):
    DECOMPOSED = "DECOMPOSED"
    IN_PRODUCTION = "IN_PRODUCTION"
    CONSENSUS = "CONSENSUS"
    CERTIFIED = "CERTIFIED"
    REJECTED = "REJECTED"
    REWORK = "REWORK"


class InstructionStatus(str, Enum):
    DRAFT = "DRAFT"
    PUBLISHED = "PUBLISHED"
    SUPERSEDED = "SUPERSEDED"


class ItemContainerStatus(str, Enum):
    DRAFT = "DRAFT"
    RELEASED = "RELEASED"
    IN_PANEL = "IN_PANEL"
    RESOLVED = "RESOLVED"


class ItemStatus(str, Enum):
    PENDING = "PENDING"
    ROUTED = "ROUTED"
    IN_REVIEW = "IN_REVIEW"
    COMPLETED = "COMPLETED"
    REWORK = "REWORK"


class ConsensusStatus(str, Enum):
    PENDING = "PENDING"
    AWAITING_CONSENSUS = "AWAITING_CONSENSUS"
    CERTIFIED = "CERTIFIED"
    HELD_QUORUM = "HELD_QUORUM"
    REJECTED = "REJECTED"
    REWORK = "REWORK"


class CommitStatus(str, Enum):
    DISPATCHED = "DISPATCHED"
    COMMITTED = "COMMITTED"
    ABSTAINED = "ABSTAINED"
    COMMIT_EXPIRED = "COMMIT_EXPIRED"


class CommitKind(str, Enum):
    PRODUCTION = "PRODUCTION"
    GOLD = "GOLD"


class PaymentStatus(str, Enum):
    UNPAID = "UNPAID"
    PENDING = "PENDING"
    ACCEPTED = "ACCEPTED"
    REVERSED = "REVERSED"


class GoldOutcome(str, Enum):
    PASSED = "PASSED"
    FLAGGED = "FLAGGED"
    FAILED = "FAILED"
    EXCLUDED_FROM_ACCURACY = "EXCLUDED_FROM_ACCURACY"


class QualificationStatus(str, Enum):
    IN_TRAINING = "IN_TRAINING"
    QUALIFIED = "QUALIFIED"
    PROBATION = "PROBATION"
    SUSPENDED = "SUSPENDED"
    REVOKED = "REVOKED"


class Tier(str, Enum):
    NOVICE = "NOVICE"
    PROFICIENT = "PROFICIENT"
    EXPERT = "EXPERT"


class SensitivityClass(str, Enum):
    STANDARD = "STANDARD"
    SENSITIVE = "SENSITIVE"
    RESTRICTED = "RESTRICTED"


class InstructionModel(str, Enum):
    IDEAL_RESPONSE = "IDEAL_RESPONSE"
    RANKED_PREFERENCE = "RANKED_PREFERENCE"
    SPAN_EXTRACTION = "SPAN_EXTRACTION"
    SAFETY_CLASSIFICATION = "SAFETY_CLASSIFICATION"


class IncidentSeverity(str, Enum):
    NONE = "NONE"
    MINOR = "MINOR"
    MAJOR = "MAJOR"
    CATASTROPHIC = "CATASTROPHIC"


class IncidentCategory(str, Enum):
    PII_EXPOSURE = "PII_EXPOSURE"
    DATASET_DOWNLOAD = "DATASET_DOWNLOAD"
    SCREEN_RECORDING = "SCREEN_RECORDING"
    UNAUTHORIZED_SHARE = "UNAUTHORIZED_SHARE"


class AppealStatus(str, Enum):
    ADVOCACY = "ADVOCACY"
    PROPOSED = "PROPOSED"
    CONCURRENCE = "CONCURRENCE"
    ADJUDICATION = "ADJUDICATION"
    ACCEPTED = "ACCEPTED"
    REVIEWER_SUSPENSION = "REVIEWER_SUSPENSION"
    REJECTED = "REJECTED"
    DEADLOCK = "DEADLOCK"


class AppealOutcome(str, Enum):
    PAY_REVERSAL = "PAY_REVERSAL"
    QUALIFICATION_RESET = "QUALIFICATION_RESET"
    OUTCOME_STANDS = "OUTCOME_STANDS"


class AppealGrounds(str, Enum):
    AMBIGUOUS_INSTRUCTIONS = "AMBIGUOUS_INSTRUCTIONS"
    INSUFFICIENT_CONTEXT = "INSUFFICIENT_CONTEXT"
    TECHNICAL_ERROR = "TECHNICAL_ERROR"


class WeekEpochStatus(str, Enum):
    OPEN = "OPEN"
    CLOSED = "CLOSED"


class UserRole(str, Enum):
    PLATFORM_ADMIN = "PlatformAdmin"
    PLATFORM_REVIEWER = "PlatformReviewer"
    WORKER = "Worker"
    ANONYMOUS = "Anonymous"


class ProgramAction(str, Enum):
    OPEN = "OPEN"
    ASSESS_CAPACITY = "ASSESS_CAPACITY"
    RECALL = "RECALL"
    FREEZE = "FREEZE"


class UnitAction(str, Enum):
    ACTIVATE = "ACTIVATE"
    REOPEN = "REOPEN"


class QualificationAction(str, Enum):
    ENROLL = "ENROLL"
    VERIFY = "VERIFY"
    RESET = "RESET"


class IncidentAction(str, Enum):
    REPORT = "REPORT"
    RESOLVE = "RESOLVE"


class ReviewerAction(str, Enum):
    RESOLVE_PANEL_DECISION = "RESOLVE_PANEL_DECISION"
    OPEN_REWORK = "OPEN_REWORK"


class AppealAction(str, Enum):
    PROPOSE = "PROPOSE"
    ESCALATE = "ESCALATE"
    SUSPEND = "SUSPEND"
    WITHDRAW = "WITHDRAW"


# --------------------------------------------------------------------------
# Entity TypedDicts. Every entity in this PRD carries the full common
# property set (id, created_at, updated_at, version).
# --------------------------------------------------------------------------

class CustomerProgram(TypedDict, total=False):
    id: str
    program_code: str
    name: str
    language_code: str
    instruction_model: str
    sensitivity_class: str
    incident_severity: str
    open_incident_count: int
    operational_restricted: bool
    min_consensus_agreement: float
    commitment_quorum: int
    commit_deadline_seconds: int
    weekly_earning_cap_cents: int
    patience_seconds: int
    deadline_utc: str
    blackout_start_utc: str
    blackout_end_utc: str
    coverage_hours: float
    capacity_points: int
    point_cost_high_accuracy: int
    point_cost_medium_accuracy: int
    point_cost_fallback: int
    accuracy_floor_pct: float
    accuracy_high_watermark_pct: float
    demand_points: int
    capacity_requirement_points: int
    capacity_multiplier: float
    capacity_feasible: bool
    projected_miss_deadline: bool
    accuracy_floor_variant_below: bool
    accepted_accuracy_pct: float
    provisional_accuracy_pct: float
    accuracy_denominator_count: int
    on_time: bool
    qa_sample_rate: float
    current_week_epoch_index: int
    status: str
    created_at: str
    updated_at: str
    version: int


class SpecUnit(TypedDict, total=False):
    id: str
    program_id: str
    unit_code: str
    parent_unit_id: Optional[str]
    max_items: int
    item_count: int
    instruction_revision: int
    instruction_status: str
    has_edge_case_guidance: bool
    edge_case_count: int
    field_schema: List[str]
    panel_size: int
    gold_rate: float
    coverage_start_utc: str
    coverage_end_utc: str
    piece_status: str
    frozen_revision: Optional[int]
    certified_item_count: int
    remaining_item_slots: int
    unit_ceiling_points: int
    unit_effective_points: int
    rework_point_multiplier: float
    unit_accuracy_pct: float
    unit_provisional_accuracy_pct: float
    status: str
    created_at: str
    updated_at: str
    version: int


class LabelingItem(TypedDict, total=False):
    id: str
    spec_unit_id: str
    item_key: str
    item_seq: int
    payload_uri: Optional[str]
    required_units: int
    instruction_revision: int
    item_status: str
    consensus_status: str
    non_abstaining_commit_count: int
    modal_label: Optional[str]
    agreement_ratio: float
    gold_audits_this_week: int
    gold_rotation: bool
    holds_quorum: bool
    rework_cycles: int
    rework_round_limit: int
    rework_started_at: Optional[str]
    rework_window_seconds: int
    rework_window_remaining_seconds: Optional[int]
    payout_complete: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class Commit(TypedDict, total=False):
    id: str
    item_id: str
    worker_id: str
    qualification_id: Optional[str]
    kind: str
    dispatch_rank: int
    payload: Optional[dict]
    committed_value: Optional[str]
    value_group_rank: Optional[int]
    is_modal_agent: bool
    is_superseded: bool
    instructions_ack: bool
    abstained: bool
    dispatched_at: str
    commit_deadline_at: str
    gold_outcome: Optional[str]
    expected_value: Optional[str]
    eligible_outcomes: Optional[List[str]]
    selected_anchor_commit_id: Optional[str]
    paid_amount_cents: int
    payment_status: str
    payment_capped: bool
    week_epoch_index: Optional[int]
    status: str
    created_at: str
    updated_at: str
    version: int


class WorkerIdentity(TypedDict, total=False):
    id: str
    handle: str
    display_name: Optional[str]
    payout_currency: str
    settlement_min_cents: int
    lifetime_earned_cents: int
    worker_receivable_cents: int
    restricted: bool
    total_accepted_payout_cents: int
    created_at: str
    updated_at: str
    version: int


class WorkerQualification(TypedDict, total=False):
    id: str
    worker_id: str
    language_code: str
    tier: str
    qualification_score: int
    tier_min_score: int
    tier_multiplier: float
    gold_audits_dispatched: int
    gold_denominator_count: int
    accepted_gold_count: int
    provisional_gold_count: int
    accuracy_pct: float
    provisional_accuracy_pct: float
    training_passed_count: int
    training_required_count: int
    gold_fail_streak: int
    restricted_accessible: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class ConfidentialityIncident(TypedDict, total=False):
    id: str
    program_id: str
    worker_id: str
    category: str
    severity: str
    description_text: str
    status: str
    created_at: str
    updated_at: str
    version: int


class AppealClaim(TypedDict, total=False):
    id: str
    program_id: str
    item_id: str
    worker_id: str
    spec_unit_id: str
    grounds: str
    statement_text: str
    requested_reviewer_id: Optional[str]
    adjudicator_id: Optional[str]
    proposed_outcome: Optional[str]
    revised_amount_cents: Optional[int]
    lock_reason: Optional[str]
    consensus_outcome: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class WeekEpoch(TypedDict, total=False):
    id: str
    index: int
    name: Optional[str]
    starts_at_utc: str
    status: str
    created_at: str
    updated_at: str
    version: int