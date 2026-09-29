"""TypedDict shapes for every resource the audio post-production API returns.

Resources that carry the full identity set expose ``id``, ``created_at``,
``updated_at`` and ``version``. The three deliberately immutable record types —
the platform specification, the QC report and the archive package — expose only
``id`` and ``created_at``.
"""

from typing import List, Optional, TypedDict


class Project(TypedDict):
    id: str
    created_at: str
    updated_at: str
    version: int
    title: str
    client_name: str
    client_user_id: str
    delivery_deadline_utc: str
    turnaround_class: str
    stage_hours_authorized: float
    picture_status: str
    picture_locked_at_utc: Optional[str]
    picture_lock_revision: int
    pipeline_stage: str
    posture: str
    stage_hours_reserved: float
    stage_hours_consumed: float
    stage_hours_available: float
    stage_cost_subtotal_cents: int
    adr_cost_cents: int
    license_fee_accrued_cents: int
    billing_total_cents: int
    license_risk_score_intake: float
    license_risk_score_audit: float
    unlicensed_usage_count: int
    stale_stem_count: int
    conformed_stem_count: int


class PlatformSpec(TypedDict):
    id: str
    created_at: str
    platform: str
    spec_label: str
    target_lufs: float
    tolerance_lu: float
    true_peak_max_dbtp: float
    channel_layout: str
    requires_me_stems: bool
    max_remediation_rounds: int
    qc_turnaround_hours: int


class MixStage(TypedDict):
    id: str
    created_at: str
    updated_at: str
    version: int
    room_code: str
    display_name: str
    hourly_rate_cents: int
    supports_remote_review: bool
    changeover_minutes: int


class Mixer(TypedDict):
    id: str
    created_at: str
    updated_at: str
    version: int
    full_name: str
    certified_platforms: List[str]
    max_daily_hours: float


class VoiceTalent(TypedDict):
    id: str
    created_at: str
    updated_at: str
    version: int
    full_name: str
    union_status: str
    daily_cap_minutes: int
    min_call_minutes: int


class LibraryAsset(TypedDict):
    id: str
    created_at: str
    updated_at: str
    version: int
    asset_code: str
    kind: str
    license_type: str
    territory_scope: str
    fee_cents: int
    expires_at_utc: Optional[str]
    status: str
    revocation_reason: Optional[str]


class AssetUsage(TypedDict):
    id: str
    created_at: str
    updated_at: str
    version: int
    library_asset_id: str
    stem_package_id: str
    usage_seconds: int
    territory_declared: str
    clearance_status: str
    accrued_fee_cents: int
    cleared_at_utc: Optional[str]
    unlicensed_reason: Optional[str]


class StemPackage(TypedDict):
    id: str
    created_at: str
    updated_at: str
    version: int
    project_id: str
    reel_label: str
    stem_layout: str
    includes_me_stems: bool
    status: str
    conform_round: int
    cue_count: int
    total_stem_minutes: float
    conform_fee_cents: int
    conformed_at_utc: Optional[str]
    stale_reason: Optional[str]


class MusicCue(TypedDict):
    id: str
    created_at: str
    updated_at: str
    version: int
    stem_package_id: str
    cue_number: str
    duration_seconds: int
    source: str
    composer_delivery_ref: Optional[str]
    status: str


class AdrSession(TypedDict):
    id: str
    created_at: str
    updated_at: str
    version: int
    project_id: str
    voice_talent_id: str
    window_start_utc: str
    window_end_utc: str
    lines_scheduled: int
    lines_recorded: int
    status: str
    scheduled_minutes: float
    billable_minutes: float
    session_cost_cents: int
    cancellation_reason: Optional[str]


class MixStageBooking(TypedDict):
    id: str
    created_at: str
    updated_at: str
    version: int
    project_id: str
    mix_stage_id: str
    mixer_id: str
    booking_type: str
    platform: str
    window_start_utc: str
    window_end_utc: str
    client_attendance: str
    client_signoff_at_utc: Optional[str]
    status: str
    reserved_hours: float
    provisional_cost_cents: int
    actual_start_utc: Optional[str]
    actual_end_utc: Optional[str]
    billable_hours_final: Optional[float]
    overtime_hours: Optional[float]
    final_cost_cents: Optional[int]
    release_reason: Optional[str]


class Deliverable(TypedDict):
    id: str
    created_at: str
    updated_at: str
    version: int
    project_id: str
    platform_spec_id: str
    stem_package_id: str
    mix_booking_id: str
    status: str
    measured_integrated_lufs: Optional[float]
    measured_true_peak_dbtp: Optional[float]
    me_stems_present: Optional[bool]
    deviation_lu: Optional[float]
    remediation_round: int
    qc_rejection_codes: List[str]
    prepared_by_user_id: str
    delivery_reference: Optional[str]
    delivered_at_utc: Optional[str]
    invalidation_reason: Optional[str]


class QcReport(TypedDict):
    id: str
    created_at: str
    deliverable_id: str
    round: int
    verdict: str
    rejection_codes: List[str]
    measured_integrated_lufs: float
    measured_true_peak_dbtp: float
    target_lufs: float
    deviation_lu: float
    submitted_by_user_id: str
    evaluated_by_user_id: str
    evaluated_at_utc: str


class ArchivePackage(TypedDict):
    id: str
    created_at: str
    project_id: str
    session_file_count: int
    retention_years: int
    stem_manifest_count: int
    archived_stem_package_ids: List[str]
    delivered_deliverable_count: int
    sealed_at_utc: str
    sealed_by_user_id: str


class ProjectLedger(TypedDict):
    stage_hours_authorized: float
    stage_hours_reserved: float
    stage_hours_consumed: float
    stage_hours_available: float
    stage_cost_subtotal_cents: int
    adr_cost_cents: int
    conform_fee_total_cents: int
    license_fee_accrued_cents: int
    pre_discount_total_cents: int
    volume_discount_cents: int
    discounted_base_cents: int
    rush_surcharge_cents: int
    billing_total_cents: int
    license_risk_score_intake: float
    license_risk_score_audit: float
    unlicensed_usage_count: int
    stale_stem_count: int
    conformed_stem_count: int
    posture: str
    pipeline_stage: str
    picture_status: str
