"""The §5 error catalogue: one identifier and one HTTP status per failure.

PRD §5 pins exactly one `data.error_id` and exactly one HTTP status to every
failure in this system, and PRD §2.6 decides which identifier a request that
violates several rules at once reports.  Every test in this module drives one
deliberate rejection through the public API and asserts three things together:
the §2.2 error envelope shape, the exact `error_id` of §5, and the exact HTTP
status §5 assigns that identifier.  Each test starts from an empty database with
the logical clock at its startup default `2026-08-01T00:00:00Z` (§2.5).
"""

from prd_bench_local_runner.testing import validate_error, validate_success
from test_helpers import api_errors as err
from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.assertions import (
    assert_envelope,
    assert_instant_equals,
    assert_money,
    assert_ratio_4dp,
    assert_score,
    assert_list_ids,
    validate_paginated,
    validate_unpaginated,
)
from test_helpers.constants import INITIAL_CLOCK, UUID_ABSENT
from test_helpers.test_users import (
    CONTENT_OPS,
    DELIVERY_ENGINEER,
    DRM_OPERATOR,
    ENCODING_ENGINEER,
    PLATFORM_ADMIN,
)


# ---------------------------------------------------------------------------
# Per-family 404 identifiers on a path parameter (§2.4, §2.6 rung 7)
# ---------------------------------------------------------------------------


def test_unknown_path_id_returns_the_addressed_familys_own_not_found(api):
    """Eight path-addressed reads answer a never-minted UUID with eight different 404 identifiers, not one generic not-found.

    PRD §2.4: "Each entity family has its own 404 identifier:
    `ERR_TITLE_NOT_FOUND`, `ERR_ASSET_NOT_FOUND`, `ERR_LADDER_NOT_FOUND`,
    `ERR_PACKAGE_NOT_FOUND`, `ERR_DEVICE_PROFILE_NOT_FOUND`,
    `ERR_VENDOR_NOT_FOUND`, `ERR_POLICY_NOT_FOUND`,
    `ERR_RESERVATION_NOT_FOUND`, `ERR_WINDOW_NOT_FOUND`, `ERR_JOB_NOT_FOUND` and
    `ERR_METRIC_WINDOW_NOT_FOUND`."

    PRD §2.6: "Every identifier in the URL path resolves to a stored row, checked
    left to right, returning that family's 404 identifier from §2.4."

    Design: Corner/errors/unknown_path_id_returns_not_found_for_every_entity_family
    """
    cases = [
        ("MezzanineAsset", lambda: api.get_mezzanine_asset(UUID_ABSENT, CONTENT_OPS)),
        ("EncodingLadder", lambda: api.get_encoding_ladder(UUID_ABSENT, ENCODING_ENGINEER)),
        ("DrmPackage", lambda: api.get_drm_package(UUID_ABSENT, DRM_OPERATOR)),
        ("CdnVendor", lambda: api.get_cdn_vendor(UUID_ABSENT, PLATFORM_ADMIN)),
        ("RoutingPolicy", lambda: api.get_routing_policy(UUID_ABSENT, DELIVERY_ENGINEER)),
        (
            "LiveEventReservation",
            lambda: api.get_live_reservation(UUID_ABSENT, DELIVERY_ENGINEER),
        ),
        ("ReprocessJob", lambda: api.get_reprocess_job(UUID_ABSENT, ENCODING_ENGINEER)),
        (
            "PlaybackMetricWindow",
            lambda: api.get_playback_metric(UUID_ABSENT, DELIVERY_ENGINEER),
        ),
    ]

    for family, call in cases:
        response = call()
        assert_envelope(response, "error")
        error = validate_error(response, err.NOT_FOUND_BY_FAMILY[family], 404)
        assert error["error_id"] == err.NOT_FOUND_BY_FAMILY[family], (family, error)
        assert error["message"].strip(), (family, error)


def test_cancelling_an_unknown_window_returns_window_not_found(api):
    """A licensing window's only path-addressed action answers a never-minted UUID with ERR_WINDOW_NOT_FOUND at 404.

    PRD §2.6: "Every identifier in the URL path resolves to a stored row, checked
    left to right, returning that family's 404 identifier from §2.4."

    PRD §2.2: "The `error_id` is a unique, machine-readable string that identifies
    the specific error."

    Design: Corner/errors/unknown_path_id_returns_not_found_for_every_entity_family
    """
    response = api.cancel_availability_window(UUID_ABSENT, CONTENT_OPS)

    assert_envelope(response, "error")
    error = validate_error(response, err.ERR_WINDOW_NOT_FOUND, 404)
    assert error["error_id"] == err.NOT_FOUND_BY_FAMILY["AvailabilityWindow"], error


# ---------------------------------------------------------------------------
# Body foreign keys report the specific missing parent (§2.4, §2.6 rung 8)
# ---------------------------------------------------------------------------


def test_asset_registration_naming_an_unstored_title_returns_title_not_found(api):
    """POST /mezzanine-assets whose `title_id` names nothing stored answers ERR_TITLE_NOT_FOUND at 404 and persists no master.

    PRD §2.6: "Every foreign key in the request body or query string resolves,
    checked in the order the endpoint declares its inputs, returning
    `ERR_TITLE_NOT_FOUND`, `ERR_LADDER_NOT_FOUND`, `ERR_VENDOR_NOT_FOUND`,
    `ERR_DEVICE_PROFILE_NOT_FOUND` or `ERR_PACKAGE_NOT_FOUND` as appropriate."

    Design: Corner/errors/unknown_body_foreign_key_returns_not_found_naming_the_missing_parent
    """
    title = fx.create_title(
        api, external_ref="TTL-BODY-FK", title_name="Body FK Cut", studio_code="NOVAPIC"
    )

    response = api.create_mezzanine_asset(
        f.mezzanine_asset_payload(
            UUID_ABSENT,
            source_uri="s3://mez/ghost.mxf",
            duration_seconds=600,
            frame_rate=24.0,
            peak_audio_lufs=-24.0,
            artifact_defect_count=0,
            audio_language="en",
            caption_languages=None,
        ),
        CONTENT_OPS,
    )

    assert_envelope(response, "error")
    validate_error(response, err.ERR_TITLE_NOT_FOUND, 404)

    rows, meta = validate_paginated(api.list_title_mezzanine_assets(title["id"], CONTENT_OPS))
    assert meta["total_count"] == 0, meta
    assert rows == [], rows


def test_metric_ingest_naming_an_unstored_device_profile_returns_device_profile_not_found(api):
    """A metric ingest whose only bad foreign key is `device_profile_id` answers ERR_DEVICE_PROFILE_NOT_FOUND at 404 and leaves the vendor's health untouched.

    PRD §2.4: "`ERR_METRIC_WINDOW_NOT_FOUND` arises only when reading a single
    playback metric window by its path identifier, and
    `ERR_DEVICE_PROFILE_NOT_FOUND` covers both an unresolvable
    `device_profile_id` and a playback entitlement check naming a `device_class`
    for which no `ACTIVE` device profile exists."

    PRD §3.7: "A new vendor's `state` is `ACTIVE`, its `reserved_gbps` is 0.00,
    its `breach_window_count` is 0, and **both** health figures —
    `health_score_rolling` and `health_score_contract` — are seeded at 100.00,
    which is the value the health calculation yields when no measurement rows
    exist yet."

    Design: Corner/errors/unknown_body_foreign_key_returns_not_found_naming_the_missing_parent
    """
    title = fx.create_title(
        api, external_ref="TTL-BODY-FK", title_name="Body FK Cut", studio_code="NOVAPIC"
    )
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
    vendor = fx.create_vendor(
        api, vendor_code="FKCDN", regions=["US"], committed_gbps=50.00, cost_per_gb_usd=0.0200
    )

    response = api.create_playback_metric(
        f.playback_metric_payload(
            title["id"],
            UUID_ABSENT,
            vendor["id"],
            region_code="US",
            window_start_at="2026-07-01T00:00:00Z",
            window_end_at="2026-07-01T01:00:00Z",
            play_attempts=100,
            rebuffer_events=1,
            startup_ms_p95=1500,
            error_count=0,
        ),
        DELIVERY_ENGINEER,
    )

    assert_envelope(response, "error")
    validate_error(response, err.ERR_DEVICE_PROFILE_NOT_FOUND, 404)

    rows, meta = validate_paginated(
        api.list_playback_metrics(DELIVERY_ENGINEER, {"vendor_id": vendor["id"]})
    )
    assert meta["total_count"] == 0, meta
    assert rows == [], rows

    stored = fx.read_vendor(api, vendor["id"])
    assert_score(stored["health_score_rolling"], 100.00, "health_score_rolling")
    assert stored["breach_window_count"] == 0, stored


