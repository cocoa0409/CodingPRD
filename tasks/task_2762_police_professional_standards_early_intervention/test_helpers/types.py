"""Typed shapes for every entity the API returns.

Each TypedDict mirrors the field list the contract declares for that resource.
Unit, HearingRoom and OfficerActivityEvent are append-only records that carry
only an identifier and a creation timestamp, so their shapes deliberately omit
``updated_at`` and ``version``; every other resource carries the full quartet.
"""

from typing import Optional, TypedDict


class ResponseMeta(TypedDict, total=False):
    """The meta block that accompanies every response."""

    api_request_id: str
    api_request_timestamp: str
    response_type: str
    limit: int
    offset: int
    total_count: int
    has_more: bool


class Unit(TypedDict):
    id: str
    created_at: str
    name: str
    unit_role: str
    command_code: str
    peer_group_code: str
    sworn_headcount: int
    intake_enabled: bool


class HearingRoom(TypedDict):
    id: str
    created_at: str
    facility_code: str
    room_name: str
    concurrent_capacity: int
    recording_enabled: bool


class OfficerActivityEvent(TypedDict):
    id: str
    created_at: str
    officer_id: str
    event_type: str
    severity_code: str
    occurred_at: str
    source_reference: Optional[str]
    base_weight: float
    weekday_index: int
    system_generated: bool


class Officer(TypedDict):
    id: str
    created_at: str
    updated_at: str
    version: int
    unit_id: str
    badge_number: str
    full_name: str
    rank: str
    assignment_type: str
    is_investigator: bool
    certification_level: int
    max_case_load: int
    annual_salary_cents: int
    demographic_code: str
    hire_date: str
    employment_status: str
    eis_score: float
    eis_alert_level: str
    open_case_load: int
    imposed_suspension_days_total: int
    open_alert_count: int
    intervention_escalation_count: int
    credibility_disclosure_active: bool
    suspension_end_date: Optional[str]


class Complaint(TypedDict):
    id: str
    created_at: str
    updated_at: str
    version: int
    intake_channel: str
    complainant_name: Optional[str]
    complainant_contact: Optional[str]
    complainant_demographic_code: str
    narrative: Optional[str]
    incident_datetime: str
    alleged_injury: bool
    reported_allegation_types: list
    subject_unit_id: str
    reporting_supervisor_officer_id: Optional[str]
    intake_sequence: int
    intake_reference_code: Optional[str]
    classification: str
    priority: int
    assigned_unit_id: str
    screening_required: bool
    statute_expires_at: str
    status: str
    received_at: str
    closed_at: Optional[str]
    retention_until: Optional[str]
    allegation_count: int
    sustained_allegation_count: int
    reclassification_count: int
    purged_at: Optional[str]


class Allegation(TypedDict):
    id: str
    created_at: str
    updated_at: str
    version: int
    complaint_id: str
    subject_officer_id: str
    allegation_type: str
    narrative: Optional[str]
    offense_class: str
    evidence_weight_for: float
    evidence_weight_against: float
    policy_compliant: bool
    support_pct: float
    preponderance_met: bool
    disposition: str
    disposed_at: Optional[str]
    prior_sustained_count_at_disposition: Optional[int]
    redacted: bool


class Investigation(TypedDict):
    id: str
    created_at: str
    updated_at: str
    version: int
    complaint_id: str
    assigned_investigator_officer_id: Optional[str]
    status: str
    statutory_days: int
    tolled_days: int
    due_at: str
    overdue: bool
    assignment_count: int
    interview_held_count: int
    findings_submitted_at: Optional[str]
    suspended_at: Optional[str]
    required_certification_level: int
    closed_at: Optional[str]


class InterviewSession(TypedDict):
    id: str
    created_at: str
    updated_at: str
    version: int
    investigation_id: str
    subject_officer_id: str
    hearing_room_id: str
    scheduled_start: str
    scheduled_end: str
    notice_served_at: str
    notice_hours: float
    representation_status: str
    status: str
    postpone_count: int
    held_at: Optional[str]
    duration_minutes: int
    interview_summary: Optional[str]


