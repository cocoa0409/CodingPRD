"""Endpoint contracts, list ordering and immediate consistency (PRD §2.2, §2.3, §2.5, §2.9).

Every test in this module starts from an empty database with the logical clock at
its startup default `2026-08-01T00:00:00Z` (PRD §2.5).  Three families of
contract are exercised here.

First, the endpoint-level obligations that no single workflow owns: the clock
control being a pure assignment, the sweep reporting its nine counters even with
nothing to do, a title patch touching neither state dimension, a vendor's
commercial terms not re-running the steering selector, a newly registered device
profile not re-scoring an already-validated ladder, and the repackage path
refusing an empty body.

Second, the §2.2 response envelope and the §2.3 paging and ordering contract:
`page` / `page_size` in the request, `page`, `page_size`, `total_count` and
`has_more` in `meta`, `created_at` ascending by default, and the explicit
overrides — a title's licensing windows by `window_start_at` ascending and an
asset's QC reports by `attempt_number` ascending.

Third, the §2.9 promise that every consequence is applied inside the originating
request: the five-hop ladder-lock cascade and a metric ingest's derived figures
are both visible in the very response that caused them and in the next read,
with no sweep and no second write in between.
"""

from prd_bench_local_runner.testing import validate_error, validate_success, get_success_data
from test_helpers import api_errors as err
from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.api_client import parse_instant
from test_helpers.assertions import (
    assert_envelope,
    assert_immutable_resource,
    assert_instant_equals,
    assert_list_ids,
    assert_money,
    assert_ordered_by,
    assert_ratio_4dp,
    assert_score,
    assert_sweep_counters,
    validate_paginated,
    validate_unpaginated,
)
from test_helpers.constants import INITIAL_CLOCK, SWEEP_COUNTER_FIELDS, UUID_ABSENT
from test_helpers.test_users import (
    CONTENT_OPS,
    DELIVERY_ENGINEER,
    DRM_OPERATOR,
    ENCODING_ENGINEER,
    PLATFORM_ADMIN,
    QC_ANALYST,
)


# ---------------------------------------------------------------------------
# The logical clock is a pure assignment (§2.5)
# ---------------------------------------------------------------------------


def test_clock_advance_echoes_the_new_instant_and_leaves_the_window_scheduled(api):
    """Moving the clock two months past a SCHEDULED window's end answers 200 echoing 2026-10-01T00:00:00Z while the window stays SCHEDULED with both instants null.

    PRD §2.5: "A `PlatformAdmin` moves the clock by supplying a `current_utc`
    instant, and the response echoes the `current_utc` value now in force.
    Moving the clock is a pure assignment: on its own it transitions nothing,
    expires nothing and publishes nothing."

    PRD §3.6: "A new window is stored in `state` `SCHEDULED` with `activated_at`
    and `closed_at` both null."

    Design: Corner/endpoints/clock_advance_alone_transitions_nothing
    """
    title = fx.create_title(
        api,
        external_ref="TTL-CLOCK-ONLY",
        title_name="Clock Only Cut",
        content_type="MOVIE",
        studio_code="NOVAPIC",
    )
    window = fx.create_window(
        api,
        title["id"],
        region_code="US",
        window_start_at="2026-08-01T00:00:00Z",
        window_end_at="2026-09-01T00:00:00Z",
        license_tier="STANDARD",
    )
    assert window["state"] == "SCHEDULED", window

    clock = validate_success(api.set_clock("2026-10-01T00:00:00Z", PLATFORM_ADMIN), 200)
    assert_instant_equals(clock["current_utc"], "2026-10-01T00:00:00Z")

    rows, meta = validate_paginated(api.list_availability_windows(title["id"], CONTENT_OPS))
    assert meta["total_count"] == 1, meta
    assert_list_ids(rows, [window["id"]])
    assert rows[0]["state"] == "SCHEDULED", rows[0]
    assert rows[0]["activated_at"] is None, rows[0]
    assert rows[0]["closed_at"] is None, rows[0]


def test_clock_advance_alone_neither_publishes_the_title_nor_stamps_last_sweep_at(api):
    """The same clock jump leaves the title in SCHEDULED with `last_sweep_at` still null, because only the availability sweep applies temporal consequences.

    PRD §2.5: "Moving the clock is a pure assignment: on its own it transitions
    nothing, expires nothing and publishes nothing."

    PRD §3.6: "During Phase 4 of the availability sweep each title is offered
    **at most one** `availability_state` transition, evaluated against the
    windows as Phase 1 left them and the packaging dimension as Phase 3 left it,
    and each transition that fires stamps `last_sweep_at` with the logical
    clock's current instant."

    Design: Corner/endpoints/clock_advance_alone_transitions_nothing
    """
    title = fx.create_title(
        api,
        external_ref="TTL-CLOCK-ONLY",
        title_name="Clock Only Cut",
        content_type="MOVIE",
        studio_code="NOVAPIC",
    )
    fx.create_window(
        api,
        title["id"],
        region_code="US",
        window_start_at="2026-08-01T00:00:00Z",
        window_end_at="2026-09-01T00:00:00Z",
        license_tier="STANDARD",
    )
    scheduled = fx.read_title(api, title["id"])
    assert scheduled["availability_state"] == "SCHEDULED", scheduled

    validate_success(api.set_clock("2026-10-01T00:00:00Z", PLATFORM_ADMIN), 200)

    after = fx.read_title(api, title["id"])
    assert after["availability_state"] == "SCHEDULED", after
    assert after["last_sweep_at"] is None, after
    assert after["packaging_state"] == "UNPACKAGED", after


# ---------------------------------------------------------------------------
# The sweep always reports its nine counters (§2.5)
# ---------------------------------------------------------------------------


def test_sweep_on_an_empty_database_returns_all_nine_counters_as_zero(api):
    """POST /availability-sweep against an empty database answers 200 with all nine declared counters present and equal to 0.

    PRD §2.5: "The sweep returns a per-phase count object with exactly nine
    integer fields: `windows_activated`, `windows_closed`, `reservations_started`,
    `reservations_ended`, `jobs_completed`, `jobs_failed`, `titles_published`,
    `titles_taken_down` and `titles_expired`."

    PRD §2.5: "Each counts the transitions that this invocation actually applied."

    Design: Corner/endpoints/sweep_on_an_empty_database_returns_nine_zero_counters
    """
    counters = validate_unpaginated(api.run_availability_sweep(PLATFORM_ADMIN), 200)

    for field in SWEEP_COUNTER_FIELDS:
        assert field in counters, f"the sweep must always report {field}: {counters}"
    assert_sweep_counters(counters)


