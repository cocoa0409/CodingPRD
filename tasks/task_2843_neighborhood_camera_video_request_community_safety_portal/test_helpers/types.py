"""Declared response shapes.

One ``TypedDict`` per entity, naming every field the contract says the entity
carries. Eleven entities carry the full common property set — ``id``,
``created_at``, ``updated_at`` and ``version``. The two append-only receipts,
``NotificationDispatch`` and ``DataControlAction``, are never updated and never
versioned, so they carry only ``id`` and ``created_at``; their shapes therefore
extend a narrower base.

These are documentation and editor support for the test suite; the runtime
assertions live in ``assertions.py``.
"""

from typing import Any, Dict, List, Optional

try:  # pragma: no cover - typing_extensions is only needed on older runtimes
    from typing import TypedDict
except ImportError:  # pragma: no cover
    from typing_extensions import TypedDict  # type: ignore


class CommonFields(TypedDict):
    """The four common properties every versioned entity carries."""

    id: str
    created_at: str
    updated_at: str
    version: int


class ReceiptFields(TypedDict):
    """The two common properties an append-only receipt carries."""

    id: str
    created_at: str


class Agency(CommonFields, total=False):
    name: str
    jurisdiction_code: str
    status: str
    onboarding_agreement_version: Optional[str]
    reviewer_note: Optional[str]
    status_reason: Optional[str]
    min_device_threshold: int
    max_open_requests: int
    period_request_quota: int
    post_share_retention_days: int
    justification_min_chars: int
    open_request_count: int
    requests_submitted_count: int
    latest_report_id: Optional[str]


class Officer(CommonFields, total=False):
    agency_id: str
    badge_number: str
    full_name: str
    duty_role: str
    requests_submitted_count: int
    audits_completed_count: int


class Resident(CommonFields, total=False):
    display_name: str
    email: str
    home_x_m: int
    home_y_m: int
    status: str
    data_sharing_opt_out: bool
    alert_radius_m: int
    notification_budget_per_day: int
    notification_mute_enabled: bool
    notifications_sent_today: int
    fatigue_state: str
    accuracy_strike_count: int
    discrimination_strike_count: int
    total_strike_score: int
    post_privilege_state: str
    lifetime_shared_footage_seconds: int
    retained_footage_seconds: int
    purged_footage_seconds: int


class Device(CommonFields, total=False):
    owner_resident_id: str
    label: str
    grid_x_m: int
    grid_y_m: int
    retention_window_days: int
    status: str
    auto_decline_requests: bool
    auto_decline_source: str
    solicitations_received_count: int
    pending_solicitation_count: int


class RequestArea(CommonFields, total=False):
    agency_id: str
    created_by_officer_id: str
    area_label: Optional[str]
    center_x_m: int
    center_y_m: int
    radius_m: int
    window_start_utc: str
    window_end_utc: str
    status: str
    locked_at: Optional[str]
    effective_min_devices: Optional[int]
    eligible_device_count: int
    derived_request_count: int
    invalidated_reason: Optional[str]


class VideoRequest(CommonFields, total=False):
    request_area_id: str
    agency_id: str
    submitting_officer_id: str
    auditor_officer_id: Optional[str]
    case_number: str
    lifecycle_state: str
    compliance_state: str
    justification_text: Optional[str]
    statutory_basis: Optional[str]
    justification_logged_at: Optional[str]
    audit_note: Optional[str]
    withdraw_reason: Optional[str]
    submitted_at: Optional[str]
    expires_at: Optional[str]
    solicitation_count: int
    pending_count: int
    shared_count: int
    declined_count: int
    expired_count: int
    withdrawn_count: int
    shared_clip_count: int
    provisional_share_rate_bps: int


class ConsentSolicitation(CommonFields, total=False):
    video_request_id: str
    device_id: str
    resident_id: str
    status: str
    distance_sq_m2: int
    dispatch_rank: int
    respond_deadline_utc: str
    notification_suppressed: bool
    suppression_reason: Optional[str]
    responded_at: Optional[str]
    decline_reason: Optional[str]
    clip_count: int


class SharedClip(CommonFields, total=False):
    consent_solicitation_id: str
    video_request_id: str
    device_id: str
    owner_resident_id: str
    recorded_start_utc: str
    duration_seconds: int
    shared_at: str
    retention_variant: str
    retention_expires_at: str
    status: str
    purged_at: Optional[str]
    purge_reason: Optional[str]


class ResidentPost(CommonFields, total=False):
    author_resident_id: str
    parent_post_id: Optional[str]
    body: str
    category: str
    post_x_m: int
    post_y_m: int
    alert_fanout_cap: int
    protected_class_term_count: int
    unverified_assertion_count: int
    location_profiling_count: int
    hostile_tone_count: int
    discrimination_score: float
    state: str
    flag_count: int
    flagged_by_resident_ids: List[str]
    revision_count: int
    alert_candidate_count: int
    alert_fanout_count: int
    alert_suppressed_count: int
    auto_flag_reason: Optional[str]


class ModerationCase(CommonFields, total=False):
    resident_post_id: str
    opened_reason: str
    opened_by_user_id: str
    decided_by_user_id: Optional[str]
    state: str
    decision: str
    decision_note: Optional[str]
    decided_at: Optional[str]
    superseded_by_case_created_at: Optional[str]
    post_discrimination_score_at_open: Optional[float]


class TransparencyReport(CommonFields, total=False):
    agency_id: str
    period_start_utc: str
    period_end_utc: str
    variant: str
    compiled_by_user_id: str
    requests_submitted_count: int
    solicitations_dispatched_count: int
    suppressed_dispatch_count: int
    shared_count: int
    declined_count: int
    expired_count: int
    withdrawn_count: int
    pending_count: int
    opt_out_excluded_count: int
    purged_clip_count: int
    provisional_share_rate_bps: int
    certified_share_rate_bps: int
    published_share_rate_bps: int
    certification_note: Optional[str]
    certified_at: Optional[str]
    certified_by_user_id: Optional[str]


class NotificationDispatch(ReceiptFields, total=False):
    """Append-only receipt: no ``updated_at`` and no ``version``."""

    resident_id: str
    kind: str
    source_ref_id: str
    batch_sequence_no: int
    suppressed: bool
    suppression_reason: Optional[str]
    recipient_budget_snapshot: int
    recipient_effective_budget: int
    dispatched_at: str


class DataControlAction(ReceiptFields, total=False):
    """Append-only receipt: no ``updated_at`` and no ``version``."""

    resident_id: str
    action_type: str
    reason: Optional[str]
    affected_device_count: int
    affected_solicitation_count: int
    affected_clip_count: int
    affected_request_count: int
    applied_at: str


class ClockState(TypedDict, total=False):
    """What setting the logical clock reports."""

    current_utc: str
    residents_daily_counter_reset_count: int


class RetentionSweepResult(TypedDict, total=False):
    """What one retention sweep reports."""

    run_at_utc: str
    solicitations_expired_count: int
    clips_purged_count: int
    clips_held_count: int
    requests_auto_closed_count: int


# Convenience aliases for readability in fixture signatures.
Envelope = Dict[str, Any]
Meta = Dict[str, Any]
