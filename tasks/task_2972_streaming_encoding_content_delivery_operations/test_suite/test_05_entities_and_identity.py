"""Entity shape, identity and immutability tests (PRD §2.3, §2.4, §3.1, §3.3, §3.5).

Every test in this module starts from an empty database with the logical clock at
its startup default `2026-08-01T00:00:00Z` (PRD §2.5) and exercises one
entity-level contract: the declared defaults of a freshly created row, the
server-minted identity fields of §2.4, the per-family 404 catalogue, the body
foreign-key resolution order, the computed fields the API exposes read-only, and
the §2.4 split between the ten versioned resources and the three immutable ones.
"""

import pytest

from prd_bench_local_runner.testing import validate_error, validate_success, get_success_data
from test_helpers import api_errors as err
from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.assertions import (
    assert_identity_fields,
    assert_immutable_resource,
    assert_instant_equals,
    assert_list_ids,
    assert_money,
    assert_score,
    assert_versioned_resource,
    validate_paginated,
)
from test_helpers.constants import INITIAL_CLOCK, UUID_ABSENT
from test_helpers.test_users import (
    CONTENT_OPS,
    DELIVERY_ENGINEER,
    DRM_OPERATOR,
    ENCODING_ENGINEER,
    PLATFORM_ADMIN,
    QC_ANALYST,
)


# ---------------------------------------------------------------------------
# Title creation: the declared defaults (§3.1)
# ---------------------------------------------------------------------------


def test_title_creation_returns_declared_state_and_score_defaults(api):
    """POST /titles with only the four required inputs answers 201 with every declared default.

    PRD §3.1: "Its `availability_state` reads `DRAFT` and its `packaging_state`
    reads `UNPACKAGED`; `takedown_reason` reads `NONE`, because it has never been
    taken down; both `readiness_score_provisional` and `readiness_score_certified`
    read 0.00; `locked_ladder_count` reads 0; `encode_budget_remaining_usd` equals
    `encode_budget_usd` exactly; and `last_sweep_at` is null, because no
    availability sweep has evaluated it yet."

    Design: Corner/entities/title_creation_returns_declared_defaults
    """
    response = api.create_title(
        f.title_payload(
            external_ref="TTL-CORNER-01",
            title_name="Corner Reference Cut",
            content_type="MOVIE",
            studio_code="NOVAPIC",
        ),
        CONTENT_OPS,
    )
    title = validate_success(response, 201)

    assert title["availability_state"] == "DRAFT", title
    assert title["packaging_state"] == "UNPACKAGED", title
    assert title["takedown_reason"] == "NONE", title
    assert_score(title["readiness_score_provisional"], 0.00, "readiness_score_provisional")
    assert_score(title["readiness_score_certified"], 0.00, "readiness_score_certified")
    assert title["locked_ladder_count"] == 0, title
    assert title["last_sweep_at"] is None, title


def test_title_creation_defaults_the_budget_and_mirrors_it_into_remaining(api):
    """An omitted `encode_budget_usd` defaults to 5000.00, is mirrored into the remaining budget, and the row starts at version 1.

    PRD §3.1: "The operator may optionally set `encode_budget_usd`, the total
    reprocessing budget granted to the title, which must be zero or greater at two
    decimal places and which defaults to 5000.00 when omitted."

    PRD §2.4: "Most resources additionally carry `updated_at`, refreshed on every
    successful mutation, and `version`, an integer that starts at 1 on creation and
    increments by one on each mutation of that row."

    Design: Corner/entities/title_creation_returns_declared_defaults
    """
    response = api.create_title(
        f.title_payload(
            external_ref="TTL-CORNER-01",
            title_name="Corner Reference Cut",
            content_type="MOVIE",
            studio_code="NOVAPIC",
        ),
        CONTENT_OPS,
    )
    title = validate_success(response, 201)

    assert_versioned_resource(title, "Title")
    assert_money(title["encode_budget_usd"], 5000.00, "encode_budget_usd")
    assert_money(title["encode_budget_remaining_usd"], 5000.00, "encode_budget_remaining_usd")
    assert title["version"] == 1, title


def test_title_retrieval_returns_stored_fields(api):
    """GET /titles/{id} returns the stored descriptive fields and the explicitly supplied budget of 1200.50, readable by a QcAnalyst.

    PRD §3.1: "Reading a title back exposes all of this together with its
    `version`, which is the token later required for ladder and reprocessing-job
    creation."

    PRD §3.1: "Its `availability_state` reads `DRAFT` and its `packaging_state`
    reads `UNPACKAGED`; `takedown_reason` reads `NONE`, because it has never been
    taken down; both `readiness_score_provisional` and `readiness_score_certified`
    read 0.00; `locked_ladder_count` reads 0; `encode_budget_remaining_usd` equals
    `encode_budget_usd` exactly; and `last_sweep_at` is null, because no
    availability sweep has evaluated it yet."

    Design: Corner/entities/title_retrieval_returns_stored_fields
    """
    created = fx.create_title(
        api,
        external_ref="TTL-READ-02",
        title_name="Readback Cut",
        content_type="EPISODE",
        studio_code="NOVAPIC",
        encode_budget_usd=1200.50,
    )

    title = validate_success(api.get_title(created["id"], QC_ANALYST), 200)

    assert title["external_ref"] == "TTL-READ-02", title
    assert title["title_name"] == "Readback Cut", title
    assert title["content_type"] == "EPISODE", title
    assert title["studio_code"] == "NOVAPIC", title
    assert_money(title["encode_budget_usd"], 1200.50, "encode_budget_usd")
    assert_money(title["encode_budget_remaining_usd"], 1200.50, "encode_budget_remaining_usd")


# ---------------------------------------------------------------------------
# Title listing: pagination and created_at ordering (§2.3)
# ---------------------------------------------------------------------------


def test_title_listing_first_page_carries_two_oldest_titles_and_has_more(api):
    """Three titles created A, B, C answer GET /titles?page=1&page_size=2 with exactly A then B, total_count 3 and has_more true.

    PRD §2.3: "Unless a specific endpoint says otherwise, list results are ordered
    by `created_at` ascending."

    PRD §2.3: "For list responses the `meta` block carries the four pagination
    fields `page`, `page_size`, `total_count` and `has_more`, where `total_count`
    is the number of rows matching the filters before paging and `has_more` states
    whether any row remains beyond the returned page."

    Design: Corner/entities/title_listing_paginated_ordered_by_created_at
    """
    fx.create_title(api, external_ref="TTL-PAGE-A", title_name="Page A")
    fx.create_title(api, external_ref="TTL-PAGE-B", title_name="Page B")
    fx.create_title(api, external_ref="TTL-PAGE-C", title_name="Page C")

    rows, meta = validate_paginated(api.list_titles(CONTENT_OPS, {"page": 1, "page_size": 2}))

    assert meta["total_count"] == 3, meta
    assert meta["has_more"] is True, meta
    assert len(rows) == 2, rows
    assert rows[0]["external_ref"] == "TTL-PAGE-A", rows
    assert rows[1]["external_ref"] == "TTL-PAGE-B", rows