def test_second_sweep_by_content_ops_repeats_the_nine_zero_counters(api):
    """A second sweep at the unchanged clock, run by ContentOps rather than PlatformAdmin, answers 200 with the identical all-zero counter object.

    PRD §2.5: "The sweep is idempotent for a fixed clock value: running it a
    second time without moving the clock transitions nothing and returns all nine
    counts as zero."

    PRD §2.5: "The consequences of time passing are applied by the **availability
    sweep**, an operations checkpoint runnable by `PlatformAdmin` or `ContentOps`."

    Design: Corner/endpoints/sweep_on_an_empty_database_returns_nine_zero_counters
    """
    first = validate_unpaginated(api.run_availability_sweep(PLATFORM_ADMIN), 200)
    assert_sweep_counters(first)

    second = validate_unpaginated(api.run_availability_sweep(CONTENT_OPS), 200)
    assert_sweep_counters(second)
    assert {field: second[field] for field in SWEEP_COUNTER_FIELDS} == {
        field: first[field] for field in SWEEP_COUNTER_FIELDS
    }, (first, second)


# ---------------------------------------------------------------------------
# A title patch bumps `version` only (§2.9, §3.1)
# ---------------------------------------------------------------------------


def test_title_patch_bumps_version_from_one_to_two_and_rewrites_the_edited_fields(api):
    """PATCH /titles/{id} with a new `title_name` and `studio_code` answers 200, stores both values and moves `version` from 1 to 2.

    PRD §3.1: "`ContentOps` may later edit `title_name`, `studio_code` and
    `encode_budget_usd`; every successful edit increments the title's `version`
    and refreshes its `updated_at`, which is precisely what invalidates a
    previously captured `expected_title_version`."

    Design: Corner/endpoints/title_patch_bumps_version_without_touching_either_state_dimension
    """
    title = fx.create_title(
        api,
        external_ref="TTL-PATCH-VER",
        title_name="Patch Version Cut",
        content_type="EPISODE",
        studio_code="NOVAPIC",
    )
    assert title["version"] == 1, title

    patched = validate_success(
        api.patch_title(
            title["id"],
            f.title_patch_payload(
                title_name="Patch Version Cut (v2)", studio_code="LUMEN"
            ),
            CONTENT_OPS,
        ),
        200,
    )

    assert patched["version"] == title["version"] + 1 == 2, patched
    assert patched["title_name"] == "Patch Version Cut (v2)", patched
    assert patched["studio_code"] == "LUMEN", patched
    assert parse_instant(patched["updated_at"]) >= parse_instant(patched["created_at"]), patched


def test_title_patch_leaves_both_state_dimensions_and_both_readiness_variants_alone(api):
    """The same patch leaves `availability_state` DRAFT, `packaging_state` UNPACKAGED and both readiness variants at 0.00.

    PRD §2.9: "Neither dimension constrains the other's transitions directly;
    they interact only through the specific cascades and gates described in §3."

    PRD §3.1: "Its `availability_state` reads `DRAFT` and its `packaging_state`
    reads `UNPACKAGED`; `takedown_reason` reads `NONE`, because it has never been
    taken down; both `readiness_score_provisional` and `readiness_score_certified`
    read 0.00; `locked_ladder_count` reads 0; `encode_budget_remaining_usd` equals
    `encode_budget_usd` exactly; and `last_sweep_at` is null, because no
    availability sweep has evaluated it yet."

    Design: Corner/endpoints/title_patch_bumps_version_without_touching_either_state_dimension
    """
    title = fx.create_title(
        api,
        external_ref="TTL-PATCH-VER",
        title_name="Patch Version Cut",
        content_type="EPISODE",
        studio_code="NOVAPIC",
    )

    patched = validate_success(
        api.patch_title(
            title["id"],
            f.title_patch_payload(
                title_name="Patch Version Cut (v2)", studio_code="LUMEN"
            ),
            CONTENT_OPS,
        ),
        200,
    )

    assert patched["availability_state"] == "DRAFT", patched
    assert patched["packaging_state"] == "UNPACKAGED", patched
    assert_score(patched["readiness_score_provisional"], 0.00, "readiness_score_provisional")
    assert_score(patched["readiness_score_certified"], 0.00, "readiness_score_certified")

    reread = fx.read_title(api, title["id"])
    assert reread["availability_state"] == "DRAFT", reread
    assert reread["packaging_state"] == "UNPACKAGED", reread
    assert_score(reread["readiness_score_certified"], 0.00, "readiness_score_certified")


# ---------------------------------------------------------------------------
# Vendor terms are editable without re-running the steering selector (§3.7)
# ---------------------------------------------------------------------------


def _cost_steered_pair(api):
    """A COST-mode US policy over ALPHACDN at 0.0100 and BRAVOCDN at 0.0300."""
    title = fx.create_title(
        api,
        external_ref="TTL-FROZEN-SEL",
        title_name="Frozen Selection Cut",
        content_type="MOVIE",
        studio_code="NOVAPIC",
    )
    alpha = fx.create_vendor(
        api,
        vendor_code="ALPHACDN",
        regions=["US"],
        committed_gbps=100.00,
        cost_per_gb_usd=0.0100,
    )
    bravo = fx.create_vendor(
        api,
        vendor_code="BRAVOCDN",
        regions=["US"],
        committed_gbps=100.00,
        cost_per_gb_usd=0.0300,
    )
    policy = fx.create_policy(api, title["id"], region_code="US", steering_mode="COST")
    return title, alpha, bravo, policy


