"""Dual-variant derivations and pinned-order formulas.

Two families of arithmetic live here.  The first is the pair of *dual variant*
derivations, where one set of stored rows feeds two figures that deliberately
disagree: a title's `readiness_score_provisional` against its
`readiness_score_certified` (PRD §3.1), and a vendor's `health_score_rolling`
against its `health_score_contract` (PRD §3.7).  The second is the family of
*pinned-order* formulas of PRD §2.8, where "the order of rounding is pinned and
is part of the contract, because the order changes the answer": the reprocessing
estimate that rounds each rung before summing (§3.9), the egress projection
whose surcharge tier is keyed on the base cost rather than the total (§3.7), and
the four-input device compatibility score (§3.3).

Every test starts from an empty database with the logical clock reading
`2026-08-01T00:00:00Z`, and no test here moves the clock.
"""

from prd_bench_local_runner.testing import validate_success
from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.assertions import (
    assert_money,
    assert_money_list,
    assert_score,
    validate_paginated,
)
from test_helpers.test_users import (
    CONTENT_OPS,
    DELIVERY_ENGINEER,
    ENCODING_ENGINEER,
    PLATFORM_ADMIN,
)

# A four-rung HEVC ladder peaking at 2160p / 12000 kbps.
RUNGS_FOUR_PEAK_2160 = [
    f.rung("480p", 480, 1200),
    f.rung("720p", 720, 2500),
    f.rung("1080p", 1080, 5000),
    f.rung("2160p", 2160, 12000),
]


def _build_readiness_reference_title(api):
    """Setup: a title with five masters -- three `QC_PASSED`, two `INGESTED` --
    one `LOCKED` HEVC ladder and one `PACKAGED` DRM package.

    The three clean masters are QC-run, the ladder is locked and the package is
    packaged while every master of the title is `QC_PASSED`, because PRD §3.5
    requires exactly that of a packaging call.  The two extra masters are
    registered afterwards, which is what re-opens the gap between the two
    readiness variants: PRD §3.1 says registering a master "immediately
    recomputes **both** readiness variants on the parent title".
    """
    fx.create_device_profile(api)
    title = fx.create_title(
        api, external_ref="TTL-READY-01", title_name="Readiness Reference Cut"
    )
    for reel in (1, 2, 3):
        fx.create_passed_asset(
            api,
            title["id"],
            source_uri=f"s3://mez/ready-01-reel{reel}.mxf",
            duration_seconds=7200,
        )
    ladder = fx.create_locked_ladder(
        api,
        title["id"],
        codec_family="HEVC",
        rungs=[dict(rung) for rung in RUNGS_FOUR_PEAK_2160],
    )
    package = fx.create_package(
        api,
        title["id"],
        ladder["id"],
        drm_systems=["WIDEVINE", "FAIRPLAY"],
        persistent_license_allowed=True,
    )
    fx.add_entitlement_rule(
        api,
        package["id"],
        max_concurrent_streams=3,
        max_playback_height_px=2160,
        hdcp_level="TYPE_1",
        offline_playback_allowed=True,
        priority=50,
    )
    fx.package_package(api, package["id"])
    for reel in (4, 5):
        fx.create_asset(
            api,
            title["id"],
            source_uri=f"s3://mez/ready-01-reel{reel}.mxf",
            duration_seconds=7200,
        )
    return title["id"], ladder["id"], package["id"]


# ---------------------------------------------------------------------------
# Title readiness: the provisional and certified variants of one stored shape
# ---------------------------------------------------------------------------


def test_readiness_provisional_is_100_while_certified_is_80(api):
    """Five masters, three of them `QC_PASSED`, split the two variants 100.00 / 80.00.

    PRD §3.1: "Both variants blend three components with fixed weights: the
    source-master component contributes half the score, the ladder component
    contributes one fifth, and the DRM-package component contributes the
    remaining three tenths."

    PRD §3.1: "Its master component is 100.00 times the count of the title's
    masters whose `qc_state` is `INGESTED` or `QC_PASSED`, divided by the count
    of *all* the title's masters regardless of state, and is 0.00 when the title
    owns no masters at all."

    Design: Difficulty/dual_variant_calc/title_readiness_provisional_vs_certified
    """
    title_id, _ladder_id, _package_id = _build_readiness_reference_title(api)

    title = validate_success(api.get_title(title_id, CONTENT_OPS), 200)

    assert_score(
        title["readiness_score_provisional"],
        100.00,
        "Title.readiness_score_provisional",
    )
    assert_score(
        title["readiness_score_certified"], 80.00, "Title.readiness_score_certified"
    )
    assert title["readiness_score_provisional"] != title["readiness_score_certified"], (
        "the two variants must diverge on this stored shape: got provisional "
        f"{title['readiness_score_provisional']} and certified "
        f"{title['readiness_score_certified']}"
    )