def test_metric_ingest_naming_an_unstored_vendor_returns_vendor_not_found(api):
    """A metric ingest whose only bad foreign key is `vendor_id` answers ERR_VENDOR_NOT_FOUND at 404 and persists no measurement window.

    PRD §2.6: "Every foreign key in the request body or query string resolves,
    checked in the order the endpoint declares its inputs, returning
    `ERR_TITLE_NOT_FOUND`, `ERR_LADDER_NOT_FOUND`, `ERR_VENDOR_NOT_FOUND`,
    `ERR_DEVICE_PROFILE_NOT_FOUND` or `ERR_PACKAGE_NOT_FOUND` as appropriate."

    Design: Corner/errors/unknown_body_foreign_key_returns_not_found_naming_the_missing_parent
    """
    title = fx.create_title(
        api, external_ref="TTL-BODY-FK", title_name="Body FK Cut", studio_code="NOVAPIC"
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
        quality_normalization_factor=0.90,
    )
    fx.create_vendor(
        api, vendor_code="FKCDN", regions=["US"], committed_gbps=50.00, cost_per_gb_usd=0.0200
    )

    response = api.create_playback_metric(
        f.playback_metric_payload(
            title["id"],
            profile["id"],
            UUID_ABSENT,
            region_code="US",
            window_start_at="2026-07-01T00:00:00Z",
            window_end_at="2026-07-01T01:00:00Z",
            play_attempts=100,
            rebuffer_events=1,
            startup_ms_p95=1500,
            error_count=0,
        ),
        DELIVERY_ENGINEER,
    )

    assert_envelope(response, "error")
    validate_error(response, err.ERR_VENDOR_NOT_FOUND, 404)

    rows, meta = validate_paginated(
        api.list_playback_metrics(DELIVERY_ENGINEER, {"title_id": title["id"]})
    )
    assert meta["total_count"] == 0, meta
    assert rows == [], rows


# ---------------------------------------------------------------------------
# Natural-key uniqueness: three distinct 409 identifiers (§2.6 rung 9)
# ---------------------------------------------------------------------------


def test_repeating_a_titles_external_ref_returns_duplicate_external_ref(api):
    """A second title carrying an already-registered `external_ref` answers ERR_DUPLICATE_EXTERNAL_REF at 409 and leaves exactly one title stored.

    PRD §3.1: "A `ContentOps` operator registers a **title** by supplying its
    `external_ref`, the studio-side catalog reference, which must be 1 to 40
    characters of uppercase letters, digits and hyphens and must be unique across
    every title ever registered — a repeat is refused with
    `ERR_DUPLICATE_EXTERNAL_REF`."

    PRD §2.6: "A `Title`'s `external_ref`, a `CdnVendor`'s `vendor_code` and a
    `DeviceProfile`'s `device_class` are each unique across all stored rows,
    compared case-sensitively, failing with `ERR_DUPLICATE_EXTERNAL_REF`,
    `ERR_DUPLICATE_VENDOR_CODE` or `ERR_DUPLICATE_DEVICE_CLASS` (all 409)."

    Design: Corner/errors/duplicate_natural_keys_are_rejected_including_a_retired_device_class
    """
    fx.create_title(
        api,
        external_ref="TTL-UNIQUE-01",
        title_name="Unique Cut",
        content_type="MOVIE",
        studio_code="NOVAPIC",
    )

    response = api.create_title(
        f.title_payload(
            external_ref="TTL-UNIQUE-01",
            title_name="Unique Cut Again",
            content_type="EPISODE",
            studio_code="LUMEN",
        ),
        CONTENT_OPS,
    )

    assert_envelope(response, "error")
    validate_error(response, err.ERR_DUPLICATE_EXTERNAL_REF, 409)

    rows, meta = validate_paginated(
        api.list_titles(CONTENT_OPS, {"external_ref": "TTL-UNIQUE-01"})
    )
    assert meta["total_count"] == 1, meta
    assert rows[0]["title_name"] == "Unique Cut", rows[0]
    assert rows[0]["content_type"] == "MOVIE", rows[0]


def test_repeating_a_vendor_code_returns_duplicate_vendor_code(api):
    """A second CDN vendor carrying an already-registered `vendor_code` answers ERR_DUPLICATE_VENDOR_CODE at 409 and leaves the stored vendor's terms untouched.

    PRD §3.7: "A `PlatformAdmin` registers each delivery partner as a **CDN
    vendor**, supplying the unique `vendor_code` of 2 to 16 uppercase characters —
    a repeat is `ERR_DUPLICATE_VENDOR_CODE` — plus `regions`, an array of 1 to 20
    distinct two-uppercase-letter region codes the vendor serves; `committed_gbps`,
    the contracted egress ceiling in Gbps, strictly greater than zero at two
    decimals; and `cost_per_gb_usd`, the egress unit price, strictly greater than
    zero at four decimals."

    Design: Corner/errors/duplicate_natural_keys_are_rejected_including_a_retired_device_class
    """
    vendor = fx.create_vendor(
        api, vendor_code="UNIQCDN", regions=["US"], committed_gbps=50.00, cost_per_gb_usd=0.0200
    )

    response = api.create_cdn_vendor(
        f.cdn_vendor_payload(
            vendor_code="UNIQCDN", regions=["CA"], committed_gbps=10.00, cost_per_gb_usd=0.0500
        ),
        PLATFORM_ADMIN,
    )

    assert_envelope(response, "error")
    validate_error(response, err.ERR_DUPLICATE_VENDOR_CODE, 409)

    stored = fx.read_vendor(api, vendor["id"])
    assert stored["vendor_code"] == "UNIQCDN", stored
    assert stored["regions"] == ["US"], stored
    assert_money(stored["committed_gbps"], 50.00, "committed_gbps")
    assert_ratio_4dp(stored["cost_per_gb_usd"], 0.0200, "cost_per_gb_usd")
    assert stored["version"] == 1, stored


def test_a_retired_device_class_still_blocks_a_new_profile_for_that_class(api):
    """Registering `SET_TOP_LEGACY` while a RETIRED profile already holds that class answers ERR_DUPLICATE_DEVICE_CLASS at 409.

    PRD §3.3: "A **device profile** describes one playback family through its
    `device_class`, which is one of `SMART_TV_4K`, `SMART_TV_HD`, `MOBILE_HIGH`,
    `MOBILE_LOW`, `SET_TOP_LEGACY` or `BROWSER_HTML5` and which must be unique
    across all profiles — a repeat is `ERR_DUPLICATE_DEVICE_CLASS`, and that
    uniqueness includes profiles that have been retired."

    Design: Corner/errors/duplicate_natural_keys_are_rejected_including_a_retired_device_class
    """
    retired = fx.create_device_profile(
        api,
        device_class="SET_TOP_LEGACY",
        max_height_px=720,
        supported_codecs=["H264"],
        min_bitrate_kbps=300,
        max_bitrate_kbps=4000,
        hdcp_required=False,
        required_drm_system="NONE",
        market_share_pct=5.00,
        quality_normalization_factor=0.70,
        state="RETIRED",
    )
    assert retired["state"] == "RETIRED", retired

    response = api.create_device_profile(
        f.device_profile_payload(
            device_class="SET_TOP_LEGACY",
            max_height_px=1080,
            supported_codecs=["H264", "HEVC"],
            min_bitrate_kbps=500,
            max_bitrate_kbps=9000,
            hdcp_required=True,
            required_drm_system="WIDEVINE",
            market_share_pct=8.00,
            quality_normalization_factor=0.80,
        ),
        PLATFORM_ADMIN,
    )

    assert_envelope(response, "error")
    validate_error(response, err.ERR_DUPLICATE_DEVICE_CLASS, 409)

    rows, meta = validate_paginated(
        api.list_device_profiles(PLATFORM_ADMIN, {"device_class": "SET_TOP_LEGACY"})
    )
    assert meta["total_count"] == 1, meta
    assert_list_ids(rows, [retired["id"]])
    assert rows[0]["state"] == "RETIRED", rows[0]


# ---------------------------------------------------------------------------
# Interval placement and the sticky legal block (§2.6 rungs 11 and 15, §3.6)
# ---------------------------------------------------------------------------