def test_cost_mode_selection_picks_the_cheaper_vendor_and_projects_ten_eighty(api):
    """A COST-mode policy over vendors at 0.0100 and 0.0300 selects ALPHACDN, keeps BRAVOCDN as backup and projects 10.80 from the zero-attempt flat 1000.00 GB.

    PRD §3.7: "Ranking second, by `steering_mode`: under `PERFORMANCE` candidates
    are ordered by `health_score_contract` descending, then `cost_per_gb_usd`
    ascending, then `created_at` ascending; under `COST` they are ordered by
    `cost_per_gb_usd` ascending, then `health_score_contract` descending, then
    `created_at` ascending; under `WEIGHTED` a composite figure is computed for
    each candidate as its `health_score_contract` reduced by its `cost_per_gb_usd`
    multiplied by 1000.0, rounded half up to four decimals, and candidates are
    ordered by that composite descending, then `created_at` ascending."

    PRD §3.7: "Step one, demand: the play attempts are summed as `play_attempts`
    across every ingested playback metric window whose `title_id` and
    `region_code` both match the policy's, with no state filter of any kind since
    metric windows are immutable events; the projected monthly volume is that
    attempt count multiplied by 2.5 gigabytes per play, rounded half up to two
    decimals, or a flat 1000.00 gigabytes when the attempt count is zero."

    Design: Corner/endpoints/vendor_terms_patch_does_not_resteer_existing_policies
    """
    _title, alpha, bravo, policy = _cost_steered_pair(api)

    assert policy["primary_vendor_id"] == alpha["id"], policy
    assert policy["backup_vendor_id"] == bravo["id"], policy
    assert policy["state"] == "ACTIVE", policy
    assert policy["selection_reason_code"] == "COST_RANK", policy
    assert policy["resteer_count"] == 0, policy
    assert policy["excluded_vendor_ids"] == [], policy
    assert_money(policy["projected_egress_cost_usd"], 10.80, "projected_egress_cost_usd")


def test_raising_the_primary_vendors_price_leaves_the_policy_frozen(api):
    """Raising ALPHACDN's `cost_per_gb_usd` from 0.0100 to 0.9000 answers 200 with vendor version 2, yet the policy keeps ALPHACDN, `resteer_count` 0 and `projected_egress_cost_usd` 10.80.

    PRD §3.7: "Changing `cost_per_gb_usd` or `regions` deliberately does **not**
    re-steer existing routing policies: a policy keeps its frozen selection until
    something re-runs the selector."

    PRD §3.7: "The **projected egress spend** is recomputed whenever a policy is
    created, re-steered by an operator, or re-steered automatically, and it
    follows a pinned five-step order."

    Design: Corner/endpoints/vendor_terms_patch_does_not_resteer_existing_policies
    """
    _title, alpha, _bravo, policy = _cost_steered_pair(api)

    patched = validate_success(
        api.patch_cdn_vendor(alpha["id"], {"cost_per_gb_usd": 0.9000}, PLATFORM_ADMIN), 200
    )
    assert_ratio_4dp(patched["cost_per_gb_usd"], 0.9000, "cost_per_gb_usd")
    assert patched["version"] == 2, patched

    frozen = fx.read_policy(api, policy["id"])
    assert frozen["primary_vendor_id"] == alpha["id"], frozen
    assert frozen["resteer_count"] == 0, frozen
    assert frozen["state"] == "ACTIVE", frozen
    assert_money(frozen["projected_egress_cost_usd"], 10.80, "projected_egress_cost_usd")


def test_only_an_explicit_resteer_moves_the_policy_to_the_surviving_vendor(api):
    """After the price rise, the explicit re-steer excludes ALPHACDN, lands STANDBY_ONLY on BRAVOCDN with a null backup, and recomputes the projection to 32.40.

    PRD §3.7: "It appends the outgoing `primary_vendor_id` to
    `excluded_vendor_ids` when one exists, re-runs the selector, rewrites
    `primary_vendor_id`, `backup_vendor_id`, `state` and `selection_reason_code`
    from the result, increments `resteer_count` by one and recomputes
    `projected_egress_cost_usd`."

    PRD §3.7: "From `ACTIVE`, when exactly one candidate remains after
    exclusions, the policy becomes `STANDBY_ONLY` with `primary_vendor_id` set to
    that single candidate and `backup_vendor_id` set to null."

    PRD §3.7: "Step three, surcharge rate: the tier is keyed on that rounded base
    cost and **never** on the eventual total — a base cost below 500.00 takes a
    rate of 0.08, a base cost of 500.00 or more but below 2000.00 takes 0.05, and
    a base cost of 2000.00 or more takes 0.03; a policy whose `steering_mode` is
    `WEIGHTED` then has a further 0.02 added to whichever rate was selected."

    Design: Corner/endpoints/vendor_terms_patch_does_not_resteer_existing_policies
    """
    _title, alpha, bravo, policy = _cost_steered_pair(api)
    validate_success(
        api.patch_cdn_vendor(alpha["id"], {"cost_per_gb_usd": 0.9000}, PLATFORM_ADMIN), 200
    )

    resteered = validate_success(
        api.resteer_routing_policy(policy["id"], DELIVERY_ENGINEER), 200
    )

    assert resteered["primary_vendor_id"] == bravo["id"], resteered
    assert resteered["backup_vendor_id"] is None, resteered
    assert resteered["state"] == "STANDBY_ONLY", resteered
    assert resteered["selection_reason_code"] == "COST_RANK", resteered
    assert resteered["resteer_count"] == 1, resteered
    assert resteered["excluded_vendor_ids"] == [alpha["id"]], resteered
    assert_money(resteered["projected_egress_cost_usd"], 32.40, "projected_egress_cost_usd")


# ---------------------------------------------------------------------------
# A ladder's compatibility figures are a validation-time snapshot (§3.3)
# ---------------------------------------------------------------------------


def _validated_two_rung_ladder(api):
    """One ACTIVE SMART_TV_HD profile at 60.00 share and a VALIDATED 2-rung H264 ladder."""
    profile = fx.create_device_profile(
        api,
        device_class="SMART_TV_HD",
        max_height_px=1080,
        supported_codecs=["H264"],
        min_bitrate_kbps=500,
        max_bitrate_kbps=8000,
        hdcp_required=False,
        required_drm_system="NONE",
        market_share_pct=60.00,
        quality_normalization_factor=1.00,
    )
    title = fx.create_title(
        api,
        external_ref="TTL-SNAPSHOT",
        title_name="Snapshot Score Cut",
        content_type="MOVIE",
        studio_code="NOVAPIC",
    )
    ladder = fx.create_ladder(
        api,
        title["id"],
        codec_family="H264",
        rungs=[f.rung("480p", 480, 1200), f.rung("720p", 720, 2500)],
    )
    validated = fx.validate_ladder(api, ladder["id"])
    return profile, title, validated


