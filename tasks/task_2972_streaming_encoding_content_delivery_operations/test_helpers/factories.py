"""Request-payload factories.

Every default below is a value the PRD accepts: money, bandwidth and score
fields are JSON numbers (never strings, §2.8), every instant is a full ISO 8601
UTC instant (never a date-only literal, §2.4), region codes are two uppercase
letters (§2.1), and enum values are drawn verbatim from the sets of §3.

Each factory takes keyword overrides, and passing ``None`` for a key removes it
from the payload so a test can exercise an omitted optional input or a missing
required one.
"""

from itertools import count
from typing import Any, Dict, List, Optional

_REF_SEQ = count(1)
_VENDOR_SEQ = count(1)

# --- Frequently reused rung shapes (§3.3) ----------------------------------
RUNGS_TWO_H264 = [
    {"label": "480p", "height_px": 480, "bitrate_kbps": 1200},
    {"label": "720p", "height_px": 720, "bitrate_kbps": 2500},
]
RUNGS_TWO_ALT = [
    {"label": "540p", "height_px": 540, "bitrate_kbps": 1500},
    {"label": "1080p", "height_px": 1080, "bitrate_kbps": 4800},
]
RUNGS_FOUR_COST_EXAMPLE = [
    {"label": "360p", "height_px": 360, "bitrate_kbps": 1150},
    {"label": "540p", "height_px": 540, "bitrate_kbps": 2350},
    {"label": "720p", "height_px": 720, "bitrate_kbps": 4850},
    {"label": "1080p", "height_px": 1080, "bitrate_kbps": 9650},
]
RUNGS_FIVE = [
    {"label": "360p", "height_px": 360, "bitrate_kbps": 900},
    {"label": "480p", "height_px": 480, "bitrate_kbps": 1200},
    {"label": "540p", "height_px": 540, "bitrate_kbps": 1600},
    {"label": "720p", "height_px": 720, "bitrate_kbps": 2500},
    {"label": "1080p", "height_px": 1080, "bitrate_kbps": 4800},
]
RUNGS_PEAK_2160 = [
    {"label": "1080p", "height_px": 1080, "bitrate_kbps": 4800},
    {"label": "2160p", "height_px": 2160, "bitrate_kbps": 16000},
]


def _apply(payload: Dict[str, Any], overrides: Dict[str, Any]) -> Dict[str, Any]:
    """Apply overrides; a value of ``None`` drops the key from the payload."""
    for key, value in overrides.items():
        if value is None:
            payload.pop(key, None)
        else:
            payload[key] = value
    return payload


# ---------------------------------------------------------------------------
# Titles (§3.1)
# ---------------------------------------------------------------------------


def title_payload(**overrides: Any) -> Dict[str, Any]:
    seq = next(_REF_SEQ)
    payload: Dict[str, Any] = {
        "external_ref": f"TTL-{seq:04d}",
        "title_name": f"Reference Feature {seq}",
        "content_type": "MOVIE",
        "studio_code": "NOVAPIC",
    }
    return _apply(payload, overrides)


def live_event_title_payload(**overrides: Any) -> Dict[str, Any]:
    """A title whose `content_type` is `LIVE_EVENT`, the only type that may
    ever carry a live capacity reservation (§3.1)."""
    payload = title_payload(content_type="LIVE_EVENT")
    return _apply(payload, overrides)


def title_patch_payload(**overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"title_name": "Reference Feature (revised)"}
    return _apply(payload, overrides)


def takedown_payload(**overrides: Any) -> Dict[str, Any]:
    """"only the value `MANUAL_LEGAL` is accepted here" (§3.6)."""
    payload: Dict[str, Any] = {"takedown_reason": "MANUAL_LEGAL"}
    return _apply(payload, overrides)


# ---------------------------------------------------------------------------
# Mezzanine assets (§3.1, §3.2)
# ---------------------------------------------------------------------------


def mezzanine_asset_payload(title_id: str, **overrides: Any) -> Dict[str, Any]:
    """A clean master: on target loudness, no artefacts, captions covering the
    audio language, so its QC verdict is `PASS` (§3.2)."""
    seq = next(_REF_SEQ)
    payload: Dict[str, Any] = {
        "title_id": title_id,
        "source_uri": f"s3://mez/reference-{seq:04d}.mxf",
        "duration_seconds": 3600,
        "frame_rate": 24.0,
        "peak_audio_lufs": -24.0,
        "artifact_defect_count": 0,
        "caption_languages": ["en"],
        "audio_language": "en",
    }
    return _apply(payload, overrides)


