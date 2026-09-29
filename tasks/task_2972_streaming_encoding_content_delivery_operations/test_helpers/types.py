"""TypedDict shapes for every resource in the PRD.

PRD §2.4 splits the resources in two: `Title`, `MezzanineAsset`,
`EncodingLadder`, `DeviceProfile`, `DrmPackage`, `CdnVendor`, `RoutingPolicy`,
`LiveEventReservation`, `AvailabilityWindow` and `ReprocessJob` carry the full
set of `id`, `created_at`, `updated_at` and `version`; the three immutable
resources -- `QualityControlReport`, `EntitlementRule` and
`PlaybackMetricWindow` -- carry only `id` and `created_at`, with no
`updated_at` and no `version` field at all.  That split is reflected below:
only the versioned shapes inherit `VersionedResource`.
"""

from typing import Any, Dict, List, Optional, TypedDict


class ImmutableResource(TypedDict):
    """Identity fields of a write-once resource (PRD §2.4)."""

    id: str
    created_at: str


class VersionedResource(ImmutableResource):
    """Identity fields of a mutable resource (PRD §2.4)."""

    updated_at: str
    version: int


class Title(VersionedResource, total=False):
    external_ref: str
    title_name: str
    content_type: str
    studio_code: str
    encode_budget_usd: float
    encode_budget_remaining_usd: float
    availability_state: str
    packaging_state: str
    takedown_reason: str
    readiness_score_provisional: float
    readiness_score_certified: float
    locked_ladder_count: int
    last_sweep_at: Optional[str]


class MezzanineAsset(VersionedResource, total=False):
    title_id: str
    source_uri: str
    duration_seconds: int
    frame_rate: float
    peak_audio_lufs: float
    artifact_defect_count: int
    caption_languages: List[str]
    audio_language: str
    qc_state: str
    qc_attempt_count: int
    latest_severity_index: float
    blocking_defect_code: str
    last_qc_report_id: Optional[str]


class QualityControlReport(ImmutableResource, total=False):
    asset_id: str
    attempt_number: int
    verdict: str
    severity_index: float
    artifact_penalty: float
    loudness_deviation_db: float
    caption_coverage_pct: float
    blocking_defect_code: str
    evaluated_at: str


class LadderRung(TypedDict, total=False):
    label: str
    height_px: int
    bitrate_kbps: int


class EncodingLadder(VersionedResource, total=False):
    title_id: str
    codec_family: str
    rungs: List[LadderRung]
    rung_count: int
    peak_bitrate_kbps: int
    peak_height_px: int
    state: str
    device_compat_score: float
    compatible_device_count: int
    validation_reason_code: str
    derived_from_ladder_id: Optional[str]
    superseded_by_ladder_id: Optional[str]


class DeviceProfile(VersionedResource, total=False):
    device_class: str
    max_height_px: int
    supported_codecs: List[str]
    min_bitrate_kbps: int
    max_bitrate_kbps: int
    hdcp_required: bool
    required_drm_system: str
    market_share_pct: float
    quality_normalization_factor: float
    state: str


class DrmPackage(VersionedResource, total=False):
    title_id: str
    ladder_id: str
    drm_systems: List[str]
    license_server_url: str
    key_rotation_hours: int
    persistent_license_allowed: bool
    state: str
    hdcp_floor: str
    stale_reason: str
    entitlement_rule_count: int
    packaged_at: Optional[str]


class EntitlementRule(ImmutableResource, total=False):
    package_id: str
    region_code: str
    subscription_tier: str
    device_class_scope: str
    max_concurrent_streams: int
    max_playback_height_px: int
    hdcp_level: str
    offline_playback_allowed: bool
    priority: int


class PlaybackEntitlementDecision(TypedDict, total=False):
    decision: str
    reason_code: str
    matched_rule_id: str
    package_id: str
    max_concurrent_streams: int
    offline_granted: bool
    effective_height_px: int


class AvailabilityWindow(VersionedResource, total=False):
    title_id: str
    region_code: str
    window_start_at: str
    window_end_at: str
    license_tier: str
    state: str
    activated_at: Optional[str]
    closed_at: Optional[str]


class CdnVendor(VersionedResource, total=False):
    vendor_code: str
    regions: List[str]
    committed_gbps: float
    cost_per_gb_usd: float
    reserved_gbps: float
    state: str
    health_score_rolling: float
    health_score_contract: float
    breach_window_count: int


class RoutingPolicy(VersionedResource, total=False):
    title_id: str
    region_code: str
    steering_mode: str
    primary_vendor_id: Optional[str]
    backup_vendor_id: Optional[str]
    state: str
    excluded_vendor_ids: List[str]
    resteer_count: int
    selection_reason_code: str
    projected_egress_cost_usd: float


class PlaybackMetricWindow(ImmutableResource, total=False):
    title_id: str
    device_profile_id: str
    vendor_id: str
    region_code: str
    window_start_at: str
    window_end_at: str
    play_attempts: int
    rebuffer_events: int
    startup_ms_p95: int
    error_count: int
    rebuffer_ratio: float
    error_rate: float
    quality_index: float
    breach_flag: bool


class LiveEventReservation(VersionedResource, total=False):
    title_id: str
    primary_vendor_id: str
    failover_vendor_id: Optional[str]
    active_vendor_id: Optional[str]
    window_start_at: str
    window_end_at: str
    reserved_gbps: float
    buffer_minutes: int
    state: str
    failover_at: Optional[str]
    released_gbps: float


class ReprocessJob(VersionedResource, total=False):
    title_id: str
    source_ladder_id: str
    trigger_reason: str
    target_codec_family: str
    state: str
    per_rung_cost_usd: List[float]
    cost_estimate_usd: float
    committed_usd: float
    priority_rank: float
    result_ladder_id: Optional[str]
    abort_reason: str


class SweepCounters(TypedDict, total=False):
    windows_activated: int
    windows_closed: int
    reservations_started: int
    reservations_ended: int
    jobs_completed: int
    jobs_failed: int
    titles_published: int
    titles_taken_down: int
    titles_expired: int


Payload = Dict[str, Any]
Headers = Dict[str, str]