def test_two_rung_ladder_scores_twenty_four_against_one_sixty_percent_profile(api):
    """A 2-rung H264 ladder validated against a single 60.00-share profile scores 24.00 with `compatible_device_count` 1, because the coverage multiplier keeps only two fifths of the reach.

    PRD §3.3: "A coverage multiplier is taken as the lesser of 1.00 and the
    ladder's `rung_count` divided by the target of 5 rungs, so a two-rung ladder
    keeps only two fifths of the reach it would otherwise claim while a five-rung
    or longer ladder keeps all of it."

    PRD §3.3: "The base figure is the sum of `market_share_pct` across all
    compatible profiles, multiplied by that coverage multiplier, and only then
    rounded half up to two decimals."

    Design: Corner/endpoints/new_device_profile_does_not_rescore_a_validated_ladder
    """
    _profile, _title, validated = _validated_two_rung_ladder(api)

    assert_score(validated["device_compat_score"], 24.00, "device_compat_score")
    assert validated["compatible_device_count"] == 1, validated
    assert validated["state"] == "VALIDATED", validated
    assert validated["validation_reason_code"] == "OK", validated


def test_registering_another_compatible_profile_does_not_rescore_the_validated_ladder(api):
    """Registering a second compatible MOBILE_HIGH profile answers 201, yet the already-validated ladder still reads 24.00 with `compatible_device_count` 1.

    PRD §3.3: "Registering a new profile does **not** re-score ladders that have
    already been validated — a ladder's compatibility figures are a snapshot taken
    at validation time and are never refreshed behind the operator's back."

    PRD §3.3: "Scoring begins with the candidate set: every device profile whose
    `state` is `ACTIVE`."

    Design: Corner/endpoints/new_device_profile_does_not_rescore_a_validated_ladder
    """
    _profile, _title, validated = _validated_two_rung_ladder(api)

    second = validate_success(
        api.create_device_profile(
            f.device_profile_payload(
                device_class="MOBILE_HIGH",
                max_height_px=1080,
                supported_codecs=["H264"],
                min_bitrate_kbps=500,
                max_bitrate_kbps=8000,
                hdcp_required=False,
                required_drm_system="NONE",
                market_share_pct=30.00,
                quality_normalization_factor=0.90,
            ),
            PLATFORM_ADMIN,
        ),
        201,
    )
    assert second["device_class"] == "MOBILE_HIGH", second

    reread = fx.read_ladder(api, validated["id"])
    assert_score(reread["device_compat_score"], 24.00, "device_compat_score")
    assert reread["compatible_device_count"] == 1, reread
    assert reread["state"] == "VALIDATED", reread
    assert reread["validation_reason_code"] == "OK", reread


# ---------------------------------------------------------------------------
# A master's QC reports are ordered by `attempt_number` ascending (§2.3, §3.2)
# ---------------------------------------------------------------------------


def _asset_through_one_revision_loop(api):
    """A master with `artifact_defect_count` 8 driven twice around the QC loop."""
    title = fx.create_title(
        api,
        external_ref="TTL-QC-LIST",
        title_name="Report Order Cut",
        content_type="MOVIE",
        studio_code="NOVAPIC",
    )
    asset = fx.create_asset(
        api,
        title["id"],
        source_uri="s3://mez/loop.mxf",
        duration_seconds=3600,
        frame_rate=24.0,
        peak_audio_lufs=-24.0,
        artifact_defect_count=8,
        caption_languages=["en"],
        audio_language="en",
    )
    fx.run_qc(api, asset["id"])
    fx.request_remediation(api, asset["id"])
    # An empty resubmission body keeps every stored measurement as it was (§3.2).
    get_success_data(api.resubmit_mezzanine_asset(asset["id"], {}, CONTENT_OPS))
    fx.run_qc(api, asset["id"])
    return title, asset


def test_qc_report_sublist_returns_attempt_one_then_attempt_two(api):
    """Two failing runs around the remediation loop answer GET /mezzanine-assets/{id}/qc-reports with exactly attempt 1 then attempt 2.

    PRD §3.2: "The per-attempt evidence is only observable through a master's
    report list, which returns its reports ordered by `attempt_number` ascending."

    PRD §2.3: "Five collections override that default because their business
    ordering is load-bearing, and each override is stated with the endpoint that
    owns it: a title's licensing windows are ordered by `window_start_at`
    ascending and then `created_at` ascending; an asset's QC reports are ordered
    by `attempt_number` ascending; playback metric windows are ordered by
    `window_start_at` descending and then `created_at` descending; live
    reservations are ordered by `window_start_at` ascending then `created_at`
    ascending; a package's entitlement rules are ordered by `priority` descending
    then `created_at` ascending; and reprocessing jobs are ordered by
    `priority_rank` descending then `created_at` ascending."

    Design: Corner/endpoints/qc_reports_are_listed_in_attempt_number_order
    """
    _title, asset = _asset_through_one_revision_loop(api)

    rows, meta = validate_paginated(api.list_qc_reports(asset["id"], QC_ANALYST))

    assert meta["total_count"] == 2, meta
    assert len(rows) == 2, rows
    assert [row["attempt_number"] for row in rows] == [1, 2], rows
    assert_ordered_by(rows, "attempt_number")
    for row in rows:
        assert row["asset_id"] == asset["id"], row
        assert_immutable_resource(row, "QualityControlReport")


