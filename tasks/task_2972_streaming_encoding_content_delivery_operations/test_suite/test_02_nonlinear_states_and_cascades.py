"""Non-linear state machines and the two deep transitive cascades.

Four behaviours are exercised here, each of which is only observable by walking a
chain several hops long and reading every intermediate row:

* the bounded QC revision loop of PRD §3.2, which terminates on the third `FAIL`
  because a resubmission deliberately does not reset `qc_attempt_count`;
* the two independent state dimensions a `Title` carries (PRD §2.9, §3.6), where
  `packaging_state` reaches `PACKAGED` while `availability_state` is still
  `SCHEDULED` and a manual takedown moves one dimension without the other;
* the five-hop ladder-lock staleness cascade of PRD §3.4; and
* the metric-ingest cascade of PRD §3.7, from a window's `breach_flag` through
  vendor health and vendor state to an automatic re-steer and a re-priced egress
  projection.

Every test starts from an empty database with the logical clock at
`2026-08-01T00:00:00Z` (PRD §2.5) and moves it only where the behaviour requires.
"""

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import api_errors as err
from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.assertions import (
    assert_instant_equals,
    assert_ratio_4dp,
    assert_score,
    assert_sweep_counters,
    validate_paginated,
    validate_unpaginated,
)
from test_helpers.test_users import (
    CONTENT_OPS,
    DELIVERY_ENGINEER,
    PLATFORM_ADMIN,
    QC_ANALYST,
)

# ---------------------------------------------------------------------------
# Shared chains
# ---------------------------------------------------------------------------

# The four HEVC rungs of the ladder that ships first: peak height 2160 so the
# derived `hdcp_floor` is `TYPE_1` (PRD §3.5).
RUNGS_HEVC_SHIPPING = [
    {"label": "480p", "height_px": 480, "bitrate_kbps": 1200},
    {"label": "720p", "height_px": 720, "bitrate_kbps": 2500},
    {"label": "1080p", "height_px": 1080, "bitrate_kbps": 5000},
    {"label": "2160p", "height_px": 2160, "bitrate_kbps": 12000},
]

# The three HEVC rungs of the replacement ladder.
RUNGS_HEVC_REPLACEMENT = [
    {"label": "540p", "height_px": 540, "bitrate_kbps": 1600},
    {"label": "1080p", "height_px": 1080, "bitrate_kbps": 5200},
    {"label": "2160p", "height_px": 2160, "bitrate_kbps": 13000},
]


def _walk_two_failed_laps(api):
    """A master with two full FAIL -> remediation -> resubmit laps behind it.

    Nine artefact defects and no caption track for an `en` audio language, so
    every run scores `severity_index` 66.00 with two blocking conditions.  After
    this chain `qc_state` is `INGESTED` and `qc_attempt_count` is 2.
    """
    title = fx.create_title(
        api,
        external_ref="TTL-CYCLE-01",
        title_name="QC Revision Cycle",
        content_type="MOVIE",
        studio_code="NOVAPIC",
    )
    asset = fx.create_asset(
        api,
        title["id"],
        source_uri="s3://mez/cycle-01-v1.mxf",
        duration_seconds=7200,
        frame_rate=24.0,
        peak_audio_lufs=-24.0,
        artifact_defect_count=9,
        caption_languages=[],
        audio_language="en",
    )
    for revision in ("v2", "v3"):
        fx.run_qc(api, asset["id"])
        fx.request_remediation(api, asset["id"])
        fx.resubmit_asset(
            api,
            asset["id"],
            source_uri=f"s3://mez/cycle-01-{revision}.mxf",
            artifact_defect_count=9,
            caption_languages=[],
            peak_audio_lufs=None,
        )
    return title["id"], asset["id"]