def test_title_listing_second_page_carries_the_newest_title_and_no_more(api):
    """The second page of the same three titles returns exactly TTL-PAGE-C with total_count 3 and has_more false.

    PRD §2.3: "List endpoints in this API are paged by two query parameters:
    `page`, which is 1-based and defaults to 1, and `page_size`, which defaults to
    20, accepts a minimum of 1 and a maximum of 100."

    PRD §2.3: "Unless a specific endpoint says otherwise, list results are ordered
    by `created_at` ascending."

    Design: Corner/entities/title_listing_paginated_ordered_by_created_at
    """
    fx.create_title(api, external_ref="TTL-PAGE-A", title_name="Page A")
    fx.create_title(api, external_ref="TTL-PAGE-B", title_name="Page B")
    fx.create_title(api, external_ref="TTL-PAGE-C", title_name="Page C")

    rows, meta = validate_paginated(api.list_titles(CONTENT_OPS, {"page": 2, "page_size": 2}))

    assert meta["total_count"] == 3, meta
    assert meta["has_more"] is False, meta
    assert len(rows) == 1, rows
    assert rows[0]["external_ref"] == "TTL-PAGE-C", rows


# ---------------------------------------------------------------------------
# The per-family 404 catalogue (§2.4)
# ---------------------------------------------------------------------------

UNKNOWN_PATH_ID_CASES = [
    ("titles", lambda api: api.get_title(UUID_ABSENT, CONTENT_OPS), err.ERR_TITLE_NOT_FOUND),
    (
        "mezzanine-assets",
        lambda api: api.get_mezzanine_asset(UUID_ABSENT, QC_ANALYST),
        err.ERR_ASSET_NOT_FOUND,
    ),
    (
        "encoding-ladders",
        lambda api: api.get_encoding_ladder(UUID_ABSENT, ENCODING_ENGINEER),
        err.ERR_LADDER_NOT_FOUND,
    ),
    (
        "drm-packages",
        lambda api: api.get_drm_package(UUID_ABSENT, DRM_OPERATOR),
        err.ERR_PACKAGE_NOT_FOUND,
    ),
    (
        "routing-policies",
        lambda api: api.get_routing_policy(UUID_ABSENT, DELIVERY_ENGINEER),
        err.ERR_POLICY_NOT_FOUND,
    ),
    (
        "live-reservations",
        lambda api: api.get_live_reservation(UUID_ABSENT, DELIVERY_ENGINEER),
        err.ERR_RESERVATION_NOT_FOUND,
    ),
    (
        "availability-windows-cancel",
        lambda api: api.cancel_availability_window(UUID_ABSENT, CONTENT_OPS),
        err.ERR_WINDOW_NOT_FOUND,
    ),
    (
        "reprocess-jobs",
        lambda api: api.get_reprocess_job(UUID_ABSENT, ENCODING_ENGINEER),
        err.ERR_JOB_NOT_FOUND,
    ),
    (
        "cdn-vendors",
        lambda api: api.get_cdn_vendor(UUID_ABSENT, PLATFORM_ADMIN),
        err.ERR_VENDOR_NOT_FOUND,
    ),
    (
        "playback-metrics",
        lambda api: api.get_playback_metric(UUID_ABSENT, DELIVERY_ENGINEER),
        err.ERR_METRIC_WINDOW_NOT_FOUND,
    ),
]


@pytest.mark.parametrize(
    "collection,call,expected_error",
    UNKNOWN_PATH_ID_CASES,
    ids=[case[0] for case in UNKNOWN_PATH_ID_CASES],
)
def test_unknown_path_id_returns_the_families_own_not_found(api, collection, call, expected_error):
    """Each of the ten path-addressable collections answers a well-formed but never-minted UUID with its own 404 identifier.

    PRD §2.4: "Each entity family has its own 404 identifier:
    `ERR_TITLE_NOT_FOUND`, `ERR_ASSET_NOT_FOUND`, `ERR_LADDER_NOT_FOUND`,
    `ERR_PACKAGE_NOT_FOUND`, `ERR_DEVICE_PROFILE_NOT_FOUND`,
    `ERR_VENDOR_NOT_FOUND`, `ERR_POLICY_NOT_FOUND`,
    `ERR_RESERVATION_NOT_FOUND`, `ERR_WINDOW_NOT_FOUND`, `ERR_JOB_NOT_FOUND` and
    `ERR_METRIC_WINDOW_NOT_FOUND`."

    PRD §2.4: "Path identifiers are resolved strictly left to right, in the order
    they appear in the URL."

    Design: Corner/entities/unknown_path_ids_across_collections_return_not_found
    """
    response = call(api)
    validate_error(response, expected_error, 404)


# ---------------------------------------------------------------------------
# Body foreign keys resolve in the endpoint's declared input order (§2.4)
# ---------------------------------------------------------------------------


def test_mezzanine_asset_with_unknown_title_id_returns_title_not_found(api):
    """POST /mezzanine-assets naming a never-minted `title_id` answers ERR_TITLE_NOT_FOUND and stores no master.

    PRD §2.4: "The same catalogue governs foreign keys arriving in a request body
    or query string — a `title_id`, `ladder_id`, `source_ladder_id`,
    `derived_from_ladder_id`, `vendor_id`, `primary_vendor_id`,
    `failover_vendor_id`, `device_profile_id` or `package_id` that names nothing
    stored produces the matching 404 — with one difference: body and query foreign
    keys are resolved in the order the fields are declared in the endpoint's input
    list, so the first unresolvable reference in that order is the one reported."

    Design: Corner/entities/body_foreign_keys_validated_in_input_order_not_found
    """
    title = fx.create_title(api, external_ref="TTL-FK-03", title_name="FK Integrity Cut")

    response = api.create_mezzanine_asset(
        f.mezzanine_asset_payload(UUID_ABSENT, source_uri="s3://mez/fk-orphan.mxf"),
        CONTENT_OPS,
    )
    validate_error(response, err.ERR_TITLE_NOT_FOUND, 404)

    rows, meta = validate_paginated(api.list_title_mezzanine_assets(title["id"], CONTENT_OPS))
    assert meta["total_count"] == 0, meta
    assert rows == [], rows