def test_qc_report_sublist_exposes_each_attempts_own_penalty_components(api):
    """Both reports carry `severity_index` 32.00 from the 8-defect artifact penalty, a 0.00 loudness deviation, 100.00 caption coverage, `ARTIFACT_BURST` and a FAIL verdict.

    PRD §3.2: "The `artifact_penalty` is the `artifact_defect_count` multiplied by
    4.0, rounded half up to two decimals."

    PRD §3.2: "An `artifact_defect_count` of 8 or more contributes
    `ARTIFACT_BURST`."

    PRD §3.2: "That list is the sole channel exposing each attempt's own
    `severity_index`, `artifact_penalty`, `loudness_deviation_db`,
    `caption_coverage_pct` and `verdict`; the master itself retains only the most
    recent `latest_severity_index` and `blocking_defect_code`."

    Design: Corner/endpoints/qc_reports_are_listed_in_attempt_number_order
    """
    _title, asset = _asset_through_one_revision_loop(api)

    rows, _meta = validate_paginated(api.list_qc_reports(asset["id"], QC_ANALYST))

    assert len(rows) == 2, rows
    for row in rows:
        assert_score(row["severity_index"], 32.00, "severity_index")
        assert_score(row["artifact_penalty"], 32.00, "artifact_penalty")
        assert_score(row["loudness_deviation_db"], 0.00, "loudness_deviation_db")
        assert_score(row["caption_coverage_pct"], 100.00, "caption_coverage_pct")
        assert row["blocking_defect_code"] == "ARTIFACT_BURST", row
        assert row["verdict"] == "FAIL", row


def test_resubmission_does_not_reset_the_attempt_count(api):
    """After the loop the master reads `qc_attempt_count` 2 and `qc_state` QC_FAILED, because the resubmission did not reset the counter.

    PRD §3.2: "Crucially, `qc_attempt_count` is **not** reset, so the loop
    `INGESTED` → `QC_FAILED` → `REMEDIATION_REQUESTED` → `INGESTED` can be walked
    at most twice: the third failing verdict is terminal no matter how many
    resubmissions preceded it."

    PRD §3.2: "A `FAIL` on the first or second attempt — that is, while
    `qc_attempt_count` stood at 0 or 1 before the run — drives the master from
    `INGESTED` to `QC_FAILED`."

    Design: Corner/endpoints/qc_reports_are_listed_in_attempt_number_order
    """
    _title, asset = _asset_through_one_revision_loop(api)

    reread = fx.read_asset(api, asset["id"])

    assert reread["qc_attempt_count"] == 2, reread
    assert reread["qc_state"] == "QC_FAILED", reread
    assert reread["blocking_defect_code"] == "ARTIFACT_BURST", reread
    assert_score(reread["latest_severity_index"], 32.00, "latest_severity_index")


# ---------------------------------------------------------------------------
# A title's licensing windows come back earliest-starting first (§2.3, §3.6)
# ---------------------------------------------------------------------------


def _windows_created_out_of_start_order(api):
    """A September US window created first, then an August CA window."""
    title = fx.create_title(
        api,
        external_ref="TTL-WIN-ORDER",
        title_name="Window Order Cut",
        content_type="MOVIE",
        studio_code="NOVAPIC",
    )
    us = fx.create_window(
        api,
        title["id"],
        region_code="US",
        window_start_at="2026-09-01T00:00:00Z",
        window_end_at="2026-10-01T00:00:00Z",
        license_tier="PREMIUM",
    )
    ca = fx.create_window(
        api,
        title["id"],
        region_code="CA",
        window_start_at="2026-08-01T00:00:00Z",
        window_end_at="2026-09-01T00:00:00Z",
        license_tier="BASIC",
    )
    return title, us, ca


def test_window_sublist_puts_the_august_row_before_the_earlier_created_september_row(api):
    """The August CA window created second is listed before the September US window created first, so creation order is not the list order.

    PRD §3.6: "A title's windows can be read back filtered by `region_code` and
    by `state`, returned earliest-starting first."

    PRD §2.3: "Unless a specific endpoint says otherwise, list results are
    ordered by `created_at` ascending."

    Design: Corner/endpoints/availability_windows_sublist_orders_by_window_start_then_created_at
    """
    title, us, ca = _windows_created_out_of_start_order(api)

    rows, meta = validate_paginated(api.list_availability_windows(title["id"], CONTENT_OPS))

    assert meta["total_count"] == 2, meta
    assert_list_ids(rows, [ca["id"], us["id"]])
    assert_ordered_by(rows, "window_start_at")
    assert_instant_equals(rows[0]["window_start_at"], "2026-08-01T00:00:00Z")
    assert_instant_equals(rows[1]["window_start_at"], "2026-09-01T00:00:00Z")


def test_window_sublist_region_filter_narrows_to_the_single_us_row(api):
    """A `region_code=US` filter on the same sublist returns exactly the September US window.

    PRD §3.6: "A title's windows can be read back filtered by `region_code` and
    by `state`, returned earliest-starting first."

    PRD §2.3: "For list responses the `meta` block carries the four pagination
    fields `page`, `page_size`, `total_count` and `has_more`, where `total_count`
    is the number of rows matching the filters before paging and `has_more` states
    whether any row remains beyond the returned page."

    Design: Corner/endpoints/availability_windows_sublist_orders_by_window_start_then_created_at
    """
    title, us, _ca = _windows_created_out_of_start_order(api)

    rows, meta = validate_paginated(
        api.list_availability_windows(title["id"], DELIVERY_ENGINEER, {"region_code": "US"})
    )

    assert meta["total_count"] == 1, meta
    assert meta["has_more"] is False, meta
    assert_list_ids(rows, [us["id"]])
    assert rows[0]["region_code"] == "US", rows[0]
    assert rows[0]["license_tier"] == "PREMIUM", rows[0]


def test_both_freshly_scheduled_windows_carry_null_activation_and_closure_instants(api):
    """Neither window has been touched by a sweep, so both read SCHEDULED with `activated_at` and `closed_at` null.

    PRD §3.6: "A new window is stored in `state` `SCHEDULED` with `activated_at`
    and `closed_at` both null."

    Design: Corner/endpoints/availability_windows_sublist_orders_by_window_start_then_created_at
    """
    title, _us, _ca = _windows_created_out_of_start_order(api)

    rows, _meta = validate_paginated(api.list_availability_windows(title["id"], PLATFORM_ADMIN))

    assert len(rows) == 2, rows
    for row in rows:
        assert row["state"] == "SCHEDULED", row
        assert row["activated_at"] is None, row
        assert row["closed_at"] is None, row