class Discipline(TypedDict):
    id: str
    created_at: str
    updated_at: str
    version: int
    allegation_id: str
    officer_id: str
    offense_class: str
    aggravator_count: int
    mitigator_count: int
    presumptive_prior_tier: int
    presumptive_days: int
    final_prior_tier: Optional[int]
    final_days: Optional[int]
    effective_days: int
    status: str
    imposed_at: Optional[str]
    effective_date: Optional[str]
    appeal_deadline_at: Optional[str]


class Appeal(TypedDict):
    id: str
    created_at: str
    updated_at: str
    version: int
    discipline_id: str
    forum: str
    grounds: Optional[str]
    filed_at: str
    days_to_file: int
    status: str
    outcome: Optional[str]
    modified_days: Optional[int]
    heard_at: Optional[str]
    decided_at: Optional[str]
    hearing_notes: Optional[str]


class Reinstatement(TypedDict):
    id: str
    created_at: str
    updated_at: str
    version: int
    appeal_id: str
    reversed_days: int
    gross_back_pay_cents: Optional[int]
    interim_earnings_cents: Optional[int]
    net_back_pay_cents: Optional[int]
    interest_cents: Optional[int]
    total_award_cents: Optional[int]
    status: str
    effective_date: Optional[str]
    finalized_at: Optional[str]


class EarlyInterventionAlert(TypedDict):
    id: str
    created_at: str
    updated_at: str
    version: int
    officer_id: str
    trigger_source: str
    composite_score: float
    score_variant: str
    alert_level: str
    breached_indicators: list
    status: str
    review_due_at: Optional[str]
    dismissal_reason: Optional[str]
    run_sequence: Optional[int]
    plan_count: int


class InterventionPlan(TypedDict):
    id: str
    created_at: str
    updated_at: str
    version: int
    alert_id: str
    officer_id: str
    supervisor_officer_id: str
    required_checkin_count: int
    duration_days: int
    interventions: list
    status: str
    activated_at: Optional[str]
    end_date: Optional[str]
    completed_checkin_count: int
    on_time_checkin_count: int
    concern_count: int
    compliance_score: Optional[float]
    closed_at: Optional[str]


class MonitoringCheckIn(TypedDict):
    id: str
    created_at: str
    updated_at: str
    version: int
    plan_id: str
    sequence_index: int
    due_at: str
    completed_at: Optional[str]
    outcome: Optional[str]
    status: str
    on_time: Optional[bool]
    notes: Optional[str]


class CredibilityDisclosure(TypedDict):
    id: str
    created_at: str
    updated_at: str
    version: int
    officer_id: str
    source_allegation_id: str
    basis: str
    status: str
    retention_until: Optional[str]
    permanent_retention: bool
    release_count: int
    last_released_at: Optional[str]


class EisProfile(TypedDict):
    """The computed early-intervention profile read, which stores nothing."""

    officer_id: str
    variant: str
    window_start: str
    window_end: str
    event_count: int
    weighted_total: float
    composite_score: float
    alert_level: str
    breached_indicators: list
    peer_pool_size: int
    peer_mean: Optional[float]


class EisRun(TypedDict):
    """The counters an early-intervention sweep reports."""

    run_sequence: int
    evaluated_officer_count: int
    alerts_created: int
    alerts_promoted: int
    checkins_missed: int
    disclosures_expired: int


class ClockState(TypedDict):
    """What the clock write reports back."""

    current_utc: str
    previous_utc: str


class OutcomeReportGroup(TypedDict):
    group_key: str
    total_complaints: Optional[int]
    sustained_complaints: Optional[int]
    sustain_rate_pct: Optional[float]
    suppressed: bool


class OutcomeReport(TypedDict):
    period_start: str
    period_end: str
    breakdown: Optional[str]
    total_complaints: int
    sustained_complaints: int
    sustain_rate_pct: float
    suppression_min_cell: int
    groups: list