def test_ladder_with_unknown_derived_from_ladder_id_returns_ladder_not_found(api):
    """POST /encoding-ladders whose `derived_from_ladder_id` names nothing stored answers ERR_LADDER_NOT_FOUND and stores no ladder.

    PRD §2.4: "The same catalogue governs foreign keys arriving in a request body
    or query string — a `title_id`, `ladder_id`, `source_ladder_id`,
    `derived_from_ladder_id`, `vendor_id`, `primary_vendor_id`,
    `failover_vendor_id`, `device_profile_id` or `package_id` that names nothing
    stored produces the matching 404 — with one difference: body and query foreign
    keys are resolved in the order the fields are declared in the endpoint's input
    list, so the first unresolvable reference in that order is the one reported."

    Design: Corner/entities/body_foreign_keys_validated_in_input_order_not_found
    """
    title = fx.create_title(api, external_ref="TTL-FK-03", title_name="FK Integrity Cut")
    version = fx.title_version(api, title["id"])

    response = api.create_encoding_ladder(
        f.encoding_ladder_payload(
            title["id"], version, codec_family="HEVC", derived_from_ladder_id=UUID_ABSENT
        ),
        ENCODING_ENGINEER,
    )
    validate_error(response, err.ERR_LADDER_NOT_FOUND, 404)

    rows, meta = validate_paginated(
        api.list_encoding_ladders(ENCODING_ENGINEER, {"title_id": title["id"]})
    )
    assert meta["total_count"] == 0, meta
    assert rows == [], rows


def test_metric_ingest_reports_the_earlier_declared_unresolvable_foreign_key(api):
    """A metric ingest carrying both an unknown `device_profile_id` and an unknown `vendor_id` reports the device profile, the earlier input field.

    PRD §2.4: "The same catalogue governs foreign keys arriving in a request body
    or query string — a `title_id`, `ladder_id`, `source_ladder_id`,
    `derived_from_ladder_id`, `vendor_id`, `primary_vendor_id`,
    `failover_vendor_id`, `device_profile_id` or `package_id` that names nothing
    stored produces the matching 404 — with one difference: body and query foreign
    keys are resolved in the order the fields are declared in the endpoint's input
    list, so the first unresolvable reference in that order is the one reported."

    PRD §3.7: "The payload carries `title_id`, `device_profile_id`, `vendor_id`,
    `region_code`, the `window_start_at` and `window_end_at` bounds with the end
    strictly after the start, the `play_attempts` count of at least 1, the
    `rebuffer_events` count of zero or more, the `startup_ms_p95` 95th-percentile
    startup latency between 0 and 60000 milliseconds, and the `error_count` of
    fatal playback errors, zero or more."

    Design: Corner/entities/body_foreign_keys_validated_in_input_order_not_found
    """
    profile = fx.create_tv_4k_profile(api)
    fx.create_vendor(api, vendor_code="ALPHA", regions=["US"], committed_gbps=100.00, cost_per_gb_usd=0.0300)
    title = fx.create_title(api, external_ref="TTL-FK-03", title_name="FK Integrity Cut")

    window_bounds = {
        "window_start_at": "2026-07-30T00:00:00Z",
        "window_end_at": "2026-07-31T00:00:00Z",
        "play_attempts": 1000,
        "rebuffer_events": 20,
        "startup_ms_p95": 2000,
        "error_count": 0,
    }

    vendor_only = api.create_playback_metric(
        f.playback_metric_payload(title["id"], profile["id"], UUID_ABSENT, **window_bounds),
        DELIVERY_ENGINEER,
    )
    validate_error(vendor_only, err.ERR_VENDOR_NOT_FOUND, 404)

    both_unknown = api.create_playback_metric(
        f.playback_metric_payload(title["id"], UUID_ABSENT, UUID_ABSENT, **window_bounds),
        DELIVERY_ENGINEER,
    )
    validate_error(both_unknown, err.ERR_DEVICE_PROFILE_NOT_FOUND, 404)

    rows, meta = validate_paginated(
        api.list_playback_metrics(DELIVERY_ENGINEER, {"title_id": title["id"]})
    )
    assert meta["total_count"] == 0, meta
    assert rows == [], rows


# ---------------------------------------------------------------------------
# Required inputs on source-master registration (§3.1, rung 6)
# ---------------------------------------------------------------------------


def test_mezzanine_asset_without_audio_language_returns_invalid_request(api):
    """Omitting the required `audio_language` answers 400 ERR_INVALID_REQUEST and stores no master.

    PRD §3.1: "A **mezzanine asset** is registered by `ContentOps` against a title,
    carrying the payload's `title_id`, the storage `source_uri` of 1 to 300
    characters, the runtime `duration_seconds` in whole seconds of at least 1, the
    source `frame_rate`, which must be exactly one of 23.976, 24.0, 25.0, 29.97,
    50.0 or 59.94, the measured program loudness `peak_audio_lufs` in LUFS
    somewhere between -60.0 and 0.0 inclusive, the `artifact_defect_count` reported
    by the ingest scanner, which is zero or greater, the `audio_language` as a
    two-character lowercase language code, and optionally `caption_languages`, an
    array of two-character lowercase language codes with no duplicates that
    defaults to empty."

    PRD §2.6: "**Rung 6 — payload schema.** Every required input is present; no
    unknown field is supplied; every value has the correct JSON type; every enum
    value is drawn from its declared set; every instant parses as ISO 8601 UTC;
    decimals sit within their declared scale; integers sit within their declared
    range; every `region_code` is two uppercase letters (or the single literal `*`
    where a rule explicitly allows a wildcard); `page` is at least 1 and
    `page_size` is between 1 and 100 inclusive."

    Design: Corner/entities/mezzanine_asset_missing_required_input_returns_invalid_request
    """
    title = fx.create_title(api, external_ref="TTL-REQ-04", title_name="Required Field Cut")

    response = api.create_mezzanine_asset(
        f.mezzanine_asset_payload(
            title["id"], source_uri="s3://mez/req-04.mxf", audio_language=None
        ),
        CONTENT_OPS,
    )
    validate_error(response, err.ERR_INVALID_REQUEST, 400)

    rows, meta = validate_paginated(api.list_title_mezzanine_assets(title["id"], CONTENT_OPS))
    assert meta["total_count"] == 0, meta
    assert rows == [], rows


def test_mezzanine_asset_without_duration_seconds_returns_invalid_request(api):
    """Omitting the required `duration_seconds` answers 400 ERR_INVALID_REQUEST and stores no master.

    PRD §3.1: "A **mezzanine asset** is registered by `ContentOps` against a title,
    carrying the payload's `title_id`, the storage `source_uri` of 1 to 300
    characters, the runtime `duration_seconds` in whole seconds of at least 1, the
    source `frame_rate`, which must be exactly one of 23.976, 24.0, 25.0, 29.97,
    50.0 or 59.94, the measured program loudness `peak_audio_lufs` in LUFS
    somewhere between -60.0 and 0.0 inclusive, the `artifact_defect_count` reported
    by the ingest scanner, which is zero or greater, the `audio_language` as a
    two-character lowercase language code, and optionally `caption_languages`, an
    array of two-character lowercase language codes with no duplicates that
    defaults to empty."

    PRD §2.6: "**Rung 6 — payload schema.** Every required input is present; no
    unknown field is supplied; every value has the correct JSON type; every enum
    value is drawn from its declared set; every instant parses as ISO 8601 UTC;
    decimals sit within their declared scale; integers sit within their declared
    range; every `region_code` is two uppercase letters (or the single literal `*`
    where a rule explicitly allows a wildcard); `page` is at least 1 and
    `page_size` is between 1 and 100 inclusive."

    Design: Corner/entities/mezzanine_asset_missing_required_input_returns_invalid_request
    """
    title = fx.create_title(api, external_ref="TTL-REQ-04", title_name="Required Field Cut")

    response = api.create_mezzanine_asset(
        f.mezzanine_asset_payload(
            title["id"], source_uri="s3://mez/req-04.mxf", duration_seconds=None
        ),
        CONTENT_OPS,
    )
    validate_error(response, err.ERR_INVALID_REQUEST, 400)

    rows, meta = validate_paginated(api.list_title_mezzanine_assets(title["id"], CONTENT_OPS))
    assert meta["total_count"] == 0, meta
    assert rows == [], rows