def test_certified_readiness_counts_only_the_three_qc_passed_masters(api):
    """The certified numerator drops the two `INGESTED` masters the provisional keeps.

    PRD §3.1: "Its master component uses the same denominator — every master of
    the title — but its numerator counts only masters whose `qc_state` is exactly
    `QC_PASSED`, and it is 0.00 when the title owns no masters."

    PRD §3.1: "Because its inclusion sets are subsets of the provisional
    variant's, the certified score is always at or below the provisional score
    computed from the same stored data."

    Design: Difficulty/dual_variant_calc/title_readiness_provisional_vs_certified
    """
    title_id, _ladder_id, _package_id = _build_readiness_reference_title(api)

    rows, meta = validate_paginated(
        api.list_title_mezzanine_assets(title_id, CONTENT_OPS)
    )
    assert meta["total_count"] == 5, f"expected five stored masters, got {meta}"
    states = [row["qc_state"] for row in rows]
    assert states.count("QC_PASSED") == 3, f"expected three QC_PASSED masters: {states}"
    assert states.count("INGESTED") == 2, f"expected two INGESTED masters: {states}"

    title = validate_success(api.get_title(title_id, CONTENT_OPS), 200)
    assert_score(
        title["readiness_score_certified"], 80.00, "Title.readiness_score_certified"
    )
    assert_score(
        title["readiness_score_provisional"],
        100.00,
        "Title.readiness_score_provisional",
    )


def test_packaged_title_with_one_locked_ladder_stays_in_draft(api):
    """`packaging_state` reads `PACKAGED` while `availability_state` is still `DRAFT`.

    PRD §3.4: "Otherwise, if any package is `PACKAGED`, it reads `PACKAGED`."

    PRD §3.6: "Publication itself is never a manual act."

    Design: Difficulty/dual_variant_calc/title_readiness_provisional_vs_certified
    """
    title_id, _ladder_id, _package_id = _build_readiness_reference_title(api)

    title = validate_success(api.get_title(title_id, CONTENT_OPS), 200)

    assert title["packaging_state"] == "PACKAGED", title
    assert title["availability_state"] == "DRAFT", title
    assert title["locked_ladder_count"] == 1, title


# ---------------------------------------------------------------------------
# Vendor health: the rolling and contract variants of one set of metric rows
# ---------------------------------------------------------------------------


def _build_vendor_health_reference(api):
    """Setup: one `SMART_TV_4K` profile with `quality_normalization_factor` 1.00,
    one vendor ALPHA serving US, and three closed metric windows on it.

    The fourth window is left to the test to ingest, because it is the trigger
    that rewrites both health variants.
    """
    profile = fx.create_tv_4k_profile(api)
    vendor = fx.create_vendor(
        api,
        vendor_code="ALPHA",
        regions=["US"],
        committed_gbps=100.00,
        cost_per_gb_usd=0.0300,
    )
    title = fx.create_title(
        api, external_ref="TTL-HEALTH-01", title_name="Health Metrics Subject"
    )
    windows = []
    for start, end, attempts, rebuffers, startup, errors in (
        ("2026-07-20T00:00:00Z", "2026-07-21T00:00:00Z", 1000, 20, 2100, 1),
        ("2026-07-22T00:00:00Z", "2026-07-23T00:00:00Z", 1000, 90, 4400, 20),
        ("2026-07-24T00:00:00Z", "2026-07-25T00:00:00Z", 1000, 30, 2600, 5),
    ):
        windows.append(
            fx.ingest_metric(
                api,
                title["id"],
                profile["id"],
                vendor["id"],
                region_code="US",
                window_start_at=start,
                window_end_at=end,
                play_attempts=attempts,
                rebuffer_events=rebuffers,
                startup_ms_p95=startup,
                error_count=errors,
            )
        )
    return profile["id"], vendor["id"], title["id"], windows


