"""Arithmetic breadth across every scored calculation in the specification.

Each test drives one calculation to a literal figure the PRD derives uniquely,
and every threshold is exercised on both sides of its boundary where the PRD
pins both sides: a `severity_index` of 40.00 against 39.94, a loudness
deviation of 6.00 against 6.01, a `quality_index` of 70.00 against 69.99, and a
`requested_streams` count at the licensed ceiling against one stream more.

Per-attempt QC evidence is read from the master's report list, which PRD §3.2
names as its sole channel.  Money, bandwidth and score fields are compared with
`assert_money` / `assert_score` at two decimals and the four-decimal ratios with
`assert_ratio_4dp`, never with a bare float equality (§2.8).
"""

from prd_bench_local_runner.testing import validate_error, validate_success, get_success_data
from test_helpers import api_errors as err
from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.assertions import (
    assert_money,
    assert_money_list,
    assert_ratio_4dp,
    assert_score,
    assert_sweep_counters,
    validate_paginated,
    validate_unpaginated,
)
from test_helpers.test_users import (
    CONTENT_OPS,
    DELIVERY_ENGINEER,
    DRM_OPERATOR,
    ENCODING_ENGINEER,
    PLATFORM_ADMIN,
    QC_ANALYST,
)

# ---------------------------------------------------------------------------
# Local helpers.  `test_helpers/` is shared infrastructure and is never edited,
# so the two shapes this file needs repeatedly live here.
# ---------------------------------------------------------------------------


def _qc_reports(api, asset_id):
    """The master's QC report list, ordered by `attempt_number` ascending (§3.2)."""
    rows, _meta = validate_paginated(api.list_qc_reports(asset_id, QC_ANALYST))
    return rows


def _run_qc(api, asset_id):
    """Run QC (a creation, so 201) and return the report the run recorded."""
    return validate_success(api.run_qc(asset_id, QC_ANALYST), 201)


def _latest_report(api, asset_id):
    reports = _qc_reports(api, asset_id)
    assert reports, f"expected at least one QC report for {asset_id}"
    return reports[-1]


def _read_asset(api, asset_id):
    return validate_success(api.get_mezzanine_asset(asset_id, CONTENT_OPS), 200)


def _mobile_high_profile(api, **overrides):
    """The MOBILE_HIGH profile of the calculation fixtures: H264 only, a
    500..8000 kbps window, 45.00 share and an unbiased normalization factor."""
    payload = {
        "device_class": "MOBILE_HIGH",
        "max_height_px": 1080,
        "supported_codecs": ["H264"],
        "min_bitrate_kbps": 500,
        "max_bitrate_kbps": 8000,
        "hdcp_required": False,
        "required_drm_system": "NONE",
        "market_share_pct": 45.00,
        "quality_normalization_factor": 1.00,
    }
    payload.update(overrides)
    return get_success_data(api.create_device_profile(payload, PLATFORM_ADMIN))


def _tv_hd_profile(api, **overrides):
    payload = {
        "device_class": "SMART_TV_HD",
        "max_height_px": 1080,
        "supported_codecs": ["H264"],
        "min_bitrate_kbps": 500,
        "max_bitrate_kbps": 8000,
        "hdcp_required": False,
        "required_drm_system": "NONE",
        "market_share_pct": 55.00,
        "quality_normalization_factor": 1.00,
    }
    payload.update(overrides)
    return get_success_data(api.create_device_profile(payload, PLATFORM_ADMIN))


RUNGS_480_1080 = [
    f.rung("480p", 480, 1200),
    f.rung("1080p", 1080, 5000),
]
RUNGS_480_720 = [
    f.rung("480p", 480, 1200),
    f.rung("720p", 720, 2500),
]


# ---------------------------------------------------------------------------
# Quality control: the aggregate-severity gate (§3.2)
# ---------------------------------------------------------------------------


def test_qc_severity_index_of_exactly_forty_is_a_blocking_fail(api):
    """Seven artefacts at -28.0 LUFS sum to severity 40.00 and FAIL as MULTI_DEFECT.

    PRD §3.2: "If none contributed but the `severity_index` reached 40.0 or
    more, the code is `MULTI_DEFECT` as an aggregate-severity breach — a
    `severity_index` of exactly 40.00 is blocking while 39.99 is not."

    Design: Corner/calculations/qc_severity_fail_threshold_is_inclusive_at_forty
    """
    title = fx.create_title(
        api,
        external_ref="TTL-QC-SEV-40",
        title_name="Severity Gate Cut",
        studio_code="NOVAPIC",
    )
    at_gate = fx.create_asset(
        api,
        title["id"],
        source_uri="s3://mez/sev-40.mxf",
        duration_seconds=7200,
        frame_rate=24.0,
        peak_audio_lufs=-28.0,
        artifact_defect_count=7,
        caption_languages=["en"],
        audio_language="en",
    )

    _run_qc(api, at_gate["id"])

    report = _latest_report(api, at_gate["id"])
    assert_score(report["artifact_penalty"], 28.00, "artifact_penalty")
    assert_score(report["loudness_deviation_db"], 4.00, "loudness_deviation_db")
    assert_score(report["caption_coverage_pct"], 100.00, "caption_coverage_pct")
    assert_score(report["severity_index"], 40.00, "severity_index")
    assert report["verdict"] == "FAIL", report
    assert report["blocking_defect_code"] == "MULTI_DEFECT", report

    asset = _read_asset(api, at_gate["id"])
    assert asset["qc_state"] == "QC_FAILED", asset
    assert_score(asset["latest_severity_index"], 40.00, "latest_severity_index")


def test_qc_severity_index_of_thirty_nine_ninety_four_is_only_a_warning(api):
    """The same shape 0.01 dB quieter sums to 39.94 and warns with code NONE.

    PRD §3.2: "Otherwise, a `severity_index` strictly greater than 0.00, or an
    `artifact_defect_count` of 3 or more, yields `WARN`."

    Design: Corner/calculations/qc_severity_fail_threshold_is_inclusive_at_forty
    """
    title = fx.create_title(
        api,
        external_ref="TTL-QC-SEV-40",
        title_name="Severity Gate Cut",
        studio_code="NOVAPIC",
    )
    under_gate = fx.create_asset(
        api,
        title["id"],
        source_uri="s3://mez/sev-3994.mxf",
        duration_seconds=7200,
        frame_rate=24.0,
        peak_audio_lufs=-27.99,
        artifact_defect_count=7,
        caption_languages=["en"],
        audio_language="en",
    )

    _run_qc(api, under_gate["id"])

    report = _latest_report(api, under_gate["id"])
    assert_score(report["loudness_deviation_db"], 3.99, "loudness_deviation_db")
    assert_score(report["severity_index"], 39.94, "severity_index")
    assert report["verdict"] == "WARN", report
    assert report["blocking_defect_code"] == "NONE", report

    asset = _read_asset(api, under_gate["id"])
    assert asset["qc_state"] == "QC_PASSED", asset


def test_qc_loudness_deviation_of_exactly_two_decibels_is_absorbed(api):
    """A 2.00 dB deviation is penalised nothing and the master simply passes.

    PRD §3.2: "A loudness penalty is then taken as the greater of zero and the
    `loudness_deviation_db` reduced by the tolerance of 2.0 decibels,
    multiplied by 6.0, rounded half up to two decimals — so a master within 2.0
    decibels of target is penalised nothing for loudness."

    Design: Corner/calculations/qc_loudness_tolerance_band_absorbs_two_decibels
    """
    title = fx.create_title(
        api,
        external_ref="TTL-QC-TOL",
        title_name="Tolerance Band Cut",
        studio_code="NOVAPIC",
    )
    at_band = fx.create_asset(
        api,
        title["id"],
        source_uri="s3://mez/tol-at.mxf",
        duration_seconds=3600,
        frame_rate=25.0,
        peak_audio_lufs=-26.0,
        artifact_defect_count=0,
        caption_languages=["en"],
        audio_language="en",
    )

    _run_qc(api, at_band["id"])

    report = _latest_report(api, at_band["id"])
    assert_score(report["loudness_deviation_db"], 2.00, "loudness_deviation_db")
    assert_score(report["severity_index"], 0.00, "severity_index")
    assert_score(report["artifact_penalty"], 0.00, "artifact_penalty")
    assert report["verdict"] == "PASS", report
    assert report["blocking_defect_code"] == "NONE", report
    assert report["attempt_number"] == 1, report

    assert _read_asset(api, at_band["id"])["qc_state"] == "QC_PASSED"


