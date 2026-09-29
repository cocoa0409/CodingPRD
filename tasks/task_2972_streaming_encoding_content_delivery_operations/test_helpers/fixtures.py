"""Composite setup builders.

Every function here performs setup only: it drives the API through the same
public endpoints a test would use and returns the created resource so a test can
assert against it.  Setup calls go through ``get_success_data``, which accepts
any 2xx and raises a readable AssertionError naming the error identifier when a
setup step fails.

Two habits are deliberate.  First, `expected_title_version` is never cached: any
builder that creates a ladder or a reprocessing job re-reads the parent title
immediately beforehand, because scheduling a window, creating a ladder, locking
one and running a job all bump `Title.version` (§2.7), so a token captured
earlier in the same chain would already be stale.  Second, the logical clock is
left where the caller put it; no builder moves it (§2.5).
"""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from prd_bench_local_runner.testing import get_success_data

from . import factories as f
from .api_client import ApiClient
from .test_users import (
    CONTENT_OPS,
    DELIVERY_ENGINEER,
    DRM_OPERATOR,
    ENCODING_ENGINEER,
    PLATFORM_ADMIN,
    QC_ANALYST,
)

# ---------------------------------------------------------------------------
# Clock and sweep (§2.5)
# ---------------------------------------------------------------------------


def set_clock(api: ApiClient, current_utc: str) -> dict:
    return get_success_data(api.set_clock(current_utc, PLATFORM_ADMIN))


def run_sweep(api: ApiClient, headers: Dict[str, str] = PLATFORM_ADMIN) -> dict:
    """Run the availability sweep and return its nine counters (§2.5)."""
    return get_success_data(api.run_availability_sweep(headers))


# ---------------------------------------------------------------------------
# Reference data and catalog (§3.1, §3.3)
# ---------------------------------------------------------------------------


def create_device_profile(api: ApiClient, **overrides: Any) -> dict:
    return get_success_data(
        api.create_device_profile(f.device_profile_payload(**overrides), PLATFORM_ADMIN)
    )


def create_mobile_profile(api: ApiClient, **overrides: Any) -> dict:
    """The MOBILE_HIGH profile the canonical pipeline is scored against."""
    return create_device_profile(api, **overrides)


def create_tv_4k_profile(api: ApiClient, **overrides: Any) -> dict:
    return get_success_data(
        api.create_device_profile(f.tv_4k_profile_payload(**overrides), PLATFORM_ADMIN)
    )


def create_tv_hd_profile(api: ApiClient, **overrides: Any) -> dict:
    return get_success_data(
        api.create_device_profile(f.tv_hd_profile_payload(**overrides), PLATFORM_ADMIN)
    )


def create_title(api: ApiClient, **overrides: Any) -> dict:
    return get_success_data(api.create_title(f.title_payload(**overrides), CONTENT_OPS))


def create_live_event_title(api: ApiClient, **overrides: Any) -> dict:
    return get_success_data(
        api.create_title(f.live_event_title_payload(**overrides), CONTENT_OPS)
    )


def read_title(api: ApiClient, title_id: str) -> dict:
    return get_success_data(api.get_title(title_id, CONTENT_OPS))


def title_version(api: ApiClient, title_id: str) -> int:
    """Read the title's current `version`, the token §2.7 requires."""
    return read_title(api, title_id)["version"]


# ---------------------------------------------------------------------------
# Source masters and quality control (§3.2)
# ---------------------------------------------------------------------------


def create_asset(api: ApiClient, title_id: str, **overrides: Any) -> dict:
    return get_success_data(
        api.create_mezzanine_asset(f.mezzanine_asset_payload(title_id, **overrides), CONTENT_OPS)
    )


def create_failing_asset(api: ApiClient, title_id: str, **overrides: Any) -> dict:
    return get_success_data(
        api.create_mezzanine_asset(f.failing_asset_payload(title_id, **overrides), CONTENT_OPS)
    )


def run_qc(api: ApiClient, asset_id: str) -> dict:
    """Run QC and return the immutable report (§3.2)."""
    return get_success_data(api.run_qc(asset_id, QC_ANALYST))


def read_asset(api: ApiClient, asset_id: str) -> dict:
    return get_success_data(api.get_mezzanine_asset(asset_id, CONTENT_OPS))