def _ingest_fourth_health_window(api, title_id, profile_id, vendor_id):
    """Ingest the newest window: 500 attempts, 10 rebuffers, 2200 ms, 2 errors."""
    payload = f.playback_metric_payload(
        title_id,
        profile_id,
        vendor_id,
        region_code="US",
        window_start_at="2026-07-26T00:00:00Z",
        window_end_at="2026-07-27T00:00:00Z",
        play_attempts=500,
        rebuffer_events=10,
        startup_ms_p95=2200,
        error_count=2,
    )
    return validate_success(api.create_playback_metric(payload, DELIVERY_ENGINEER), 201)


def test_each_metric_window_scores_its_own_quality_index(api):
    """The four windows score 93.10, 33.50, 81.50 and 90.40, and only the second breaches.

    PRD §3.7: "A raw penalty is then assembled from three terms and rounded half
    up to four decimals: the `rebuffer_ratio` multiplied by 100 and then by a
    weight of 2.5; plus the greater of zero and the `startup_ms_p95` reduced by
    the target of 2000 milliseconds, divided by 100.0 and multiplied by a weight
    of 1.5; plus the `error_rate` multiplied by 100 and then by a weight of 4.0."

    PRD §3.7: "Finally the `quality_index` is 100.00 reduced by that penalty,
    clamped into the range 0.00 to 100.00, and rounded half up to two decimals,
    and the `breach_flag` is true exactly when `quality_index` is strictly below
    70.00; a `quality_index` of exactly 70.00 is not a breach while 69.99 is."

    Design: Difficulty/dual_variant_calc/vendor_health_rolling_vs_contract
    """
    profile_id, vendor_id, title_id, windows = _build_vendor_health_reference(api)
    fourth = _ingest_fourth_health_window(api, title_id, profile_id, vendor_id)

    assert_score(windows[0]["quality_index"], 93.10, "PlaybackMetricWindow.quality_index")
    assert_score(windows[1]["quality_index"], 33.50, "PlaybackMetricWindow.quality_index")
    assert windows[1]["breach_flag"] is True, windows[1]
    assert_score(windows[2]["quality_index"], 81.50, "PlaybackMetricWindow.quality_index")
    assert_score(fourth["quality_index"], 90.40, "PlaybackMetricWindow.quality_index")


def test_vendor_health_rolling_and_contract_diverge_on_the_same_rows(api):
    """The same four rows give a rolling 68.47 and a contract 72.37.

    PRD §3.7: "The `health_score_rolling` variant sorts those rows by
    `window_start_at` descending with `created_at` descending as its only
    tie-break, takes the newest 3 rows, and stores their unweighted arithmetic
    mean of `quality_index`, rounded half up to two decimals; when the vendor has
    fewer than 3 rows the mean is taken over however many exist, and when it has
    none at all the value is 100.00."

    PRD §3.7: "The `health_score_contract` variant instead takes every row and
    computes a `play_attempts`-weighted mean: the sum over all rows of
    `quality_index` multiplied by `play_attempts`, divided by the sum of
    `play_attempts` across those rows, rounded half up to two decimals, and again
    100.00 when no rows exist."

    Design: Difficulty/dual_variant_calc/vendor_health_rolling_vs_contract
    """
    profile_id, vendor_id, title_id, _windows = _build_vendor_health_reference(api)
    _ingest_fourth_health_window(api, title_id, profile_id, vendor_id)

    vendor = validate_success(api.get_cdn_vendor(vendor_id, PLATFORM_ADMIN), 200)

    assert_score(vendor["health_score_rolling"], 68.47, "CdnVendor.health_score_rolling")
    assert_score(
        vendor["health_score_contract"], 72.37, "CdnVendor.health_score_contract"
    )
    assert vendor["health_score_rolling"] != vendor["health_score_contract"], (
        "the weighting and the window size must pull the two variants apart: got "
        f"rolling {vendor['health_score_rolling']} and contract "
        f"{vendor['health_score_contract']}"
    )