def test_a_zero_length_licensing_interval_returns_window_bounds_invalid(api):
    """A window whose start equals its end answers ERR_WINDOW_BOUNDS_INVALID at 422 and stores nothing.

    PRD §3.6: "The interval must be well-formed, with `window_start_at` strictly
    before `window_end_at`, otherwise `ERR_WINDOW_BOUNDS_INVALID`; it must not begin
    in the past, meaning `window_start_at` is at or after the current logical clock,
    otherwise `ERR_WINDOW_IN_PAST`; and it must not overlap any `SCHEDULED` or
    `ACTIVE` window of the same title and the same region under the half-open
    comparison of §2.10, otherwise `ERR_WINDOW_OVERLAP`."

    Design: Corner/errors/window_bounds_past_start_and_legal_takedown_are_rejected
    """
    title = fx.create_title(
        api, external_ref="TTL-WINBOUND", title_name="Bounds Cut", studio_code="NOVAPIC"
    )

    response = api.create_availability_window(
        title["id"],
        f.availability_window_payload(
            region_code="US",
            window_start_at="2026-08-15T00:00:00Z",
            window_end_at="2026-08-15T00:00:00Z",
        ),
        CONTENT_OPS,
    )

    assert_envelope(response, "error")
    validate_error(response, err.ERR_WINDOW_BOUNDS_INVALID, 422)

    rows, meta = validate_paginated(api.list_availability_windows(title["id"], CONTENT_OPS))
    assert meta["total_count"] == 0, meta
    assert rows == [], rows


def test_a_well_formed_interval_starting_before_the_clock_returns_window_in_past(api):
    """A well-formed July interval scheduled while the clock reads 2026-08-01 answers ERR_WINDOW_IN_PAST at 422, not a bounds error.

    PRD §3.6: "The interval must be well-formed, with `window_start_at` strictly
    before `window_end_at`, otherwise `ERR_WINDOW_BOUNDS_INVALID`; it must not begin
    in the past, meaning `window_start_at` is at or after the current logical clock,
    otherwise `ERR_WINDOW_IN_PAST`; and it must not overlap any `SCHEDULED` or
    `ACTIVE` window of the same title and the same region under the half-open
    comparison of §2.10, otherwise `ERR_WINDOW_OVERLAP`."

    PRD §2.5: "At process startup the logical clock reads exactly
    `2026-08-01T00:00:00Z`; before any operator moves it, that instant is what the
    server sees, and it must never fall back to real time."

    Design: Corner/errors/window_bounds_past_start_and_legal_takedown_are_rejected
    """
    title = fx.create_title(
        api, external_ref="TTL-WINPAST", title_name="Past Cut", studio_code="NOVAPIC"
    )

    response = api.create_availability_window(
        title["id"],
        f.availability_window_payload(
            region_code="US",
            window_start_at="2026-07-01T00:00:00Z",
            window_end_at="2026-07-15T00:00:00Z",
        ),
        CONTENT_OPS,
    )

    assert_envelope(response, "error")
    validate_error(response, err.ERR_WINDOW_IN_PAST, 422)

    rows, meta = validate_paginated(api.list_availability_windows(title["id"], CONTENT_OPS))
    assert meta["total_count"] == 0, meta

    # The very same interval shifted to start at the startup clock is accepted,
    # which locates the boundary the rejection was measured against.
    accepted = validate_success(
        api.create_availability_window(
            title["id"],
            f.availability_window_payload(
                region_code="US",
                window_start_at=INITIAL_CLOCK,
                window_end_at="2026-08-15T00:00:00Z",
            ),
            CONTENT_OPS,
        ),
        201,
    )
    assert accepted["state"] == "SCHEDULED", accepted
    assert_instant_equals(accepted["window_start_at"], INITIAL_CLOCK)


def test_scheduling_on_a_legally_taken_down_title_returns_title_legally_blocked(api):
    """After a MANUAL_LEGAL takedown, a fresh non-overlapping future window answers ERR_TITLE_LEGALLY_BLOCKED at 409.

    PRD §3.6: "Scheduling is also refused outright on a title that is `TAKEN_DOWN`
    with `takedown_reason` of `MANUAL_LEGAL`, with `ERR_TITLE_LEGALLY_BLOCKED` —
    legal takedowns are not routed around by adding fresh contract dates."

    PRD §3.6: "A manual takedown moves `availability_state` from `PUBLISHED` to
    `TAKEN_DOWN`, sets `takedown_reason` to `MANUAL_LEGAL`, increments the title's
    `version` by one, and closes every one of the title's `ACTIVE` windows with
    `closed_at` set to the logical clock's current instant."

    Design: Corner/errors/window_bounds_past_start_and_legal_takedown_are_rejected
    """
    pipeline = fx.build_published_title(api)
    published = fx.read_title(api, pipeline.title_id)
    assert published["availability_state"] == "PUBLISHED", published

    taken_down = fx.takedown_title(api, pipeline.title_id, takedown_reason="MANUAL_LEGAL")
    assert taken_down["availability_state"] == "TAKEN_DOWN", taken_down
    assert taken_down["takedown_reason"] == "MANUAL_LEGAL", taken_down

    response = api.create_availability_window(
        pipeline.title_id,
        f.availability_window_payload(
            region_code="GB",
            window_start_at="2026-09-01T00:00:00Z",
            window_end_at="2026-10-01T00:00:00Z",
        ),
        CONTENT_OPS,
    )

    assert_envelope(response, "error")
    validate_error(response, err.ERR_TITLE_LEGALLY_BLOCKED, 409)

    rows, meta = validate_paginated(
        api.list_availability_windows(pipeline.title_id, CONTENT_OPS, {"region_code": "GB"})
    )
    assert meta["total_count"] == 0, meta
    assert rows == [], rows


# ---------------------------------------------------------------------------
# Terminal states are locked down, each with its own 409 (§2.6 rung 10)
# ---------------------------------------------------------------------------


def test_cancelling_an_already_cancelled_window_returns_window_state_invalid(api):
    """The second cancel of a CANCELLED window answers ERR_WINDOW_STATE_INVALID at 409 and leaves `closed_at` as the first cancel stamped it.

    PRD §3.6: "`ContentOps` can cancel a window whose `state` is `SCHEDULED` or
    `ACTIVE`; a window already `CLOSED` or `CANCELLED` answers
    `ERR_WINDOW_STATE_INVALID`."

    PRD §3.6: "Cancellation moves the window to the terminal `CANCELLED`, records
    `closed_at` at the logical clock's current instant, and releases the interval so
    a later window may legally occupy it."

    Design: Corner/errors/repeat_terminal_actions_on_window_and_package_are_rejected
    """
    title = fx.create_title(
        api, external_ref="TTL-TERMINAL", title_name="Terminal Cut", studio_code="NOVAPIC"
    )
    window = fx.create_window(
        api,
        title["id"],
        region_code="US",
        window_start_at="2026-09-01T00:00:00Z",
        window_end_at="2026-10-01T00:00:00Z",
    )
    assert window["state"] == "SCHEDULED", window

    cancelled = fx.cancel_window(api, window["id"])
    assert cancelled["state"] == "CANCELLED", cancelled
    assert_instant_equals(cancelled["closed_at"], INITIAL_CLOCK)

    response = api.cancel_availability_window(window["id"], CONTENT_OPS)

    assert_envelope(response, "error")
    validate_error(response, err.ERR_WINDOW_STATE_INVALID, 409)

    rows, meta = validate_paginated(api.list_availability_windows(title["id"], CONTENT_OPS))
    assert meta["total_count"] == 1, meta
    assert rows[0]["state"] == "CANCELLED", rows[0]
    assert_instant_equals(rows[0]["closed_at"], INITIAL_CLOCK)


def test_revoking_an_already_revoked_package_returns_package_state_invalid(api):
    """The first revoke of a PENDING package drops the title to UNPACKAGED; the second answers ERR_PACKAGE_STATE_INVALID at 409.

    PRD §3.5: "The reverse operation is **revocation**, available from `PENDING`,
    `PACKAGED` or `STALE` into the terminal `REVOKED`; revoking an
    already-`REVOKED` package is `ERR_PACKAGE_STATE_INVALID`."

    PRD §3.4: "If any DRM package of the title is `STALE`, the dimension reads
    `STALE`. Otherwise, if any package is `PACKAGED`, it reads `PACKAGED`.
    Otherwise, if `locked_ladder_count` is 1 or more, it reads `PACKAGING`.
    Otherwise it reads `UNPACKAGED`. Packages in `REVOKED` are ignored by every
    branch of that precedence, as though they had never existed."

    Design: Corner/errors/repeat_terminal_actions_on_window_and_package_are_rejected
    """
    title = fx.create_title(
        api, external_ref="TTL-TERMINAL", title_name="Terminal Cut", studio_code="NOVAPIC"
    )
    ladder = fx.create_ladder(api, title["id"])
    assert ladder["state"] == "DRAFT", ladder
    package = fx.create_package(api, title["id"], ladder["id"])
    assert package["state"] == "PENDING", package

    revoked = fx.revoke_package(api, package["id"])
    assert revoked["state"] == "REVOKED", revoked

    after_first = fx.read_title(api, title["id"])
    assert after_first["packaging_state"] == "UNPACKAGED", after_first
    assert after_first["locked_ladder_count"] == 0, after_first

    response = api.revoke_drm_package(package["id"], DRM_OPERATOR)

    assert_envelope(response, "error")
    validate_error(response, err.ERR_PACKAGE_STATE_INVALID, 409)

    stored = fx.read_package(api, package["id"])
    assert stored["state"] == "REVOKED", stored
    assert fx.read_title(api, title["id"])["packaging_state"] == "UNPACKAGED"