def test_the_third_failing_verdict_drives_the_master_to_qc_rejected(api):
    """After two failed laps the third FAIL is terminal and answers 201.

    PRD §3.2: "Crucially, `qc_attempt_count` is **not** reset, so the loop
    `INGESTED` → `QC_FAILED` → `REMEDIATION_REQUESTED` → `INGESTED` can be walked
    at most twice: the third failing verdict is terminal no matter how many
    resubmissions preceded it."

    Design: Difficulty/non_linear_state_machine/mezzanine_qc_revision_cycle_terminates
    """
    _title_id, asset_id = _walk_two_failed_laps(api)

    report = validate_success(api.run_qc(asset_id, QC_ANALYST), 201)
    assert report["attempt_number"] == 3, report
    assert report["verdict"] == "FAIL", report

    asset = fx.read_asset(api, asset_id)
    assert asset["qc_state"] == "QC_REJECTED", asset
    assert asset["qc_attempt_count"] == 3, asset


def test_the_rejected_master_retains_the_third_attempts_severity_and_code(api):
    """The master keeps only the newest report's figures: 66.00 / MULTI_DEFECT.

    PRD §3.2: "That list is the sole channel exposing each attempt's own
    `severity_index`, `artifact_penalty`, `loudness_deviation_db`,
    `caption_coverage_pct` and `verdict`; the master itself retains only the most
    recent `latest_severity_index` and `blocking_defect_code`."

    Design: Difficulty/non_linear_state_machine/mezzanine_qc_revision_cycle_terminates
    """
    _title_id, asset_id = _walk_two_failed_laps(api)
    validate_success(api.run_qc(asset_id, QC_ANALYST), 201)

    asset = fx.read_asset(api, asset_id)
    assert asset["blocking_defect_code"] == "MULTI_DEFECT", asset
    assert_score(asset["latest_severity_index"], 66.00, "MezzanineAsset.latest_severity_index")


def test_every_attempt_of_the_cycle_scored_the_same_blocking_failure(api):
    """All three reports score 66.00 = 36.00 artefacts + 30.0 missing captions.

    PRD §3.2: "The `severity_index` is the sum of the artifact penalty, the
    loudness penalty and the caption penalty, rounded half up to two decimals."

    Design: Difficulty/non_linear_state_machine/mezzanine_qc_revision_cycle_terminates
    """
    _title_id, asset_id = _walk_two_failed_laps(api)
    validate_success(api.run_qc(asset_id, QC_ANALYST), 201)

    rows, meta = validate_paginated(api.list_qc_reports(asset_id, QC_ANALYST))
    assert meta["total_count"] == 3, meta
    assert len(rows) == 3, rows
    assert [row["attempt_number"] for row in rows] == [1, 2, 3], rows
    for row in rows:
        assert row["verdict"] == "FAIL", row
        assert row["blocking_defect_code"] == "MULTI_DEFECT", row
        assert_score(row["severity_index"], 66.00, "QualityControlReport.severity_index")
        assert_score(row["artifact_penalty"], 36.00, "QualityControlReport.artifact_penalty")
        assert_score(
            row["caption_coverage_pct"], 0.00, "QualityControlReport.caption_coverage_pct"
        )
        assert_score(
            row["loudness_deviation_db"], 0.00, "QualityControlReport.loudness_deviation_db"
        )


def test_a_fourth_qc_run_against_the_rejected_master_is_refused(api):
    """The cycle is closed: a run against `QC_REJECTED` is a 409.

    PRD §3.2: "A `QcAnalyst` runs quality control against a master whose
    `qc_state` is `INGESTED`; attempting it against any other state — including
    anything at all against the terminal `QC_REJECTED` — is refused with
    `ERR_ASSET_STATE_INVALID`."

    Design: Difficulty/non_linear_state_machine/mezzanine_qc_revision_cycle_terminates
    """
    _title_id, asset_id = _walk_two_failed_laps(api)
    validate_success(api.run_qc(asset_id, QC_ANALYST), 201)
    validate_paginated(api.list_qc_reports(asset_id, QC_ANALYST))

    validate_error(api.run_qc(asset_id, QC_ANALYST), err.ERR_ASSET_STATE_INVALID, 409)