def test_one_breach_window_leaves_the_vendor_active(api):
    """`breach_window_count` reads 1 and the vendor stays `ACTIVE`.

    PRD §3.7: "The `breach_window_count` is simply the number of the vendor's
    rows whose `breach_flag` is true."

    PRD §3.7: "Otherwise, while `breach_window_count` is below 5, a vendor in
    `ACTIVE` whose `health_score_rolling` fell below 50.00 moves to `DEGRADED`,
    and a vendor in `DEGRADED` whose `health_score_rolling` reached 75.00 or more
    moves back to `ACTIVE`, which is the recovery arm of the `ACTIVE` →
    `DEGRADED` → `ACTIVE` cycle."

    Design: Difficulty/dual_variant_calc/vendor_health_rolling_vs_contract
    """
    profile_id, vendor_id, title_id, _windows = _build_vendor_health_reference(api)
    _ingest_fourth_health_window(api, title_id, profile_id, vendor_id)

    vendor = validate_success(api.get_cdn_vendor(vendor_id, PLATFORM_ADMIN), 200)

    assert vendor["breach_window_count"] == 1, vendor
    assert vendor["state"] == "ACTIVE", vendor


# ---------------------------------------------------------------------------
# Reprocessing cost: rounding each rung before summing
# ---------------------------------------------------------------------------


def _build_reprocess_cost_reference(api):
    """Setup: a title with one 6000-second `QC_PASSED` master and one `LOCKED`
    H264 ladder whose rungs are 1150 / 2350 / 4850 / 9650 kbps.

    Two profiles are registered so the H264 ladder scores above 0.00 and can
    therefore reach `VALIDATED` and then `LOCKED`.  The title keeps the default
    `encode_budget_usd` of 5000.00.
    """
    fx.create_device_profile(api)
    fx.create_device_profile(
        api,
        device_class="SET_TOP_LEGACY",
        max_height_px=720,
        supported_codecs=["H264"],
        min_bitrate_kbps=500,
        max_bitrate_kbps=3000,
        market_share_pct=25.00,
        quality_normalization_factor=0.75,
    )
    title = fx.create_title(
        api, external_ref="TTL-REPRO-01", title_name="Reprocess Cost Reference"
    )
    fx.create_passed_asset(
        api, title["id"], source_uri="s3://mez/repro-01.mxf", duration_seconds=6000
    )
    ladder = fx.create_locked_ladder(
        api,
        title["id"],
        codec_family="H264",
        rungs=[dict(rung) for rung in f.RUNGS_FOUR_COST_EXAMPLE],
    )
    return title["id"], ladder["id"]


def _queue_hevc_reprocess_job(api, title_id, ladder_id):
    """Queue the `CODEC_DEPRECATION` job into HEVC; a creation, so it answers 201."""
    payload = f.reprocess_job_payload(
        title_id,
        ladder_id,
        fx.title_version(api, title_id),
        trigger_reason="CODEC_DEPRECATION",
        target_codec_family="HEVC",
    )
    return validate_success(api.create_reprocess_job(payload, ENCODING_ENGINEER), 201)


def test_per_rung_costs_round_to_cents_before_they_are_summed(api):
    """100 billable HEVC minutes over four rungs total 48.62, not 48.60.

    PRD §3.9: "The `cost_estimate_usd` is then the sum of those **already-rounded**
    per-rung entries, re-rounded to two decimals."

    PRD §3.9: "The order is load-bearing: 100 billable minutes of `HEVC` over
    source rungs of 1150, 2350, 4850 and 9650 kilobits per second give per-rung
    costs of 3.11, 6.35, 13.10 and 26.06 and a total of 48.62, whereas summing the
    unrounded products first and rounding once would give 48.60, which is the
    wrong answer."

    Design: Difficulty/combinatorial_formula/reprocess_cost_round_per_rung_then_sum
    """
    title_id, ladder_id = _build_reprocess_cost_reference(api)

    job = _queue_hevc_reprocess_job(api, title_id, ladder_id)

    assert_money_list(
        job["per_rung_cost_usd"],
        [3.11, 6.35, 13.10, 26.06],
        "ReprocessJob.per_rung_cost_usd",
    )
    assert_money(job["cost_estimate_usd"], 48.62, "ReprocessJob.cost_estimate_usd")
    assert round(float(job["cost_estimate_usd"]), 2) != 48.60, (
        "48.60 is the answer produced by summing the unrounded products and "
        f"rounding once, which the PRD rejects: got {job['cost_estimate_usd']}"
    )