# ---------------------------------------------------------------------------
# Three distinct reprocessing rejections (§2.6 rungs 10, 14 and 17, §3.9)
# ---------------------------------------------------------------------------


def test_reprocessing_into_the_source_codec_returns_reprocess_codec_unchanged(api):
    """A job asking H264 → H264 answers ERR_REPROCESS_CODEC_UNCHANGED at 422 and bumps neither the title's version nor its budget.

    PRD §3.9: "The target codec must actually be a change: a
    `target_codec_family` equal to the source ladder's `codec_family` is
    `ERR_REPROCESS_CODEC_UNCHANGED`."

    Design: Corner/errors/reprocess_job_referential_inflight_and_terminal_codes_are_triggerable
    """
    pipeline = fx.build_locked_ladder_title(
        api,
        title_overrides={
            "external_ref": "TTL-JOB-CODES",
            "title_name": "Job Codes Cut",
            "studio_code": "NOVAPIC",
        },
    )
    before = fx.read_title(api, pipeline.title_id)
    assert_money(before["encode_budget_remaining_usd"], 5000.00, "encode_budget_remaining_usd")

    response = api.create_reprocess_job(
        f.reprocess_job_payload(
            pipeline.title_id,
            pipeline.ladder_id,
            before["version"],
            trigger_reason="CODEC_DEPRECATION",
            target_codec_family="H264",
        ),
        ENCODING_ENGINEER,
    )

    assert_envelope(response, "error")
    validate_error(response, err.ERR_REPROCESS_CODEC_UNCHANGED, 422)

    after = fx.read_title(api, pipeline.title_id)
    assert after["version"] == before["version"], (before, after)
    assert_money(after["encode_budget_remaining_usd"], 5000.00, "encode_budget_remaining_usd")

    rows, meta = validate_paginated(
        api.list_reprocess_jobs(ENCODING_ENGINEER, {"title_id": pipeline.title_id})
    )
    assert meta["total_count"] == 0, meta
    assert rows == [], rows


def test_a_second_job_while_one_is_queued_returns_reprocess_job_in_flight(api):
    """The accepted HEVC job is QUEUED with `committed_usd` 0.00 and bumps the title's version by one; a further AV1 job answers ERR_REPROCESS_JOB_IN_FLIGHT at 409.

    PRD §3.9: "Only one job per title may be in flight: a second creation while
    another job of the same title is `QUEUED` or `RUNNING` is
    `ERR_REPROCESS_JOB_IN_FLIGHT`, while jobs in `COMPLETED`, `FAILED` or
    `ABORTED` block nothing."

    PRD §3.9: "A job that clears all four is stored in `state` `QUEUED` with
    `result_ladder_id` null, `committed_usd` 0.00, `abort_reason` `NONE`, and the
    title's `version` incremented by one."

    Design: Corner/errors/reprocess_job_referential_inflight_and_terminal_codes_are_triggerable
    """
    pipeline = fx.build_locked_ladder_title(
        api,
        title_overrides={
            "external_ref": "TTL-JOB-CODES",
            "title_name": "Job Codes Cut",
            "studio_code": "NOVAPIC",
        },
    )
    version_before = fx.title_version(api, pipeline.title_id)

    job = validate_success(
        api.create_reprocess_job(
            f.reprocess_job_payload(
                pipeline.title_id,
                pipeline.ladder_id,
                version_before,
                trigger_reason="CODEC_DEPRECATION",
                target_codec_family="HEVC",
            ),
            ENCODING_ENGINEER,
        ),
        201,
    )
    assert job["state"] == "QUEUED", job
    assert job["result_ladder_id"] is None, job
    assert job["abort_reason"] == "NONE", job
    assert_money(job["committed_usd"], 0.00, "committed_usd")

    version_after = fx.title_version(api, pipeline.title_id)
    assert version_after == version_before + 1, (version_before, version_after)

    response = api.create_reprocess_job(
        f.reprocess_job_payload(
            pipeline.title_id,
            pipeline.ladder_id,
            version_after,
            trigger_reason="STANDARD_UPDATE",
            target_codec_family="AV1",
        ),
        ENCODING_ENGINEER,
    )

    assert_envelope(response, "error")
    validate_error(response, err.ERR_REPROCESS_JOB_IN_FLIGHT, 409)

    rows, meta = validate_paginated(
        api.list_reprocess_jobs(ENCODING_ENGINEER, {"title_id": pipeline.title_id})
    )
    assert meta["total_count"] == 1, meta
    assert_list_ids(rows, [job["id"]])


def test_aborting_an_already_aborted_job_returns_job_state_invalid(api):
    """Aborting a QUEUED job succeeds with `committed_usd` 0.00; the second abort answers ERR_JOB_STATE_INVALID at 409 and the budget never moves.

    PRD §3.9: "An abort attempted on a job already `COMPLETED`, `FAILED` or
    `ABORTED` answers `ERR_JOB_STATE_INVALID`."

    PRD §3.9: "Aborting from `QUEUED` is also legal and is the cheaper case:
    nothing was ever debited, so `committed_usd` stays 0.00 and
    `encode_budget_remaining_usd` is unchanged."

    Design: Corner/errors/reprocess_job_referential_inflight_and_terminal_codes_are_triggerable
    """
    pipeline = fx.build_locked_ladder_title(
        api,
        title_overrides={
            "external_ref": "TTL-JOB-CODES",
            "title_name": "Job Codes Cut",
            "studio_code": "NOVAPIC",
        },
    )
    job = fx.create_job(
        api,
        pipeline.title_id,
        pipeline.ladder_id,
        trigger_reason="CODEC_DEPRECATION",
        target_codec_family="HEVC",
    )

    aborted = fx.abort_job(api, job["id"], abort_reason="OPERATOR_ABORT")
    assert aborted["state"] == "ABORTED", aborted
    assert aborted["abort_reason"] == "OPERATOR_ABORT", aborted
    assert_money(aborted["committed_usd"], 0.00, "committed_usd")
    assert_money(
        fx.read_title(api, pipeline.title_id)["encode_budget_remaining_usd"],
        5000.00,
        "encode_budget_remaining_usd",
    )

    response = api.abort_reprocess_job(
        job["id"], f.abort_payload(abort_reason="OPERATOR_ABORT"), ENCODING_ENGINEER
    )

    assert_envelope(response, "error")
    validate_error(response, err.ERR_JOB_STATE_INVALID, 409)

    stored = fx.read_job(api, job["id"])
    assert stored["state"] == "ABORTED", stored
    assert_money(stored["committed_usd"], 0.00, "committed_usd")
    assert_money(
        fx.read_title(api, pipeline.title_id)["encode_budget_remaining_usd"],
        5000.00,
        "encode_budget_remaining_usd",
    )


# ---------------------------------------------------------------------------
# Reservation booking: three rejections that hold no capacity (§3.8)
# ---------------------------------------------------------------------------