def test_qc_loudness_penalty_charges_only_the_excess_over_the_tolerance(api):
    """One hundredth beyond the band costs 0.06, the excess and not the whole 2.01.

    PRD §3.2: "The `severity_index` is the sum of the artifact penalty, the
    loudness penalty and the caption penalty, rounded half up to two decimals."

    Design: Corner/calculations/qc_loudness_tolerance_band_absorbs_two_decibels
    """
    title = fx.create_title(
        api,
        external_ref="TTL-QC-TOL",
        title_name="Tolerance Band Cut",
        studio_code="NOVAPIC",
    )
    over_band = fx.create_asset(
        api,
        title["id"],
        source_uri="s3://mez/tol-over.mxf",
        duration_seconds=3600,
        frame_rate=25.0,
        peak_audio_lufs=-26.01,
        artifact_defect_count=0,
        caption_languages=["en"],
        audio_language="en",
    )

    _run_qc(api, over_band["id"])

    report = _latest_report(api, over_band["id"])
    assert_score(report["loudness_deviation_db"], 2.01, "loudness_deviation_db")
    assert_score(report["severity_index"], 0.06, "severity_index")
    assert report["verdict"] == "WARN", report
    assert report["blocking_defect_code"] == "NONE", report

    assert _read_asset(api, over_band["id"])["qc_state"] == "QC_PASSED"


def test_qc_deviation_of_exactly_six_decibels_is_not_a_blocking_condition(api):
    """A -30.0 LUFS master deviates 6.00 dB, warns at severity 24.00, code NONE.

    PRD §3.2: "A `loudness_deviation_db` strictly greater than 6.0 contributes
    `LOUDNESS_OUT_OF_SPEC`; a deviation of exactly 6.0 does not, while 6.01
    does."

    Design: Corner/calculations/qc_loudness_fail_boundary_is_exclusive_at_six_decibels
    """
    title = fx.create_title(
        api,
        external_ref="TTL-QC-LOUD",
        title_name="Loudness Gate Cut",
        studio_code="NOVAPIC",
    )
    at_boundary = fx.create_asset(
        api,
        title["id"],
        source_uri="s3://mez/loud-at.mxf",
        duration_seconds=3600,
        frame_rate=24.0,
        peak_audio_lufs=-30.0,
        artifact_defect_count=0,
        caption_languages=["en"],
        audio_language="en",
    )

    _run_qc(api, at_boundary["id"])

    report = _latest_report(api, at_boundary["id"])
    assert_score(report["loudness_deviation_db"], 6.00, "loudness_deviation_db")
    assert_score(report["severity_index"], 24.00, "severity_index")
    assert report["verdict"] == "WARN", report
    assert report["blocking_defect_code"] == "NONE", report

    assert _read_asset(api, at_boundary["id"])["qc_state"] == "QC_PASSED"


def test_qc_deviation_of_six_point_zero_one_blocks_as_loudness_out_of_spec(api):
    """A 6.01 dB deviation fails the master on the loudness condition alone.

    PRD §3.2: "If exactly one contributed, it is that one."

    Design: Corner/calculations/qc_loudness_fail_boundary_is_exclusive_at_six_decibels
    """
    title = fx.create_title(
        api,
        external_ref="TTL-QC-LOUD",
        title_name="Loudness Gate Cut",
        studio_code="NOVAPIC",
    )
    over_boundary = fx.create_asset(
        api,
        title["id"],
        source_uri="s3://mez/loud-over.mxf",
        duration_seconds=3600,
        frame_rate=24.0,
        peak_audio_lufs=-30.01,
        artifact_defect_count=0,
        caption_languages=["en"],
        audio_language="en",
    )

    _run_qc(api, over_boundary["id"])

    report = _latest_report(api, over_boundary["id"])
    assert_score(report["loudness_deviation_db"], 6.01, "loudness_deviation_db")
    assert_score(report["severity_index"], 24.06, "severity_index")
    assert report["verdict"] == "FAIL", report
    assert report["blocking_defect_code"] == "LOUDNESS_OUT_OF_SPEC", report

    asset = _read_asset(api, over_boundary["id"])
    assert asset["qc_state"] == "QC_FAILED", asset
    assert asset["qc_attempt_count"] == 1, asset


def test_qc_a_caption_only_defect_reports_caption_missing_at_severity_thirty(api):
    """No caption track at all costs a flat 30.00 and blocks as CAPTION_MISSING.

    PRD §3.2: "A `caption_coverage_pct` of 0.00 contributes `CAPTION_MISSING`."

    Design: Corner/calculations/qc_blocking_set_size_decides_single_code_versus_multi_defect
    """
    title = fx.create_title(
        api,
        external_ref="TTL-QC-MULTI",
        title_name="Blocking Set Cut",
        studio_code="NOVAPIC",
    )
    caption_only = fx.create_asset(
        api,
        title["id"],
        source_uri="s3://mez/cap-only.mxf",
        duration_seconds=3600,
        frame_rate=24.0,
        peak_audio_lufs=-24.0,
        artifact_defect_count=0,
        caption_languages=None,
        audio_language="en",
    )

    _run_qc(api, caption_only["id"])

    report = _latest_report(api, caption_only["id"])
    assert_score(report["caption_coverage_pct"], 0.00, "caption_coverage_pct")
    assert_score(report["severity_index"], 30.00, "severity_index")
    assert report["verdict"] == "FAIL", report
    assert report["blocking_defect_code"] == "CAPTION_MISSING", report

    assert _read_asset(api, caption_only["id"])["qc_state"] == "QC_FAILED"


def test_qc_an_artifact_only_defect_reports_artifact_burst_not_multi_defect(api):
    """Eight artefacts alone block as ARTIFACT_BURST even though 32.00 is below 40.00.

    PRD §3.2: "An `artifact_defect_count` of 8 or more contributes
    `ARTIFACT_BURST`."

    Design: Corner/calculations/qc_blocking_set_size_decides_single_code_versus_multi_defect
    """
    title = fx.create_title(
        api,
        external_ref="TTL-QC-MULTI",
        title_name="Blocking Set Cut",
        studio_code="NOVAPIC",
    )
    artifact_only = fx.create_asset(
        api,
        title["id"],
        source_uri="s3://mez/art-only.mxf",
        duration_seconds=3600,
        frame_rate=24.0,
        peak_audio_lufs=-24.0,
        artifact_defect_count=8,
        caption_languages=["en"],
        audio_language="en",
    )

    _run_qc(api, artifact_only["id"])

    report = _latest_report(api, artifact_only["id"])
    assert_score(report["artifact_penalty"], 32.00, "artifact_penalty")
    assert_score(report["caption_coverage_pct"], 100.00, "caption_coverage_pct")
    assert_score(report["severity_index"], 32.00, "severity_index")
    assert report["blocking_defect_code"] == "ARTIFACT_BURST", report
    assert report["verdict"] == "FAIL", report

    assert _read_asset(api, artifact_only["id"])["qc_state"] == "QC_FAILED"


def test_qc_two_blocking_conditions_collapse_into_multi_defect(api):
    """Eight artefacts and no captions together report MULTI_DEFECT at 62.00.

    PRD §3.2: "If two or more conditions contributed, `blocking_defect_code` is
    `MULTI_DEFECT`."

    Design: Corner/calculations/qc_blocking_set_size_decides_single_code_versus_multi_defect
    """
    title = fx.create_title(
        api,
        external_ref="TTL-QC-MULTI",
        title_name="Blocking Set Cut",
        studio_code="NOVAPIC",
    )
    both = fx.create_asset(
        api,
        title["id"],
        source_uri="s3://mez/both.mxf",
        duration_seconds=3600,
        frame_rate=24.0,
        peak_audio_lufs=-24.0,
        artifact_defect_count=8,
        caption_languages=None,
        audio_language="en",
    )

    _run_qc(api, both["id"])

    report = _latest_report(api, both["id"])
    assert_score(report["artifact_penalty"], 32.00, "artifact_penalty")
    assert_score(report["severity_index"], 62.00, "severity_index")
    assert report["blocking_defect_code"] == "MULTI_DEFECT", report
    assert report["verdict"] == "FAIL", report

    assert _read_asset(api, both["id"])["qc_state"] == "QC_FAILED"


def test_qc_loudness_deviation_is_rounded_before_the_tolerance_is_subtracted(api):
    """A 2.765 dB raw deviation is stored as 2.77 and drives severity 4.62.

    PRD §3.2: "The `loudness_deviation_db` is the absolute difference between
    the master's `peak_audio_lufs` and the platform loudness target of -24.0
    LUFS, rounded half up to two decimals."

    Design: Corner/calculations/qc_loudness_deviation_rounds_half_up_before_the_tolerance_subtraction
    """
    title = fx.create_title(
        api,
        external_ref="TTL-QC-PREC",
        title_name="Rounding Cut",
        studio_code="NOVAPIC",
    )
    asset = fx.create_asset(
        api,
        title["id"],
        source_uri="s3://mez/prec.mxf",
        duration_seconds=3600,
        frame_rate=29.97,
        peak_audio_lufs=-21.235,
        artifact_defect_count=0,
        caption_languages=["en"],
        audio_language="en",
    )

    _run_qc(api, asset["id"])

    report = _latest_report(api, asset["id"])
    assert_score(report["loudness_deviation_db"], 2.77, "loudness_deviation_db")
    assert_score(report["severity_index"], 4.62, "severity_index")
    assert report["verdict"] == "WARN", report
    assert report["blocking_defect_code"] == "NONE", report

    stored = _read_asset(api, asset["id"])
    assert_score(stored["latest_severity_index"], 4.62, "latest_severity_index")
    assert stored["qc_state"] == "QC_PASSED", stored


