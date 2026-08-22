"""Domain types for the Return-To-Work & Modified Duty Program API.

Entity TypedDicts, status enums and the role enum, all named exactly as the
PRD names them.
"""
from enum import Enum
from typing import Any, Dict, List, Optional, TypedDict


# ─── Roles ────────────────────────────────────────────────────────────────

class UserRole(str, Enum):
    PROGRAM_ADMIN = "ProgramAdmin"
    RTW_COORDINATOR = "RTWCoordinator"
    OCC_HEALTH_NURSE = "OccHealthNurse"
    CLAIM_ADJUSTER = "ClaimAdjuster"
    TREATING_PROVIDER = "TreatingProvider"
    SUPERVISOR = "Supervisor"
    EMPLOYEE = "Employee"


# ─── Status enums ─────────────────────────────────────────────────────────

class EmploymentStatus(str, Enum):
    ACTIVE = "ACTIVE"
    ON_LEAVE = "ON_LEAVE"
    SEPARATED = "SEPARATED"


class BenefitTier(str, Enum):
    TIER_A = "TIER_A"
    TIER_B = "TIER_B"
    TIER_C = "TIER_C"


class ClaimStatus(str, Enum):
    OPEN = "OPEN"
    RTW_ELIGIBLE = "RTW_ELIGIBLE"
    SUSPENDED = "SUSPENDED"
    CLOSED = "CLOSED"


class RtwPosture(str, Enum):
    OPEN = "OPEN"
    RESTRICTED = "RESTRICTED"
    FROZEN = "FROZEN"


class CredentialStatus(str, Enum):
    VERIFIED = "VERIFIED"
    PROVISIONAL = "PROVISIONAL"
    REVOKED = "REVOKED"


class RestrictionSetStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    CLARIFICATION_REQUESTED = "CLARIFICATION_REQUESTED"
    VERIFIED = "VERIFIED"
    ACTIVE = "ACTIVE"
    SUPERSEDED = "SUPERSEDED"
    EXPIRED = "EXPIRED"


class OversightStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class TrainingStatus(str, Enum):
    VALID = "VALID"
    EXPIRING_SOON = "EXPIRING_SOON"
    EXPIRED = "EXPIRED"
    NONE = "NONE"


class CurriculumCode(str, Enum):
    RTW_CORE = "RTW_CORE"
    RESTRICTION_HANDLING = "RESTRICTION_HANDLING"
    REINJURY_RESPONSE = "REINJURY_RESPONSE"


class TrainingRecordStatus(str, Enum):
    VALID = "VALID"
    EXPIRING_SOON = "EXPIRING_SOON"
    EXPIRED = "EXPIRED"
    SUPERSEDED = "SUPERSEDED"


class JobStatus(str, Enum):
    OPEN = "OPEN"
    PAUSED = "PAUSED"
    RETIRED = "RETIRED"