def test_reserving_against_a_movie_title_returns_not_live_event_title(api):
    """A MOVIE title answers ERR_NOT_LIVE_EVENT_TITLE at 422 even though the same request would also miss every licensing window, and the vendor holds nothing.

    PRD §3.8: "The title must be a live event: a `content_type` other than
    `LIVE_EVENT` is `ERR_NOT_LIVE_EVENT_TITLE`."

    PRD §2.6: "The **first** rule violated determines the single error returned,
    and no later rule is evaluated once a rule has fired — even when a later rule's
    condition also holds."

    Design: Corner/errors/live_reservation_referential_and_license_containment_are_rejected
    """
    movie = fx.create_title(
        api,
        external_ref="TTL-MOVIE-RES",
        title_name="Not Live Cut",
        content_type="MOVIE",
        studio_code="NOVAPIC",
    )
    vendor = fx.create_vendor(
        api, vendor_code="LIVECDN", regions=["US"], committed_gbps=100.00, cost_per_gb_usd=0.0200
    )

    response = api.create_live_reservation(
        f.live_reservation_payload(
            movie["id"],
            vendor["id"],
            window_start_at="2026-09-05T00:00:00Z",
            window_end_at="2026-09-05T04:00:00Z",
            reserved_gbps=10.00,
        ),
        DELIVERY_ENGINEER,
    )

    assert_envelope(response, "error")
    validate_error(response, err.ERR_NOT_LIVE_EVENT_TITLE, 422)

    assert_money(fx.read_vendor(api, vendor["id"])["reserved_gbps"], 0.00, "reserved_gbps")


def test_a_standby_equal_to_the_primary_returns_failover_same_as_primary(api):
    """Naming the primary vendor again as the standby answers ERR_FAILOVER_SAME_AS_PRIMARY at 422 and stores no reservation.

    PRD §3.8: "A contracted standby must be a genuinely different partner: a
    `failover_vendor_id` equal to the `primary_vendor_id` is
    `ERR_FAILOVER_SAME_AS_PRIMARY`."

    Design: Corner/errors/live_reservation_referential_and_license_containment_are_rejected
    """
    pipeline = fx.build_live_event_pipeline(
        api,
        window_overrides={
            "region_code": "US",
            "window_start_at": "2026-09-01T00:00:00Z",
            "window_end_at": "2026-10-01T00:00:00Z",
            "license_tier": "PREMIUM",
        },
    )
    vendor_id = pipeline.vendor_ids[0]

    response = api.create_live_reservation(
        f.live_reservation_payload(
            pipeline.title_id,
            vendor_id,
            failover_vendor_id=vendor_id,
            window_start_at="2026-09-05T00:00:00Z",
            window_end_at="2026-09-05T04:00:00Z",
            reserved_gbps=10.00,
        ),
        DELIVERY_ENGINEER,
    )

    assert_envelope(response, "error")
    validate_error(response, err.ERR_FAILOVER_SAME_AS_PRIMARY, 422)

    rows, meta = validate_paginated(
        api.list_live_reservations(DELIVERY_ENGINEER, {"title_id": pipeline.title_id})
    )
    assert meta["total_count"] == 0, meta
    assert_money(fx.read_vendor(api, vendor_id)["reserved_gbps"], 0.00, "reserved_gbps")


def test_a_broadcast_outside_every_licensing_window_returns_reservation_outside_license(api):
    """An August broadcast against a September-only licence answers ERR_RESERVATION_OUTSIDE_LICENSE at 422; the same booking inside the window is accepted and holds 10.00 Gbps.

    PRD §3.8: "The broadcast must sit inside licensed dates: the reservation's
    window must fall **entirely inside one single** `SCHEDULED` or `ACTIVE`
    availability window of the same title, in any region — a reservation is not
    region-scoped, so it is enough that one licensing window of any region covers
    it end to end, and a broadcast straddling the boundary between two abutting
    licensing windows is refused with `ERR_RESERVATION_OUTSIDE_LICENSE` even though
    the two windows jointly cover it."

    PRD §3.8: "A successful booking stores the reservation in `state` `RESERVED`
    with `active_vendor_id` set to `primary_vendor_id`, `failover_at` null and
    `released_gbps` 0.00, and immediately recomputes the primary vendor's
    `reserved_gbps`."

    Design: Corner/errors/live_reservation_referential_and_license_containment_are_rejected
    """
    pipeline = fx.build_live_event_pipeline(
        api,
        window_overrides={
            "region_code": "US",
            "window_start_at": "2026-09-01T00:00:00Z",
            "window_end_at": "2026-10-01T00:00:00Z",
            "license_tier": "PREMIUM",
        },
    )
    vendor_id = pipeline.vendor_ids[0]

    response = api.create_live_reservation(
        f.live_reservation_payload(
            pipeline.title_id,
            vendor_id,
            window_start_at="2026-08-20T00:00:00Z",
            window_end_at="2026-08-20T04:00:00Z",
            reserved_gbps=10.00,
        ),
        DELIVERY_ENGINEER,
    )

    assert_envelope(response, "error")
    validate_error(response, err.ERR_RESERVATION_OUTSIDE_LICENSE, 422)
    assert_money(fx.read_vendor(api, vendor_id)["reserved_gbps"], 0.00, "reserved_gbps")

    accepted = validate_success(
        api.create_live_reservation(
            f.live_reservation_payload(
                pipeline.title_id,
                vendor_id,
                window_start_at="2026-09-05T00:00:00Z",
                window_end_at="2026-09-05T04:00:00Z",
                reserved_gbps=10.00,
            ),
            DELIVERY_ENGINEER,
        ),
        201,
    )
    assert accepted["state"] == "RESERVED", accepted
    assert accepted["active_vendor_id"] == vendor_id, accepted
    assert accepted["failover_at"] is None, accepted
    assert_money(accepted["released_gbps"], 0.00, "released_gbps")
    assert_money(fx.read_vendor(api, vendor_id)["reserved_gbps"], 10.00, "reserved_gbps")

    rows, meta = validate_paginated(
        api.list_availability_windows(pipeline.title_id, CONTENT_OPS)
    )
    assert meta["total_count"] == 1, meta
    assert rows[0]["state"] == "SCHEDULED", rows[0]


# ---------------------------------------------------------------------------
# Routing policies: one per region, and an empty pool at creation (§3.7)
# ---------------------------------------------------------------------------


def test_a_second_policy_for_the_same_region_returns_duplicate_routing_policy(api):
    """A COST policy for US beside an existing PERFORMANCE one answers ERR_DUPLICATE_ROUTING_POLICY at 409, and the stored policy keeps its single-candidate assignment.

    PRD §3.7: "A title may hold at most one policy per region, and a second
    attempt for the same pair is `ERR_DUPLICATE_ROUTING_POLICY`."

    PRD §3.7: "Assignment third: `primary_vendor_id` becomes the first-ranked
    candidate, `backup_vendor_id` becomes the second-ranked candidate when two or
    more candidates survive and is null otherwise, `state` becomes `ACTIVE` with two
    or more candidates and `STANDBY_ONLY` with exactly one, and
    `selection_reason_code` records which branch chose the primary —
    `PERFORMANCE_RANK`, `COST_RANK` or `WEIGHTED_RANK` according to the mode."

    Design: Corner/errors/duplicate_routing_policy_and_empty_candidate_pool_are_rejected
    """
    title = fx.create_title(
        api, external_ref="TTL-POLICY-DUP", title_name="Policy Dup Cut", studio_code="NOVAPIC"
    )
    vendor = fx.create_vendor(
        api, vendor_code="ROUTECDN", regions=["US"], committed_gbps=80.00, cost_per_gb_usd=0.0200
    )
    policy = fx.create_policy(api, title["id"], region_code="US", steering_mode="PERFORMANCE")

    response = api.create_routing_policy(
        f.routing_policy_payload(title["id"], region_code="US", steering_mode="COST"),
        DELIVERY_ENGINEER,
    )

    assert_envelope(response, "error")
    validate_error(response, err.ERR_DUPLICATE_ROUTING_POLICY, 409)

    rows, meta = validate_paginated(
        api.list_routing_policies(DELIVERY_ENGINEER, {"title_id": title["id"]})
    )
    assert meta["total_count"] == 1, meta
    assert_list_ids(rows, [policy["id"]])

    stored = fx.read_policy(api, policy["id"])
    assert stored["state"] == "STANDBY_ONLY", stored
    assert stored["primary_vendor_id"] == vendor["id"], stored
    assert stored["backup_vendor_id"] is None, stored
    assert stored["selection_reason_code"] == "PERFORMANCE_RANK", stored
    assert stored["resteer_count"] == 0, stored