# ---------------------------------------------------------------------------
# Omitted optional inputs take their declared defaults (§3.3, §3.5)
# ---------------------------------------------------------------------------


def test_device_profile_registered_without_state_defaults_to_active(api):
    """A device profile created without `state` reads ACTIVE, not null.

    PRD §3.3: "A profile's `state` is either `ACTIVE` or `RETIRED` and may be set
    at registration, defaulting to `ACTIVE`."

    Design: Corner/entities/omitted_optional_inputs_apply_declared_defaults
    """
    response = api.create_device_profile(f.device_profile_payload(), PLATFORM_ADMIN)
    profile = validate_success(response, 201)

    assert profile["state"] == "ACTIVE", profile


def test_drm_package_created_without_optional_inputs_takes_declared_defaults(api):
    """A package created without `key_rotation_hours` and without `persistent_license_allowed` reads 24 and false, PENDING, hdcp_floor NONE, stale_reason NONE and packaged_at null.

    PRD §3.5: "The package declares `drm_systems`, an array of 1 to 3 distinct
    members drawn from `WIDEVINE`, `PLAYREADY` and `FAIRPLAY`;
    `license_server_url`, the HTTPS endpoint that will issue content keys, which
    must begin with `https://` and run 8 to 300 characters; `key_rotation_hours`,
    the content-key rotation period in whole hours from 1 to 168, defaulting to 24;
    and `persistent_license_allowed`, a boolean defaulting to false that states
    whether offline licenses may ever be issued for this package."

    PRD §3.5: "On creation the package's `state` is `PENDING`, its `stale_reason`
    is `NONE`, its `entitlement_rule_count` is 0 and its `packaged_at` is null."

    PRD §3.5: "The package's `hdcp_floor` is derived, not supplied: it reads
    `TYPE_1` when the bound ladder's `peak_height_px` is 2160 or greater, `TYPE_0`
    when that height is 1080 or greater but below 2160, and `NONE` otherwise."

    Design: Corner/entities/omitted_optional_inputs_apply_declared_defaults
    """
    title = fx.create_title(api, external_ref="TTL-DEF-05", title_name="Defaults Cut")
    ladder = fx.create_ladder(api, title["id"], codec_family="H264")

    response = api.create_drm_package(
        f.drm_package_payload(title["id"], ladder["id"]), DRM_OPERATOR
    )
    package = validate_success(response, 201)

    assert package["key_rotation_hours"] == 24, package
    assert package["persistent_license_allowed"] is False, package
    assert package["state"] == "PENDING", package
    assert package["hdcp_floor"] == "NONE", package
    assert package["stale_reason"] == "NONE", package
    assert package["packaged_at"] is None, package
    assert package["entitlement_rule_count"] == 0, package


def test_entitlement_rule_created_without_optional_inputs_takes_declared_defaults(api):
    """A rule attached without `device_class_scope` and without `offline_playback_allowed` reads ALL and false, and lifts the package's rule count to 1.

    PRD §3.5: "Each rule names the `region_code` it applies to, either two
    uppercase letters or the single wildcard character `*` meaning any region; the
    `subscription_tier` it applies to, one of `BASIC`, `STANDARD`, `PREMIUM` or
    `ANY`, where `ANY` matches every tier; and optionally the `device_class_scope`,
    one of `ALL`, `TV_ONLY` or `MOBILE_ONLY` and defaulting to `ALL`, where
    `TV_ONLY` covers `SMART_TV_4K`, `SMART_TV_HD` and `SET_TOP_LEGACY` and
    `MOBILE_ONLY` covers `MOBILE_HIGH` and `MOBILE_LOW`."

    PRD §3.5: "The rule then states the ceiling it licenses:
    `max_concurrent_streams`, the number of simultaneous sessions permitted, from 1
    to 10; `max_playback_height_px`, the tallest rendition licensed, from 240 to
    2160; `hdcp_level`, the output protection it mandates, one of `NONE`, `TYPE_0`
    or `TYPE_1`; `offline_playback_allowed`, a boolean defaulting to false; and
    `priority`, the selector rank from 1 to 100 where a higher number wins."

    PRD §3.5: "A successful attachment increments the package's
    `entitlement_rule_count` by one."

    Design: Corner/entities/omitted_optional_inputs_apply_declared_defaults
    """
    fx.create_device_profile(api)
    title = fx.create_title(api, external_ref="TTL-DEF-05", title_name="Defaults Cut")
    ladder = fx.create_ladder(api, title["id"], codec_family="H264")
    package = fx.create_package(api, title["id"], ladder["id"])

    response = api.create_entitlement_rule(
        package["id"],
        f.entitlement_rule_payload(device_class_scope=None, max_concurrent_streams=2),
        DRM_OPERATOR,
    )
    rule = validate_success(response, 201)

    assert rule["device_class_scope"] == "ALL", rule
    assert rule["offline_playback_allowed"] is False, rule

    stored_package = fx.read_package(api, package["id"])
    assert stored_package["entitlement_rule_count"] == 1, stored_package


# ---------------------------------------------------------------------------
# Ladder aggregates are derived from the rungs, not supplied (§3.3)
# ---------------------------------------------------------------------------

RUNGS_THREE_PEAK_1080 = [
    {"label": "360p", "height_px": 360, "bitrate_kbps": 900},
    {"label": "720p", "height_px": 720, "bitrate_kbps": 2500},
    {"label": "1080p", "height_px": 1080, "bitrate_kbps": 5000},
]