def failing_asset_payload(title_id: str, **overrides: Any) -> Dict[str, Any]:
    """A master whose measurements yield a blocking `FAIL` verdict: nine
    artefacts contribute `ARTIFACT_BURST` and a missing caption track
    contributes `CAPTION_MISSING`, so `blocking_defect_code` is
    `MULTI_DEFECT` (§3.2)."""
    payload = mezzanine_asset_payload(
        title_id, artifact_defect_count=9, caption_languages=[]
    )
    return _apply(payload, overrides)


def resubmit_payload(**overrides: Any) -> Dict[str, Any]:
    """A resubmission "accepts corrected values for `source_uri`,
    `peak_audio_lufs`, `artifact_defect_count` and `caption_languages`" (§3.2)."""
    payload: Dict[str, Any] = {
        "peak_audio_lufs": -24.0,
        "artifact_defect_count": 0,
        "caption_languages": ["en"],
    }
    return _apply(payload, overrides)


# ---------------------------------------------------------------------------
# Device profiles (§3.3)
# ---------------------------------------------------------------------------


def device_profile_payload(**overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "device_class": "MOBILE_HIGH",
        "max_height_px": 1080,
        "supported_codecs": ["H264", "HEVC"],
        "min_bitrate_kbps": 800,
        "max_bitrate_kbps": 6000,
        "hdcp_required": False,
        "required_drm_system": "NONE",
        "market_share_pct": 45.00,
        "quality_normalization_factor": 0.90,
    }
    return _apply(payload, overrides)


def tv_4k_profile_payload(**overrides: Any) -> Dict[str, Any]:
    payload = device_profile_payload(
        device_class="SMART_TV_4K",
        max_height_px=2160,
        supported_codecs=["HEVC", "AV1"],
        min_bitrate_kbps=3000,
        max_bitrate_kbps=25000,
        hdcp_required=True,
        required_drm_system="WIDEVINE",
        market_share_pct=30.00,
        quality_normalization_factor=1.00,
    )
    return _apply(payload, overrides)


def tv_hd_profile_payload(**overrides: Any) -> Dict[str, Any]:
    payload = device_profile_payload(
        device_class="SMART_TV_HD",
        max_height_px=1080,
        supported_codecs=["H264"],
        min_bitrate_kbps=1000,
        max_bitrate_kbps=8000,
        hdcp_required=False,
        required_drm_system="NONE",
        market_share_pct=20.00,
        quality_normalization_factor=1.00,
    )
    return _apply(payload, overrides)


# ---------------------------------------------------------------------------
# Encoding ladders (§3.3)
# ---------------------------------------------------------------------------


def encoding_ladder_payload(
    title_id: str, expected_title_version: int, **overrides: Any
) -> Dict[str, Any]:
    """`expected_title_version` is a non-optional input on ladder creation
    (§2.7)."""
    payload: Dict[str, Any] = {
        "title_id": title_id,
        "codec_family": "H264",
        "rungs": [dict(rung) for rung in RUNGS_TWO_H264],
        "expected_title_version": expected_title_version,
    }
    return _apply(payload, overrides)


def rung(label: str, height_px: int, bitrate_kbps: int) -> Dict[str, Any]:
    return {"label": label, "height_px": height_px, "bitrate_kbps": bitrate_kbps}


# ---------------------------------------------------------------------------
# DRM packages and entitlement rules (§3.5)
# ---------------------------------------------------------------------------


def drm_package_payload(title_id: str, ladder_id: str, **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "title_id": title_id,
        "ladder_id": ladder_id,
        "drm_systems": ["WIDEVINE"],
        "license_server_url": "https://lic.novapic.example/v1",
    }
    return _apply(payload, overrides)


def entitlement_rule_payload(**overrides: Any) -> Dict[str, Any]:
    """A wildcard rule that matches every region and tier, with `hdcp_level`
    `NONE` -- valid only against a package whose `hdcp_floor` is `NONE` (§3.5)."""
    payload: Dict[str, Any] = {
        "region_code": "*",
        "subscription_tier": "ANY",
        "device_class_scope": "ALL",
        "max_concurrent_streams": 4,
        "max_playback_height_px": 720,
        "hdcp_level": "NONE",
        "priority": 50,
    }
    return _apply(payload, overrides)


