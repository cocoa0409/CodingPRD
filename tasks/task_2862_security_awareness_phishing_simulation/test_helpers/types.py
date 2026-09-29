"""TypedDict shapes for every entity and computed payload of the awareness program API.

Three entities are append only and therefore carry `id` and `created_at` but
neither `updated_at` nor `version`: `InteractionEvent`, `IncidentRecord` and
`CommunicationWindow`.  Every other entity carries the full identity block.
"""

from __future__ import annotations

from typing import Any, List, Optional, TypedDict


class MutableIdentity(TypedDict):
    """Identity block of a versioned, mutable entity."""

    id: str
    created_at: str
    updated_at: str
    version: int


class AppendOnlyIdentity(TypedDict):
    """Identity block of an append-only entity."""

    id: str
    created_at: str


class Employee(MutableIdentity, total=False):
    email: str
    full_name: str
    department: str
    role_code: str
    hire_date: str
    manager_id: Optional[str]
    employment_status: str
    compliance_state: str
    access_posture: str
    tenure_band: str
    active_suspension_count: int
    repeat_clicker_tier: int
    consecutive_clean_simulations: int
    reserved_simulation_slots: int
    risk_score_provisional: float
    risk_score_settled: float


class TrainingModule(MutableIdentity, total=False):
    code: str
    title: str
    module_type: str
    applies_to_role_codes: List[str]
    criticality: str
    passing_score_pct: int
    reminder_offsets_days: List[int]
    escalate_after_reminders: int
    max_extension_days: int
    state: str


class CurriculumAssignment(MutableIdentity, total=False):
    employee_id: str
    module_id: str
    assignment_reason: str
    state: str
    due_at: str
    granted_extension_days: int
    effective_due_at: str
    days_overdue: int
    escalation_level: int
    reminders_sent: int
    next_reminder_due_at: Optional[str]
    attempt_count: int
    last_score_pct: Optional[int]
    started_at: Optional[str]
    completed_at: Optional[str]
    void_reason_code: Optional[str]
    superseded_by_assignment_id: Optional[str]


class EscalationNotice(MutableIdentity, total=False):
    assignment_id: str
    manager_id: str
    level: int
    state: str
    sent_at: str
    acknowledged_at: Optional[str]
    action_plan_note: Optional[str]


class AccessConsequence(MutableIdentity, total=False):
    employee_id: str
    source_assignment_id: Optional[str]
    consequence_type: str
    severity_rank: int
    state: str
    reason_code: str
    applied_at: str
    lifted_at: Optional[str]
    lift_reason_code: Optional[str]


class PhishingTemplate(MutableIdentity, total=False):
    name: str
    pretext_category: str
    difficulty_tier: str
    theme_tags: List[str]
    harmful_flag_hits: List[str]
    credential_capture_enabled: bool
    review_state: str
    blocked_reason: Optional[str]


class PhishingCampaign(MutableIdentity, total=False):
    name: str
    template_id: str
    difficulty_tier: str
    author_user_id: str
    reviewer_user_id: Optional[str]
    state: str
    target_departments: List[str]
    target_tenure_bands: List[str]
    target_min_repeat_tier: int
    communication_policy_ack: bool
    rejection_reason: Optional[str]
    debrief_note: Optional[str]
    scheduled_send_at: Optional[str]
    launched_at: Optional[str]
    closed_at: Optional[str]
    cancelled_at: Optional[str]
    target_count: int
    evaluable_count: int
    click_rate: Optional[float]
    report_rate: Optional[float]
    credential_rate: Optional[float]
    resilience_ratio: Optional[float]


class SimulationDelivery(MutableIdentity, total=False):
    campaign_id: str
    employee_id: str
    state: str
    effective_difficulty_tier: str
    outcome_class: str
    delivered_at: Optional[str]
    quiet_period_until: Optional[str]
    first_click_at: Optional[str]
    first_report_at: Optional[str]
    credential_submitted_at: Optional[str]
    time_to_report_minutes: Optional[int]
    excluded_reason: Optional[str]


class InteractionEvent(AppendOnlyIdentity, total=False):
    delivery_id: str
    event_type: str
    occurred_at: str
    source: str
    sequence_index: int
    superseding_effect: str


class RepeatClickerIntervention(MutableIdentity, total=False):
    employee_id: str
    triggering_delivery_id: str
    tier_at_open: int
    current_tier: int
    simulation_frequency_days: int
    state: str
    opened_at: str
    coaching_assignment_id: Optional[str]
    tier_decay_applied: bool
    resolution_code: Optional[str]
    closed_at: Optional[str]


class IncidentRecord(AppendOnlyIdentity, total=False):
    incident_type: str
    severity: str
    department: str
    occurred_at: str
    summary: str
    root_cause_employee_id: Optional[str]
    phish_related: bool


class CommunicationWindow(AppendOnlyIdentity, total=False):
    window_type: str
    start_at: str
    end_at: str
    reason: str
    scope_department: Optional[str]


class ComplianceSweepResult(TypedDict, total=False):
    assignments_scanned: int
    reminders_sent_count: int
    overdue_count: int
    escalations_created_count: int
    consequences_applied_count: int
    swept_at: str


class ClockState(TypedDict, total=False):
    current_utc: str
    previous_utc: str


class ScorecardSegment(TypedDict, total=False):
    key: str
    click_rate: Optional[float]
    report_rate: Optional[float]
    credential_rate: Optional[float]
    resilience_ratio: Optional[float]


class CampaignScorecard(TypedDict, total=False):
    campaign_id: str
    click_rate: Optional[float]
    report_rate: Optional[float]
    credential_rate: Optional[float]
    resilience_ratio: Optional[float]
    department_segments: Any
    tenure_band_segments: Any


class EffectivenessBucket(TypedDict, total=False):
    report_rate: Optional[float]
    incident_count: int


class EffectivenessReport(TypedDict, total=False):
    variant: str
    buckets: List[EffectivenessBucket]
    pair_count: int
    mean_report_rate: Optional[float]
    total_incidents: int
    correlation: Optional[float]
    correlation_reason_code: Optional[str]