def test_draft_ladder_aggregates_are_derived_from_its_three_rungs(api):
    """A three-rung ladder peaking at 1080p/5000 kbps reads rung_count 3, peak_bitrate_kbps 5000, peak_height_px 1080 and state DRAFT.

    PRD §3.3: "A newly authored ladder is stored in `state` `DRAFT` with
    `rung_count` set to the number of elements in `rungs`, `peak_bitrate_kbps` set
    to the largest `bitrate_kbps` across the rungs and `peak_height_px` set to the
    largest `height_px`."

    Design: Corner/entities/ladder_computed_aggregates_derived_from_rungs
    """
    fx.create_device_profile(api)
    title = fx.create_title(api, external_ref="TTL-COMP-06", title_name="Computed Fields Cut")

    response = api.create_encoding_ladder(
        f.encoding_ladder_payload(
            title["id"],
            fx.title_version(api, title["id"]),
            codec_family="H264",
            rungs=[dict(rung) for rung in RUNGS_THREE_PEAK_1080],
        ),
        ENCODING_ENGINEER,
    )
    ladder = validate_success(response, 201)

    assert ladder["rung_count"] == 3, ladder
    assert ladder["peak_bitrate_kbps"] == 5000, ladder
    assert ladder["peak_height_px"] == 1080, ladder
    assert ladder["state"] == "DRAFT", ladder


def test_draft_ladder_leaves_the_evaluated_fields_and_lineage_unwritten(api):
    """Before validation the ladder reads device_compat_score 0.00, compatible_device_count 0, validation_reason_code NONE, both lineage links null, and leaves the title's locked_ladder_count at 0.

    PRD §3.3: "Its `device_compat_score` reads 0.00, its `compatible_device_count`
    reads 0 and its `validation_reason_code` reads `NONE`, because nothing has been
    evaluated yet."

    PRD §3.3: "An engineer cloning an existing ladder may name the ancestor in
    `derived_from_ladder_id`, which is null for hand-authored ladders and which —
    together with `superseded_by_ladder_id`, null while the ladder is current —
    traverses the ladder lineage in both directions."

    PRD §3.4: "The ladder moves from `VALIDATED` to `LOCKED`, the title's
    `locked_ladder_count` is recomputed as the number of that title's ladders in
    `LOCKED`, and the title's `version` increments by one."

    Design: Corner/entities/ladder_computed_aggregates_derived_from_rungs
    """
    fx.create_device_profile(api)
    title = fx.create_title(api, external_ref="TTL-COMP-06", title_name="Computed Fields Cut")

    ladder = fx.create_ladder(
        api,
        title["id"],
        codec_family="H264",
        rungs=[dict(rung) for rung in RUNGS_THREE_PEAK_1080],
    )

    assert_score(ladder["device_compat_score"], 0.00, "device_compat_score")
    assert ladder["compatible_device_count"] == 0, ladder
    assert ladder["validation_reason_code"] == "NONE", ladder
    assert ladder["derived_from_ladder_id"] is None, ladder
    assert ladder["superseded_by_ladder_id"] is None, ladder

    stored_title = fx.read_title(api, title["id"])
    assert stored_title["locked_ladder_count"] == 0, stored_title


# ---------------------------------------------------------------------------
# A computed field supplied by the client is an unknown input (§2.6 rung 6)
# ---------------------------------------------------------------------------


def test_ladder_creation_carrying_rung_count_returns_invalid_request(api):
    """Supplying the derived `rung_count` on ladder creation answers 400 ERR_INVALID_REQUEST and stores no ladder.

    PRD §2: "Second, **derived values are never client-supplied**: readiness
    scores, health scores, compatibility scores, cost estimates, selected vendors
    and capacity ledgers are all computed from stored facts under pinned evaluation
    orders, and the API exposes them read-only."

    PRD §2.6: "**Rung 6 — payload schema.** Every required input is present; no
    unknown field is supplied; every value has the correct JSON type; every enum
    value is drawn from its declared set; every instant parses as ISO 8601 UTC;
    decimals sit within their declared scale; integers sit within their declared
    range; every `region_code` is two uppercase letters (or the single literal `*`
    where a rule explicitly allows a wildcard); `page` is at least 1 and
    `page_size` is between 1 and 100 inclusive."

    Design: Corner/entities/client_supplied_computed_field_returns_invalid_request
    """
    title = fx.create_title(api, external_ref="TTL-CF-07", title_name="Computed Input Cut")

    response = api.create_encoding_ladder(
        f.encoding_ladder_payload(
            title["id"], fx.title_version(api, title["id"]), rung_count=2
        ),
        ENCODING_ENGINEER,
    )
    validate_error(response, err.ERR_INVALID_REQUEST, 400)

    rows, meta = validate_paginated(
        api.list_encoding_ladders(ENCODING_ENGINEER, {"title_id": title["id"]})
    )
    assert meta["total_count"] == 0, meta
    assert rows == [], rows

    stored_title = fx.read_title(api, title["id"])
    assert stored_title["version"] == 1, stored_title


def test_title_creation_carrying_readiness_score_certified_returns_invalid_request(api):
    """Supplying the derived `readiness_score_certified` on title creation answers 400 ERR_INVALID_REQUEST and stores no title.

    PRD §2: "Second, **derived values are never client-supplied**: readiness
    scores, health scores, compatibility scores, cost estimates, selected vendors
    and capacity ledgers are all computed from stored facts under pinned evaluation
    orders, and the API exposes them read-only."

    PRD §2.6: "**Rung 6 — payload schema.** Every required input is present; no
    unknown field is supplied; every value has the correct JSON type; every enum
    value is drawn from its declared set; every instant parses as ISO 8601 UTC;
    decimals sit within their declared scale; integers sit within their declared
    range; every `region_code` is two uppercase letters (or the single literal `*`
    where a rule explicitly allows a wildcard); `page` is at least 1 and
    `page_size` is between 1 and 100 inclusive."

    Design: Corner/entities/client_supplied_computed_field_returns_invalid_request
    """
    response = api.create_title(
        f.title_payload(
            external_ref="TTL-CF-08",
            title_name="Computed Input Cut 2",
            readiness_score_certified=100.00,
        ),
        CONTENT_OPS,
    )
    validate_error(response, err.ERR_INVALID_REQUEST, 400)

    rows, meta = validate_paginated(api.list_titles(CONTENT_OPS))
    assert meta["total_count"] == 0, meta
    assert rows == [], rows


# ---------------------------------------------------------------------------
# Identity, timestamps and versioning are server business (§2.4)
# ---------------------------------------------------------------------------


def test_title_identity_fields_are_server_minted_at_version_one(api):
    """A freshly registered title carries a bare-UUID id, a three-fraction-digit created_at, an updated_at and version 1.

    PRD §2.4: "Every resource carries a server-minted `id`, which is a UUID string
    with no type prefix, and a `created_at` timestamp recording when the row was
    stored."

    PRD §2.4: "Most resources additionally carry `updated_at`, refreshed on every
    successful mutation, and `version`, an integer that starts at 1 on creation and
    increments by one on each mutation of that row."

    Design: Corner/entities/title_system_fields_minted_and_versioned_by_server
    """
    response = api.create_title(
        f.title_payload(external_ref="TTL-SYS-09", title_name="System Fields Cut"), CONTENT_OPS
    )
    title = validate_success(response, 201)

    assert_versioned_resource(title, "Title")
    assert title["version"] == 1, title
    assert "titles/" not in title["id"], title
    assert ":" not in title["id"], title
    assert_instant_equals(title["created_at"], INITIAL_CLOCK, "Title.created_at")