def entitlement_check_payload(title_id: str, **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "title_id": title_id,
        "region_code": "US",
        "subscription_tier": "STANDARD",
        "device_class": "MOBILE_HIGH",
        "requested_streams": 1,
    }
    return _apply(payload, overrides)


# ---------------------------------------------------------------------------
# Availability windows (§3.6)
# ---------------------------------------------------------------------------


def availability_window_payload(**overrides: Any) -> Dict[str, Any]:
    """A window opening at the logical clock's start instant, so the next sweep
    activates it (§2.5, §3.6)."""
    payload: Dict[str, Any] = {
        "region_code": "US",
        "window_start_at": "2026-08-01T00:00:00Z",
        "window_end_at": "2026-09-01T00:00:00Z",
        "license_tier": "STANDARD",
    }
    return _apply(payload, overrides)


# ---------------------------------------------------------------------------
# CDN vendors, routing policies, playback metrics (§3.7)
# ---------------------------------------------------------------------------


def cdn_vendor_payload(**overrides: Any) -> Dict[str, Any]:
    seq = next(_VENDOR_SEQ)
    payload: Dict[str, Any] = {
        "vendor_code": f"VENDOR{seq:02d}",
        "regions": ["US"],
        "committed_gbps": 100.00,
        "cost_per_gb_usd": 0.0300,
    }
    return _apply(payload, overrides)


def vendor_patch_payload(**overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"cost_per_gb_usd": 0.0250}
    return _apply(payload, overrides)


def routing_policy_payload(title_id: str, **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "title_id": title_id,
        "region_code": "US",
        "steering_mode": "PERFORMANCE",
    }
    return _apply(payload, overrides)


def playback_metric_payload(
    title_id: str, device_profile_id: str, vendor_id: str, **overrides: Any
) -> Dict[str, Any]:
    """A closed measurement window ending before the logical clock's start
    instant, with a startup latency at or below the 2000 ms target so that term
    contributes nothing (§3.7)."""
    payload: Dict[str, Any] = {
        "title_id": title_id,
        "device_profile_id": device_profile_id,
        "vendor_id": vendor_id,
        "region_code": "US",
        "window_start_at": "2026-07-25T00:00:00Z",
        "window_end_at": "2026-07-26T00:00:00Z",
        "play_attempts": 1000,
        "rebuffer_events": 0,
        "startup_ms_p95": 1500,
        "error_count": 0,
    }
    return _apply(payload, overrides)


# ---------------------------------------------------------------------------
# Live-event reservations (§3.8)
# ---------------------------------------------------------------------------


def live_reservation_payload(
    title_id: str, primary_vendor_id: str, **overrides: Any
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "title_id": title_id,
        "primary_vendor_id": primary_vendor_id,
        "window_start_at": "2026-08-02T00:00:00Z",
        "window_end_at": "2026-08-02T04:00:00Z",
        "reserved_gbps": 40.00,
    }
    return _apply(payload, overrides)


# ---------------------------------------------------------------------------
# Reprocessing jobs (§3.9)
# ---------------------------------------------------------------------------


def reprocess_job_payload(
    title_id: str, source_ladder_id: str, expected_title_version: int, **overrides: Any
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "title_id": title_id,
        "source_ladder_id": source_ladder_id,
        "trigger_reason": "CODEC_DEPRECATION",
        "target_codec_family": "HEVC",
        "expected_title_version": expected_title_version,
    }
    return _apply(payload, overrides)


def abort_payload(**overrides: Any) -> Dict[str, Any]:
    """"Only `OPERATOR_ABORT` is accepted from an operator" (§3.9)."""
    payload: Dict[str, Any] = {"abort_reason": "OPERATOR_ABORT"}
    return _apply(payload, overrides)


# ---------------------------------------------------------------------------
# Query-parameter helpers
# ---------------------------------------------------------------------------


def page_params(page: Optional[int] = None, page_size: Optional[int] = None, **filters: Any):
    params: Dict[str, Any] = {}
    if page is not None:
        params["page"] = page
    if page_size is not None:
        params["page_size"] = page_size
    params.update({key: value for key, value in filters.items() if value is not None})
    return params


__all__: List[str] = [name for name in dir() if name.endswith("_payload")] + [
    "RUNGS_TWO_H264",
    "RUNGS_TWO_ALT",
    "RUNGS_FOUR_COST_EXAMPLE",
    "RUNGS_FIVE",
    "RUNGS_PEAK_2160",
    "page_params",
    "rung",
]