# ---------------------------------------------------------------------------
# Playback quality: the breach gate and the clamp (§3.7)
# ---------------------------------------------------------------------------


def _ingest_metric(api, payload):
    created = validate_success(api.create_playback_metric(payload, DELIVERY_ENGINEER), 201)
    return validate_success(api.get_playback_metric(created["id"], DELIVERY_ENGINEER), 200)


def test_playback_quality_index_of_exactly_seventy_is_not_a_breach(api):
    """A window landing on 70.00 exactly carries `breach_flag` false.

    PRD §3.7: "Finally the `quality_index` is 100.00 reduced by that penalty,
    clamped into the range 0.00 to 100.00, and rounded half up to two decimals,
    and the `breach_flag` is true exactly when `quality_index` is strictly below
    70.00; a `quality_index` of exactly 70.00 is not a breach while 69.99 is."

    Design: Corner/calculations/playback_breach_threshold_is_strict_at_seventy
    """
    title = fx.create_title(
        api, external_ref="TTL-QI-70", title_name="Breach Gate Cut", studio_code="NOVAPIC"
    )
    profile = _mobile_high_profile(api)
    vendor = fx.create_vendor(
        api,
        vendor_code="ALPHACDN",
        regions=["US"],
        committed_gbps=100.00,
        cost_per_gb_usd=0.0300,
    )

    at_gate = _ingest_metric(
        api,
        f.playback_metric_payload(
            title["id"],
            profile["id"],
            vendor["id"],
            region_code="US",
            window_start_at="2026-07-10T00:00:00Z",
            window_end_at="2026-07-11T00:00:00Z",
            play_attempts=1000,
            rebuffer_events=120,
            startup_ms_p95=2000,
            error_count=0,
        ),
    )

    assert_ratio_4dp(at_gate["rebuffer_ratio"], 0.1200, "rebuffer_ratio")
    assert_ratio_4dp(at_gate["error_rate"], 0.0000, "error_rate")
    assert_score(at_gate["quality_index"], 70.00, "quality_index")
    assert at_gate["breach_flag"] is False, at_gate


def test_playback_quality_index_of_sixty_nine_ninety_nine_is_a_breach(api):
    """One millisecond of extra startup latency drops the index to 69.99 and breaches.

    PRD §3.7: "A raw penalty is then assembled from three terms and rounded half
    up to four decimals: the `rebuffer_ratio` multiplied by 100 and then by a
    weight of 2.5; plus the greater of zero and the `startup_ms_p95` reduced by
    the target of 2000 milliseconds, divided by 100.0 and multiplied by a weight
    of 1.5; plus the `error_rate` multiplied by 100 and then by a weight of
    4.0."

    Design: Corner/calculations/playback_breach_threshold_is_strict_at_seventy
    """
    title = fx.create_title(
        api, external_ref="TTL-QI-70", title_name="Breach Gate Cut", studio_code="NOVAPIC"
    )
    profile = _mobile_high_profile(api)
    vendor = fx.create_vendor(
        api,
        vendor_code="ALPHACDN",
        regions=["US"],
        committed_gbps=100.00,
        cost_per_gb_usd=0.0300,
    )
    base = dict(
        region_code="US",
        play_attempts=1000,
        rebuffer_events=120,
        error_count=0,
    )

    _ingest_metric(
        api,
        f.playback_metric_payload(
            title["id"],
            profile["id"],
            vendor["id"],
            window_start_at="2026-07-10T00:00:00Z",
            window_end_at="2026-07-11T00:00:00Z",
            startup_ms_p95=2000,
            **base,
        ),
    )
    over_gate = _ingest_metric(
        api,
        f.playback_metric_payload(
            title["id"],
            profile["id"],
            vendor["id"],
            window_start_at="2026-07-11T00:00:00Z",
            window_end_at="2026-07-12T00:00:00Z",
            startup_ms_p95=2001,
            **base,
        ),
    )

    assert_score(over_gate["quality_index"], 69.99, "quality_index")
    assert over_gate["breach_flag"] is True, over_gate

    assert fx.read_vendor(api, vendor["id"])["breach_window_count"] == 1


def test_playback_quality_index_clamps_at_zero_with_four_decimal_ratios(api):
    """A three-attempt disaster scores 0.00 rather than going negative.

    PRD §3.7: "The `rebuffer_ratio` is `rebuffer_events` divided by
    `play_attempts`, rounded half up to four decimals, and the `error_rate` is
    `error_count` divided by `play_attempts`, likewise to four decimals."

    Design: Corner/calculations/playback_index_clamps_at_zero_with_four_decimal_ratios
    """
    title = fx.create_title(
        api, external_ref="TTL-QI-CLAMP", title_name="Clamp Cut", studio_code="NOVAPIC"
    )
    profile = get_success_data(
        api.create_device_profile(
            {
                "device_class": "MOBILE_LOW",
                "max_height_px": 720,
                "supported_codecs": ["H264"],
                "min_bitrate_kbps": 200,
                "max_bitrate_kbps": 3000,
                "hdcp_required": False,
                "required_drm_system": "NONE",
                "market_share_pct": 10.00,
                "quality_normalization_factor": 0.85,
            },
            PLATFORM_ADMIN,
        )
    )
    vendor = fx.create_vendor(
        api,
        vendor_code="CLAMPCDN",
        regions=["US"],
        committed_gbps=50.00,
        cost_per_gb_usd=0.0200,
    )

    metric = _ingest_metric(
        api,
        f.playback_metric_payload(
            title["id"],
            profile["id"],
            vendor["id"],
            region_code="US",
            window_start_at="2026-07-05T00:00:00Z",
            window_end_at="2026-07-05T01:00:00Z",
            play_attempts=3,
            rebuffer_events=1,
            startup_ms_p95=2000,
            error_count=1,
        ),
    )

    assert_ratio_4dp(metric["rebuffer_ratio"], 0.3333, "rebuffer_ratio")
    assert_ratio_4dp(metric["error_rate"], 0.3333, "error_rate")
    assert_score(metric["quality_index"], 0.00, "quality_index")
    assert metric["breach_flag"] is True, metric


def test_playback_startup_below_the_target_scores_the_same_as_the_target(api):
    """1200 ms and 2000 ms windows with identical counters both score 93.00.

    PRD §3.7: "Because of the clamp, a window whose startup latency is at or
    below 2000 milliseconds contributes exactly nothing from that term and is
    not rewarded for being faster."

    Design: Corner/calculations/startup_latency_below_target_contributes_zero_penalty
    """
    title = fx.create_title(
        api, external_ref="TTL-QI-START", title_name="Startup Clamp Cut", studio_code="NOVAPIC"
    )
    profile = _tv_hd_profile(api, market_share_pct=30.00)
    vendor = fx.create_vendor(
        api,
        vendor_code="STARTCDN",
        regions=["US"],
        committed_gbps=80.00,
        cost_per_gb_usd=0.0250,
    )
    base = dict(region_code="US", play_attempts=1000, rebuffer_events=20, error_count=5)

    fast = _ingest_metric(
        api,
        f.playback_metric_payload(
            title["id"],
            profile["id"],
            vendor["id"],
            window_start_at="2026-07-06T00:00:00Z",
            window_end_at="2026-07-07T00:00:00Z",
            startup_ms_p95=1200,
            **base,
        ),
    )
    at_target = _ingest_metric(
        api,
        f.playback_metric_payload(
            title["id"],
            profile["id"],
            vendor["id"],
            window_start_at="2026-07-07T00:00:00Z",
            window_end_at="2026-07-08T00:00:00Z",
            startup_ms_p95=2000,
            **base,
        ),
    )

    assert_ratio_4dp(fast["rebuffer_ratio"], 0.0200, "rebuffer_ratio")
    assert_ratio_4dp(fast["error_rate"], 0.0050, "error_rate")
    assert_score(fast["quality_index"], 93.00, "quality_index")
    assert fast["breach_flag"] is False, fast
    assert_score(at_target["quality_index"], 93.00, "quality_index")
    assert at_target["breach_flag"] is False, at_target


def test_vendor_health_variants_agree_when_every_window_scores_alike(api):
    """Two 1000-attempt windows at 93.00 give both variants 93.00 and no breaches.

    PRD §3.7: "The `health_score_contract` variant instead takes every row and
    computes a `play_attempts`-weighted mean: the sum over all rows of
    `quality_index` multiplied by `play_attempts`, divided by the sum of
    `play_attempts` across those rows, rounded half up to two decimals, and
    again 100.00 when no rows exist."

    Design: Corner/calculations/startup_latency_below_target_contributes_zero_penalty
    """
    title = fx.create_title(
        api, external_ref="TTL-QI-START", title_name="Startup Clamp Cut", studio_code="NOVAPIC"
    )
    profile = _tv_hd_profile(api, market_share_pct=30.00)
    vendor = fx.create_vendor(
        api,
        vendor_code="STARTCDN",
        regions=["US"],
        committed_gbps=80.00,
        cost_per_gb_usd=0.0250,
    )
    base = dict(region_code="US", play_attempts=1000, rebuffer_events=20, error_count=5)

    _ingest_metric(
        api,
        f.playback_metric_payload(
            title["id"],
            profile["id"],
            vendor["id"],
            window_start_at="2026-07-06T00:00:00Z",
            window_end_at="2026-07-07T00:00:00Z",
            startup_ms_p95=1200,
            **base,
        ),
    )
    _ingest_metric(
        api,
        f.playback_metric_payload(
            title["id"],
            profile["id"],
            vendor["id"],
            window_start_at="2026-07-07T00:00:00Z",
            window_end_at="2026-07-08T00:00:00Z",
            startup_ms_p95=2000,
            **base,
        ),
    )

    stored = fx.read_vendor(api, vendor["id"])
    assert_score(stored["health_score_rolling"], 93.00, "health_score_rolling")
    assert_score(stored["health_score_contract"], 93.00, "health_score_contract")
    assert stored["breach_window_count"] == 0, stored