def test_priority_rank_adds_the_trigger_weight_to_the_cost_share(api):
    """A `CODEC_DEPRECATION` job costing 48.62 ranks 44.86.

    PRD §3.9: "The `priority_rank` follows from the same figures: it is the weight
    of the job's `trigger_reason` — 40.0 for `CODEC_DEPRECATION`, 30.0 for
    `STANDARD_UPDATE`, 20.0 for `QUALITY_REGRESSION` and 10.0 for
    `DEVICE_MATRIX_CHANGE` — plus the lesser of 20.0 and the `cost_estimate_usd`
    divided by 10.0, rounded half up to two decimals."

    Design: Difficulty/combinatorial_formula/reprocess_cost_round_per_rung_then_sum
    """
    title_id, ladder_id = _build_reprocess_cost_reference(api)

    job = _queue_hevc_reprocess_job(api, title_id, ladder_id)

    assert_money(job["cost_estimate_usd"], 48.62, "ReprocessJob.cost_estimate_usd")
    assert_score(job["priority_rank"], 44.86, "ReprocessJob.priority_rank")


def test_a_queued_job_debits_nothing_from_the_encode_budget(api):
    """The job sits in `QUEUED` with `committed_usd` 0.00 and the budget untouched.

    PRD §3.9: "A job that clears all four is stored in `state` `QUEUED` with
    `result_ladder_id` null, `committed_usd` 0.00, `abort_reason` `NONE`, and the
    title's `version` incremented by one."

    PRD §3.9: "At every observable moment `encode_budget_remaining_usd` equals the
    title's `encode_budget_usd` less the rounded sum of `cost_estimate_usd` over
    that title's jobs whose `state` is `RUNNING` or `COMPLETED`, to two decimals."

    Design: Difficulty/combinatorial_formula/reprocess_cost_round_per_rung_then_sum
    """
    title_id, ladder_id = _build_reprocess_cost_reference(api)

    job = _queue_hevc_reprocess_job(api, title_id, ladder_id)

    assert job["state"] == "QUEUED", job
    assert_money(job["committed_usd"], 0.00, "ReprocessJob.committed_usd")

    title = validate_success(api.get_title(title_id, CONTENT_OPS), 200)
    assert_money(
        title["encode_budget_remaining_usd"],
        5000.00,
        "Title.encode_budget_remaining_usd",
    )


# ---------------------------------------------------------------------------
# Egress projection: the surcharge tier is keyed on the base cost
# ---------------------------------------------------------------------------


def _build_egress_tier_reference(api):
    """Setup: one vendor CHARLIE serving US and CA at 0.0400 per GB -- the only
    vendor serving CA -- and one closed CA metric window carrying 4800 attempts,
    so the projected monthly volume is 12000.00 GB and the base cost 480.00.
    """
    profile = fx.create_device_profile(api)
    vendor = fx.create_vendor(
        api,
        vendor_code="CHARLIE",
        regions=["US", "CA"],
        committed_gbps=60.00,
        cost_per_gb_usd=0.0400,
    )
    title = fx.create_title(
        api, external_ref="TTL-EGRESS-01", title_name="Egress Tier Reference"
    )
    window = fx.ingest_metric(
        api,
        title["id"],
        profile["id"],
        vendor["id"],
        region_code="CA",
        window_start_at="2026-07-25T00:00:00Z",
        window_end_at="2026-07-26T00:00:00Z",
        play_attempts=4800,
        rebuffer_events=96,
        startup_ms_p95=2100,
        error_count=5,
    )
    return vendor["id"], title["id"], window


def _create_ca_performance_policy(api, title_id):
    payload = f.routing_policy_payload(
        title_id, region_code="CA", steering_mode="PERFORMANCE"
    )
    return validate_success(api.create_routing_policy(payload, DELIVERY_ENGINEER), 201)


def test_egress_tier_is_keyed_on_the_rounded_base_cost(api):
    """A `PERFORMANCE` policy with a base cost of 480.00 totals 518.40.

    PRD §3.7: "Step three, surcharge rate: the tier is keyed on that rounded base
    cost and **never** on the eventual total — a base cost below 500.00 takes a
    rate of 0.08, a base cost of 500.00 or more but below 2000.00 takes 0.05, and a
    base cost of 2000.00 or more takes 0.03; a policy whose `steering_mode` is
    `WEIGHTED` then has a further 0.02 added to whichever rate was selected."

    PRD §3.7: "The pinned order matters because the total and the tier look
    circular: a base cost of 480.00 under `PERFORMANCE` steering takes the 0.08
    rate for a surcharge of 38.40 and a total of 518.40, whereas re-keying the tier
    on that 518.40 total would wrongly yield 504.00."

    Design: Difficulty/combinatorial_formula/egress_tier_keyed_on_base_cost
    """
    _vendor_id, title_id, _window = _build_egress_tier_reference(api)

    policy = _create_ca_performance_policy(api, title_id)

    assert_money(
        policy["projected_egress_cost_usd"],
        518.40,
        "RoutingPolicy.projected_egress_cost_usd",
    )
    assert round(float(policy["projected_egress_cost_usd"]), 2) != 504.00, (
        "504.00 is the total produced by re-keying the tier on the total itself, "
        f"which the PRD rejects: got {policy['projected_egress_cost_usd']}"
    )