def test_renaming_a_title_bumps_the_version_and_preserves_created_at(api):
    """A single PATCH takes the title's version from 1 to 2, keeps its id and created_at, and stores the new name.

    PRD §3.1: "`ContentOps` may later edit `title_name`, `studio_code` and
    `encode_budget_usd`; every successful edit increments the title's `version` and
    refreshes its `updated_at`, which is precisely what invalidates a previously
    captured `expected_title_version`."

    PRD §2.4: "Most resources additionally carry `updated_at`, refreshed on every
    successful mutation, and `version`, an integer that starts at 1 on creation and
    increments by one on each mutation of that row."

    Design: Corner/entities/title_system_fields_minted_and_versioned_by_server
    """
    created = fx.create_title(
        api, external_ref="TTL-SYS-09", title_name="System Fields Cut"
    )
    assert created["version"] == 1, created

    response = api.patch_title(
        created["id"],
        f.title_patch_payload(title_name="System Fields Cut (Renamed)"),
        CONTENT_OPS,
    )
    patched = validate_success(response, 200)

    assert patched["id"] == created["id"], patched
    assert patched["version"] == 2, patched
    assert patched["title_name"] == "System Fields Cut (Renamed)", patched
    assert_instant_equals(patched["created_at"], created["created_at"], "Title.created_at")

    stored = fx.read_title(api, created["id"])
    assert stored["version"] == 2, stored
    assert stored["title_name"] == "System Fields Cut (Renamed)", stored
    assert_instant_equals(stored["created_at"], created["created_at"], "Title.created_at")


# ---------------------------------------------------------------------------
# Declared type and enum constraints are enforced, not merely documented (§2.6)
# ---------------------------------------------------------------------------


def test_title_with_a_content_type_outside_the_declared_set_is_rejected(api):
    """`content_type` SHORT_FILM is not a declared member, so creation answers 400 ERR_INVALID_REQUEST.

    PRD §3.1: "Alongside it come the human-readable `title_name` of 1 to 200
    characters, the `content_type`, which is one of `MOVIE`, `EPISODE` or
    `LIVE_EVENT` and which alone decides whether live capacity may ever be reserved
    against this title, and the owning `studio_code` of 2 to 10 uppercase
    characters, which is carried for reporting and influences nothing else."

    PRD §2.6: "**Rung 6 — payload schema.** Every required input is present; no
    unknown field is supplied; every value has the correct JSON type; every enum
    value is drawn from its declared set; every instant parses as ISO 8601 UTC;
    decimals sit within their declared scale; integers sit within their declared
    range; every `region_code` is two uppercase letters (or the single literal `*`
    where a rule explicitly allows a wildcard); `page` is at least 1 and
    `page_size` is between 1 and 100 inclusive."

    Design: Corner/entities/type_constraint_violations_rejected
    """
    response = api.create_title(
        f.title_payload(
            external_ref="TTL-TYPE-11", title_name="Bad Content Type", content_type="SHORT_FILM"
        ),
        CONTENT_OPS,
    )
    validate_error(response, err.ERR_INVALID_REQUEST, 400)

    rows, meta = validate_paginated(api.list_titles(CONTENT_OPS))
    assert meta["total_count"] == 0, meta
    assert rows == [], rows


def test_ladder_with_a_codec_family_outside_the_declared_set_is_rejected(api):
    """`codec_family` VP9 is not a declared member, so ladder authoring answers 400 ERR_INVALID_REQUEST.

    PRD §3.3: "An `EncodingEngineer` authors an **encoding ladder** for a title by
    supplying the payload's `title_id`, the `codec_family` every rung of the ladder
    will use — one of `H264`, `HEVC` or `AV1` — and the `rungs` array itself,
    together with the mandatory `expected_title_version` described in §2.7."

    PRD §2.6: "**Rung 6 — payload schema.** Every required input is present; no
    unknown field is supplied; every value has the correct JSON type; every enum
    value is drawn from its declared set; every instant parses as ISO 8601 UTC;
    decimals sit within their declared scale; integers sit within their declared
    range; every `region_code` is two uppercase letters (or the single literal `*`
    where a rule explicitly allows a wildcard); `page` is at least 1 and
    `page_size` is between 1 and 100 inclusive."

    Design: Corner/entities/type_constraint_violations_rejected
    """
    title = fx.create_title(api, external_ref="TTL-TYPE-10", title_name="Type Constraint Cut")

    response = api.create_encoding_ladder(
        f.encoding_ladder_payload(
            title["id"], fx.title_version(api, title["id"]), codec_family="VP9"
        ),
        ENCODING_ENGINEER,
    )
    validate_error(response, err.ERR_INVALID_REQUEST, 400)

    rows, meta = validate_paginated(
        api.list_encoding_ladders(ENCODING_ENGINEER, {"title_id": title["id"]})
    )
    assert meta["total_count"] == 0, meta
    assert rows == [], rows


def test_window_with_a_lowercase_three_letter_region_code_is_rejected(api):
    """A `region_code` of "usa" is not two uppercase letters, so scheduling answers 400 ERR_INVALID_REQUEST and the title stays DRAFT.

    PRD §3.6: "Each window names the `region_code` it licenses as two uppercase
    letters, the half-open interval `window_start_at` inclusive to `window_end_at`
    exclusive, and the `license_tier`, which is the lowest subscriber tier licensed
    in that window and is one of `BASIC`, `STANDARD` or `PREMIUM`."

    PRD §3.6: "Scheduling the **first** window of a title that is still in `DRAFT`
    also advances the title's `availability_state` from `DRAFT` to `SCHEDULED` and
    increments the title's `version` by one; windows added while the title is
    already `SCHEDULED`, `PUBLISHED` or `TAKEN_DOWN` leave `availability_state`
    exactly as it was."

    Design: Corner/entities/type_constraint_violations_rejected
    """
    title = fx.create_title(api, external_ref="TTL-TYPE-10", title_name="Type Constraint Cut")

    response = api.create_availability_window(
        title["id"],
        f.availability_window_payload(
            region_code="usa",
            window_start_at="2026-09-01T00:00:00Z",
            window_end_at="2026-10-01T00:00:00Z",
        ),
        CONTENT_OPS,
    )
    validate_error(response, err.ERR_INVALID_REQUEST, 400)

    stored_title = fx.read_title(api, title["id"])
    assert stored_title["availability_state"] == "DRAFT", stored_title
    assert stored_title["version"] == 1, stored_title