# ---------------------------------------------------------------------------
# Vendor health defaults and the egress projection (§3.7)
# ---------------------------------------------------------------------------


def test_a_metricless_vendor_reports_both_health_variants_at_one_hundred(api):
    """A brand-new vendor is seeded at 100.00 on both variants, not at 0.00.

    PRD §3.7: "A new vendor's `state` is `ACTIVE`, its `reserved_gbps` is 0.00,
    its `breach_window_count` is 0, and **both** health figures —
    `health_score_rolling` and `health_score_contract` — are seeded at 100.00,
    which is the value the health calculation yields when no measurement rows
    exist yet."

    Design: Corner/calculations/vendor_health_defaults_to_one_hundred_with_no_metric_rows
    """
    vendor = fx.create_vendor(
        api,
        vendor_code="FRESHCDN",
        regions=["US"],
        committed_gbps=40.00,
        cost_per_gb_usd=0.0500,
    )

    stored = validate_success(api.get_cdn_vendor(vendor["id"], PLATFORM_ADMIN), 200)
    assert_score(stored["health_score_rolling"], 100.00, "health_score_rolling")
    assert_score(stored["health_score_contract"], 100.00, "health_score_contract")
    assert stored["breach_window_count"] == 0, stored
    assert stored["state"] == "ACTIVE", stored
    assert_money(stored["reserved_gbps"], 0.00, "reserved_gbps")


def test_the_default_health_is_high_enough_to_be_routing_eligible(api):
    """The 100.00 default clears the 60.00 eligibility floor, so the policy is admitted.

    PRD §3.7: "Eligibility first: a vendor is a candidate when its `state` is
    exactly `ACTIVE`, the policy's `region_code` appears in the vendor's
    `regions`, its `health_score_contract` is at least 60.00, and its `id` is
    absent from the policy's `excluded_vendor_ids`."

    Design: Corner/calculations/vendor_health_defaults_to_one_hundred_with_no_metric_rows
    """
    title = fx.create_title(
        api, external_ref="TTL-HEALTH-DEF", title_name="Health Default Cut", studio_code="NOVAPIC"
    )
    vendor = fx.create_vendor(
        api,
        vendor_code="FRESHCDN",
        regions=["US"],
        committed_gbps=40.00,
        cost_per_gb_usd=0.0500,
    )

    policy = validate_success(
        api.create_routing_policy(
            f.routing_policy_payload(title["id"], region_code="US", steering_mode="PERFORMANCE"),
            DELIVERY_ENGINEER,
        ),
        201,
    )

    stored = fx.read_policy(api, policy["id"])
    assert stored["primary_vendor_id"] == vendor["id"], stored
    assert stored["backup_vendor_id"] is None, stored
    assert stored["state"] == "STANDBY_ONLY", stored
    assert stored["selection_reason_code"] == "PERFORMANCE_RANK", stored


def test_egress_projection_falls_back_to_the_default_thousand_gigabytes(api):
    """With no metric rows the projection bills 1000.00 GB, so 0.4000 USD/GB totals 432.00.

    PRD §3.7: "Step one, demand: the play attempts are summed as `play_attempts`
    across every ingested playback metric window whose `title_id` and
    `region_code` both match the policy's, with no state filter of any kind
    since metric windows are immutable events; the projected monthly volume is
    that attempt count multiplied by 2.5 gigabytes per play, rounded half up to
    two decimals, or a flat 1000.00 gigabytes when the attempt count is zero."

    Design: Corner/calculations/egress_projection_uses_the_default_volume_when_no_metrics_exist
    """
    title = fx.create_title(
        api, external_ref="TTL-EGRESS-DEF", title_name="Default Volume Cut", studio_code="NOVAPIC"
    )
    vendor = fx.create_vendor(
        api,
        vendor_code="DEFVOLCDN",
        regions=["US"],
        committed_gbps=60.00,
        cost_per_gb_usd=0.4000,
    )

    policy = validate_success(
        api.create_routing_policy(
            f.routing_policy_payload(title["id"], region_code="US", steering_mode="PERFORMANCE"),
            DELIVERY_ENGINEER,
        ),
        201,
    )

    stored = fx.read_policy(api, policy["id"])
    assert stored["primary_vendor_id"] == vendor["id"], stored
    assert_money(stored["projected_egress_cost_usd"], 432.00, "projected_egress_cost_usd")
    assert stored["selection_reason_code"] == "PERFORMANCE_RANK", stored


def test_weighted_steering_adds_two_points_to_the_surcharge_rate(api):
    """The same 400.00 base costs 440.00 under WEIGHTED because the rate becomes 0.10.

    PRD §3.7: "Step three, surcharge rate: the tier is keyed on that rounded
    base cost and **never** on the eventual total — a base cost below 500.00
    takes a rate of 0.08, a base cost of 500.00 or more but below 2000.00 takes
    0.05, and a base cost of 2000.00 or more takes 0.03; a policy whose
    `steering_mode` is `WEIGHTED` then has a further 0.02 added to whichever
    rate was selected."

    Design: Corner/calculations/egress_weighted_mode_adds_two_points_to_the_tier_rate
    """
    title = fx.create_title(
        api, external_ref="TTL-EGRESS-WTD", title_name="Weighted Addon Cut", studio_code="NOVAPIC"
    )
    fx.create_vendor(
        api,
        vendor_code="WTDCDN",
        regions=["US"],
        committed_gbps=60.00,
        cost_per_gb_usd=0.4000,
    )

    policy = validate_success(
        api.create_routing_policy(
            f.routing_policy_payload(title["id"], region_code="US", steering_mode="WEIGHTED"),
            DELIVERY_ENGINEER,
        ),
        201,
    )

    stored = fx.read_policy(api, policy["id"])
    assert_money(stored["projected_egress_cost_usd"], 440.00, "projected_egress_cost_usd")
    assert stored["selection_reason_code"] == "WEIGHTED_RANK", stored


def test_the_weighted_addon_is_worth_exactly_eight_dollars_on_a_four_hundred_base(api):
    """Two titles on one vendor: WEIGHTED 440.00 against PERFORMANCE 432.00.

    PRD §3.7: "Step five: `projected_egress_cost_usd` is the base cost plus the
    surcharge, rounded half up to two decimals."

    Design: Corner/calculations/egress_weighted_mode_adds_two_points_to_the_tier_rate
    """
    weighted_title = fx.create_title(
        api, external_ref="TTL-EGRESS-WTD", title_name="Weighted Addon Cut", studio_code="NOVAPIC"
    )
    performance_title = fx.create_title(
        api, external_ref="TTL-EGRESS-PERF", title_name="Baseline Addon Cut", studio_code="NOVAPIC"
    )
    fx.create_vendor(
        api,
        vendor_code="WTDCDN",
        regions=["US"],
        committed_gbps=60.00,
        cost_per_gb_usd=0.4000,
    )

    weighted = validate_success(
        api.create_routing_policy(
            f.routing_policy_payload(
                weighted_title["id"], region_code="US", steering_mode="WEIGHTED"
            ),
            DELIVERY_ENGINEER,
        ),
        201,
    )
    performance = validate_success(
        api.create_routing_policy(
            f.routing_policy_payload(
                performance_title["id"], region_code="US", steering_mode="PERFORMANCE"
            ),
            DELIVERY_ENGINEER,
        ),
        201,
    )

    assert_money(
        fx.read_policy(api, weighted["id"])["projected_egress_cost_usd"],
        440.00,
        "weighted projected_egress_cost_usd",
    )
    assert_money(
        fx.read_policy(api, performance["id"])["projected_egress_cost_usd"],
        432.00,
        "performance projected_egress_cost_usd",
    )


# ---------------------------------------------------------------------------
# Device compatibility scoring (§3.3)
# ---------------------------------------------------------------------------