def test_the_demand_metric_window_scores_93_79_without_breaching(api):
    """The CA window carrying the 4800 attempts scores 93.79 and does not breach.

    PRD §3.7: "The raw penalty is then multiplied by the
    `quality_normalization_factor` of the device profile named by
    `device_profile_id` and rounded half up to four decimals — and that factor is
    read even when the profile's `state` is `RETIRED`, because the measurement is
    historical fact."

    PRD §3.7: "Step one, demand: the play attempts are summed as `play_attempts`
    across every ingested playback metric window whose `title_id` and
    `region_code` both match the policy's, with no state filter of any kind since
    metric windows are immutable events; the projected monthly volume is that
    attempt count multiplied by 2.5 gigabytes per play, rounded half up to two
    decimals, or a flat 1000.00 gigabytes when the attempt count is zero."

    Design: Difficulty/combinatorial_formula/egress_tier_keyed_on_base_cost
    """
    _vendor_id, title_id, window = _build_egress_tier_reference(api)

    assert_score(window["quality_index"], 93.79, "PlaybackMetricWindow.quality_index")
    assert window["breach_flag"] is False, window
    assert window["play_attempts"] == 4800, window

    policy = _create_ca_performance_policy(api, title_id)
    assert_money(
        policy["projected_egress_cost_usd"],
        518.40,
        "RoutingPolicy.projected_egress_cost_usd",
    )


def test_a_single_eligible_vendor_lands_the_policy_on_standby_only(api):
    """CHARLIE is the only CA candidate, so the policy is `STANDBY_ONLY` with no backup.

    PRD §3.7: "Assignment third: `primary_vendor_id` becomes the first-ranked
    candidate, `backup_vendor_id` becomes the second-ranked candidate when two or
    more candidates survive and is null otherwise, `state` becomes `ACTIVE` with
    two or more candidates and `STANDBY_ONLY` with exactly one, and
    `selection_reason_code` records which branch chose the primary —
    `PERFORMANCE_RANK`, `COST_RANK` or `WEIGHTED_RANK` according to the mode."

    Design: Difficulty/combinatorial_formula/egress_tier_keyed_on_base_cost
    """
    vendor_id, title_id, _window = _build_egress_tier_reference(api)

    policy = _create_ca_performance_policy(api, title_id)

    assert policy["primary_vendor_id"] == vendor_id, policy
    assert policy["backup_vendor_id"] is None, policy
    assert policy["state"] == "STANDBY_ONLY", policy
    assert policy["selection_reason_code"] == "PERFORMANCE_RANK", policy


# ---------------------------------------------------------------------------
# Device compatibility: four inputs interacting on one validation
# ---------------------------------------------------------------------------


def _build_device_compat_reference(api):
    """Setup: all three device profiles `ACTIVE`, a title with one `QC_PASSED`
    master, one `DRAFT` HEVC ladder of four rungs peaking at 2160p / 12000 kbps,
    and one `PENDING` DRM package advertising WIDEVINE bound to that draft ladder.
    """
    fx.create_tv_4k_profile(api)
    fx.create_device_profile(api)
    fx.create_device_profile(
        api,
        device_class="SET_TOP_LEGACY",
        max_height_px=720,
        supported_codecs=["H264"],
        min_bitrate_kbps=500,
        max_bitrate_kbps=3000,
        market_share_pct=25.00,
        quality_normalization_factor=0.75,
    )
    title = fx.create_title(
        api, external_ref="TTL-COMPAT-01", title_name="Compatibility Matrix Reference"
    )
    fx.create_passed_asset(
        api, title["id"], source_uri="s3://mez/compat-01.mxf", duration_seconds=7200
    )
    ladder = fx.create_ladder(
        api,
        title["id"],
        codec_family="HEVC",
        rungs=[dict(rung) for rung in RUNGS_FOUR_PEAK_2160],
    )
    package = fx.create_package(
        api,
        title["id"],
        ladder["id"],
        drm_systems=["WIDEVINE"],
        persistent_license_allowed=False,
    )
    return title["id"], ladder["id"], package["id"]