def test_listing_titles_with_a_page_size_above_one_hundred_is_rejected(api):
    """A `page_size` of 101 is rejected rather than clamped, answering 400 ERR_INVALID_REQUEST.

    PRD §2.3: "A `page` below 1, or a `page_size` below 1 or above 100, is a
    payload violation and is rejected with `ERR_INVALID_REQUEST` (HTTP 400) rather
    than being silently clamped."

    Design: Corner/entities/type_constraint_violations_rejected
    """
    fx.create_title(api, external_ref="TTL-TYPE-10", title_name="Type Constraint Cut")

    response = api.list_titles(CONTENT_OPS, f.page_params(page=1, page_size=101))
    validate_error(response, err.ERR_INVALID_REQUEST, 400)


# ---------------------------------------------------------------------------
# Entitlement rules are immutable rows, ranked not amended (§3.5, §2.4)
# ---------------------------------------------------------------------------


def _package_with_two_rules(api):
    """Attach a priority-20 and a priority-90 rule to one PENDING package."""
    title = fx.create_title(api, external_ref="TTL-IMM-12", title_name="Immutable Rule Cut")
    ladder = fx.create_ladder(api, title["id"], codec_family="H264")
    package = fx.create_package(api, title["id"], ladder["id"])

    low = fx.add_entitlement_rule(
        api,
        package["id"],
        subscription_tier="BASIC",
        max_concurrent_streams=1,
        max_playback_height_px=480,
        priority=20,
    )
    high = fx.add_entitlement_rule(
        api,
        package["id"],
        subscription_tier="PREMIUM",
        max_concurrent_streams=4,
        max_playback_height_px=720,
        priority=90,
    )
    return package, low, high


def test_package_rules_are_listed_highest_priority_first(api):
    """Two rules at priority 20 and 90 come back 90 first, and the package counts both.

    PRD §3.5: "A package's rules can be listed with an optional `region_code`
    filter, returned by `priority` descending and then oldest first, which is
    exactly the ranking the selector applies after filtering."

    PRD §3.5: "A successful attachment increments the package's
    `entitlement_rule_count` by one."

    Design: Corner/entities/entitlement_rule_is_immutable_with_no_version_field
    """
    package, low, high = _package_with_two_rules(api)

    rows, meta = validate_paginated(api.list_entitlement_rules(package["id"], DRM_OPERATOR))
    assert meta["total_count"] == 2, meta
    assert_list_ids(rows, [high["id"], low["id"]])
    assert rows[0]["priority"] == 90, rows
    assert rows[1]["priority"] == 20, rows

    stored_package = fx.read_package(api, package["id"])
    assert stored_package["entitlement_rule_count"] == 2, stored_package


def test_entitlement_rules_carry_no_version_and_no_updated_at(api):
    """Every listed rule exposes id and created_at and neither version nor updated_at.

    PRD §3.5: "Rules are immutable — they carry no `updated_at` and no `version`,
    are never edited and are never deleted, and a superseding policy is expressed by
    attaching a higher-`priority` rule."

    PRD §2.4: "Three resources are deliberately immutable and therefore carry only
    `id` and `created_at`, with **no** `updated_at` and **no** `version` field at
    all: the `QualityControlReport` produced by a QC run, the `EntitlementRule`
    attached to a DRM package, and the `PlaybackMetricWindow` ingested from the
    delivery pipeline."

    Design: Corner/entities/entitlement_rule_is_immutable_with_no_version_field
    """
    package, low, high = _package_with_two_rules(api)

    assert_immutable_resource(low, "EntitlementRule")
    assert_immutable_resource(high, "EntitlementRule")

    rows, _ = validate_paginated(api.list_entitlement_rules(package["id"], DRM_OPERATOR))
    for row in rows:
        assert_immutable_resource(row, "EntitlementRule")


# ---------------------------------------------------------------------------
# QC reports and metric windows are write-once event records (§2.4)
# ---------------------------------------------------------------------------


def test_qc_report_is_a_write_once_attempt_record(api):
    """The first QC run of a clean master records attempt 1 with verdict PASS, stamps evaluated_at from the clock, and carries neither version nor updated_at.

    PRD §3.2: "A run is permitted only while `qc_attempt_count` is below 3, and
    each run produces an immutable **quality control report** whose `asset_id` names
    the master it scores and whose `attempt_number` is the master's
    `qc_attempt_count` incremented by one, so the first run records attempt 1."

    PRD §3.2: "The report also records the `evaluated_at` instant taken from the
    logical clock."

    PRD §3.2: "Everything else yields `PASS`."

    PRD §2.4: "Three resources are deliberately immutable and therefore carry only
    `id` and `created_at`, with **no** `updated_at` and **no** `version` field at
    all: the `QualityControlReport` produced by a QC run, the `EntitlementRule`
    attached to a DRM package, and the `PlaybackMetricWindow` ingested from the
    delivery pipeline."

    Design: Corner/entities/immutable_event_entities_carry_no_version_field
    """
    title = fx.create_title(api, external_ref="TTL-EVT-13", title_name="Event Entity Cut")
    asset = fx.create_asset(api, title["id"], source_uri="s3://mez/evt-13.mxf")

    report = validate_success(api.run_qc(asset["id"], QC_ANALYST), 201)

    assert report["asset_id"] == asset["id"], report
    assert report["attempt_number"] == 1, report
    assert report["verdict"] == "PASS", report
    assert_instant_equals(report["evaluated_at"], INITIAL_CLOCK, "QualityControlReport.evaluated_at")
    assert_immutable_resource(report, "QualityControlReport")

    rows, meta = validate_paginated(api.list_qc_reports(asset["id"], QC_ANALYST))
    assert meta["total_count"] == 1, meta
    assert_list_ids(rows, [report["id"]])
    assert rows[0]["attempt_number"] == 1, rows
    assert rows[0]["verdict"] == "PASS", rows
    assert_immutable_resource(rows[0], "QualityControlReport")


def test_playback_metric_window_is_a_write_once_measurement(api):
    """A 2% rebuffer window on a 1.00-normalisation profile reads quality_index 95.00 and carries neither version nor updated_at.

    PRD §3.7: "A raw penalty is then assembled from three terms and rounded half up
    to four decimals: the `rebuffer_ratio` multiplied by 100 and then by a weight of
    2.5; plus the greater of zero and the `startup_ms_p95` reduced by the target of
    2000 milliseconds, divided by 100.0 and multiplied by a weight of 1.5; plus the
    `error_rate` multiplied by 100 and then by a weight of 4.0."

    PRD §3.7: "Finally the `quality_index` is 100.00 reduced by that penalty,
    clamped into the range 0.00 to 100.00, and rounded half up to two decimals, and
    the `breach_flag` is true exactly when `quality_index` is strictly below 70.00; a
    `quality_index` of exactly 70.00 is not a breach while 69.99 is."

    PRD §2.4: "Three resources are deliberately immutable and therefore carry only
    `id` and `created_at`, with **no** `updated_at` and **no** `version` field at
    all: the `QualityControlReport` produced by a QC run, the `EntitlementRule`
    attached to a DRM package, and the `PlaybackMetricWindow` ingested from the
    delivery pipeline."

    Design: Corner/entities/immutable_event_entities_carry_no_version_field
    """
    profile = fx.create_tv_4k_profile(api)
    vendor = fx.create_vendor(api, vendor_code="ALPHA")
    title = fx.create_title(api, external_ref="TTL-EVT-13", title_name="Event Entity Cut")

    response = api.create_playback_metric(
        f.playback_metric_payload(
            title["id"],
            profile["id"],
            vendor["id"],
            window_start_at="2026-07-30T00:00:00Z",
            window_end_at="2026-07-31T00:00:00Z",
            play_attempts=1000,
            rebuffer_events=20,
            startup_ms_p95=2000,
            error_count=0,
        ),
        DELIVERY_ENGINEER,
    )
    window = validate_success(response, 201)

    assert_score(window["quality_index"], 95.00, "quality_index")
    assert_immutable_resource(window, "PlaybackMetricWindow")

    stored = validate_success(api.get_playback_metric(window["id"], DELIVERY_ENGINEER), 200)
    assert_score(stored["quality_index"], 95.00, "quality_index")
    assert_immutable_resource(stored, "PlaybackMetricWindow")