def test_the_rejected_master_zeroes_both_readiness_variants(api):
    """A single rejected master leaves both numerators, so both scores read 0.00.

    PRD §3.1: "A master in the terminal `QC_REJECTED` state stays in the
    denominator of both variants and leaves both numerators, so an abandoned
    master permanently depresses readiness until other masters are added; a
    `REVOKED` DRM package counts for neither variant."

    Design: Difficulty/non_linear_state_machine/mezzanine_qc_revision_cycle_terminates
    """
    title_id, asset_id = _walk_two_failed_laps(api)
    validate_success(api.run_qc(asset_id, QC_ANALYST), 201)

    title = fx.read_title(api, title_id)
    assert_score(
        title["readiness_score_provisional"], 0.00, "Title.readiness_score_provisional"
    )
    assert_score(title["readiness_score_certified"], 0.00, "Title.readiness_score_certified")


# ---------------------------------------------------------------------------
# Title's two independent state dimensions
# ---------------------------------------------------------------------------


def _build_parallel_dimensions_title(api):
    """A title whose packaging dimension is `PACKAGED` while its availability
    dimension is still `SCHEDULED`.

    One `MOBILE_HIGH` profile, a US window running 2026-09-01 to 2026-11-01, one
    `QC_PASSED` master, a `LOCKED` HEVC ladder peaking at 2160 and a `PACKAGED`
    DRM package.  The logical clock is left at its 2026-08-01T00:00:00Z default,
    so the window has not activated yet.
    """
    fx.create_device_profile(api)
    title = fx.create_title(
        api,
        external_ref="TTL-PARALLEL-01",
        title_name="Parallel Dimensions",
        content_type="MOVIE",
        studio_code="NOVAPIC",
    )
    window = fx.create_window(
        api,
        title["id"],
        region_code="US",
        window_start_at="2026-09-01T00:00:00Z",
        window_end_at="2026-11-01T00:00:00Z",
        license_tier="STANDARD",
    )
    fx.create_passed_asset(
        api,
        title["id"],
        source_uri="s3://mez/parallel-01.mxf",
        duration_seconds=7200,
        frame_rate=24.0,
        peak_audio_lufs=-24.0,
        artifact_defect_count=0,
        caption_languages=["en"],
        audio_language="en",
    )
    ladder = fx.create_locked_ladder(
        api,
        title["id"],
        codec_family="HEVC",
        rungs=[dict(rung) for rung in RUNGS_HEVC_SHIPPING],
    )
    package = fx.create_package(
        api,
        title["id"],
        ladder["id"],
        drm_systems=["WIDEVINE", "PLAYREADY"],
        license_server_url="https://lic.novapic.example/v1",
        persistent_license_allowed=True,
    )
    fx.add_entitlement_rule(
        api,
        package["id"],
        region_code="US",
        subscription_tier="PREMIUM",
        device_class_scope="ALL",
        max_concurrent_streams=2,
        max_playback_height_px=2160,
        hdcp_level="TYPE_1",
        offline_playback_allowed=True,
        priority=50,
    )
    fx.package_package(api, package["id"])
    return title["id"], window["id"], ladder["id"], package["id"]


def test_packaging_reaches_packaged_while_availability_is_still_scheduled(api):
    """The two dimensions disagree: `SCHEDULED` alongside `PACKAGED`.

    PRD §2.9: "Neither dimension constrains the other's transitions directly;
    they interact only through the specific cascades and gates described in §3."

    Design: Difficulty/non_linear_state_machine/title_parallel_dimensions_evolve_independently
    """
    title_id, _window_id, _ladder_id, _package_id = _build_parallel_dimensions_title(api)

    title = fx.read_title(api, title_id)
    assert title["availability_state"] == "SCHEDULED", title
    assert title["packaging_state"] == "PACKAGED", title