def test_a_two_rung_ladder_keeps_only_two_fifths_of_the_reach(api):
    """A single 60.00-share compatible profile scores 24.00, not 60.00.

    PRD §3.3: "A coverage multiplier is taken as the lesser of 1.00 and the
    ladder's `rung_count` divided by the target of 5 rungs, so a two-rung ladder
    keeps only two fifths of the reach it would otherwise claim while a five-rung
    or longer ladder keeps all of it."

    Design: Corner/calculations/device_compat_coverage_multiplier_scales_with_rung_count
    """
    _tv_hd_profile(api, market_share_pct=60.00)
    title = fx.create_title(
        api,
        external_ref="TTL-COMPAT-MUL",
        title_name="Coverage Multiplier Cut",
        studio_code="NOVAPIC",
    )
    ladder = fx.create_ladder(api, title["id"], codec_family="H264", rungs=RUNGS_480_720)

    validate_success(api.validate_encoding_ladder(ladder["id"], ENCODING_ENGINEER), 200)

    stored = fx.read_ladder(api, ladder["id"])
    assert stored["compatible_device_count"] == 1, stored
    assert_score(stored["device_compat_score"], 24.00, "device_compat_score")


def test_the_coverage_discount_still_validates_the_two_rung_ladder(api):
    """The discounted 24.00 is strictly above zero, so the accepting arm fires.

    PRD §3.3: "The **accepting arm** applies when the ladder's `rungs` are
    strictly increasing in both `height_px` and `bitrate_kbps` in stored array
    order, no two rungs share a `height_px`, and the computed
    `device_compat_score` is strictly greater than 0.00."

    Design: Corner/calculations/device_compat_coverage_multiplier_scales_with_rung_count
    """
    _tv_hd_profile(api, market_share_pct=60.00)
    title = fx.create_title(
        api,
        external_ref="TTL-COMPAT-MUL",
        title_name="Coverage Multiplier Cut",
        studio_code="NOVAPIC",
    )
    ladder = fx.create_ladder(api, title["id"], codec_family="H264", rungs=RUNGS_480_720)

    validate_success(api.validate_encoding_ladder(ladder["id"], ENCODING_ENGINEER), 200)

    stored = fx.read_ladder(api, ladder["id"])
    assert stored["rung_count"] == 2, stored
    assert stored["peak_height_px"] == 720, stored
    assert stored["peak_bitrate_kbps"] == 2500, stored
    assert stored["state"] == "VALIDATED", stored
    assert stored["validation_reason_code"] == "OK", stored


def _four_k_profiles(api):
    tv = get_success_data(
        api.create_device_profile(
            {
                "device_class": "SMART_TV_4K",
                "max_height_px": 2160,
                "supported_codecs": ["HEVC"],
                "min_bitrate_kbps": 500,
                "max_bitrate_kbps": 25000,
                "hdcp_required": False,
                "required_drm_system": "NONE",
                "market_share_pct": 60.00,
                "quality_normalization_factor": 1.00,
            },
            PLATFORM_ADMIN,
        )
    )
    mobile = get_success_data(
        api.create_device_profile(
            {
                "device_class": "MOBILE_HIGH",
                "max_height_px": 1080,
                "supported_codecs": ["HEVC"],
                "min_bitrate_kbps": 800,
                "max_bitrate_kbps": 6000,
                "hdcp_required": False,
                "required_drm_system": "NONE",
                "market_share_pct": 40.00,
                "quality_normalization_factor": 0.95,
            },
            PLATFORM_ADMIN,
        )
    )
    return tv, mobile


RUNGS_FIVE_TO_2160 = [
    f.rung("360p", 360, 900),
    f.rung("480p", 480, 1200),
    f.rung("720p", 720, 2500),
    f.rung("1080p", 1080, 5000),
    f.rung("2160p", 2160, 12000),
]


def test_the_four_k_bonus_is_added_before_the_hundred_point_cap(api):
    """A 100.00 base plus the 5.00 bonus stores the capped 100.00.

    PRD §3.3: "The stored `device_compat_score` is the lesser of 100.00 and the
    sum of the base and the bonus, rounded half up to two decimals."

    Design: Corner/calculations/device_compat_score_is_capped_after_the_four_k_bonus
    """
    _four_k_profiles(api)
    title = fx.create_title(
        api, external_ref="TTL-COMPAT-CAP", title_name="Score Cap Cut", studio_code="NOVAPIC"
    )
    ladder = fx.create_ladder(
        api, title["id"], codec_family="HEVC", rungs=RUNGS_FIVE_TO_2160
    )

    validate_success(api.validate_encoding_ladder(ladder["id"], ENCODING_ENGINEER), 200)

    stored = fx.read_ladder(api, ladder["id"])
    assert_score(stored["device_compat_score"], 100.00, "device_compat_score")
    assert stored["state"] == "VALIDATED", stored
    assert stored["validation_reason_code"] == "OK", stored


def test_both_four_k_era_profiles_are_counted_as_compatible(api):
    """A five-rung ladder keeps all of its reach and reaches both profiles.

    PRD §3.3: "A bonus of 5.00 is added when the ladder's `peak_height_px` is
    2160 or greater **and** its `compatible_device_count` is at least 1;
    otherwise the bonus is 0.00."

    Design: Corner/calculations/device_compat_score_is_capped_after_the_four_k_bonus
    """
    _four_k_profiles(api)
    title = fx.create_title(
        api, external_ref="TTL-COMPAT-CAP", title_name="Score Cap Cut", studio_code="NOVAPIC"
    )
    ladder = fx.create_ladder(
        api, title["id"], codec_family="HEVC", rungs=RUNGS_FIVE_TO_2160
    )

    validate_success(api.validate_encoding_ladder(ladder["id"], ENCODING_ENGINEER), 200)

    stored = fx.read_ladder(api, ladder["id"])
    assert stored["rung_count"] == 5, stored
    assert stored["peak_height_px"] == 2160, stored
    assert stored["compatible_device_count"] == 2, stored


# ---------------------------------------------------------------------------
# Reprocessing cost and priority (§3.9)
# ---------------------------------------------------------------------------


RUNGS_FOUR_TO_1080 = [
    f.rung("240p", 240, 400),
    f.rung("480p", 480, 1200),
    f.rung("720p", 720, 2500),
    f.rung("1080p", 1080, 5000),
]


def _ten_hour_reprocess_fixture(api):
    """A locked four-rung H264 ladder over a single ten-hour `QC_PASSED` master."""
    _mobile_high_profile(api)
    title = fx.create_title(
        api, external_ref="TTL-REPROC-CAP", title_name="Priority Cap Cut", studio_code="NOVAPIC"
    )
    asset = fx.create_asset(
        api,
        title["id"],
        source_uri="s3://mez/tenhour.mxf",
        duration_seconds=36000,
        frame_rate=24.0,
        peak_audio_lufs=-24.0,
        artifact_defect_count=0,
        caption_languages=["en"],
        audio_language="en",
    )
    _run_qc(api, asset["id"])
    ladder = fx.create_locked_ladder(
        api, title["id"], codec_family="H264", rungs=RUNGS_FOUR_TO_1080
    )
    return title, ladder


def _queue_av1_job(api, title_id, ladder_id):
    payload = f.reprocess_job_payload(
        title_id,
        ladder_id,
        fx.title_version(api, title_id),
        trigger_reason="CODEC_DEPRECATION",
        target_codec_family="AV1",
    )
    return validate_success(api.create_reprocess_job(payload, ENCODING_ENGINEER), 201)


def test_reprocess_cost_rounds_each_rung_and_sums_to_two_two_nine_three_two(api):
    """600 AV1 minutes over 400/1200/2500/5000 kbps cost 10.08, 30.24, 63.00, 126.00.

    PRD §3.9: "Then, walking the source ladder's `rungs` in their stored array
    order and **not** in any re-sorted order, each rung contributes one entry to
    `per_rung_cost_usd`, computed as the duration in minutes multiplied by the
    rung's `bitrate_kbps` divided by 1000.0, multiplied by the codec factor,
    multiplied by the rate of 0.02 US dollars per minute per megabit per second,
    and rounded half up to two decimals."

    Design: Corner/calculations/reprocess_priority_rank_cost_component_is_capped_at_twenty
    """
    title, ladder = _ten_hour_reprocess_fixture(api)

    job = _queue_av1_job(api, title["id"], ladder["id"])

    stored = fx.read_job(api, job["id"])
    assert_money_list(
        stored["per_rung_cost_usd"], [10.08, 30.24, 63.00, 126.00], "per_rung_cost_usd"
    )
    assert_money(stored["cost_estimate_usd"], 229.32, "cost_estimate_usd")
    assert stored["state"] == "QUEUED", stored
    assert_money(stored["committed_usd"], 0.00, "committed_usd")
    assert_money(
        fx.read_title(api, title["id"])["encode_budget_remaining_usd"],
        5000.00,
        "encode_budget_remaining_usd",
    )