def test_creating_a_policy_for_an_unserved_region_returns_no_eligible_vendor(api):
    """A CA policy while the only vendor serves US alone answers ERR_NO_ELIGIBLE_VENDOR at 422 with nothing persisted.

    PRD §3.7: "At creation time it is fatal: the policy is refused with
    `ERR_NO_ELIGIBLE_VENDOR` (HTTP 422) and nothing at all is persisted."

    PRD §3.7: "Eligibility first: a vendor is a candidate when its `state` is
    exactly `ACTIVE`, the policy's `region_code` appears in the vendor's `regions`,
    its `health_score_contract` is at least 60.00, and its `id` is absent from the
    policy's `excluded_vendor_ids`."

    Design: Corner/errors/duplicate_routing_policy_and_empty_candidate_pool_are_rejected
    """
    title = fx.create_title(
        api, external_ref="TTL-POLICY-DUP", title_name="Policy Dup Cut", studio_code="NOVAPIC"
    )
    fx.create_vendor(
        api, vendor_code="ROUTECDN", regions=["US"], committed_gbps=80.00, cost_per_gb_usd=0.0200
    )
    us_policy = fx.create_policy(api, title["id"], region_code="US", steering_mode="PERFORMANCE")

    response = api.create_routing_policy(
        f.routing_policy_payload(title["id"], region_code="CA", steering_mode="PERFORMANCE"),
        DELIVERY_ENGINEER,
    )

    assert_envelope(response, "error")
    validate_error(response, err.ERR_NO_ELIGIBLE_VENDOR, 422)

    rows, meta = validate_paginated(
        api.list_routing_policies(DELIVERY_ENGINEER, {"title_id": title["id"]})
    )
    assert meta["total_count"] == 1, meta
    assert_list_ids(rows, [us_policy["id"]])

    ca_rows, ca_meta = validate_paginated(
        api.list_routing_policies(DELIVERY_ENGINEER, {"region_code": "CA"})
    )
    assert ca_meta["total_count"] == 0, ca_meta
    assert ca_rows == [], ca_rows


# ---------------------------------------------------------------------------
# A metric window is bound to the vendor's own footprint (§3.7)
# ---------------------------------------------------------------------------


def test_ingesting_a_region_the_vendor_does_not_serve_returns_vendor_region_not_served(api):
    """A CA measurement window against a US-only vendor answers ERR_VENDOR_REGION_NOT_SERVED at 422 and leaves both health variants at their no-rows 100.00.

    PRD §3.7: "The window must already be closed against the logical clock — a
    `window_end_at` strictly after the current clock is
    `ERR_METRIC_WINDOW_IN_FUTURE` — and the named vendor must actually serve the
    named region, meaning `region_code` appears in that vendor's `regions`,
    otherwise `ERR_VENDOR_REGION_NOT_SERVED`."

    PRD §3.7: "The `breach_window_count` is simply the number of the vendor's rows
    whose `breach_flag` is true."

    Design: Corner/errors/metric_ingest_for_an_unserved_region_is_rejected
    """
    title = fx.create_title(
        api, external_ref="TTL-REGION-MISS", title_name="Region Miss Cut", studio_code="NOVAPIC"
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
        quality_normalization_factor=0.90,
    )
    vendor = fx.create_vendor(
        api, vendor_code="USONLYCDN", regions=["US"], committed_gbps=60.00, cost_per_gb_usd=0.0200
    )

    response = api.create_playback_metric(
        f.playback_metric_payload(
            title["id"],
            profile["id"],
            vendor["id"],
            region_code="CA",
            window_start_at="2026-07-01T00:00:00Z",
            window_end_at="2026-07-01T01:00:00Z",
            play_attempts=100,
            rebuffer_events=0,
            startup_ms_p95=1500,
            error_count=0,
        ),
        DELIVERY_ENGINEER,
    )

    assert_envelope(response, "error")
    validate_error(response, err.ERR_VENDOR_REGION_NOT_SERVED, 422)

    stored = fx.read_vendor(api, vendor["id"])
    assert_score(stored["health_score_rolling"], 100.00, "health_score_rolling")
    assert_score(stored["health_score_contract"], 100.00, "health_score_contract")
    assert stored["breach_window_count"] == 0, stored

    rows, meta = validate_paginated(
        api.list_playback_metrics(DELIVERY_ENGINEER, {"vendor_id": vendor["id"]})
    )
    assert meta["total_count"] == 0, meta
    assert rows == [], rows


def test_the_same_window_in_a_served_region_is_accepted_with_a_clean_quality_index(api):
    """The identical window ingested for US is accepted at 201 with `rebuffer_ratio` 0.0000, `error_rate` 0.0000, `quality_index` 100.00 and `breach_flag` false.

    PRD §3.7: "The `rebuffer_ratio` is `rebuffer_events` divided by
    `play_attempts`, rounded half up to four decimals, and the `error_rate` is
    `error_count` divided by `play_attempts`, likewise to four decimals."

    PRD §3.7: "Because of the clamp, a window whose startup latency is at or below
    2000 milliseconds contributes exactly nothing from that term and is not rewarded
    for being faster."

    PRD §3.7: "Finally the `quality_index` is 100.00 reduced by that penalty,
    clamped into the range 0.00 to 100.00, and rounded half up to two decimals, and
    the `breach_flag` is true exactly when `quality_index` is strictly below 70.00; a
    `quality_index` of exactly 70.00 is not a breach while 69.99 is."

    Design: Corner/errors/metric_ingest_for_an_unserved_region_is_rejected
    """
    title = fx.create_title(
        api, external_ref="TTL-REGION-MISS", title_name="Region Miss Cut", studio_code="NOVAPIC"
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
        quality_normalization_factor=0.90,
    )
    vendor = fx.create_vendor(
        api, vendor_code="USONLYCDN", regions=["US"], committed_gbps=60.00, cost_per_gb_usd=0.0200
    )

    metric = validate_success(
        api.create_playback_metric(
            f.playback_metric_payload(
                title["id"],
                profile["id"],
                vendor["id"],
                region_code="US",
                window_start_at="2026-07-01T00:00:00Z",
                window_end_at="2026-07-01T01:00:00Z",
                play_attempts=100,
                rebuffer_events=0,
                startup_ms_p95=1500,
                error_count=0,
            ),
            DELIVERY_ENGINEER,
        ),
        201,
    )
    assert_ratio_4dp(metric["rebuffer_ratio"], 0.0000, "rebuffer_ratio")
    assert_ratio_4dp(metric["error_rate"], 0.0000, "error_rate")
    assert_score(metric["quality_index"], 100.00, "quality_index")
    assert metric["breach_flag"] is False, metric

    stored = fx.read_vendor(api, vendor["id"])
    assert_score(stored["health_score_rolling"], 100.00, "health_score_rolling")
    assert_score(stored["health_score_contract"], 100.00, "health_score_contract")
    assert stored["state"] == "ACTIVE", stored
    assert stored["breach_window_count"] == 0, stored


# ---------------------------------------------------------------------------
# The PATCH arm of the capacity guard (§3.7)
# ---------------------------------------------------------------------------


def test_lowering_committed_capacity_below_the_held_hold_returns_vendor_capacity_exceeded(api):
    """39.99 Gbps committed against a live 40.00 Gbps hold answers ERR_VENDOR_CAPACITY_EXCEEDED at 422 and leaves both `committed_gbps` and `version` untouched.

    PRD §3.7: "Lowering `committed_gbps` below the vendor's current `reserved_gbps`
    is refused with `ERR_VENDOR_CAPACITY_EXCEEDED`, since capacity already sold
    cannot be un-sold."

    Design: Corner/errors/patch_lowering_committed_gbps_below_reserved_is_rejected_then_accepted_at_equality
    """
    pipeline = fx.build_live_event_pipeline(
        api,
        window_overrides={
            "region_code": "US",
            "window_start_at": "2026-09-01T00:00:00Z",
            "window_end_at": "2026-10-01T00:00:00Z",
            "license_tier": "PREMIUM",
        },
    )
    vendor_id = pipeline.vendor_ids[0]
    fx.create_reservation(
        api,
        pipeline.title_id,
        vendor_id,
        window_start_at="2026-09-10T18:00:00Z",
        window_end_at="2026-09-10T22:00:00Z",
        reserved_gbps=40.00,
    )
    before = fx.read_vendor(api, vendor_id)
    assert_money(before["committed_gbps"], 100.00, "committed_gbps")
    assert_money(before["reserved_gbps"], 40.00, "reserved_gbps")

    response = api.patch_cdn_vendor(vendor_id, {"committed_gbps": 39.99}, PLATFORM_ADMIN)

    assert_envelope(response, "error")
    validate_error(response, err.ERR_VENDOR_CAPACITY_EXCEEDED, 422)

    after = fx.read_vendor(api, vendor_id)
    assert_money(after["committed_gbps"], 100.00, "committed_gbps")
    assert_money(after["reserved_gbps"], 40.00, "reserved_gbps")
    # The refusal stores nothing, so the vendor's version is exactly where the
    # booking's own §2.9 ledger cascade left it.
    assert after["version"] == before["version"], (before, after)