def test_the_sweep_publishes_the_title_without_touching_the_packaging_dimension(api):
    """One window activation and one publication; the seven other counters are 0.

    PRD §3.6: "A title in `SCHEDULED` moves to `PUBLISHED` when at least one of
    its windows is `ACTIVE` after Phase 1, its `packaging_state` is `PACKAGED`
    after Phase 3, and its `readiness_score_certified` is at least 80.00."

    Design: Difficulty/non_linear_state_machine/title_parallel_dimensions_evolve_independently
    """
    title_id, _window_id, _ladder_id, _package_id = _build_parallel_dimensions_title(api)
    fx.set_clock(api, "2026-09-15T00:00:00Z")

    counters = validate_unpaginated(api.run_availability_sweep(PLATFORM_ADMIN), 200)
    assert_sweep_counters(counters, windows_activated=1, titles_published=1)

    title = fx.read_title(api, title_id)
    assert title["availability_state"] == "PUBLISHED", title
    assert title["packaging_state"] == "PACKAGED", title


def test_a_manual_legal_takedown_leaves_the_packaging_dimension_packaged(api):
    """Availability drops to `TAKEN_DOWN` while packaging stays `PACKAGED`.

    PRD §3.6: "A manual takedown moves `availability_state` from `PUBLISHED` to
    `TAKEN_DOWN`, sets `takedown_reason` to `MANUAL_LEGAL`, increments the title's
    `version` by one, and closes every one of the title's `ACTIVE` windows with
    `closed_at` set to the logical clock's current instant."

    Design: Difficulty/non_linear_state_machine/title_parallel_dimensions_evolve_independently
    """
    title_id, _window_id, _ladder_id, _package_id = _build_parallel_dimensions_title(api)
    fx.set_clock(api, "2026-09-15T00:00:00Z")
    fx.run_sweep(api)

    fx.takedown_title(api, title_id, takedown_reason="MANUAL_LEGAL")

    title = fx.read_title(api, title_id)
    assert title["availability_state"] == "TAKEN_DOWN", title
    assert title["takedown_reason"] == "MANUAL_LEGAL", title
    assert title["packaging_state"] == "PACKAGED", title
    assert_score(title["readiness_score_certified"], 100.00, "Title.readiness_score_certified")


def test_a_manual_legal_takedown_closes_the_titles_active_window(api):
    """The publication dimension carries the window down with it, to `CLOSED`.

    PRD §3.6: "Because the reason is sticky, no later sweep will bring the title
    back."

    PRD §3.6: "A manual takedown moves `availability_state` from `PUBLISHED` to
    `TAKEN_DOWN`, sets `takedown_reason` to `MANUAL_LEGAL`, increments the title's
    `version` by one, and closes every one of the title's `ACTIVE` windows with
    `closed_at` set to the logical clock's current instant."

    Design: Difficulty/non_linear_state_machine/title_parallel_dimensions_evolve_independently
    """
    title_id, window_id, _ladder_id, _package_id = _build_parallel_dimensions_title(api)
    fx.set_clock(api, "2026-09-15T00:00:00Z")
    fx.run_sweep(api)
    fx.takedown_title(api, title_id, takedown_reason="MANUAL_LEGAL")

    rows, meta = validate_paginated(api.list_availability_windows(title_id, CONTENT_OPS))
    assert meta["total_count"] == 1, meta
    window = next(row for row in rows if row["id"] == window_id)
    assert window["state"] == "CLOSED", window
    assert_instant_equals(window["closed_at"], "2026-09-15T00:00:00Z")


# ---------------------------------------------------------------------------
# The five-hop ladder-lock staleness cascade
# ---------------------------------------------------------------------------