def test_reprocess_priority_rank_saturates_at_sixty(api):
    """A tenth of 229.32 is 22.932, so the cost term freezes at 20.0 and the rank at 60.00.

    PRD §3.9: "The `priority_rank` follows from the same figures: it is the
    weight of the job's `trigger_reason` — 40.0 for `CODEC_DEPRECATION`, 30.0 for
    `STANDARD_UPDATE`, 20.0 for `QUALITY_REGRESSION` and 10.0 for
    `DEVICE_MATRIX_CHANGE` — plus the lesser of 20.0 and the
    `cost_estimate_usd` divided by 10.0, rounded half up to two decimals."

    Design: Corner/calculations/reprocess_priority_rank_cost_component_is_capped_at_twenty
    """
    title, ladder = _ten_hour_reprocess_fixture(api)

    job = _queue_av1_job(api, title["id"], ladder["id"])

    stored = fx.read_job(api, job["id"])
    assert_score(stored["priority_rank"], 60.00, "priority_rank")

    scored_ladder = fx.read_ladder(api, ladder["id"])
    assert_score(scored_ladder["device_compat_score"], 36.00, "device_compat_score")
    assert scored_ladder["compatible_device_count"] == 1, scored_ladder


# ---------------------------------------------------------------------------
# Traffic steering: the three ranking modes (§3.7)
# ---------------------------------------------------------------------------


def _two_us_vendors(api, alpha_cost=0.0300, bravo_cost=0.0300):
    alpha = fx.create_vendor(
        api,
        vendor_code="ALPHACDN",
        regions=["US"],
        committed_gbps=100.00,
        cost_per_gb_usd=alpha_cost,
    )
    bravo = fx.create_vendor(
        api,
        vendor_code="BRAVOCDN",
        regions=["US"],
        committed_gbps=100.00,
        cost_per_gb_usd=bravo_cost,
    )
    return alpha, bravo


def test_performance_mode_falls_through_to_created_at_ascending(api):
    """Two vendors identical on health and cost resolve to the earlier-created primary.

    PRD §3.7: "In all three modes `created_at` ascending is the final and
    exhaustive tie-break."

    Design: Corner/calculations/routing_performance_mode_breaks_ties_by_created_at
    """
    title = fx.create_title(
        api, external_ref="TTL-ROUTE-TIE", title_name="Tie Break Cut", studio_code="NOVAPIC"
    )
    alpha, bravo = _two_us_vendors(api)

    policy = validate_success(
        api.create_routing_policy(
            f.routing_policy_payload(title["id"], region_code="US", steering_mode="PERFORMANCE"),
            DELIVERY_ENGINEER,
        ),
        201,
    )

    stored = fx.read_policy(api, policy["id"])
    assert stored["primary_vendor_id"] == alpha["id"], stored
    assert stored["backup_vendor_id"] == bravo["id"], stored
    assert stored["state"] == "ACTIVE", stored
    assert stored["selection_reason_code"] == "PERFORMANCE_RANK", stored


def test_a_freshly_created_policy_has_no_exclusions_and_projects_thirty_two_forty(api):
    """Two candidates at 0.0300 USD/GB project 32.40 from a 30.00 base cost.

    PRD §3.7: "Step two, base cost: if the policy currently has no
    `primary_vendor_id`, `projected_egress_cost_usd` is 0.00 and evaluation stops
    there; otherwise the base cost is the projected monthly volume multiplied by
    the **current primary vendor's** `cost_per_gb_usd`, rounded half up to two
    decimals."

    Design: Corner/calculations/routing_performance_mode_breaks_ties_by_created_at
    """
    title = fx.create_title(
        api, external_ref="TTL-ROUTE-TIE", title_name="Tie Break Cut", studio_code="NOVAPIC"
    )
    _two_us_vendors(api)

    policy = validate_success(
        api.create_routing_policy(
            f.routing_policy_payload(title["id"], region_code="US", steering_mode="PERFORMANCE"),
            DELIVERY_ENGINEER,
        ),
        201,
    )

    stored = fx.read_policy(api, policy["id"])
    assert stored["resteer_count"] == 0, stored
    assert stored["excluded_vendor_ids"] == [], stored
    assert_money(stored["projected_egress_cost_usd"], 32.40, "projected_egress_cost_usd")


def test_cost_mode_prefers_the_cheaper_vendor_over_the_earlier_one(api):
    """BRAVOCDN at 0.0100 outranks the earlier ALPHACDN at 0.0300.

    PRD §3.7: "Ranking second, by `steering_mode`: under `PERFORMANCE` candidates
    are ordered by `health_score_contract` descending, then `cost_per_gb_usd`
    ascending, then `created_at` ascending; under `COST` they are ordered by
    `cost_per_gb_usd` ascending, then `health_score_contract` descending, then
    `created_at` ascending; under `WEIGHTED` a composite figure is computed for
    each candidate as its `health_score_contract` reduced by its
    `cost_per_gb_usd` multiplied by 1000.0, rounded half up to four decimals, and
    candidates are ordered by that composite descending, then `created_at`
    ascending."

    Design: Corner/calculations/routing_cost_mode_orders_by_price_not_creation_order
    """
    title = fx.create_title(
        api, external_ref="TTL-ROUTE-COST", title_name="Cost Rank Cut", studio_code="NOVAPIC"
    )
    alpha, bravo = _two_us_vendors(api, alpha_cost=0.0300, bravo_cost=0.0100)

    policy = validate_success(
        api.create_routing_policy(
            f.routing_policy_payload(title["id"], region_code="US", steering_mode="COST"),
            DELIVERY_ENGINEER,
        ),
        201,
    )

    stored = fx.read_policy(api, policy["id"])
    assert stored["primary_vendor_id"] == bravo["id"], stored
    assert stored["backup_vendor_id"] == alpha["id"], stored
    assert stored["selection_reason_code"] == "COST_RANK", stored
    assert stored["state"] == "ACTIVE", stored


def test_the_cost_mode_projection_reads_the_chosen_primary_price(api):
    """The projection bills the winner's 0.0100, giving 10.80 and not 32.40.

    PRD §3.7: "Step four: the steering surcharge is the base cost multiplied by
    that rate, rounded half up to two decimals."

    Design: Corner/calculations/routing_cost_mode_orders_by_price_not_creation_order
    """
    title = fx.create_title(
        api, external_ref="TTL-ROUTE-COST", title_name="Cost Rank Cut", studio_code="NOVAPIC"
    )
    _two_us_vendors(api, alpha_cost=0.0300, bravo_cost=0.0100)

    policy = validate_success(
        api.create_routing_policy(
            f.routing_policy_payload(title["id"], region_code="US", steering_mode="COST"),
            DELIVERY_ENGINEER,
        ),
        201,
    )

    assert_money(
        fx.read_policy(api, policy["id"])["projected_egress_cost_usd"],
        10.80,
        "projected_egress_cost_usd",
    )


def _weighted_routing_fixture(api):
    """ALPHACDN cheap but health-dented at 95.00; BRAVOCDN pristine but dearer."""
    title = fx.create_title(
        api, external_ref="TTL-ROUTE-WTD", title_name="Weighted Rank Cut", studio_code="NOVAPIC"
    )
    profile = _mobile_high_profile(api)
    alpha, bravo = _two_us_vendors(api, alpha_cost=0.0100, bravo_cost=0.0300)
    metric = _ingest_metric(
        api,
        f.playback_metric_payload(
            title["id"],
            profile["id"],
            alpha["id"],
            region_code="US",
            window_start_at="2026-07-15T00:00:00Z",
            window_end_at="2026-07-16T00:00:00Z",
            play_attempts=2000,
            rebuffer_events=40,
            startup_ms_p95=2000,
            error_count=0,
        ),
    )
    return title, alpha, bravo, metric


def test_weighted_mode_prefers_a_dented_but_cheap_vendor(api):
    """95.00 health at 0.0100 composes to 85.0000 and beats 100.00 health at 0.0300.

    PRD §3.7: "Ranking second, by `steering_mode`: under `PERFORMANCE` candidates
    are ordered by `health_score_contract` descending, then `cost_per_gb_usd`
    ascending, then `created_at` ascending; under `COST` they are ordered by
    `cost_per_gb_usd` ascending, then `health_score_contract` descending, then
    `created_at` ascending; under `WEIGHTED` a composite figure is computed for
    each candidate as its `health_score_contract` reduced by its
    `cost_per_gb_usd` multiplied by 1000.0, rounded half up to four decimals, and
    candidates are ordered by that composite descending, then `created_at`
    ascending."

    Design: Corner/calculations/routing_weighted_composite_trades_health_against_price
    """
    title, alpha, bravo, metric = _weighted_routing_fixture(api)

    assert_score(metric["quality_index"], 95.00, "quality_index")
    assert metric["breach_flag"] is False, metric
    assert_score(
        fx.read_vendor(api, alpha["id"])["health_score_contract"], 95.00, "health_score_contract"
    )
    assert fx.read_vendor(api, alpha["id"])["state"] == "ACTIVE", alpha
    assert_score(
        fx.read_vendor(api, bravo["id"])["health_score_contract"], 100.00, "health_score_contract"
    )

    policy = validate_success(
        api.create_routing_policy(
            f.routing_policy_payload(title["id"], region_code="US", steering_mode="WEIGHTED"),
            DELIVERY_ENGINEER,
        ),
        201,
    )

    stored = fx.read_policy(api, policy["id"])
    assert stored["primary_vendor_id"] == alpha["id"], stored
    assert stored["backup_vendor_id"] == bravo["id"], stored
    assert stored["selection_reason_code"] == "WEIGHTED_RANK", stored
    assert stored["state"] == "ACTIVE", stored