def test_lowering_committed_capacity_to_exactly_the_held_hold_is_accepted(api):
    """Committing exactly 40.00 Gbps against a 40.00 Gbps hold answers 200, increments `version` by one and leaves the reservation RESERVED.

    PRD §3.7: "Commercial terms are editable by `PlatformAdmin` or by the vendor's
    own `VendorOperator`, covering `committed_gbps`, `cost_per_gb_usd` and
    `regions`, and each successful update increments the vendor's `version`."

    PRD §2.9: "The rule is that **every consequence is applied inside the
    originating request**, transitively, and each affected row's `updated_at` is
    refreshed and its `version` incremented, exactly as if it had been mutated
    directly."

    PRD §3.7: "That figure is always the rounded sum of `reserved_gbps` over every
    reservation charged to the vendor through `active_vendor_id` in `RESERVED`,
    `ARMED`, `LIVE` or `FAILED_OVER` — it is a derived ledger, never an
    incrementally patched counter, and §2.9's bandwidth invariant holds over it at
    every observable moment."

    Design: Corner/errors/patch_lowering_committed_gbps_below_reserved_is_rejected_then_accepted_at_equality
    """
    pipeline = fx.build_live_event_pipeline(
        api,
        window_overrides={
            "region_code": "US",
            "window_start_at": "2026-09-01T00:00:00Z",
            "window_end_at": "2026-10-01T00:00:00Z",
            "license_tier": "PREMIUM",
        },
    )
    vendor_id = pipeline.vendor_ids[0]
    reservation = fx.create_reservation(
        api,
        pipeline.title_id,
        vendor_id,
        window_start_at="2026-09-10T18:00:00Z",
        window_end_at="2026-09-10T22:00:00Z",
        reserved_gbps=40.00,
    )
    before = fx.read_vendor(api, vendor_id)

    patched = validate_success(
        api.patch_cdn_vendor(vendor_id, {"committed_gbps": 40.00}, PLATFORM_ADMIN), 200
    )
    assert_money(patched["committed_gbps"], 40.00, "committed_gbps")
    assert_money(patched["reserved_gbps"], 40.00, "reserved_gbps")
    assert patched["version"] == before["version"] + 1, (before, patched)

    assert fx.read_reservation(api, reservation["id"])["state"] == "RESERVED"


# ---------------------------------------------------------------------------
# The derived HDCP floor carries a packaging obligation (§3.5)
# ---------------------------------------------------------------------------


def test_a_playready_only_package_on_a_4k_ladder_returns_drm_system_unsupported(api):
    """A 2160-tall ladder forces a TYPE_1 floor, so a PLAYREADY-only package answers ERR_DRM_SYSTEM_UNSUPPORTED at 422 and nothing is stored.

    PRD §3.5: "The package's `hdcp_floor` is derived, not supplied: it reads
    `TYPE_1` when the bound ladder's `peak_height_px` is 2160 or greater, `TYPE_0`
    when that height is 1080 or greater but below 2160, and `NONE` otherwise."

    PRD §3.5: "The floor is the minimum output-protection level every entitlement
    rule on the package must meet, and it carries one packaging obligation of its
    own: whenever `hdcp_floor` is `TYPE_1`, the package's `drm_systems` must include
    `WIDEVINE`, and a 4K-capable package that omits it is refused with
    `ERR_DRM_SYSTEM_UNSUPPORTED`."

    Design: Corner/errors/drm_package_omitting_widevine_at_a_type_one_floor_is_rejected
    """
    title = fx.create_title(
        api, external_ref="TTL-4K-DRM", title_name="Ultra Cut", studio_code="NOVAPIC"
    )
    ladder = fx.create_ladder(
        api,
        title["id"],
        codec_family="HEVC",
        rungs=[dict(r) for r in f.RUNGS_PEAK_2160],
    )
    assert ladder["peak_height_px"] == 2160, ladder
    assert ladder["state"] == "DRAFT", ladder

    response = api.create_drm_package(
        f.drm_package_payload(
            title["id"],
            ladder["id"],
            drm_systems=["PLAYREADY"],
            license_server_url="https://lic.novapic.example/pr",
        ),
        DRM_OPERATOR,
    )

    assert_envelope(response, "error")
    validate_error(response, err.ERR_DRM_SYSTEM_UNSUPPORTED, 422)

    rows, meta = validate_paginated(
        api.list_drm_packages(DRM_OPERATOR, {"title_id": title["id"]})
    )
    assert meta["total_count"] == 0, meta
    assert rows == [], rows
    assert fx.read_title(api, title["id"])["packaging_state"] == "UNPACKAGED"


def test_adding_widevine_at_a_type_one_floor_is_accepted_as_pending(api):
    """The same 4K binding with WIDEVINE beside PLAYREADY answers 201 with `hdcp_floor` TYPE_1 and `state` PENDING.

    PRD §3.5: "On creation the package's `state` is `PENDING`, its `stale_reason`
    is `NONE`, its `entitlement_rule_count` is 0 and its `packaged_at` is null."

    PRD §3.5: "The floor is the minimum output-protection level every entitlement
    rule on the package must meet, and it carries one packaging obligation of its
    own: whenever `hdcp_floor` is `TYPE_1`, the package's `drm_systems` must include
    `WIDEVINE`, and a 4K-capable package that omits it is refused with
    `ERR_DRM_SYSTEM_UNSUPPORTED`."

    Design: Corner/errors/drm_package_omitting_widevine_at_a_type_one_floor_is_rejected
    """
    title = fx.create_title(
        api, external_ref="TTL-4K-DRM", title_name="Ultra Cut", studio_code="NOVAPIC"
    )
    ladder = fx.create_ladder(
        api,
        title["id"],
        codec_family="HEVC",
        rungs=[dict(r) for r in f.RUNGS_PEAK_2160],
    )

    package = validate_success(
        api.create_drm_package(
            f.drm_package_payload(
                title["id"],
                ladder["id"],
                drm_systems=["WIDEVINE", "PLAYREADY"],
                license_server_url="https://lic.novapic.example/pr",
            ),
            DRM_OPERATOR,
        ),
        201,
    )
    assert package["hdcp_floor"] == "TYPE_1", package
    assert package["state"] == "PENDING", package
    assert package["stale_reason"] == "NONE", package
    assert package["entitlement_rule_count"] == 0, package
    assert package["packaged_at"] is None, package


# ---------------------------------------------------------------------------
# Rule uniqueness is on the triple only (§2.6 rung 17, §3.5)
# ---------------------------------------------------------------------------


def test_repeating_the_region_tier_scope_triple_returns_duplicate_entitlement_rule(api):
    """A second `*`/ANY/ALL rule answers ERR_DUPLICATE_ENTITLEMENT_RULE at 409 even with a different priority, and `entitlement_rule_count` stays 1.

    PRD §3.5: "Additionally, the combination of `region_code`,
    `subscription_tier` and `device_class_scope` must be unique within the package,
    and a repeat is `ERR_DUPLICATE_ENTITLEMENT_RULE`."

    PRD §3.5: "and optionally the `device_class_scope`, one of `ALL`, `TV_ONLY` or
    `MOBILE_ONLY` and defaulting to `ALL`, where `TV_ONLY` covers `SMART_TV_4K`,
    `SMART_TV_HD` and `SET_TOP_LEGACY` and `MOBILE_ONLY` covers `MOBILE_HIGH` and
    `MOBILE_LOW`."

    Design: Corner/errors/duplicate_entitlement_rule_triple_is_rejected_but_a_narrower_scope_is_accepted
    """
    title = fx.create_title(
        api, external_ref="TTL-RULE-DUP", title_name="Rule Dup Cut", studio_code="NOVAPIC"
    )
    ladder = fx.create_ladder(api, title["id"])
    package = fx.create_package(api, title["id"], ladder["id"], drm_systems=["WIDEVINE"])
    first = fx.add_entitlement_rule(
        api,
        package["id"],
        region_code="*",
        subscription_tier="ANY",
        device_class_scope=None,
        max_concurrent_streams=2,
        max_playback_height_px=720,
        hdcp_level="NONE",
        priority=10,
    )
    assert first["device_class_scope"] == "ALL", first

    response = api.create_entitlement_rule(
        package["id"],
        f.entitlement_rule_payload(
            region_code="*",
            subscription_tier="ANY",
            device_class_scope=None,
            max_concurrent_streams=5,
            max_playback_height_px=480,
            hdcp_level="NONE",
            priority=80,
        ),
        DRM_OPERATOR,
    )

    assert_envelope(response, "error")
    validate_error(response, err.ERR_DUPLICATE_ENTITLEMENT_RULE, 409)

    assert fx.read_package(api, package["id"])["entitlement_rule_count"] == 1