def create_passed_asset(api: ApiClient, title_id: str, **overrides: Any) -> dict:
    """Register a clean master and run QC on it, leaving it `QC_PASSED` (§3.2)."""
    asset = create_asset(api, title_id, **overrides)
    run_qc(api, asset["id"])
    return read_asset(api, asset["id"])


def request_remediation(api: ApiClient, asset_id: str) -> dict:
    return get_success_data(api.request_remediation(asset_id, QC_ANALYST))


def resubmit_asset(api: ApiClient, asset_id: str, **overrides: Any) -> dict:
    return get_success_data(
        api.resubmit_mezzanine_asset(asset_id, f.resubmit_payload(**overrides), CONTENT_OPS)
    )


# ---------------------------------------------------------------------------
# Encoding ladders (§3.3, §3.4)
# ---------------------------------------------------------------------------


def create_ladder(api: ApiClient, title_id: str, **overrides: Any) -> dict:
    """Author a DRAFT ladder, re-reading `Title.version` first (§2.7)."""
    version = overrides.pop("expected_title_version", None)
    if version is None:
        version = title_version(api, title_id)
    payload = f.encoding_ladder_payload(title_id, version, **overrides)
    return get_success_data(api.create_encoding_ladder(payload, ENCODING_ENGINEER))


def validate_ladder(api: ApiClient, ladder_id: str) -> dict:
    """Validate a DRAFT ladder; both arms answer 200 with the ladder (§3.3)."""
    return get_success_data(api.validate_encoding_ladder(ladder_id, ENCODING_ENGINEER))


def lock_ladder(api: ApiClient, ladder_id: str) -> dict:
    return get_success_data(api.lock_encoding_ladder(ladder_id, ENCODING_ENGINEER))


def create_locked_ladder(api: ApiClient, title_id: str, **overrides: Any) -> dict:
    """Author, validate and lock one ladder, returning it in state `LOCKED`.

    The title must already own at least one `QC_PASSED` master and none in
    `REMEDIATION_REQUESTED`, per the two cross-entity guards of §3.4.
    """
    ladder = create_ladder(api, title_id, **overrides)
    validate_ladder(api, ladder["id"])
    return lock_ladder(api, ladder["id"])


def read_ladder(api: ApiClient, ladder_id: str) -> dict:
    return get_success_data(api.get_encoding_ladder(ladder_id, ENCODING_ENGINEER))


# ---------------------------------------------------------------------------
# DRM packages and entitlement rules (§3.5)
# ---------------------------------------------------------------------------


def create_package(api: ApiClient, title_id: str, ladder_id: str, **overrides: Any) -> dict:
    return get_success_data(
        api.create_drm_package(f.drm_package_payload(title_id, ladder_id, **overrides), DRM_OPERATOR)
    )


def add_entitlement_rule(api: ApiClient, package_id: str, **overrides: Any) -> dict:
    return get_success_data(
        api.create_entitlement_rule(package_id, f.entitlement_rule_payload(**overrides), DRM_OPERATOR)
    )


def package_package(api: ApiClient, package_id: str, ladder_id: Optional[str] = None) -> dict:
    """Package a PENDING package, or repackage a STALE one against `ladder_id` (§3.5)."""
    payload: Dict[str, Any] = {} if ladder_id is None else {"ladder_id": ladder_id}
    return get_success_data(api.package_drm_package(package_id, DRM_OPERATOR, payload))


def revoke_package(api: ApiClient, package_id: str) -> dict:
    return get_success_data(api.revoke_drm_package(package_id, DRM_OPERATOR))


def read_package(api: ApiClient, package_id: str) -> dict:
    return get_success_data(api.get_drm_package(package_id, DRM_OPERATOR))


def create_packaged_package(
    api: ApiClient, title_id: str, ladder_id: str, rule_overrides: Optional[dict] = None, **overrides: Any
) -> dict:
    """Create a package, license it with one entitlement rule, and package it.

    Packaging requires the bound ladder to be `LOCKED`, every master of the
    title to be `QC_PASSED`, and `entitlement_rule_count` of 1 or more (§3.5).
    """
    package = create_package(api, title_id, ladder_id, **overrides)
    add_entitlement_rule(api, package["id"], **(rule_overrides or {}))
    return package_package(api, package["id"])