class RiskClass(str, Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"


class PlacementStatus(str, Enum):
    PROPOSED = "PROPOSED"
    ADJUSTER_PENDING = "ADJUSTER_PENDING"
    ACTIVE = "ACTIVE"
    PROGRESSION_HOLD = "PROGRESSION_HOLD"
    SUSPENDED = "SUSPENDED"
    COMPLETED = "COMPLETED"
    TERMINATED_EARLY = "TERMINATED_EARLY"
    DECLINED = "DECLINED"


class ComplianceStatus(str, Enum):
    COMPLIANT = "COMPLIANT"
    WATCH = "WATCH"
    NONCOMPLIANT = "NONCOMPLIANT"
    REMEDIATED = "REMEDIATED"


class SuspensionReason(str, Enum):
    RESTRICTION_CONFLICT = "RESTRICTION_CONFLICT"
    MEDICAL_HOLD = "MEDICAL_HOLD"
    OPERATIONAL = "OPERATIONAL"


class ReinjuryRiskVariant(str, Enum):
    BASELINE = "BASELINE"
    SURVEILLANCE = "SURVEILLANCE"


class BenefitContinuationStatus(str, Enum):
    PENDING = "PENDING"
    EMPLOYER_SUBSIDIZED = "EMPLOYER_SUBSIDIZED"
    EMPLOYEE_PAID = "EMPLOYEE_PAID"
    LAPSED = "LAPSED"


class DirectiveStatus(str, Enum):
    PENDING = "PENDING"
    AUTHORIZED = "AUTHORIZED"
    AUTHORIZED_WITH_CONDITIONS = "AUTHORIZED_WITH_CONDITIONS"
    DENIED = "DENIED"
    SUPERSEDED = "SUPERSEDED"


class ReviewStatus(str, Enum):
    """ProgressionReview.review_status."""
    SCHEDULED = "SCHEDULED"
    IN_REVIEW = "IN_REVIEW"
    ADVANCED = "ADVANCED"
    EXTENDED = "EXTENDED"
    ESCALATED = "ESCALATED"


class FindingSeverity(str, Enum):
    NONE = "NONE"
    MINOR = "MINOR"
    MAJOR = "MAJOR"
    CRITICAL = "CRITICAL"


class FindingCode(str, Enum):
    RESTRICTION_DEVIATION = "RESTRICTION_DEVIATION"
    HOURS_DEVIATION = "HOURS_DEVIATION"
    SUPERVISION_GAP = "SUPERVISION_GAP"
    DOCUMENTATION = "DOCUMENTATION"
    NONE = "NONE"


class WageVariant(str, Enum):
    PROVISIONAL = "PROVISIONAL"
    FINAL = "FINAL"


class WageEntryStatus(str, Enum):
    POSTED = "POSTED"
    REVERSED = "REVERSED"
    REVERSAL = "REVERSAL"


class ReinjurySeverity(str, Enum):
    NEAR_MISS = "NEAR_MISS"
    MINOR = "MINOR"
    SIGNIFICANT = "SIGNIFICANT"
    SEVERE = "SEVERE"


class ReportStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    TRIAGED = "TRIAGED"
    ESCALATED = "ESCALATED"


class CaseReviewStatus(str, Enum):
    OPEN = "OPEN"
    VOTING = "VOTING"
    DECIDED_CONTINUE = "DECIDED_CONTINUE"
    DECIDED_MODIFY = "DECIDED_MODIFY"
    DECIDED_TERMINATE = "DECIDED_TERMINATE"


class CaseReviewTrigger(str, Enum):
    REINJURY = "REINJURY"
    RESTRICTION_CONFLICT = "RESTRICTION_CONFLICT"
    DURATION_CAP = "DURATION_CAP"
    COMPLIANCE_CRITICAL = "COMPLIANCE_CRITICAL"
    ADJUSTER_DENIAL = "ADJUSTER_DENIAL"


class Ballot(str, Enum):
    CONTINUE = "CONTINUE"
    MODIFY = "MODIFY"
    TERMINATE = "TERMINATE"


class VoteStatus(str, Enum):
    COUNTED = "COUNTED"
    SUPERSEDED = "SUPERSEDED"


# ─── Entity shapes ────────────────────────────────────────────────────────
# Resources that carry id + created_at + updated_at + version.

class Employee(TypedDict):
    id: str
    full_name: str
    employee_number: str
    department_code: str
    pre_injury_weekly_wage_cents: int
    pre_injury_weekly_hours: float
    benefit_tier: str
    employment_status: str
    open_claim_count: int
    created_at: str
    updated_at: str
    version: int


class Claim(TypedDict):
    id: str
    employee_id: str
    claim_number: str
    adjuster_user_id: str
    injury_date: str
    claim_status: str
    max_authorized_weekly_cost_cents: int
    rtw_posture: str
    cumulative_transitional_days: int
    wage_differential_paid_cents: int
    active_restriction_set_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class TreatingProvider(TypedDict):
    id: str
    full_name: str
    npi: str
    specialty: str
    credential_status: str
    created_at: str
    updated_at: str
    version: int


class RestrictionSet(TypedDict):
    id: str
    claim_id: str
    treating_provider_id: str
    supersedes_restriction_set_id: Optional[str]
    status: str
    effective_from: str
    valid_through: str
    max_lift_lbs: float
    max_continuous_standing_minutes: float
    max_hours_per_day: float
    keyboard_minutes_per_hour: float
    overhead_reach_allowed: bool
    driving_allowed: bool
    clarification_note: Optional[str]
    clarification_round_count: int
    severity_index: int
    active_placement_count: int
    created_at: str
    updated_at: str
    version: int


class Supervisor(TypedDict):
    id: str
    full_name: str
    department_code: str
    oversight_status: str
    compliance_strike_points: int
    strike_forgiveness_points: int
    effective_strike_points: int
    training_status: str
    created_at: str
    updated_at: str
    version: int


class TrainingRecord(TypedDict):
    id: str
    supervisor_id: str
    curriculum_code: str
    completed_on: str
    valid_through: str
    record_status: str
    renewal_count: int
    created_at: str
    updated_at: str
    version: int


class TransitionalJob(TypedDict):
    id: str
    supervisor_id: str
    title: str
    department_code: str
    seat_capacity: int
    filled_seats: int
    demand_lift_lbs: float
    demand_standing_minutes: float
    demand_hours_per_day: float
    demand_keyboard_minutes_per_hour: float
    requires_overhead_reach: bool
    requires_driving: bool
    hourly_rate_cents: int
    risk_class: str
    job_status: str
    created_at: str
    updated_at: str
    version: int


class Placement(TypedDict):
    id: str
    claim_id: str
    restriction_set_id: str
    transitional_job_id: str
    supervisor_id: str
    created_by_user_id: str
    placement_status: str
    compliance_status: str
    start_date: str
    end_date: str
    scheduled_hours_per_day: float
    activated_on: Optional[str]
    ended_on: Optional[str]
    suspension_reason: Optional[str]
    decline_reason: Optional[str]
    logged_hours: List[Dict[str, Any]]
    progression_step: int
    match_score: float
    reinjury_risk_score: int
    reinjury_risk_variant: str
    cumulative_days: int
    employer_premium_share_cents: int
    employee_premium_share_cents: int
    benefit_continuation_status: str
    projected_weekly_cost_cents: int
    current_adjuster_directive_id: Optional[str]
    current_progression_review_id: Optional[str]
    open_case_review_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class AdjusterDirective(TypedDict):
    id: str
    placement_id: str
    directive_status: str
    requested_weekly_cost_cents: int
    authorized_weekly_cost_cents: int
    condition_note: Optional[str]
    denial_reason: Optional[str]
    decided_by_user_id: Optional[str]
    decided_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ProgressionReview(TypedDict):
    id: str
    placement_id: str
    step_index: int
    due_date: str
    review_status: str
    deferral_count: int
    reviewed_by_user_id: Optional[str]
    target_hours_per_day: Optional[float]
    target_lift_lbs: Optional[float]
    outcome_note: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ReinjuryReport(TypedDict):
    id: str
    placement_id: str
    reported_by_user_id: str
    occurred_on: str
    severity: str
    body_part_code: str
    mechanism_code: str
    report_status: str
    triage_note: Optional[str]
    risk_points_applied: int
    created_at: str
    updated_at: str
    version: int


class CaseReview(TypedDict):
    id: str
    placement_id: str
    trigger_reason: str
    review_status: str
    quorum_required: int
    opened_by_user_id: str
    vote_count: int
    continue_votes: int
    modify_votes: int
    terminate_votes: int
    decision_ratio: float
    winning_ballot: Optional[str]
    closed_by_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


# Append-only observations: id + created_at only — no updated_at, no version.

class ComplianceAudit(TypedDict):
    id: str
    placement_id: str
    auditor_user_id: str
    observed_on: str
    finding_severity: str
    finding_code: str
    restriction_deviation_detected: bool
    corrective_action_note: Optional[str]
    created_at: str


class WageDifferentialEntry(TypedDict):
    id: str
    placement_id: str
    claim_id: str
    reverses_entry_id: Optional[str]
    variant: str
    period_start: str
    period_end: str
    counted_day_count: int
    tier_multiplier: float
    gross_differential_cents: int
    offset_cents: int
    net_amount_cents: int
    entry_status: str
    created_at: str


class CaseReviewVote(TypedDict):
    id: str
    case_review_id: str
    voter_user_id: str
    voter_role: str
    ballot: str
    rationale: Optional[str]
    vote_status: str
    created_at: str


APPEND_ONLY_ENTITIES = ("ComplianceAudit", "WageDifferentialEntry", "CaseReviewVote")