def _build_lock_cascade_subject(api):
    """A `PUBLISHED` title with an `ACTIVE` window, a shipping HEVC ladder L1, a
    `PACKAGED` package bound to L1, and a second HEVC ladder L2 in `VALIDATED`.

    The logical clock stands at 2026-09-15T00:00:00Z, inside the window, and the
    single sweep that published the title has already run.
    """
    fx.create_device_profile(api)
    title = fx.create_title(
        api,
        external_ref="TTL-CASCADE-01",
        title_name="Lock Cascade Subject",
        content_type="MOVIE",
        studio_code="NOVAPIC",
    )
    window = fx.create_window(
        api,
        title["id"],
        region_code="US",
        window_start_at="2026-09-01T00:00:00Z",
        window_end_at="2026-11-01T00:00:00Z",
        license_tier="STANDARD",
    )
    fx.create_passed_asset(
        api,
        title["id"],
        source_uri="s3://mez/cascade-01.mxf",
        duration_seconds=7200,
        frame_rate=24.0,
        peak_audio_lufs=-24.0,
        artifact_defect_count=0,
        caption_languages=["en"],
        audio_language="en",
    )
    ladder_one = fx.create_locked_ladder(
        api,
        title["id"],
        codec_family="HEVC",
        rungs=[dict(rung) for rung in RUNGS_HEVC_SHIPPING],
    )
    package = fx.create_package(
        api,
        title["id"],
        ladder_one["id"],
        drm_systems=["WIDEVINE"],
        license_server_url="https://lic.novapic.example/v1",
        persistent_license_allowed=True,
    )
    fx.add_entitlement_rule(
        api,
        package["id"],
        region_code="US",
        subscription_tier="ANY",
        device_class_scope="ALL",
        max_concurrent_streams=2,
        max_playback_height_px=2160,
        hdcp_level="TYPE_1",
        offline_playback_allowed=False,
        priority=40,
    )
    fx.package_package(api, package["id"])
    fx.set_clock(api, "2026-09-15T00:00:00Z")
    fx.run_sweep(api)
    ladder_two = fx.create_ladder(
        api,
        title["id"],
        codec_family="HEVC",
        rungs=[dict(rung) for rung in RUNGS_HEVC_REPLACEMENT],
    )
    fx.validate_ladder(api, ladder_two["id"])
    return title["id"], window["id"], ladder_one["id"], ladder_two["id"], package["id"]


def test_locking_the_replacement_ladder_supersedes_the_shipping_one(api):
    """Hops 1 and 2: L2 becomes `LOCKED` and L1 becomes `SUPERSEDED` by it.

    PRD §3.4: "**Hop 2.** Because this ladder locked, any *other* ladder of the
    same `title_id` **and** the same `codec_family` that was in `LOCKED` moves to
    the terminal `SUPERSEDED`, with its `superseded_by_ladder_id` pointing at the
    ladder that just locked."

    Design: Difficulty/transitive_cascade/ladder_lock_supersede_chain
    """
    title_id, _window_id, l1_id, l2_id, _package_id = _build_lock_cascade_subject(api)

    fx.lock_ladder(api, l2_id)

    assert fx.read_ladder(api, l2_id)["state"] == "LOCKED"
    ladder_one = fx.read_ladder(api, l1_id)
    assert ladder_one["state"] == "SUPERSEDED", ladder_one
    assert ladder_one["superseded_by_ladder_id"] == l2_id, ladder_one
    assert fx.read_title(api, title_id)["locked_ladder_count"] == 1


def test_the_supersede_drives_the_bound_drm_package_stale(api):
    """Hop 3: the package bound to L1 goes `STALE` with `LADDER_SUPERSEDED`.

    PRD §3.4: "**Hop 3.** Because that ladder became `SUPERSEDED`, every DRM
    package bound to it whose `state` was `PACKAGED` moves to `STALE` with
    `stale_reason` of `LADDER_SUPERSEDED`."

    Design: Difficulty/transitive_cascade/ladder_lock_supersede_chain
    """
    _title_id, _window_id, _l1_id, l2_id, package_id = _build_lock_cascade_subject(api)

    fx.lock_ladder(api, l2_id)

    package = fx.read_package(api, package_id)
    assert package["state"] == "STALE", package
    assert package["stale_reason"] == "LADDER_SUPERSEDED", package