def test_the_same_region_and_tier_with_a_narrower_device_scope_is_accepted(api):
    """`*`/ANY/TV_ONLY beside `*`/ANY/ALL is accepted at 201, takes the count to 2 and lists priority-descending.

    PRD §3.5: "A successful attachment increments the package's
    `entitlement_rule_count` by one."

    PRD §3.5: "A package's rules can be listed with an optional `region_code`
    filter, returned by `priority` descending and then oldest first, which is exactly
    the ranking the selector applies after filtering."

    Design: Corner/errors/duplicate_entitlement_rule_triple_is_rejected_but_a_narrower_scope_is_accepted
    """
    title = fx.create_title(
        api, external_ref="TTL-RULE-DUP", title_name="Rule Dup Cut", studio_code="NOVAPIC"
    )
    ladder = fx.create_ladder(api, title["id"])
    package = fx.create_package(api, title["id"], ladder["id"], drm_systems=["WIDEVINE"])
    first = fx.add_entitlement_rule(
        api,
        package["id"],
        region_code="*",
        subscription_tier="ANY",
        device_class_scope=None,
        max_concurrent_streams=2,
        max_playback_height_px=720,
        hdcp_level="NONE",
        priority=10,
    )

    tv_rule = validate_success(
        api.create_entitlement_rule(
            package["id"],
            f.entitlement_rule_payload(
                region_code="*",
                subscription_tier="ANY",
                device_class_scope="TV_ONLY",
                max_concurrent_streams=5,
                max_playback_height_px=720,
                hdcp_level="NONE",
                priority=80,
            ),
            DRM_OPERATOR,
        ),
        201,
    )
    assert tv_rule["device_class_scope"] == "TV_ONLY", tv_rule
    assert fx.read_package(api, package["id"])["entitlement_rule_count"] == 2

    rows, meta = validate_paginated(api.list_entitlement_rules(package["id"], DRM_OPERATOR))
    assert meta["total_count"] == 2, meta
    assert_list_ids(rows, [tv_rule["id"], first["id"]])


# ---------------------------------------------------------------------------
# The two entitlement denials are 403s reached at different stages (§3.5)
# ---------------------------------------------------------------------------


def test_a_basic_request_against_a_premium_only_rule_returns_entitlement_no_rule(api):
    """A BASIC session against a single PREMIUM wildcard rule qualifies nothing and answers ERR_ENTITLEMENT_NO_RULE at 403.

    PRD §3.5: "Third, **rule eligibility**: a rule of the selected package
    qualifies when its `region_code` either equals the requested `region_code` or is
    the wildcard; its `subscription_tier` either equals the requested tier or is
    `ANY`; its `device_class_scope` is `ALL`, or is `TV_ONLY` and the requested
    `device_class` is one of `SMART_TV_4K`, `SMART_TV_HD` or `SET_TOP_LEGACY`, or is
    `MOBILE_ONLY` and the requested `device_class` is one of `MOBILE_HIGH` or
    `MOBILE_LOW`; and, when the resolved device's `hdcp_required` is true, its
    `hdcp_level` is either `TYPE_0` or `TYPE_1` — a device demanding protected output
    cannot be served by a rule mandating `NONE`."

    PRD §3.5: "If no rule qualified, the check is refused with
    `ERR_ENTITLEMENT_NO_RULE` (HTTP 403)."

    Design: Corner/errors/entitlement_denials_return_forbidden_for_tier_miss_and_offline_request
    """
    pipeline = fx.build_packaged_title(
        api,
        title_overrides={
            "external_ref": "TTL-DENIALS",
            "title_name": "Denials Cut",
            "studio_code": "NOVAPIC",
        },
        rule_overrides={
            "region_code": "*",
            "subscription_tier": "PREMIUM",
            "device_class_scope": None,
            "max_concurrent_streams": 2,
            "max_playback_height_px": 720,
            "hdcp_level": "NONE",
            "priority": 30,
        },
    )
    package = fx.read_package(api, pipeline.package_id)
    assert package["state"] == "PACKAGED", package
    assert package["persistent_license_allowed"] is False, package

    response = api.create_playback_entitlement_check(
        f.entitlement_check_payload(
            pipeline.title_id,
            region_code="US",
            subscription_tier="BASIC",
            device_class="MOBILE_HIGH",
            requested_streams=1,
        ),
        DELIVERY_ENGINEER,
    )

    assert_envelope(response, "error")
    validate_error(response, err.ERR_ENTITLEMENT_NO_RULE, 403)


def test_offline_on_a_non_persistent_package_returns_offline_playback_denied(api):
    """A PREMIUM session that does match its rule is still denied offline playback with ERR_OFFLINE_PLAYBACK_DENIED at 403.

    PRD §3.5: "Fifth, two **post-match gates** are applied in this order: if
    `requested_streams` is strictly greater than the winning rule's
    `max_concurrent_streams` the answer is `ERR_CONCURRENCY_LIMIT_EXCEEDED` (HTTP
    403), where asking for exactly the licensed number of streams is allowed; and if
    `offline_requested` is true while either the winning rule's
    `offline_playback_allowed` or the selected package's
    `persistent_license_allowed` is false, the answer is
    `ERR_OFFLINE_PLAYBACK_DENIED` (HTTP 403)."

    Design: Corner/errors/entitlement_denials_return_forbidden_for_tier_miss_and_offline_request
    """
    pipeline = fx.build_packaged_title(
        api,
        title_overrides={
            "external_ref": "TTL-DENIALS",
            "title_name": "Denials Cut",
            "studio_code": "NOVAPIC",
        },
        rule_overrides={
            "region_code": "*",
            "subscription_tier": "PREMIUM",
            "device_class_scope": None,
            "max_concurrent_streams": 2,
            "max_playback_height_px": 720,
            "hdcp_level": "NONE",
            "priority": 30,
        },
    )

    response = api.create_playback_entitlement_check(
        f.entitlement_check_payload(
            pipeline.title_id,
            region_code="US",
            subscription_tier="PREMIUM",
            device_class="MOBILE_HIGH",
            requested_streams=1,
            offline_requested=True,
        ),
        DELIVERY_ENGINEER,
    )

    assert_envelope(response, "error")
    validate_error(response, err.ERR_OFFLINE_PLAYBACK_DENIED, 403)


def test_the_same_premium_request_without_offline_is_allowed_at_720(api):
    """Dropping `offline_requested` turns the same session into ALLOW/MATCHED with `effective_height_px` 720 and `offline_granted` false.

    PRD §3.5: "A check that clears all five stages answers with `decision` of
    `ALLOW` and `reason_code` of `MATCHED`, together with `matched_rule_id` naming
    the winning rule, `package_id` naming the selected package,
    `max_concurrent_streams` echoing the winning rule's ceiling, `offline_granted` —
    true when `offline_requested` was true and both offline permissions held, false
    otherwise, including when offline playback was never requested — and
    `effective_height_px`, the playback ceiling actually available, which is the
    smallest of three numbers: the winning rule's `max_playback_height_px`, the
    resolved device's `max_height_px`, and the `peak_height_px` of the ladder the
    selected package is bound to."

    Design: Corner/errors/entitlement_denials_return_forbidden_for_tier_miss_and_offline_request
    """
    pipeline = fx.build_packaged_title(
        api,
        title_overrides={
            "external_ref": "TTL-DENIALS",
            "title_name": "Denials Cut",
            "studio_code": "NOVAPIC",
        },
        rule_overrides={
            "region_code": "*",
            "subscription_tier": "PREMIUM",
            "device_class_scope": None,
            "max_concurrent_streams": 2,
            "max_playback_height_px": 720,
            "hdcp_level": "NONE",
            "priority": 30,
        },
    )

    decision = validate_unpaginated(
        api.create_playback_entitlement_check(
            f.entitlement_check_payload(
                pipeline.title_id,
                region_code="US",
                subscription_tier="PREMIUM",
                device_class="MOBILE_HIGH",
                requested_streams=1,
            ),
            DELIVERY_ENGINEER,
        )
    )
    assert decision["decision"] == "ALLOW", decision
    assert decision["reason_code"] == "MATCHED", decision
    assert decision["matched_rule_id"] == pipeline.rule_id, decision
    assert decision["package_id"] == pipeline.package_id, decision
    assert decision["max_concurrent_streams"] == 2, decision
    assert decision["effective_height_px"] == 720, decision
    assert decision["offline_granted"] is False, decision