def test_the_weighted_projection_prices_five_thousand_gigabytes_at_a_tenth(api):
    """2000 attempts make 5000.00 GB, 50.00 of base cost and a 0.10 rate, so 55.00.

    PRD §3.7: "Step one, demand: the play attempts are summed as `play_attempts`
    across every ingested playback metric window whose `title_id` and
    `region_code` both match the policy's, with no state filter of any kind since
    metric windows are immutable events; the projected monthly volume is that
    attempt count multiplied by 2.5 gigabytes per play, rounded half up to two
    decimals, or a flat 1000.00 gigabytes when the attempt count is zero."

    Design: Corner/calculations/routing_weighted_composite_trades_health_against_price
    """
    title, _alpha, _bravo, _metric = _weighted_routing_fixture(api)

    policy = validate_success(
        api.create_routing_policy(
            f.routing_policy_payload(title["id"], region_code="US", steering_mode="WEIGHTED"),
            DELIVERY_ENGINEER,
        ),
        201,
    )

    assert_money(
        fx.read_policy(api, policy["id"])["projected_egress_cost_usd"],
        55.00,
        "projected_egress_cost_usd",
    )


# ---------------------------------------------------------------------------
# Entitlement selection and its post-match gates (§3.5)
# ---------------------------------------------------------------------------


def _licensable_1080_package(api, external_ref, title_name, source_uri):
    """A PACKAGED package on a 1080p-peaking ladder, with a SCHEDULED US window."""
    _mobile_high_profile(api)
    title = fx.create_title(
        api, external_ref=external_ref, title_name=title_name, studio_code="NOVAPIC"
    )
    fx.create_window(api, title["id"])
    asset = fx.create_asset(
        api,
        title["id"],
        source_uri=source_uri,
        duration_seconds=7200,
        frame_rate=24.0,
        peak_audio_lufs=-24.0,
        artifact_defect_count=0,
        caption_languages=["en"],
        audio_language="en",
    )
    _run_qc(api, asset["id"])
    ladder = fx.create_locked_ladder(
        api, title["id"], codec_family="H264", rungs=RUNGS_480_1080
    )
    package = fx.create_package(api, title["id"], ladder["id"])
    return title, ladder, package


def _check(api, title_id, **overrides):
    return api.create_playback_entitlement_check(
        f.entitlement_check_payload(title_id, **overrides), DELIVERY_ENGINEER
    )


def test_a_wildcard_rule_at_ninety_outranks_an_exact_region_rule_at_fifty(api):
    """Priority 90 on `*` wins over priority 50 on `US` for a US/STANDARD session.

    PRD §3.5: "`priority` dominates specificity, so a wildcard rule at priority 90
    beats an exact-region rule at priority 50; specificity only breaks ties
    between equal priorities."

    Design: Corner/calculations/entitlement_priority_dominates_region_specificity
    """
    title, _ladder, package = _licensable_1080_package(
        api, "TTL-ENT-PRIO", "Priority Wins Cut", "s3://mez/ent-prio.mxf"
    )
    fx.add_entitlement_rule(
        api,
        package["id"],
        region_code="US",
        subscription_tier="STANDARD",
        max_concurrent_streams=1,
        max_playback_height_px=480,
        hdcp_level="TYPE_0",
        priority=50,
    )
    wildcard = fx.add_entitlement_rule(
        api,
        package["id"],
        region_code="*",
        subscription_tier="ANY",
        max_concurrent_streams=4,
        max_playback_height_px=1080,
        hdcp_level="TYPE_0",
        priority=90,
    )
    fx.package_package(api, package["id"])

    decision = validate_unpaginated(
        _check(
            api,
            title["id"],
            region_code="US",
            subscription_tier="STANDARD",
            device_class="MOBILE_HIGH",
            requested_streams=4,
        ),
        200,
    )

    assert decision["decision"] == "ALLOW", decision
    assert decision["reason_code"] == "MATCHED", decision
    assert decision["matched_rule_id"] == wildcard["id"], decision
    assert decision["package_id"] == package["id"], decision


def test_the_winning_rule_supplies_the_four_stream_and_1080_ceilings(api):
    """The ceilings echoed are the wildcard's 4 and 1080, not the US rule's 1 and 480.

    PRD §3.5: "A check that clears all five stages answers with `decision` of
    `ALLOW` and `reason_code` of `MATCHED`, together with `matched_rule_id` naming
    the winning rule, `package_id` naming the selected package,
    `max_concurrent_streams` echoing the winning rule's ceiling,
    `offline_granted` — true when `offline_requested` was true and both offline
    permissions held, false otherwise, including when offline playback was never
    requested — and `effective_height_px`, the playback ceiling actually
    available, which is the smallest of three numbers: the winning rule's
    `max_playback_height_px`, the resolved device's `max_height_px`, and the
    `peak_height_px` of the ladder the selected package is bound to."

    Design: Corner/calculations/entitlement_priority_dominates_region_specificity
    """
    title, _ladder, package = _licensable_1080_package(
        api, "TTL-ENT-PRIO", "Priority Wins Cut", "s3://mez/ent-prio.mxf"
    )
    fx.add_entitlement_rule(
        api,
        package["id"],
        region_code="US",
        subscription_tier="STANDARD",
        max_concurrent_streams=1,
        max_playback_height_px=480,
        hdcp_level="TYPE_0",
        priority=50,
    )
    fx.add_entitlement_rule(
        api,
        package["id"],
        region_code="*",
        subscription_tier="ANY",
        max_concurrent_streams=4,
        max_playback_height_px=1080,
        hdcp_level="TYPE_0",
        priority=90,
    )
    fx.package_package(api, package["id"])

    decision = validate_unpaginated(
        _check(
            api,
            title["id"],
            region_code="US",
            subscription_tier="STANDARD",
            device_class="MOBILE_HIGH",
            requested_streams=4,
        ),
        200,
    )

    assert decision["max_concurrent_streams"] == 4, decision
    assert decision["effective_height_px"] == 1080, decision

    stored = fx.read_package(api, package["id"])
    assert stored["hdcp_floor"] == "TYPE_0", stored
    assert stored["entitlement_rule_count"] == 2, stored
    assert stored["state"] == "PACKAGED", stored


def _four_stream_licensed_title(api):
    title, _ladder, package = _licensable_1080_package(
        api, "TTL-ENT-LIMIT", "Stream Limit Cut", "s3://mez/ent-limit.mxf"
    )
    rule = fx.add_entitlement_rule(
        api,
        package["id"],
        region_code="*",
        subscription_tier="ANY",
        max_concurrent_streams=4,
        max_playback_height_px=1080,
        hdcp_level="TYPE_0",
        priority=60,
    )
    fx.package_package(api, package["id"])
    return title, package, rule


def test_asking_for_exactly_the_licensed_four_streams_is_allowed(api):
    """`requested_streams` 4 against a 4-stream rule clears the concurrency gate.

    PRD §3.5: "Fifth, two **post-match gates** are applied in this order: if
    `requested_streams` is strictly greater than the winning rule's
    `max_concurrent_streams` the answer is `ERR_CONCURRENCY_LIMIT_EXCEEDED` (HTTP
    403), where asking for exactly the licensed number of streams is allowed; and
    if `offline_requested` is true while either the winning rule's
    `offline_playback_allowed` or the selected package's
    `persistent_license_allowed` is false, the answer is
    `ERR_OFFLINE_PLAYBACK_DENIED` (HTTP 403)."

    Design: Corner/calculations/requested_streams_at_the_limit_is_allowed_and_one_more_is_rejected
    """
    title, _package, rule = _four_stream_licensed_title(api)

    decision = validate_unpaginated(
        _check(
            api,
            title["id"],
            region_code="US",
            subscription_tier="PREMIUM",
            device_class="MOBILE_HIGH",
            requested_streams=4,
        ),
        200,
    )

    assert decision["decision"] == "ALLOW", decision
    assert decision["matched_rule_id"] == rule["id"], decision
    assert decision["max_concurrent_streams"] == 4, decision


def test_a_fifth_stream_is_refused_and_mutates_nothing(api):
    """One stream past the licensed four is 403, and the read-only check persists nothing.

    PRD §3.5: "Available to `DeliveryEngineer` and `DrmOperator`, it is a computed
    read carried in a request body and it persists nothing, answering 200 OK."

    Design: Corner/calculations/requested_streams_at_the_limit_is_allowed_and_one_more_is_rejected
    """
    title, package, _rule = _four_stream_licensed_title(api)
    before = fx.read_title(api, title["id"])

    validate_error(
        _check(
            api,
            title["id"],
            region_code="US",
            subscription_tier="PREMIUM",
            device_class="MOBILE_HIGH",
            requested_streams=5,
        ),
        err.ERR_CONCURRENCY_LIMIT_EXCEEDED,
        403,
    )

    after = fx.read_title(api, title["id"])
    assert after["version"] == before["version"], after
    assert after["availability_state"] == before["availability_state"], after
    assert after["packaging_state"] == before["packaging_state"], after
    stored = fx.read_package(api, package["id"])
    assert stored["state"] == "PACKAGED", stored
    assert stored["entitlement_rule_count"] == 1, stored