def test_the_stale_package_takes_the_published_title_down(api):
    """Hops 4 and 5: `packaging_state` `STALE`, then `TAKEN_DOWN`/`PACKAGING_STALE`.

    PRD §3.4: "**Hop 4.** Because a DRM package of the title is now `STALE`, the
    title's `packaging_state` moves from `PACKAGED` to `STALE` and
    `readiness_score_certified` is recomputed — it drops, because no `PACKAGED`
    package remains."

    PRD §3.4: "**Hop 5.** Because the title's `packaging_state` became `STALE`, a
    title whose `availability_state` was `PUBLISHED` moves to `TAKEN_DOWN` with
    `takedown_reason` of `PACKAGING_STALE`, and every licensing window of that
    title whose `state` was `ACTIVE` moves to `CLOSED` with `closed_at` set to the
    logical clock's current instant."

    Design: Difficulty/transitive_cascade/ladder_lock_supersede_chain
    """
    title_id, _window_id, _l1_id, l2_id, _package_id = _build_lock_cascade_subject(api)

    fx.lock_ladder(api, l2_id)

    title = fx.read_title(api, title_id)
    assert title["packaging_state"] == "STALE", title
    assert title["availability_state"] == "TAKEN_DOWN", title
    assert title["takedown_reason"] == "PACKAGING_STALE", title


def test_the_stale_packaging_closes_the_titles_active_licensing_window(api):
    """Hop 5's second consequence: the `ACTIVE` window is `CLOSED` at the clock.

    PRD §2.9: "Each hop is caused by the *previous* hop, not by the original call,
    which matters when a hop's own precondition is not met — the chain simply stops
    there."

    PRD §3.4: "**Hop 5.** Because the title's `packaging_state` became `STALE`, a
    title whose `availability_state` was `PUBLISHED` moves to `TAKEN_DOWN` with
    `takedown_reason` of `PACKAGING_STALE`, and every licensing window of that
    title whose `state` was `ACTIVE` moves to `CLOSED` with `closed_at` set to the
    logical clock's current instant."

    Design: Difficulty/transitive_cascade/ladder_lock_supersede_chain
    """
    title_id, window_id, _l1_id, l2_id, _package_id = _build_lock_cascade_subject(api)

    fx.lock_ladder(api, l2_id)

    rows, meta = validate_paginated(api.list_availability_windows(title_id, CONTENT_OPS))
    assert meta["total_count"] == 1, meta
    window = next(row for row in rows if row["id"] == window_id)
    assert window["state"] == "CLOSED", window
    assert_instant_equals(window["closed_at"], "2026-09-15T00:00:00Z")


def test_the_lock_cascade_leaves_both_readiness_variants_at_seventy(api):
    """A passed master and a locked ladder but no live package: 50 + 20 + 0.

    PRD §3.1: "Both variants blend three components with fixed weights: the
    source-master component contributes half the score, the ladder component
    contributes one fifth, and the DRM-package component contributes the remaining
    three tenths."

    Design: Difficulty/transitive_cascade/ladder_lock_supersede_chain
    """
    title_id, _window_id, _l1_id, l2_id, _package_id = _build_lock_cascade_subject(api)

    fx.lock_ladder(api, l2_id)

    title = fx.read_title(api, title_id)
    assert_score(title["readiness_score_certified"], 70.00, "Title.readiness_score_certified")
    assert_score(
        title["readiness_score_provisional"], 70.00, "Title.readiness_score_provisional"
    )


# ---------------------------------------------------------------------------
# The metric-ingest cascade
# ---------------------------------------------------------------------------

# The breaching measurement: 90 rebuffers and 20 errors over 1000 attempts with a
# 4400 ms p95 startup, read against a `quality_normalization_factor` of 1.00.
BREACHING_WINDOW = {
    "region_code": "US",
    "window_start_at": "2026-07-25T00:00:00Z",
    "window_end_at": "2026-07-26T00:00:00Z",
    "play_attempts": 1000,
    "rebuffer_events": 90,
    "startup_ms_p95": 4400,
    "error_count": 20,
}