# ---------------------------------------------------------------------------
# Repackaging a STALE package demands an explicit rebind (§3.5)
# ---------------------------------------------------------------------------


def _stale_package_and_a_second_locked_ladder(api):
    """A PACKAGED package driven STALE by locking a second H264 ladder on the same title."""
    fx.create_device_profile(
        api,
        device_class="MOBILE_HIGH",
        max_height_px=1080,
        supported_codecs=["H264"],
        min_bitrate_kbps=500,
        max_bitrate_kbps=8000,
        hdcp_required=False,
        required_drm_system="NONE",
        market_share_pct=45.00,
        quality_normalization_factor=1.00,
    )
    title = fx.create_title(
        api,
        external_ref="TTL-REBIND",
        title_name="Rebind Cut",
        content_type="MOVIE",
        studio_code="NOVAPIC",
    )
    fx.create_passed_asset(
        api,
        title["id"],
        source_uri="s3://mez/rebind.mxf",
        duration_seconds=5400,
        frame_rate=24.0,
        peak_audio_lufs=-24.0,
        artifact_defect_count=0,
        caption_languages=["en"],
        audio_language="en",
    )
    first = fx.create_locked_ladder(
        api,
        title["id"],
        codec_family="H264",
        rungs=[f.rung("480p", 480, 1200), f.rung("720p", 720, 2500)],
    )
    package = fx.create_package(
        api,
        title["id"],
        first["id"],
        drm_systems=["WIDEVINE"],
        license_server_url="https://lic.novapic.example/wv",
    )
    fx.add_entitlement_rule(
        api,
        package["id"],
        region_code="*",
        subscription_tier="ANY",
        max_concurrent_streams=2,
        max_playback_height_px=720,
        hdcp_level="NONE",
        priority=20,
    )
    fx.package_package(api, package["id"])
    second = fx.create_locked_ladder(
        api,
        title["id"],
        codec_family="H264",
        rungs=[f.rung("480p", 480, 1500), f.rung("720p", 720, 3000)],
    )
    return title, package, first, second


def test_repackaging_a_stale_package_with_an_empty_body_is_rejected(api):
    """The second lock leaves the package STALE with `stale_reason` LADDER_SUPERSEDED, and an empty-bodied repackage is refused with 409 ERR_LADDER_NOT_LOCKED.

    PRD §3.5: "When the bound — or newly rebound — ladder is not `LOCKED`, the
    answer is `ERR_LADDER_NOT_LOCKED`, and that includes the common mistake of
    repackaging a `STALE` package without supplying a `ladder_id` at all."

    PRD §3.5: "From `STALE` it is a **repackage**, and it additionally requires
    the request to supply a `ladder_id` naming a ladder that is `LOCKED` and
    belongs to the same title, because the ladder the package was bound to is
    precisely the one that went away; the same master-quality requirement
    applies."

    Design: Corner/endpoints/stale_package_repackage_without_a_rebind_is_rejected
    """
    title, package, first, _second = _stale_package_and_a_second_locked_ladder(api)

    before = fx.read_package(api, package["id"])
    assert before["state"] == "STALE", before
    assert before["stale_reason"] == "LADDER_SUPERSEDED", before
    assert fx.read_ladder(api, first["id"])["state"] == "SUPERSEDED"

    validate_error(
        api.package_drm_package(package["id"], DRM_OPERATOR, {}),
        err.ERR_LADDER_NOT_LOCKED,
    )

    after = fx.read_package(api, package["id"])
    assert after["state"] == "STALE", after
    assert after["stale_reason"] == "LADDER_SUPERSEDED", after
    assert fx.read_title(api, title["id"])["packaging_state"] == "STALE"


def test_repackaging_against_the_second_locked_ladder_rebinds_and_clears_the_staleness(api):
    """Naming the surviving LOCKED ladder answers 200 PACKAGED with `ladder_id` rewritten, `stale_reason` back to NONE, `hdcp_floor` NONE and the title PACKAGED again.

    PRD §3.5: "A successful packaging sets the package's `state` to `PACKAGED`,
    sets `packaged_at` to the logical clock's current instant, clears
    `stale_reason` back to `NONE`, and re-derives `hdcp_floor` from the possibly
    rebound ladder's `peak_height_px`."

    PRD §3.5: "On the repackage path the package's `ladder_id` is rewritten to
    the supplied ladder."

    Design: Corner/endpoints/stale_package_repackage_without_a_rebind_is_rejected
    """
    title, package, _first, second = _stale_package_and_a_second_locked_ladder(api)

    repackaged = validate_success(
        api.package_drm_package(package["id"], DRM_OPERATOR, {"ladder_id": second["id"]}),
        200,
    )

    assert repackaged["state"] == "PACKAGED", repackaged
    assert repackaged["ladder_id"] == second["id"], repackaged
    assert repackaged["stale_reason"] == "NONE", repackaged
    assert repackaged["hdcp_floor"] == "NONE", repackaged
    assert_instant_equals(repackaged["packaged_at"], INITIAL_CLOCK)
    assert fx.read_title(api, title["id"])["packaging_state"] == "PACKAGED"


# ---------------------------------------------------------------------------
# The §2.2 envelope on an object read, a list read and a 404
# ---------------------------------------------------------------------------


def test_single_title_read_is_an_object_envelope_with_a_req_prefixed_request_id(api):
    """Reading one title answers 200 with `response_type` "object" and a `meta` carrying a `req_`-prefixed id and a three-fractional-digit timestamp.

    PRD §2.2: "The `api_request_id` is a server-generated unique identifier for
    the request that starts with `req_`."

    PRD §2.2: "The `response_type` is either "object" for a single resource or
    "array" for a list of resources."

    Design: Corner/endpoints/response_envelope_shape_on_object_list_and_error
    """
    title = fx.create_title(
        api,
        external_ref="TTL-ENVELOPE",
        title_name="Envelope Cut",
        content_type="MOVIE",
        studio_code="NOVAPIC",
    )

    response = api.get_title(title["id"], CONTENT_OPS)
    assert response.status_code == 200, response.text
    body = assert_envelope(response, "object")

    assert body["data"]["id"] == title["id"], body
    assert body["data"]["external_ref"] == "TTL-ENVELOPE", body