# ---------------------------------------------------------------------------
# Licensing windows (§3.6)
# ---------------------------------------------------------------------------


def create_window(api: ApiClient, title_id: str, **overrides: Any) -> dict:
    return get_success_data(
        api.create_availability_window(
            title_id, f.availability_window_payload(**overrides), CONTENT_OPS
        )
    )


def cancel_window(api: ApiClient, window_id: str) -> dict:
    return get_success_data(api.cancel_availability_window(window_id, CONTENT_OPS))


def takedown_title(api: ApiClient, title_id: str, **overrides: Any) -> dict:
    return get_success_data(
        api.takedown_title(title_id, f.takedown_payload(**overrides), CONTENT_OPS)
    )


# ---------------------------------------------------------------------------
# Delivery: vendors, policies, metrics (§3.7)
# ---------------------------------------------------------------------------


def create_vendor(api: ApiClient, **overrides: Any) -> dict:
    return get_success_data(api.create_cdn_vendor(f.cdn_vendor_payload(**overrides), PLATFORM_ADMIN))


def read_vendor(api: ApiClient, vendor_id: str) -> dict:
    return get_success_data(api.get_cdn_vendor(vendor_id, PLATFORM_ADMIN))


def create_policy(api: ApiClient, title_id: str, **overrides: Any) -> dict:
    return get_success_data(
        api.create_routing_policy(f.routing_policy_payload(title_id, **overrides), DELIVERY_ENGINEER)
    )


def resteer_policy(api: ApiClient, policy_id: str) -> dict:
    return get_success_data(api.resteer_routing_policy(policy_id, DELIVERY_ENGINEER))


def read_policy(api: ApiClient, policy_id: str) -> dict:
    return get_success_data(api.get_routing_policy(policy_id, DELIVERY_ENGINEER))


def ingest_metric(
    api: ApiClient, title_id: str, device_profile_id: str, vendor_id: str, **overrides: Any
) -> dict:
    """Ingest one closed measurement window; a creation, so it answers 201 (§4)."""
    payload = f.playback_metric_payload(title_id, device_profile_id, vendor_id, **overrides)
    return get_success_data(api.create_playback_metric(payload, DELIVERY_ENGINEER))


# ---------------------------------------------------------------------------
# Live-event reservations (§3.8)
# ---------------------------------------------------------------------------


def create_reservation(api: ApiClient, title_id: str, primary_vendor_id: str, **overrides: Any) -> dict:
    return get_success_data(
        api.create_live_reservation(
            f.live_reservation_payload(title_id, primary_vendor_id, **overrides), DELIVERY_ENGINEER
        )
    )


def arm_reservation(api: ApiClient, reservation_id: str) -> dict:
    return get_success_data(api.arm_live_reservation(reservation_id, DELIVERY_ENGINEER))


def failover_reservation(api: ApiClient, reservation_id: str) -> dict:
    return get_success_data(api.failover_live_reservation(reservation_id, DELIVERY_ENGINEER))


def cancel_reservation(api: ApiClient, reservation_id: str) -> dict:
    return get_success_data(api.cancel_live_reservation(reservation_id, DELIVERY_ENGINEER))


def read_reservation(api: ApiClient, reservation_id: str) -> dict:
    return get_success_data(api.get_live_reservation(reservation_id, DELIVERY_ENGINEER))


# ---------------------------------------------------------------------------
# Reprocessing jobs (§3.9)
# ---------------------------------------------------------------------------


def create_job(api: ApiClient, title_id: str, source_ladder_id: str, **overrides: Any) -> dict:
    """Queue a reprocessing job, re-reading `Title.version` first (§2.7)."""
    version = overrides.pop("expected_title_version", None)
    if version is None:
        version = title_version(api, title_id)
    payload = f.reprocess_job_payload(title_id, source_ladder_id, version, **overrides)
    return get_success_data(api.create_reprocess_job(payload, ENCODING_ENGINEER))


def run_job(api: ApiClient, job_id: str) -> dict:
    return get_success_data(api.run_reprocess_job(job_id, ENCODING_ENGINEER))


