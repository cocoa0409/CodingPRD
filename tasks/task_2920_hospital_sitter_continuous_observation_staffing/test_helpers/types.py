"""
Typed shapes for the resources the API returns, transcribed from the PRD's field
declarations.

Note the deliberate asymmetry required by PRD section 2.4: every entity carries
``id``, ``created_at``, ``updated_at`` and ``version`` *except* the reassessment
record, which "carries only ``id`` and ``created_at``" and has "no ``updated_at``
and no ``version`` field at all". ``Reassessment`` below therefore does not
inherit the common-field base.
"""

from typing import Any, Dict, List, Optional, TypedDict


class CommonFields(TypedDict):
    """id + created_at + updated_at + version (PRD 2.4)."""

    id: str
    created_at: str
    updated_at: str
    version: int


class Unit(CommonFields, total=False):
    unit_code: str
    name: str
    observation_cost_budget_cents: int
    video_monitoring_enabled: bool
    status: str
    restriction_reason: Optional[str]
    observed_cost_to_date_cents: int
    open_order_count: int


class Patient(CommonFields, total=False):
    unit_id: str
    mrn: str
    full_name: str
    age_years: int
    status: str
    discharged_at: Optional[str]


class Staff(CommonFields, total=False):
    home_unit_id: str
    full_name: str
    source_pool: str
    hourly_rate_cents: int
    competency_level: str
    deescalation_cert_expires_on: str
    status: str
    suspension_reason: Optional[str]
    last_shift_end_at: Optional[str]
    total_watch_minutes: int


class ObservationOrder(CommonFields, total=False):
    patient_id: str
    ordering_provider_user_id: str
    risk_categories: List[str]
    required_modality: str
    clinical_rationale: str
    status: str
    elopement_risk_score: float
    risk_score_variant: str
    reassessment_interval_hours: int
    last_reassessed_at: Optional[str]
    next_reassessment_due_at: Optional[str]
    reassessment_count: int
    coverage_gap_flag: bool
    discontinuation_recommendation: Optional[str]
    discontinuation_review_opened_by_user_id: Optional[str]
    discontinued_at: Optional[str]
    lapsed_at: Optional[str]


class Reassessment(TypedDict, total=False):
    """The one entity with no ``updated_at`` and no ``version`` (PRD 2.4)."""

    id: str
    created_at: str
    order_id: str
    performed_by_user_id: str
    risk_categories_after: List[str]
    score_before: float
    score_after: float
    interval_hours_after: int
    reassessed_at: str


class SitterAssignment(CommonFields, total=False):
    order_id: str
    staff_id: str
    shift_start_at: str
    shift_end_at: str
    scheduled_minutes: int
    watch_status: str
    documentation_status: str
    provisional_cost_cents: int
    final_cost_cents: Optional[int]
    current_segment_started_at: Optional[str]
    break_started_at: Optional[str]
    watch_segment_count: int
    watched_minutes: int
    completion_reason: Optional[str]
    voided_at: Optional[str]
    float_authorization_code: Optional[str]


class HandoffRecord(CommonFields, total=False):
    outgoing_assignment_id: str
    incoming_assignment_id: str
    behavior_summary: str
    interventions_used: List[str]
    documentation_state: str
    countersigned_by_staff_id: Optional[str]
    countersigned_at: Optional[str]


class MonitoringStation(CommonFields, total=False):
    observer_staff_id: str
    station_label: str
    declared_max_span: int
    status: str
    active_feed_count: int
    active_acuity_weight: float
    effective_span_limit: int
    offlined_at: Optional[str]


class VideoFeed(CommonFields, total=False):
    station_id: str
    order_id: str
    monitor_start_at: str
    monitor_end_at: str
    status: str
    acuity_weight: float
    release_reason: Optional[str]
    released_at: Optional[str]


class SafetyEvent(CommonFields, total=False):
    order_id: str
    assignment_id: Optional[str]
    event_kind: str
    narrative: str
    status: str
    occurred_at: str
    reported_by_staff_id: str
    response_actions: Optional[List[str]]
    review_opened_by_user_id: Optional[str]
    review_findings: Optional[str]
    closed_by_user_id: Optional[str]
    resolution: Optional[str]


class CostEntry(CommonFields, total=False):
    unit_id: str
    assignment_id: str
    entry_kind: str
    amount_cents: int
    status: str
    posted_at: str
    reversed_at: Optional[str]
    source_pool: str
    night_differential_applied: bool
    segment_index: Optional[int]
    segment_minutes: Optional[int]


class CostCloseResult(TypedDict, total=False):
    """The cost-close response body; none of the four figures is persisted."""

    subtotal_cents: int
    coverage_surcharge_pct: float
    coverage_surcharge_cents: int
    charge_total_cents: int
    unit_status: str
    unit_version: int


class ClockResult(TypedDict, total=False):
    current_utc: str
    orders_marked_reassessment_due: int
    orders_lapsed: int


Json = Dict[str, Any]