def test_device_compat_score_interacts_four_inputs_to_reach_65(api):
    """Two compatible profiles, a 4/5 coverage multiplier and the 4K bonus give 65.00.

    PRD §3.3: "Third, either the profile's `required_drm_system` is `NONE`, or the
    ladder's title already owns at least one DRM package whose `state` is `PENDING`
    or `PACKAGED` and whose `drm_systems` array contains that required system;
    packages in `STALE` or `REVOKED` never satisfy a device's DRM requirement."

    PRD §3.3: "A coverage multiplier is taken as the lesser of 1.00 and the
    ladder's `rung_count` divided by the target of 5 rungs, so a two-rung ladder
    keeps only two fifths of the reach it would otherwise claim while a five-rung
    or longer ladder keeps all of it."

    PRD §3.3: "A bonus of 5.00 is added when the ladder's `peak_height_px` is 2160
    or greater **and** its `compatible_device_count` is at least 1; otherwise the
    bonus is 0.00."

    Design: Difficulty/combinatorial_formula/device_compat_score_four_input_interaction
    """
    _title_id, ladder_id, _package_id = _build_device_compat_reference(api)

    ladder = validate_success(
        api.validate_encoding_ladder(ladder_id, ENCODING_ENGINEER), 200
    )

    assert ladder["compatible_device_count"] == 2, ladder
    assert_score(
        ladder["device_compat_score"], 65.00, "EncodingLadder.device_compat_score"
    )


def test_the_accepting_arm_validates_the_ladder_and_keeps_its_peaks(api):
    """The strictly increasing four-rung ladder reaches `VALIDATED` with reason `OK`.

    PRD §3.3: "The **accepting arm** applies when the ladder's `rungs` are strictly
    increasing in both `height_px` and `bitrate_kbps` in stored array order, no two
    rungs share a `height_px`, and the computed `device_compat_score` is strictly
    greater than 0.00."

    PRD §3.3: "A newly authored ladder is stored in `state` `DRAFT` with
    `rung_count` set to the number of elements in `rungs`, `peak_bitrate_kbps` set
    to the largest `bitrate_kbps` across the rungs and `peak_height_px` set to the
    largest `height_px`."

    Design: Difficulty/combinatorial_formula/device_compat_score_four_input_interaction
    """
    _title_id, ladder_id, _package_id = _build_device_compat_reference(api)

    ladder = validate_success(
        api.validate_encoding_ladder(ladder_id, ENCODING_ENGINEER), 200
    )

    assert ladder["state"] == "VALIDATED", ladder
    assert ladder["validation_reason_code"] == "OK", ladder
    assert ladder["rung_count"] == 4, ladder
    assert ladder["peak_height_px"] == 2160, ladder
    assert ladder["peak_bitrate_kbps"] == 12000, ladder


def test_the_enabling_package_derives_a_type_1_hdcp_floor(api):
    """The package bound to the 2160p ladder derives `hdcp_floor` `TYPE_1`.

    PRD §3.5: "The package's `hdcp_floor` is derived, not supplied: it reads
    `TYPE_1` when the bound ladder's `peak_height_px` is 2160 or greater, `TYPE_0`
    when that height is 1080 or greater but below 2160, and `NONE` otherwise."

    PRD §3.5: "The floor is the minimum output-protection level every entitlement
    rule on the package must meet, and it carries one packaging obligation of its
    own: whenever `hdcp_floor` is `TYPE_1`, the package's `drm_systems` must include
    `WIDEVINE`, and a 4K-capable package that omits it is refused with
    `ERR_DRM_SYSTEM_UNSUPPORTED`."

    Design: Difficulty/combinatorial_formula/device_compat_score_four_input_interaction
    """
    _title_id, ladder_id, package_id = _build_device_compat_reference(api)

    package = validate_success(api.get_drm_package(package_id, PLATFORM_ADMIN), 200)

    assert package["hdcp_floor"] == "TYPE_1", package
    assert package["state"] == "PENDING", package
    assert package["drm_systems"] == ["WIDEVINE"], package

    ladder = validate_success(
        api.validate_encoding_ladder(ladder_id, ENCODING_ENGINEER), 200
    )
    assert ladder["compatible_device_count"] == 2, ladder