def _build_steering_cascade_subject(api):
    """Three ACTIVE US vendors and one COST-mode policy priced off the cheapest.

    ALPHA (0.0250/GB), BRAVO (0.0300/GB) and CHARLIE (0.0400/GB, US and CA) are
    registered in that order and all seeded at health 100.00, so the `COST`
    selector fills the policy with primary ALPHA and backup BRAVO.  The logical
    clock is left at its 2026-08-01T00:00:00Z default.
    """
    profile = fx.create_tv_4k_profile(api)
    alpha = fx.create_vendor(
        api, vendor_code="ALPHA", regions=["US"], committed_gbps=100.00, cost_per_gb_usd=0.0250
    )
    bravo = fx.create_vendor(
        api, vendor_code="BRAVO", regions=["US"], committed_gbps=80.00, cost_per_gb_usd=0.0300
    )
    charlie = fx.create_vendor(
        api,
        vendor_code="CHARLIE",
        regions=["US", "CA"],
        committed_gbps=60.00,
        cost_per_gb_usd=0.0400,
    )
    title = fx.create_title(
        api,
        external_ref="TTL-STEER-01",
        title_name="Steering Cascade Subject",
        content_type="MOVIE",
        studio_code="NOVAPIC",
    )
    policy = fx.create_policy(api, title["id"], region_code="US", steering_mode="COST")
    return {
        "profile_id": profile["id"],
        "alpha_id": alpha["id"],
        "bravo_id": bravo["id"],
        "charlie_id": charlie["id"],
        "title_id": title["id"],
        "policy_id": policy["id"],
    }


def test_the_cost_policy_starts_on_the_cheapest_vendor_priced_at_27(api):
    """Before the breach: primary ALPHA, backup BRAVO, 1000.00 GB * 0.0250 + 8%.

    PRD §3.7: "Step one, demand: the play attempts are summed as `play_attempts`
    across every ingested playback metric window whose `title_id` and
    `region_code` both match the policy's, with no state filter of any kind since
    metric windows are immutable events; the projected monthly volume is that
    attempt count multiplied by 2.5 gigabytes per play, rounded half up to two
    decimals, or a flat 1000.00 gigabytes when the attempt count is zero."

    Design: Difficulty/transitive_cascade/metric_breach_resteer_chain
    """
    ids = _build_steering_cascade_subject(api)

    policy = fx.read_policy(api, ids["policy_id"])
    assert policy["primary_vendor_id"] == ids["alpha_id"], policy
    assert policy["backup_vendor_id"] == ids["bravo_id"], policy
    assert policy["state"] == "ACTIVE", policy
    assert policy["selection_reason_code"] == "COST_RANK", policy
    assert policy["resteer_count"] == 0, policy
    assert_score(
        policy["projected_egress_cost_usd"], 27.00, "RoutingPolicy.projected_egress_cost_usd"
    )


def test_the_ingested_window_computes_a_breaching_quality_index(api):
    """Hop 1: quality_index 33.50 from a 66.5000 penalty, so `breach_flag` is true.

    PRD §3.7: "Finally the `quality_index` is 100.00 reduced by that penalty,
    clamped into the range 0.00 to 100.00, and rounded half up to two decimals,
    and the `breach_flag` is true exactly when `quality_index` is strictly below
    70.00; a `quality_index` of exactly 70.00 is not a breach while 69.99 is."

    Design: Difficulty/transitive_cascade/metric_breach_resteer_chain
    """
    ids = _build_steering_cascade_subject(api)

    payload = f.playback_metric_payload(
        ids["title_id"], ids["profile_id"], ids["alpha_id"], **BREACHING_WINDOW
    )
    window = validate_success(api.create_playback_metric(payload, DELIVERY_ENGINEER), 201)

    assert_score(window["quality_index"], 33.50, "PlaybackMetricWindow.quality_index")
    assert_ratio_4dp(window["rebuffer_ratio"], 0.0900, "PlaybackMetricWindow.rebuffer_ratio")
    assert_ratio_4dp(window["error_rate"], 0.0200, "PlaybackMetricWindow.error_rate")
    assert window["breach_flag"] is True, window