def test_title_list_read_is_an_array_envelope_carrying_the_four_paging_fields(api):
    """Listing the one title answers `response_type` "array" with `page` 1, `page_size` 20, `total_count` 1 and `has_more` false.

    PRD §2.3: "List endpoints in this API are paged by two query parameters:
    `page`, which is 1-based and defaults to 1, and `page_size`, which defaults to
    20, accepts a minimum of 1 and a maximum of 100."

    PRD §2.3: "For list responses the `meta` block carries the four pagination
    fields `page`, `page_size`, `total_count` and `has_more`, where `total_count`
    is the number of rows matching the filters before paging and `has_more` states
    whether any row remains beyond the returned page."

    Design: Corner/endpoints/response_envelope_shape_on_object_list_and_error
    """
    title = fx.create_title(
        api,
        external_ref="TTL-ENVELOPE",
        title_name="Envelope Cut",
        content_type="MOVIE",
        studio_code="NOVAPIC",
    )

    response = api.list_titles(CONTENT_OPS)
    assert response.status_code == 200, response.text
    assert_envelope(response, "array")

    rows, meta = validate_paginated(response)
    assert meta["page"] == 1, meta
    assert meta["page_size"] == 20, meta
    assert meta["total_count"] == 1, meta
    assert meta["has_more"] is False, meta
    assert_list_ids(rows, [title["id"]])


def test_unknown_title_id_answers_an_error_envelope_holding_only_id_and_message(api):
    """Reading an absent title answers 404 with `response_type` "error", `error_id` ERR_TITLE_NOT_FOUND, a non-empty `message` and a two-field `meta`.

    PRD §2.2: "The `meta` object for error responses contains only
    `api_request_id` and `api_request_timestamp`."

    PRD §2.2: "The `error_id` is a unique, machine-readable string that identifies
    the specific error."

    Design: Corner/endpoints/response_envelope_shape_on_object_list_and_error
    """
    fx.create_title(
        api,
        external_ref="TTL-ENVELOPE",
        title_name="Envelope Cut",
        content_type="MOVIE",
        studio_code="NOVAPIC",
    )

    response = api.get_title(UUID_ABSENT, CONTENT_OPS)
    validate_error(response, err.ERR_TITLE_NOT_FOUND)

    body = assert_envelope(response, "error")
    assert response.status_code == 404, response.text
    assert set(body["meta"]) == {"api_request_id", "api_request_timestamp"}, body["meta"]
    assert body["data"]["error_id"] == err.ERR_TITLE_NOT_FOUND, body
    assert isinstance(body["data"]["message"], str) and body["data"]["message"].strip(), body


# ---------------------------------------------------------------------------
# The ladder-lock cascade is applied inside the originating request (§2.9, §3.4)
# ---------------------------------------------------------------------------


def _packaged_title_with_a_second_validated_ladder(api):
    """A LOCKED ladder carrying a PACKAGED package, plus a second VALIDATED H264 ladder."""
    fx.create_device_profile(
        api,
        device_class="MOBILE_HIGH",
        max_height_px=1080,
        supported_codecs=["H264"],
        min_bitrate_kbps=500,
        max_bitrate_kbps=8000,
        hdcp_required=False,
        required_drm_system="NONE",
        market_share_pct=40.00,
        quality_normalization_factor=0.90,
    )
    title = fx.create_title(
        api,
        external_ref="TTL-IMMEDIATE",
        title_name="Immediate Cut",
        content_type="MOVIE",
        studio_code="NOVAPIC",
    )
    fx.create_passed_asset(
        api,
        title["id"],
        source_uri="s3://mez/immediate.mxf",
        duration_seconds=3600,
        frame_rate=24.0,
        peak_audio_lufs=-24.0,
        artifact_defect_count=0,
        caption_languages=["en"],
        audio_language="en",
    )
    first = fx.create_locked_ladder(
        api,
        title["id"],
        codec_family="H264",
        rungs=[f.rung("480p", 480, 1200), f.rung("720p", 720, 2500)],
    )
    package = fx.create_packaged_package(
        api,
        title["id"],
        first["id"],
        drm_systems=["WIDEVINE"],
        license_server_url="https://lic.novapic.example/wv",
    )
    second = fx.create_ladder(
        api,
        title["id"],
        codec_family="H264",
        rungs=[f.rung("480p", 480, 1500), f.rung("720p", 720, 3000)],
    )
    fx.validate_ladder(api, second["id"])
    return title, package, first, second


def test_the_lock_response_itself_already_reports_the_second_ladder_locked(api):
    """The 200 body of the lock call already names the second ladder in LOCKED, with nothing deferred to a later read.

    PRD §2.9: "A single request in this system routinely mutates several
    resources."

    PRD §3.4: "**Hop 1.** The ladder moves from `VALIDATED` to `LOCKED`, the
    title's `locked_ladder_count` is recomputed as the number of that title's
    ladders in `LOCKED`, and the title's `version` increments by one."

    Design: Corner/consistency_model/lock_cascade_is_visible_in_the_same_response_and_the_next_read
    """
    _title, _package, _first, second = _packaged_title_with_a_second_validated_ladder(api)

    locked = validate_success(api.lock_encoding_ladder(second["id"], ENCODING_ENGINEER), 200)

    assert locked["id"] == second["id"], locked
    assert locked["state"] == "LOCKED", locked
    assert locked["superseded_by_ladder_id"] is None, locked