def abort_job(api: ApiClient, job_id: str, **overrides: Any) -> dict:
    return get_success_data(
        api.abort_reprocess_job(job_id, f.abort_payload(**overrides), ENCODING_ENGINEER)
    )


def read_job(api: ApiClient, job_id: str) -> dict:
    return get_success_data(api.get_reprocess_job(job_id, ENCODING_ENGINEER))


# ---------------------------------------------------------------------------
# Composite pipelines
# ---------------------------------------------------------------------------


@dataclass
class Pipeline:
    """Ids minted while walking a title through the pipeline."""

    title_id: str
    profile_id: Optional[str] = None
    asset_id: Optional[str] = None
    ladder_id: Optional[str] = None
    package_id: Optional[str] = None
    rule_id: Optional[str] = None
    window_id: Optional[str] = None
    vendor_ids: List[str] = field(default_factory=list)
    sweep: Optional[dict] = None


def build_locked_ladder_title(
    api: ApiClient,
    title_overrides: Optional[dict] = None,
    asset_overrides: Optional[dict] = None,
    ladder_overrides: Optional[dict] = None,
    profile_overrides: Optional[dict] = None,
) -> Pipeline:
    """A title with one ACTIVE MOBILE_HIGH profile, one `QC_PASSED` master and
    one `LOCKED` H264 ladder -- `packaging_state` `PACKAGING`."""
    profile = create_device_profile(api, **(profile_overrides or {}))
    title = create_title(api, **(title_overrides or {}))
    asset = create_passed_asset(api, title["id"], **(asset_overrides or {}))
    ladder = create_locked_ladder(api, title["id"], **(ladder_overrides or {}))
    return Pipeline(
        title_id=title["id"],
        profile_id=profile["id"],
        asset_id=asset["id"],
        ladder_id=ladder["id"],
    )


def build_packaged_title(
    api: ApiClient,
    title_overrides: Optional[dict] = None,
    asset_overrides: Optional[dict] = None,
    ladder_overrides: Optional[dict] = None,
    profile_overrides: Optional[dict] = None,
    package_overrides: Optional[dict] = None,
    rule_overrides: Optional[dict] = None,
) -> Pipeline:
    """A title whose `packaging_state` is `PACKAGED`: locked ladder, one
    licensed DRM package in `PACKAGED`, and a US licensing window covering the
    clock's start instant.  `availability_state` is still `SCHEDULED` because
    publication only ever happens in Phase 4 of a sweep (§3.6)."""
    pipeline = build_locked_ladder_title(
        api,
        title_overrides=title_overrides,
        asset_overrides=asset_overrides,
        ladder_overrides=ladder_overrides,
        profile_overrides=profile_overrides,
    )
    package = create_package(
        api, pipeline.title_id, pipeline.ladder_id, **(package_overrides or {})
    )
    window = create_window(api, pipeline.title_id)
    rule = add_entitlement_rule(api, package["id"], **(rule_overrides or {}))
    package_package(api, package["id"])
    pipeline.package_id = package["id"]
    pipeline.rule_id = rule["id"]
    pipeline.window_id = window["id"]
    return pipeline


def build_published_title(api: ApiClient, **kwargs: Any) -> Pipeline:
    """The canonical publishable title, swept once so that it is `PUBLISHED`
    with `readiness_score_certified` 100.00, `packaging_state` `PACKAGED` and
    its window `ACTIVE` (§3.6)."""
    pipeline = build_packaged_title(api, **kwargs)
    pipeline.sweep = run_sweep(api)
    return pipeline


def build_live_event_pipeline(
    api: ApiClient,
    vendor_count: int = 1,
    committed_gbps: float = 100.00,
    window_overrides: Optional[dict] = None,
) -> Pipeline:
    """A `LIVE_EVENT` title with a `SCHEDULED` US licensing window and one or
    more `ACTIVE` vendors serving US, ready for a capacity reservation (§3.8)."""
    title = create_live_event_title(api)
    window = create_window(api, title["id"], **(window_overrides or {}))
    vendor_ids = [
        create_vendor(api, committed_gbps=committed_gbps)["id"] for _ in range(vendor_count)
    ]
    return Pipeline(title_id=title["id"], window_id=window["id"], vendor_ids=vendor_ids)