def test_the_breach_degrades_the_primary_vendor_on_both_health_variants(api):
    """Hop 2: one row makes both variants 33.50, so ACTIVE falls to `DEGRADED`.

    PRD §3.7: "Otherwise, while `breach_window_count` is below 5, a vendor in
    `ACTIVE` whose `health_score_rolling` fell below 50.00 moves to `DEGRADED`,
    and a vendor in `DEGRADED` whose `health_score_rolling` reached 75.00 or more
    moves back to `ACTIVE`, which is the recovery arm of the `ACTIVE` →
    `DEGRADED` → `ACTIVE` cycle."

    Design: Difficulty/transitive_cascade/metric_breach_resteer_chain
    """
    ids = _build_steering_cascade_subject(api)
    fx.ingest_metric(
        api, ids["title_id"], ids["profile_id"], ids["alpha_id"], **BREACHING_WINDOW
    )

    alpha = fx.read_vendor(api, ids["alpha_id"])
    assert_score(alpha["health_score_rolling"], 33.50, "CdnVendor.health_score_rolling")
    assert_score(alpha["health_score_contract"], 33.50, "CdnVendor.health_score_contract")
    assert alpha["breach_window_count"] == 1, alpha
    assert alpha["state"] == "DEGRADED", alpha


def test_the_degraded_primary_cascades_into_an_automatic_resteer(api):
    """Hop 3: ALPHA is excluded and the COST selector promotes BRAVO over CHARLIE.

    PRD §3.7: "If and only if the vendor moved to `DEGRADED` or to `DRAINED`,
    every routing policy whose `primary_vendor_id` is that vendor re-runs the
    selector with that vendor added to its `excluded_vendor_ids` and its
    `resteer_count` incremented by one, landing in `ACTIVE`, `STANDBY_ONLY` or
    `UNROUTABLE` exactly as an operator-driven re-steer would; policies in
    `ACTIVE` and `STANDBY_ONLY` are both eligible for this cascade."

    Design: Difficulty/transitive_cascade/metric_breach_resteer_chain
    """
    ids = _build_steering_cascade_subject(api)
    fx.ingest_metric(
        api, ids["title_id"], ids["profile_id"], ids["alpha_id"], **BREACHING_WINDOW
    )

    policy = fx.read_policy(api, ids["policy_id"])
    assert policy["primary_vendor_id"] == ids["bravo_id"], policy
    assert policy["backup_vendor_id"] == ids["charlie_id"], policy
    assert policy["state"] == "ACTIVE", policy
    assert policy["resteer_count"] == 1, policy
    assert ids["alpha_id"] in policy["excluded_vendor_ids"], policy

    bravo = fx.read_vendor(api, ids["bravo_id"])
    assert bravo["state"] == "ACTIVE", bravo
    assert_score(bravo["health_score_contract"], 100.00, "CdnVendor.health_score_contract")


def test_the_resteer_reprices_egress_against_the_new_primary(api):
    """Hop 4: 27.00 becomes 81.00 -- 2500.00 GB * 0.0300 plus the 0.08 tier.

    PRD §3.7: "Step three, surcharge rate: the tier is keyed on that rounded base
    cost and **never** on the eventual total — a base cost below 500.00 takes a
    rate of 0.08, a base cost of 500.00 or more but below 2000.00 takes 0.05, and
    a base cost of 2000.00 or more takes 0.03; a policy whose `steering_mode` is
    `WEIGHTED` then has a further 0.02 added to whichever rate was selected."

    Design: Difficulty/transitive_cascade/metric_breach_resteer_chain
    """
    ids = _build_steering_cascade_subject(api)
    fx.ingest_metric(
        api, ids["title_id"], ids["profile_id"], ids["alpha_id"], **BREACHING_WINDOW
    )

    policy = fx.read_policy(api, ids["policy_id"])
    assert_score(
        policy["projected_egress_cost_usd"], 81.00, "RoutingPolicy.projected_egress_cost_usd"
    )