def test_the_next_three_reads_after_the_lock_already_show_the_whole_cascade(api):
    """With no sweep and no second write, the reads immediately after the lock show the first ladder SUPERSEDED, the package STALE and the title STALE with one locked ladder.

    PRD §2.9: "The rule is that **every consequence is applied inside the
    originating request**, transitively, and each affected row's `updated_at` is
    refreshed and its `version` incremented, exactly as if it had been mutated
    directly."

    PRD §3.4: "A `LOCKED` ladder can also be superseded from the other direction
    — by a reprocessing job's result ladder replacing it, described in §3.9.
    Whichever cause applies, the `SUPERSEDED` transition always carries the same
    two consequences beyond the state change itself: the ladder's
    `superseded_by_ladder_id` is set to the replacing ladder, every `PACKAGED` DRM
    package bound to the superseded ladder goes `STALE` with `stale_reason` of
    `LADDER_SUPERSEDED`, and the title's `locked_ladder_count` is recomputed."

    Design: Corner/consistency_model/lock_cascade_is_visible_in_the_same_response_and_the_next_read
    """
    title, package, first, second = _packaged_title_with_a_second_validated_ladder(api)

    validate_success(api.lock_encoding_ladder(second["id"], ENCODING_ENGINEER), 200)

    superseded = fx.read_ladder(api, first["id"])
    assert superseded["state"] == "SUPERSEDED", superseded
    assert superseded["superseded_by_ladder_id"] == second["id"], superseded

    stale = fx.read_package(api, package["id"])
    assert stale["state"] == "STALE", stale
    assert stale["stale_reason"] == "LADDER_SUPERSEDED", stale

    reread = fx.read_title(api, title["id"])
    assert reread["packaging_state"] == "STALE", reread
    assert reread["locked_ladder_count"] == 1, reread


# ---------------------------------------------------------------------------
# A metric ingest reports its derived figures in its own response (§2.9, §3.7)
# ---------------------------------------------------------------------------


def _metric_ingest_ready(api):
    """A title, a MOBILE_HIGH profile at normalization factor 1.00, and one US vendor."""
    title = fx.create_title(
        api,
        external_ref="TTL-METRIC-NOW",
        title_name="Metric Now Cut",
        content_type="MOVIE",
        studio_code="NOVAPIC",
    )
    profile = fx.create_device_profile(
        api,
        device_class="MOBILE_HIGH",
        max_height_px=1080,
        supported_codecs=["H264"],
        min_bitrate_kbps=500,
        max_bitrate_kbps=8000,
        hdcp_required=False,
        required_drm_system="NONE",
        market_share_pct=40.00,
        quality_normalization_factor=1.00,
    )
    vendor = fx.create_vendor(
        api,
        vendor_code="NOWCDN",
        regions=["US"],
        committed_gbps=60.00,
        cost_per_gb_usd=0.0200,
    )
    return title, profile, vendor


def _breaching_metric_payload(title, profile, vendor):
    """200 attempts, 10 rebuffers, a 3000 ms p95 and 2 errors — a 68.50 window."""
    return f.playback_metric_payload(
        title["id"],
        profile["id"],
        vendor["id"],
        region_code="US",
        window_start_at="2026-07-01T00:00:00Z",
        window_end_at="2026-07-01T01:00:00Z",
        play_attempts=200,
        rebuffer_events=10,
        startup_ms_p95=3000,
        error_count=2,
    )


def test_metric_ingest_returns_its_ratios_quality_index_and_breach_flag_at_once(api):
    """The 201 ingest body already carries `rebuffer_ratio` 0.0500, `error_rate` 0.0100, `quality_index` 68.50 and `breach_flag` true.

    PRD §3.7: "Ingestion computes the window's quality figures before anything
    else happens."

    PRD §3.7: "The `rebuffer_ratio` is `rebuffer_events` divided by
    `play_attempts`, rounded half up to four decimals, and the `error_rate` is
    `error_count` divided by `play_attempts`, likewise to four decimals."

    PRD §3.7: "Finally the `quality_index` is 100.00 reduced by that penalty,
    clamped into the range 0.00 to 100.00, and rounded half up to two decimals,
    and the `breach_flag` is true exactly when `quality_index` is strictly below
    70.00; a `quality_index` of exactly 70.00 is not a breach while 69.99 is."

    Design: Corner/consistency_model/metric_ingest_returns_its_derived_fields_in_the_same_response
    """
    title, profile, vendor = _metric_ingest_ready(api)

    metric = validate_success(
        api.create_playback_metric(
            _breaching_metric_payload(title, profile, vendor), DELIVERY_ENGINEER
        ),
        201,
    )

    assert_ratio_4dp(metric["rebuffer_ratio"], 0.0500, "rebuffer_ratio")
    assert_ratio_4dp(metric["error_rate"], 0.0100, "error_rate")
    assert_score(metric["quality_index"], 68.50, "quality_index")
    assert metric["breach_flag"] is True, metric

    stored = validate_success(api.get_playback_metric(metric["id"], DELIVERY_ENGINEER), 200)
    assert_score(stored["quality_index"], 68.50, "quality_index")
    assert stored["breach_flag"] is True, stored


def test_the_vendor_read_right_after_the_ingest_already_shows_both_health_variants(api):
    """Reading the vendor immediately after the ingest shows both health variants at 68.50, `breach_window_count` 1 and the vendor still ACTIVE.

    PRD §3.7: "The `health_score_rolling` variant sorts those rows by
    `window_start_at` descending with `created_at` descending as its only
    tie-break, takes the newest 3 rows, and stores their unweighted arithmetic
    mean of `quality_index`, rounded half up to two decimals; when the vendor has
    fewer than 3 rows the mean is taken over however many exist, and when it has
    none at all the value is 100.00."

    PRD §3.7: "The `breach_window_count` is simply the number of the vendor's rows
    whose `breach_flag` is true."

    PRD §3.7: "Otherwise, while `breach_window_count` is below 5, a vendor in
    `ACTIVE` whose `health_score_rolling` fell below 50.00 moves to `DEGRADED`,
    and a vendor in `DEGRADED` whose `health_score_rolling` reached 75.00 or more
    moves back to `ACTIVE`, which is the recovery arm of the `ACTIVE` →
    `DEGRADED` → `ACTIVE` cycle."

    Design: Corner/consistency_model/metric_ingest_returns_its_derived_fields_in_the_same_response
    """
    title, profile, vendor = _metric_ingest_ready(api)
    assert_score(vendor["health_score_rolling"], 100.00, "health_score_rolling")

    validate_success(
        api.create_playback_metric(
            _breaching_metric_payload(title, profile, vendor), DELIVERY_ENGINEER
        ),
        201,
    )

    reread = fx.read_vendor(api, vendor["id"])
    assert_score(reread["health_score_rolling"], 68.50, "health_score_rolling")
    assert_score(reread["health_score_contract"], 68.50, "health_score_contract")
    assert reread["breach_window_count"] == 1, reread
    assert reread["state"] == "ACTIVE", reread