# ---------------------------------------------------------------------------
# The self-referential lineage link is traversable in both directions (§3.3)
# ---------------------------------------------------------------------------


def _title_with_a_ladder_and_its_clone(api):
    """Author L1 by hand, then clone it into L2 via `derived_from_ladder_id`."""
    title = fx.create_title(api, external_ref="TTL-LIN-14", title_name="Lineage Cut")
    first = fx.create_ladder(api, title["id"], codec_family="H264")
    second = fx.create_ladder(
        api, title["id"], codec_family="HEVC", derived_from_ladder_id=first["id"]
    )
    return title, first, second


def test_filtering_ladders_by_derived_from_ladder_id_returns_only_the_clone(api):
    """Filtering on the ancestor's id returns exactly the clone, whose lineage link names the ancestor while the ancestor's own link is null.

    PRD §3.3: "An engineer cloning an existing ladder may name the ancestor in
    `derived_from_ladder_id`, which is null for hand-authored ladders and which —
    together with `superseded_by_ladder_id`, null while the ladder is current —
    traverses the ladder lineage in both directions."

    PRD §3.3: "Ladders may be listed filtered by `title_id`, by `codec_family`, by
    `state`, and by either lineage link, `derived_from_ladder_id` or
    `superseded_by_ladder_id`, with `page` and `page_size`."

    Design: Corner/entities/ladder_lineage_reachable_by_self_referential_filter
    """
    _title, first, second = _title_with_a_ladder_and_its_clone(api)

    assert first["derived_from_ladder_id"] is None, first
    assert second["derived_from_ladder_id"] == first["id"], second

    rows, meta = validate_paginated(
        api.list_encoding_ladders(ENCODING_ENGINEER, {"derived_from_ladder_id": first["id"]})
    )
    assert meta["total_count"] == 1, meta
    assert_list_ids(rows, [second["id"]])
    assert rows[0]["derived_from_ladder_id"] == first["id"], rows


def test_filtering_ladders_by_title_id_returns_both_oldest_first(api):
    """Both of the title's ladders come back created_at ascending, ancestor before clone, and authoring the first one took the title to version 2.

    PRD §2.3: "Unless a specific endpoint says otherwise, list results are ordered
    by `created_at` ascending."

    PRD §3.3: "Authoring it increments the parent title's `version` by one,
    re-derives the title's `packaging_state`, and recomputes both readiness
    variants."

    Design: Corner/entities/ladder_lineage_reachable_by_self_referential_filter
    """
    title = fx.create_title(api, external_ref="TTL-LIN-14", title_name="Lineage Cut")
    assert fx.title_version(api, title["id"]) == 1, "a fresh title starts at version 1"

    first = fx.create_ladder(api, title["id"], codec_family="H264")
    assert fx.title_version(api, title["id"]) == 2, "authoring a ladder bumps Title.version"

    second = fx.create_ladder(
        api, title["id"], codec_family="HEVC", derived_from_ladder_id=first["id"]
    )

    rows, meta = validate_paginated(
        api.list_encoding_ladders(ENCODING_ENGINEER, {"title_id": title["id"]})
    )
    assert meta["total_count"] == 2, meta
    assert_list_ids(rows, [first["id"], second["id"]])


# ---------------------------------------------------------------------------
# The device matrix is inspectable by state before anything is validated (§3.3)
# ---------------------------------------------------------------------------


def _active_and_retired_profiles(api):
    """One ACTIVE MOBILE_HIGH profile and one RETIRED SET_TOP_LEGACY profile."""
    active = fx.create_device_profile(api)
    retired = fx.create_device_profile(
        api,
        device_class="SET_TOP_LEGACY",
        max_height_px=720,
        supported_codecs=["H264"],
        min_bitrate_kbps=500,
        max_bitrate_kbps=3000,
        hdcp_required=False,
        required_drm_system="NONE",
        market_share_pct=25.00,
        quality_normalization_factor=0.75,
        state="RETIRED",
    )
    return active, retired


def test_device_profile_listing_filtered_by_state_returns_only_the_retired_one(api):
    """Filtering the matrix on RETIRED returns exactly the retired profile.

    PRD §3.3: "A profile's `state` is either `ACTIVE` or `RETIRED` and may be set at
    registration, defaulting to `ACTIVE`."

    PRD §3.3: "The profile list can be filtered by `state` and by `device_class`,
    with `page` and `page_size`, so an operator can confirm exactly which profiles
    the matrix will consider before validating anything."

    Design: Corner/entities/device_profile_listing_filtered_by_state
    """
    _active, retired = _active_and_retired_profiles(api)
    assert retired["state"] == "RETIRED", retired

    rows, meta = validate_paginated(
        api.list_device_profiles(PLATFORM_ADMIN, {"state": "RETIRED"})
    )
    assert meta["total_count"] == 1, meta
    assert_list_ids(rows, [retired["id"]])
    assert rows[0]["state"] == "RETIRED", rows


def test_device_profile_listing_filtered_by_state_returns_only_the_active_one(api):
    """Filtering the matrix on ACTIVE returns exactly the profile registered without a state.

    PRD §3.3: "A profile's `state` is either `ACTIVE` or `RETIRED` and may be set at
    registration, defaulting to `ACTIVE`."

    PRD §3.3: "The profile list can be filtered by `state` and by `device_class`,
    with `page` and `page_size`, so an operator can confirm exactly which profiles
    the matrix will consider before validating anything."

    Design: Corner/entities/device_profile_listing_filtered_by_state
    """
    active, _retired = _active_and_retired_profiles(api)
    assert active["state"] == "ACTIVE", active

    rows, meta = validate_paginated(
        api.list_device_profiles(ENCODING_ENGINEER, {"state": "ACTIVE"})
    )
    assert meta["total_count"] == 1, meta
    assert_list_ids(rows, [active["id"]])
    assert rows[0]["state"] == "ACTIVE", rows