def test_a_matching_rule_on_a_pending_package_is_never_reached(api):
    """The only package is `PENDING`, so the check dies at 409 and not at the rule stage.

    PRD §3.5: "Evaluation proceeds in five stages, and the order determines which
    rejection a caller sees. First, **package selection**: the candidate set is the
    title's DRM packages whose `state` is `PACKAGED`, and if that set is empty the
    check is refused with `ERR_NO_PACKAGED_DRM` (HTTP 409); otherwise the oldest
    such package by `created_at` is selected and no other package is consulted."

    Design: Corner/calculations/entitlement_rules_on_a_pending_package_never_participate
    """
    _mobile_high_profile(api)
    title = fx.create_title(
        api, external_ref="TTL-ENT-PEND", title_name="Pending Package Cut", studio_code="NOVAPIC"
    )
    ladder = fx.create_ladder(api, title["id"], codec_family="H264", rungs=RUNGS_480_720)
    package = fx.create_package(api, title["id"], ladder["id"])
    fx.add_entitlement_rule(
        api,
        package["id"],
        region_code="*",
        subscription_tier="ANY",
        max_concurrent_streams=2,
        max_playback_height_px=720,
        hdcp_level="NONE",
        priority=10,
    )

    validate_error(
        _check(
            api,
            title["id"],
            region_code="US",
            subscription_tier="BASIC",
            device_class="MOBILE_HIGH",
            requested_streams=1,
        ),
        err.ERR_NO_PACKAGED_DRM,
        409,
    )

    stored = fx.read_package(api, package["id"])
    assert stored["state"] == "PENDING", stored
    assert stored["hdcp_floor"] == "NONE", stored
    assert stored["entitlement_rule_count"] == 1, stored


# ---------------------------------------------------------------------------
# The publication gate and the two readiness variants (§3.1, §3.6)
# ---------------------------------------------------------------------------


def _gate_fixture(api):
    """A window-covered, locked-ladder title whose only package is still `PENDING`."""
    _tv_hd_profile(api)
    title = fx.create_title(
        api, external_ref="TTL-GATE-CERT", title_name="Publish Gate Cut", studio_code="NOVAPIC"
    )
    window = fx.create_window(api, title["id"])
    asset = fx.create_asset(
        api,
        title["id"],
        source_uri="s3://mez/gate.mxf",
        duration_seconds=5400,
        frame_rate=24.0,
        peak_audio_lufs=-24.0,
        artifact_defect_count=0,
        caption_languages=["en"],
        audio_language="en",
    )
    _run_qc(api, asset["id"])
    ladder = fx.create_locked_ladder(
        api, title["id"], codec_family="H264", rungs=RUNGS_480_720
    )
    package = fx.create_package(api, title["id"], ladder["id"])
    fx.add_entitlement_rule(
        api,
        package["id"],
        region_code="*",
        subscription_tier="ANY",
        max_concurrent_streams=2,
        max_playback_height_px=720,
        hdcp_level="NONE",
        priority=10,
    )
    return title, window, package


def test_a_certified_seventy_is_not_published_though_provisional_reads_one_hundred(api):
    """The first sweep activates the window but publishes nothing at certified 70.00.

    PRD §3.1: "The certified variant is the **only** variant any gate consults:
    automated publication requires `readiness_score_certified` of at least 80.00,
    and 80.00 exactly is sufficient."

    Design: Corner/calculations/publish_gate_reads_the_certified_variant_not_the_provisional
    """
    title, window, _package = _gate_fixture(api)

    counters = fx.run_sweep(api)

    assert_sweep_counters(counters, windows_activated=1, titles_published=0)
    windows, _meta = validate_paginated(
        api.list_availability_windows(title["id"], CONTENT_OPS)
    )
    activated = [row for row in windows if row["id"] == window["id"]]
    assert activated and activated[0]["state"] == "ACTIVE", windows
    stored = fx.read_title(api, title["id"])
    assert_score(
        stored["readiness_score_provisional"], 100.00, "readiness_score_provisional"
    )
    assert_score(stored["readiness_score_certified"], 70.00, "readiness_score_certified")
    assert stored["availability_state"] == "SCHEDULED", stored
    assert stored["packaging_state"] == "PACKAGING", stored


def test_packaging_the_pending_package_lifts_certified_to_one_hundred(api):
    """Packaging supplies the missing three tenths, taking certified from 70.00 to 100.00.

    PRD §3.1: "Its ladder component is 100.00 only when at least one ladder of the
    title is `LOCKED`, and its package component is 100.00 only when at least one
    DRM package of the title is `PACKAGED`."

    Design: Corner/calculations/publish_gate_reads_the_certified_variant_not_the_provisional
    """
    title, _window, package = _gate_fixture(api)
    fx.run_sweep(api)

    fx.package_package(api, package["id"])

    stored = fx.read_title(api, title["id"])
    assert_score(stored["readiness_score_certified"], 100.00, "readiness_score_certified")
    assert stored["packaging_state"] == "PACKAGED", stored


def test_the_very_next_sweep_publishes_the_now_certified_title(api):
    """With the window already `ACTIVE`, the second sweep activates none and publishes one.

    PRD §3.6: "A title in `SCHEDULED` moves to `PUBLISHED` when at least one of
    its windows is `ACTIVE` after Phase 1, its `packaging_state` is `PACKAGED`
    after Phase 3, and its `readiness_score_certified` is at least 80.00."

    Design: Corner/calculations/publish_gate_reads_the_certified_variant_not_the_provisional
    """
    title, _window, package = _gate_fixture(api)
    fx.run_sweep(api)
    fx.package_package(api, package["id"])

    counters = fx.run_sweep(api)

    assert_sweep_counters(counters, windows_activated=0, titles_published=1)
    stored = fx.read_title(api, title["id"])
    assert stored["availability_state"] == "PUBLISHED", stored
    assert stored["takedown_reason"] == "NONE", stored


def _revoke_readiness_fixture(api):
    """Two masters, one `QC_PASSED`, a `LOCKED` ladder and one `PENDING` package."""
    _tv_hd_profile(api)
    title = fx.create_title(
        api,
        external_ref="TTL-READY-REVOKE",
        title_name="Revoked Package Cut",
        studio_code="NOVAPIC",
    )
    passed = fx.create_asset(
        api,
        title["id"],
        source_uri="s3://mez/rev-a.mxf",
        duration_seconds=5400,
        frame_rate=24.0,
        peak_audio_lufs=-24.0,
        artifact_defect_count=0,
        caption_languages=["en"],
        audio_language="en",
    )
    ingested = fx.create_asset(
        api,
        title["id"],
        source_uri="s3://mez/rev-b.mxf",
        duration_seconds=5400,
        frame_rate=24.0,
        peak_audio_lufs=-24.0,
        artifact_defect_count=0,
        caption_languages=["en"],
        audio_language="en",
    )
    _run_qc(api, passed["id"])
    ladder = fx.create_locked_ladder(
        api, title["id"], codec_family="H264", rungs=RUNGS_480_720
    )
    package = fx.create_package(api, title["id"], ladder["id"])
    return title, passed, ingested, package


def test_a_pending_package_still_earns_the_full_provisional_three_tenths(api):
    """Half a certified master pool plus a locked ladder is 45.00 against a full 100.00.

    PRD §3.1: "Its package component is 100.00 when the title owns at least one
    DRM package whose `state` is `PENDING` or `PACKAGED`, and 0.00 otherwise."

    Design: Corner/calculations/readiness_ignores_a_revoked_package_in_both_variants
    """
    title, passed, ingested, _package = _revoke_readiness_fixture(api)

    stored = fx.read_title(api, title["id"])
    assert_score(
        stored["readiness_score_provisional"], 100.00, "readiness_score_provisional"
    )
    assert_score(stored["readiness_score_certified"], 45.00, "readiness_score_certified")
    assert fx.read_asset(api, ingested["id"])["qc_state"] == "INGESTED", ingested
    assert fx.read_asset(api, passed["id"])["qc_state"] == "QC_PASSED", passed


def test_revoking_the_package_drops_provisional_but_leaves_certified(api):
    """Provisional falls 100.00 to 70.00 while certified is unmoved at 45.00.

    PRD §3.1: "A master in the terminal `QC_REJECTED` state stays in the
    denominator of both variants and leaves both numerators, so an abandoned
    master permanently depresses readiness until other masters are added; a
    `REVOKED` DRM package counts for neither variant."

    Design: Corner/calculations/readiness_ignores_a_revoked_package_in_both_variants
    """
    title, _passed, _ingested, package = _revoke_readiness_fixture(api)

    revoked = validate_success(api.revoke_drm_package(package["id"], DRM_OPERATOR), 200)
    assert revoked["state"] == "REVOKED", revoked

    stored = fx.read_title(api, title["id"])
    assert_score(
        stored["readiness_score_provisional"], 70.00, "readiness_score_provisional"
    )
    assert_score(stored["readiness_score_certified"], 45.00, "readiness_score_certified")
