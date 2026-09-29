"""The twenty-rung request validation ladder of PRD §2.6.

Every test here drives a single request that violates *several* rules at once and
asserts which rung fires **first**: the exact `error_id`, the HTTP status the PRD
pins to that identifier, and — by construction of `validate_error` — the absence
of the later rung's identifier.  Each pairing is then completed by repairing only
the earlier violation, so the later rung is shown to have been reachable all
along rather than simply absent.

Where the ladder says nothing is persisted, the claim is proved by re-reading the
parent resource or by listing the collection that would have grown.

Every test builds its own world from an empty database with the logical clock at
its startup value of `2026-08-01T00:00:00Z`.
"""

from prd_bench_local_runner.testing import validate_error, validate_success
from test_helpers import api_errors as err
from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.assertions import assert_money, assert_score, validate_paginated
from test_helpers.constants import UUID_ABSENT
from test_helpers.test_users import (
    CONTENT_OPS,
    DELIVERY_ENGINEER,
    DRM_OPERATOR,
    ENCODING_ENGINEER,
    PLATFORM_ADMIN,
    VENDOR_OPERATOR_UNKNOWN,
    headers_missing_role,
)

# ---------------------------------------------------------------------------
# Rung 1 (credentials) versus rung 6 (payload schema)
# ---------------------------------------------------------------------------

# A title registration that omits the required `title_name`, so rung 6 has a
# genuine violation to report if rung 1 ever fails to fire first.
_TITLE_MISSING_NAME = dict(
    external_ref="TTL-AUTH-FIRST",
    content_type="MOVIE",
    studio_code="NOVAPIC",
    title_name=None,
)


def test_missing_role_header_outranks_the_missing_required_field(api):
    """A create that omits `X-User-Role` *and* a required body field answers 401.

    PRD §2.6: "Both `X-User-ID` and `X-User-Role` are present and non-empty;
    absent, empty or whitespace-only fails with `ERR_UNAUTHENTICATED` (401)."

    Design: Corner/validations/auth_check_beats_payload_schema_returns_unauthenticated
    """
    response = api.create_title(
        f.title_payload(**_TITLE_MISSING_NAME), headers_missing_role()
    )
    validate_error(response, err.ERR_UNAUTHENTICATED, 401)


def test_a_request_stopped_at_rung_one_stores_no_title_though_rung_six_was_live(api):
    """The same payload with a valid role reaches rung 6 and answers 400; the
    401 arm stored nothing.

    PRD §2.6: "The **first** rule violated determines the single error returned,
    and no later rule is evaluated once a rule has fired — even when a later
    rule's condition also holds."

    Design: Corner/validations/auth_check_beats_payload_schema_returns_unauthenticated
    """
    payload = f.title_payload(**_TITLE_MISSING_NAME)
    validate_error(
        api.create_title(payload, headers_missing_role()), err.ERR_UNAUTHENTICATED, 401
    )

    rows, meta = validate_paginated(api.list_titles(CONTENT_OPS))
    assert meta["total_count"] == 0, f"the rejected create stored a Title: {rows}"

    # Rung 6 was reachable all along: only the credentials were repaired.
    validate_error(
        api.create_title(payload, CONTENT_OPS), err.ERR_INVALID_REQUEST, 400
    )


# ---------------------------------------------------------------------------
# Rung 3 (role permitted) versus rung 7 (path existence)
# ---------------------------------------------------------------------------


def test_an_unauthorised_role_reading_an_absent_title_gets_403_not_404(api):
    """`GET /titles/{id}` for a never-minted id answers 403 to a `VendorOperator`.

    PRD §2.6: "Authentication and authorisation always precede existence, so
    probing for a valid identifier with a bad role yields 403 and never 404."

    Design: Corner/validations/role_check_beats_path_existence_returns_forbidden
    """
    response = api.get_title(UUID_ABSENT, VENDOR_OPERATOR_UNKNOWN)
    validate_error(response, err.ERR_ROLE_NOT_PERMITTED, 403)


def test_the_same_absent_title_answers_404_to_an_authorised_role(api):
    """The identical URL read by `ContentOps` reports the path rung's 404.

    PRD §2.6: "Every identifier in the URL path resolves to a stored row,
    checked left to right, returning that family's 404 identifier from §2.4."

    Design: Corner/validations/role_check_beats_path_existence_returns_forbidden
    """
    validate_error(
        api.get_title(UUID_ABSENT, VENDOR_OPERATOR_UNKNOWN),
        err.ERR_ROLE_NOT_PERMITTED,
        403,
    )
    validate_error(
        api.get_title(UUID_ABSENT, CONTENT_OPS), err.ERR_TITLE_NOT_FOUND, 404
    )


# ---------------------------------------------------------------------------
# Rung 6 (payload schema) versus rung 8 (body foreign keys)
# ---------------------------------------------------------------------------


def _absent_title_asset_payload(**overrides):
    """A source-master payload whose `title_id` names nothing stored."""
    return f.mezzanine_asset_payload(
        UUID_ABSENT,
        source_uri="s3://mez/nope.mxf",
        duration_seconds=3600,
        peak_audio_lufs=-24.0,
        artifact_defect_count=0,
        audio_language="en",
        caption_languages=None,
        **overrides,
    )


def test_an_undeclared_frame_rate_outranks_the_unresolvable_title_id(api):
    """A master carrying both `frame_rate` 30.0 and an absent `title_id` answers 400.

    PRD §2.6: "Every required input is present; no unknown field is supplied;
    every value has the correct JSON type; every enum value is drawn from its
    declared set; every instant parses as ISO 8601 UTC; decimals sit within their
    declared scale; integers sit within their declared range; every `region_code`
    is two uppercase letters (or the single literal `*` where a rule explicitly
    allows a wildcard); `page` is at least 1 and `page_size` is between 1 and 100
    inclusive."

    Design: Corner/validations/payload_schema_beats_body_fk_lookup_returns_invalid_request
    """
    response = api.create_mezzanine_asset(
        _absent_title_asset_payload(frame_rate=30.0), CONTENT_OPS
    )
    validate_error(response, err.ERR_INVALID_REQUEST, 400)


def test_repairing_only_the_frame_rate_exposes_the_body_foreign_key_rung(api):
    """The identical request with a declared `frame_rate` reports the 404 instead.

    PRD §2.6: "Every foreign key in the request body or query string resolves,
    checked in the order the endpoint declares its inputs, returning
    `ERR_TITLE_NOT_FOUND`, `ERR_LADDER_NOT_FOUND`, `ERR_VENDOR_NOT_FOUND`,
    `ERR_DEVICE_PROFILE_NOT_FOUND` or `ERR_PACKAGE_NOT_FOUND` as appropriate."

    Design: Corner/validations/payload_schema_beats_body_fk_lookup_returns_invalid_request
    """
    validate_error(
        api.create_mezzanine_asset(
            _absent_title_asset_payload(frame_rate=30.0), CONTENT_OPS
        ),
        err.ERR_INVALID_REQUEST,
        400,
    )
    validate_error(
        api.create_mezzanine_asset(
            _absent_title_asset_payload(frame_rate=24.0), CONTENT_OPS
        ),
        err.ERR_TITLE_NOT_FOUND,
        404,
    )


# ---------------------------------------------------------------------------
# Rung 8 (body foreign keys) versus rung 11 (ladder bindability)
# ---------------------------------------------------------------------------


def _rejected_ladder_world(api):
    """One title and one `REJECTED` ladder: with no device profile stored at all
    the candidate pool is empty, so validation scores 0.00 and takes the
    rejecting arm."""
    title = fx.create_title(
        api,
        external_ref="TTL-BIND-ORDER",
        title_name="Bind Order Cut",
        content_type="MOVIE",
        studio_code="NOVAPIC",
    )
    ladder = fx.create_ladder(api, title["id"], codec_family="H264")
    validated = fx.validate_ladder(api, ladder["id"])
    return title, validated


def test_validation_with_no_device_profile_rejects_the_ladder_outright(api):
    """An empty `ACTIVE` candidate pool scores 0.00 and rejects the ladder.

    PRD §3.3: "The **rejecting arm** applies when at least one of the opposite
    conditions holds: the rungs are not strictly increasing, or two rungs share a
    `height_px`, or the computed score is exactly 0.00 — which is what an empty
    `ACTIVE` candidate pool always produces."

    Design: Corner/validations/body_fk_lookup_beats_ladder_bindability_returns_not_found
    """
    _title, ladder = _rejected_ladder_world(api)
    assert ladder["state"] == "REJECTED", ladder
    assert ladder["validation_reason_code"] == "NO_COMPATIBLE_DEVICE", ladder
    assert_score(ladder["device_compat_score"], 0.00, "device_compat_score")
    assert ladder["compatible_device_count"] == 0, ladder


def test_an_absent_ladder_id_outranks_the_bindability_guard(api):
    """Binding a package to a never-minted `ladder_id` answers 404, not 409.

    PRD §2.6: "Every foreign key in the request body or query string resolves,
    checked in the order the endpoint declares its inputs, returning
    `ERR_TITLE_NOT_FOUND`, `ERR_LADDER_NOT_FOUND`, `ERR_VENDOR_NOT_FOUND`,
    `ERR_DEVICE_PROFILE_NOT_FOUND` or `ERR_PACKAGE_NOT_FOUND` as appropriate."

    Design: Corner/validations/body_fk_lookup_beats_ladder_bindability_returns_not_found
    """
    title, _ladder = _rejected_ladder_world(api)
    response = api.create_drm_package(
        f.drm_package_payload(
            title["id"],
            UUID_ABSENT,
            drm_systems=["WIDEVINE"],
            license_server_url="https://lic.novapic.example/wv",
        ),
        DRM_OPERATOR,
    )
    validate_error(response, err.ERR_LADDER_NOT_FOUND, 404)


def test_naming_the_stored_rejected_ladder_exposes_the_bindability_rung(api):
    """The same create against the stored `REJECTED` ladder answers 409, and
    neither attempt stored a package.

    PRD §3.5: "A ladder in `REJECTED` or `SUPERSEDED` cannot be bound and
    answers `ERR_LADDER_NOT_BINDABLE`."

    Design: Corner/validations/body_fk_lookup_beats_ladder_bindability_returns_not_found
    """
    title, ladder = _rejected_ladder_world(api)
    validate_error(
        api.create_drm_package(
            f.drm_package_payload(
                title["id"],
                UUID_ABSENT,
                drm_systems=["WIDEVINE"],
                license_server_url="https://lic.novapic.example/wv",
            ),
            DRM_OPERATOR,
        ),
        err.ERR_LADDER_NOT_FOUND,
        404,
    )
    validate_error(
        api.create_drm_package(
            f.drm_package_payload(
                title["id"],
                ladder["id"],
                drm_systems=["WIDEVINE"],
                license_server_url="https://lic.novapic.example/wv",
            ),
            DRM_OPERATOR,
        ),
        err.ERR_LADDER_NOT_BINDABLE,
        409,
    )

    rows, meta = validate_paginated(
        api.list_drm_packages(DRM_OPERATOR, params={"title_id": title["id"]})
    )
    assert meta["total_count"] == 0, f"a rejected create stored a DrmPackage: {rows}"


# ---------------------------------------------------------------------------
# Rung 12 (optimistic concurrency) versus rung 17 (rung shape)
# ---------------------------------------------------------------------------

# Heights 720 then 480: a shape violation under rung 17, in stored array order.
_RUNGS_NOT_INCREASING = [
    {"label": "720p", "height_px": 720, "bitrate_kbps": 2500},
    {"label": "480p", "height_px": 480, "bitrate_kbps": 1200},
]


def _stale_and_fresh_versions(api):
    """A title whose captured `version` is invalidated by a later PATCH."""
    title = fx.create_title(
        api,
        external_ref="TTL-OCC-SHAPE",
        title_name="Occ Shape Cut",
        content_type="MOVIE",
        studio_code="NOVAPIC",
    )
    stale = fx.title_version(api, title["id"])
    validate_success(
        api.patch_title(
            title["id"],
            f.title_patch_payload(title_name="Occ Shape Cut (renamed)"),
            CONTENT_OPS,
        ),
        200,
    )
    fresh = fx.title_version(api, title["id"])
    return title, stale, fresh


def test_editing_a_title_bumps_the_version_by_exactly_one(api):
    """The PATCH that invalidates the captured token moves `version` from 1 to 2.

    PRD §3.1: "`ContentOps` may later edit `title_name`, `studio_code` and
    `encode_budget_usd`; every successful edit increments the title's `version`
    and refreshes its `updated_at`, which is precisely what invalidates a
    previously captured `expected_title_version`."

    Design: Corner/validations/stale_title_version_beats_rung_shape_check
    """
    _title, stale, fresh = _stale_and_fresh_versions(api)
    assert fresh == stale + 1, f"expected {stale} + 1, got {fresh}"


def test_a_stale_title_version_outranks_the_invalid_rung_shape(api):
    """A ladder create that is both version-stale and shape-invalid answers 412.

    PRD §2.7: "If that value does not equal the title's current `version`, the
    create is rejected with `ERR_STALE_TITLE_VERSION` and HTTP 412, and nothing
    is stored."

    Design: Corner/validations/stale_title_version_beats_rung_shape_check
    """
    title, stale, _fresh = _stale_and_fresh_versions(api)
    response = api.create_encoding_ladder(
        f.encoding_ladder_payload(
            title["id"], stale, codec_family="H264", rungs=_RUNGS_NOT_INCREASING
        ),
        ENCODING_ENGINEER,
    )
    validate_error(response, err.ERR_STALE_TITLE_VERSION, 412)


def test_the_current_version_exposes_the_rung_shape_check_and_nothing_persists(api):
    """Re-sending the identical rungs with the current version answers 409, and
    neither attempt stored a ladder or moved the title's `version`.

    PRD §3.3: "The array must hold between 2 and 8 elements, its `height_px`
    values must be strictly increasing in stored array order, and no `label` may
    repeat within the array; a violation of any of those three is
    `ERR_RUNG_SHAPE_INVALID`, while an empty array or an element missing one of
    the three keys is caught earlier as a payload violation."

    Design: Corner/validations/stale_title_version_beats_rung_shape_check
    """
    title, stale, fresh = _stale_and_fresh_versions(api)
    validate_error(
        api.create_encoding_ladder(
            f.encoding_ladder_payload(
                title["id"], stale, codec_family="H264", rungs=_RUNGS_NOT_INCREASING
            ),
            ENCODING_ENGINEER,
        ),
        err.ERR_STALE_TITLE_VERSION,
        412,
    )
    validate_error(
        api.create_encoding_ladder(
            f.encoding_ladder_payload(
                title["id"], fresh, codec_family="H264", rungs=_RUNGS_NOT_INCREASING
            ),
            ENCODING_ENGINEER,
        ),
        err.ERR_RUNG_SHAPE_INVALID,
        409,
    )

    rows, meta = validate_paginated(
        api.list_encoding_ladders(ENCODING_ENGINEER, params={"title_id": title["id"]})
    )
    assert meta["total_count"] == 0, f"a rejected create stored a ladder: {rows}"
    assert fx.title_version(api, title["id"]) == fresh, (
        "neither rejected create may increment the title's version"
    )


# ---------------------------------------------------------------------------
# Rung 10 (own-entity state) versus rung 11 (cross-entity guards)
# ---------------------------------------------------------------------------


def _draft_ladder_without_a_passed_master(api):
    """A title with one master left in `INGESTED` and one `DRAFT` ladder, with no
    device profile registered yet."""
    title = fx.create_title(
        api,
        external_ref="TTL-GATE-ORDER",
        title_name="Gate Order Cut",
        content_type="MOVIE",
        studio_code="NOVAPIC",
    )
    asset = fx.create_asset(
        api,
        title["id"],
        source_uri="s3://mez/gate-order.mxf",
        duration_seconds=3600,
        frame_rate=24.0,
        peak_audio_lufs=-24.0,
        artifact_defect_count=0,
        caption_languages=["en"],
        audio_language="en",
    )
    ladder = fx.create_ladder(api, title["id"], codec_family="H264")
    return title, asset, ladder


def _register_mobile_high_profile(api):
    return fx.create_device_profile(
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


def test_locking_a_draft_ladder_reports_its_own_state_not_the_missing_master(api):
    """A lock that is both wrongly-stated and unsupported by QC answers 409
    `ERR_LADDER_STATE_INVALID`.

    PRD §3.4: "An `EncodingEngineer` may lock a ladder whose `state` is
    `VALIDATED`; a ladder that is `DRAFT`, already `LOCKED`, `REJECTED` or
    `SUPERSEDED` answers `ERR_LADDER_STATE_INVALID`, which also means a second
    lock of the same ladder is refused."

    Design: Corner/validations/own_state_gate_beats_cross_entity_guard_on_lock
    """
    _title, _asset, ladder = _draft_ladder_without_a_passed_master(api)
    response = api.lock_encoding_ladder(ladder["id"], ENCODING_ENGINEER)
    validate_error(response, err.ERR_LADDER_STATE_INVALID, 409)


def test_the_two_rung_ladder_validates_to_a_coverage_discounted_18_00(api):
    """One 45.00-share profile and a two-rung ladder score exactly 18.00.

    PRD §3.3: "A coverage multiplier is taken as the lesser of 1.00 and the
    ladder's `rung_count` divided by the target of 5 rungs, so a two-rung ladder
    keeps only two fifths of the reach it would otherwise claim while a five-rung
    or longer ladder keeps all of it."

    Design: Corner/validations/own_state_gate_beats_cross_entity_guard_on_lock
    """
    _title, _asset, ladder = _draft_ladder_without_a_passed_master(api)
    validate_error(
        api.lock_encoding_ladder(ladder["id"], ENCODING_ENGINEER),
        err.ERR_LADDER_STATE_INVALID,
        409,
    )
    _register_mobile_high_profile(api)
    validated = validate_success(
        api.validate_encoding_ladder(ladder["id"], ENCODING_ENGINEER), 200
    )
    assert validated["state"] == "VALIDATED", validated
    assert_score(validated["device_compat_score"], 18.00, "device_compat_score")


def test_a_validated_ladder_exposes_the_cross_entity_qc_guard(api):
    """Once the ladder is `VALIDATED` the identical lock answers 409
    `ERR_NO_PASSED_ASSET`, and nothing locked.

    PRD §3.4: "Two cross-entity guards then apply, both drawn from the
    quality-control desk's work rather than the encoding desk's: the title must
    own at least one master whose `qc_state` is `QC_PASSED`, otherwise
    `ERR_NO_PASSED_ASSET`, and no master of the title may sit in
    `REMEDIATION_REQUESTED`, otherwise `ERR_ASSET_REMEDIATION_PENDING` — the
    second holds even when another master has already passed."

    Design: Corner/validations/own_state_gate_beats_cross_entity_guard_on_lock
    """
    title, asset, ladder = _draft_ladder_without_a_passed_master(api)
    validate_error(
        api.lock_encoding_ladder(ladder["id"], ENCODING_ENGINEER),
        err.ERR_LADDER_STATE_INVALID,
        409,
    )
    _register_mobile_high_profile(api)
    fx.validate_ladder(api, ladder["id"])

    validate_error(
        api.lock_encoding_ladder(ladder["id"], ENCODING_ENGINEER),
        err.ERR_NO_PASSED_ASSET,
        409,
    )
    assert fx.read_ladder(api, ladder["id"])["state"] == "VALIDATED"
    assert fx.read_title(api, title["id"])["locked_ladder_count"] == 0
    assert fx.read_asset(api, asset["id"])["qc_state"] == "INGESTED"


# ---------------------------------------------------------------------------
# Rung 10's routing-policy exemption
# ---------------------------------------------------------------------------


def _single_vendor_policy_world(api):
    """One title and exactly one vendor serving US, so the policy is created
    `STANDBY_ONLY` and a single re-steer exhausts the candidate pool."""
    title = fx.create_title(
        api,
        external_ref="TTL-RESTEER-OK",
        title_name="Resteer Exempt Cut",
        content_type="MOVIE",
        studio_code="NOVAPIC",
    )
    vendor = fx.create_vendor(
        api,
        vendor_code="SOLOCDN",
        regions=["US"],
        committed_gbps=30.00,
        cost_per_gb_usd=0.0200,
    )
    policy = fx.create_policy(
        api, title["id"], region_code="US", steering_mode="PERFORMANCE"
    )
    return title, vendor, policy


def test_a_lone_candidate_creates_the_policy_standby_only(api):
    """With exactly one eligible vendor the new policy is `STANDBY_ONLY` with a
    null backup.

    PRD §3.7: "Assignment third: `primary_vendor_id` becomes the first-ranked
    candidate, `backup_vendor_id` becomes the second-ranked candidate when two or
    more candidates survive and is null otherwise, `state` becomes `ACTIVE` with
    two or more candidates and `STANDBY_ONLY` with exactly one, and
    `selection_reason_code` records which branch chose the primary —
    `PERFORMANCE_RANK`, `COST_RANK` or `WEIGHTED_RANK` according to the mode."

    Design: Corner/validations/resteer_of_an_unroutable_policy_is_accepted
    """
    _title, vendor, policy = _single_vendor_policy_world(api)
    assert policy["state"] == "STANDBY_ONLY", policy
    assert policy["primary_vendor_id"] == vendor["id"], policy
    assert policy["backup_vendor_id"] is None, policy


def test_a_resteer_that_exhausts_the_pool_is_accepted_and_goes_unroutable(api):
    """Excluding the only candidate answers 200 and drives the policy
    `UNROUTABLE` rather than failing a state or cardinality rung.

    PRD §2.6: "A re-steer of a policy whose `excluded_vendor_ids` already covers
    every eligible vendor is *not* an error under this rung — it is accepted and
    drives the policy to `UNROUTABLE`."

    Design: Corner/validations/resteer_of_an_unroutable_policy_is_accepted
    """
    _title, vendor, policy = _single_vendor_policy_world(api)
    resteered = validate_success(
        api.resteer_routing_policy(policy["id"], DELIVERY_ENGINEER), 200
    )
    assert resteered["state"] == "UNROUTABLE", resteered
    assert resteered["primary_vendor_id"] is None, resteered
    assert resteered["backup_vendor_id"] is None, resteered
    assert resteered["selection_reason_code"] == "NO_CANDIDATE", resteered
    assert resteered["excluded_vendor_ids"] == [vendor["id"]], resteered
    assert resteered["resteer_count"] == 1, resteered
    assert_money(
        resteered["projected_egress_cost_usd"], 0.00, "projected_egress_cost_usd"
    )


def test_resteering_an_already_unroutable_policy_only_bumps_the_counter(api):
    """A second re-steer of an `UNROUTABLE` policy still answers 200 and moves
    only `resteer_count`, from 1 to 2.

    PRD §3.7: "From `UNROUTABLE`, when no candidate is available, the policy
    stays `UNROUTABLE`: both vendor slots stay null, `selection_reason_code`
    stays `NO_CANDIDATE`, `excluded_vendor_ids` is unchanged because there is no
    outgoing primary to exclude, and `projected_egress_cost_usd` stays 0.00."

    Design: Corner/validations/resteer_of_an_unroutable_policy_is_accepted
    """
    _title, vendor, policy = _single_vendor_policy_world(api)
    first = fx.resteer_policy(api, policy["id"])
    assert first["resteer_count"] == 1, first

    second = validate_success(
        api.resteer_routing_policy(policy["id"], DELIVERY_ENGINEER), 200
    )
    assert second["resteer_count"] == 2, second
    assert second["state"] == "UNROUTABLE", second
    assert second["primary_vendor_id"] is None, second
    assert second["backup_vendor_id"] is None, second
    assert second["selection_reason_code"] == "NO_CANDIDATE", second
    assert second["excluded_vendor_ids"] == [vendor["id"]], second
    assert_money(second["projected_egress_cost_usd"], 0.00, "projected_egress_cost_usd")


# ---------------------------------------------------------------------------
# Rung 15 — a metric window closed exactly at the clock
# ---------------------------------------------------------------------------


def _metric_ingest_world(api):
    """One title, one `ACTIVE` MOBILE_HIGH profile and one vendor serving US, with
    the logical clock left at its startup instant."""
    title = fx.create_title(
        api,
        external_ref="TTL-METRIC-CLOCK",
        title_name="Clock Bound Cut",
        content_type="MOVIE",
        studio_code="NOVAPIC",
    )
    profile = _register_mobile_high_profile(api)
    vendor = fx.create_vendor(
        api,
        vendor_code="CLOCKCDN",
        regions=["US"],
        committed_gbps=25.00,
        cost_per_gb_usd=0.0200,
    )
    return title, profile, vendor


def _clock_bounded_metric_payload(title, profile, vendor, window_end_at):
    return f.playback_metric_payload(
        title["id"],
        profile["id"],
        vendor["id"],
        region_code="US",
        window_start_at="2026-07-31T00:00:00Z",
        window_end_at=window_end_at,
        play_attempts=1000,
        rebuffer_events=0,
        startup_ms_p95=1000,
        error_count=0,
    )


def test_a_metric_window_ending_exactly_at_the_clock_is_ingested(api):
    """A window whose `window_end_at` equals the clock is accepted at 201 with a
    `quality_index` of 100.00 and no breach.

    PRD §3.7: "Finally the `quality_index` is 100.00 reduced by that penalty,
    clamped into the range 0.00 to 100.00, and rounded half up to two decimals,
    and the `breach_flag` is true exactly when `quality_index` is strictly below
    70.00; a `quality_index` of exactly 70.00 is not a breach while 69.99 is."

    Design: Corner/validations/metric_window_ending_at_the_clock_accepted_and_one_second_later_rejected
    """
    title, profile, vendor = _metric_ingest_world(api)
    window = validate_success(
        api.create_playback_metric(
            _clock_bounded_metric_payload(
                title, profile, vendor, "2026-08-01T00:00:00Z"
            ),
            DELIVERY_ENGINEER,
        ),
        201,
    )
    assert_score(window["quality_index"], 100.00, "quality_index")
    assert window["breach_flag"] is False, window


def test_a_metric_window_ending_one_second_later_is_refused_as_in_future(api):
    """The same window ending one second past the clock answers 422, leaving
    exactly one stored window and the vendor's health untouched.

    PRD §3.7: "The window must already be closed against the logical clock — a
    `window_end_at` strictly after the current clock is
    `ERR_METRIC_WINDOW_IN_FUTURE` — and the named vendor must actually serve the
    named region, meaning `region_code` appears in that vendor's `regions`,
    otherwise `ERR_VENDOR_REGION_NOT_SERVED`."

    Design: Corner/validations/metric_window_ending_at_the_clock_accepted_and_one_second_later_rejected
    """
    title, profile, vendor = _metric_ingest_world(api)
    validate_success(
        api.create_playback_metric(
            _clock_bounded_metric_payload(
                title, profile, vendor, "2026-08-01T00:00:00Z"
            ),
            DELIVERY_ENGINEER,
        ),
        201,
    )
    validate_error(
        api.create_playback_metric(
            _clock_bounded_metric_payload(
                title, profile, vendor, "2026-08-01T00:00:01Z"
            ),
            DELIVERY_ENGINEER,
        ),
        err.ERR_METRIC_WINDOW_IN_FUTURE,
        422,
    )

    rows, meta = validate_paginated(
        api.list_playback_metrics(PLATFORM_ADMIN, params={"vendor_id": vendor["id"]})
    )
    assert meta["total_count"] == 1, f"expected exactly one metric window: {rows}"

    stored_vendor = fx.read_vendor(api, vendor["id"])
    assert_score(
        stored_vendor["health_score_rolling"], 100.00, "health_score_rolling"
    )
    assert stored_vendor["breach_window_count"] == 0, stored_vendor


# ---------------------------------------------------------------------------
# Rung 11's cascading reprocess arm
# ---------------------------------------------------------------------------


def _title_with_a_draft_source_ladder(api):
    """One title carrying a `DRAFT` H264 ladder and no source masters at all."""
    title = fx.create_title(
        api,
        external_ref="TTL-REPROC-CASCADE",
        title_name="Cascade Check Cut",
        content_type="MOVIE",
        studio_code="NOVAPIC",
    )
    ladder = fx.create_ladder(api, title["id"], codec_family="H264")
    return title, ladder


def _hevc_job_payload(api, title, ladder):
    return f.reprocess_job_payload(
        title["id"],
        ladder["id"],
        fx.title_version(api, title["id"]),
        trigger_reason="STANDARD_UPDATE",
        target_codec_family="HEVC",
    )


def test_a_title_with_no_master_at_all_skips_the_ladder_lock_rung(api):
    """With zero source masters the job create reports 422, not the 409 the
    unlocked source ladder would otherwise earn.

    PRD §2.6: "A title with no eligible source master therefore skips this rung
    entirely and falls through to rung 18's `ERR_REPROCESS_NO_SOURCE_ASSET` (422)
    instead of reporting `ERR_LADDER_NOT_LOCKED`."

    Design: Corner/validations/reprocess_source_checks_cascade_from_asset_pool_to_ladder_state
    """
    title, ladder = _title_with_a_draft_source_ladder(api)
    validate_error(
        api.create_reprocess_job(
            _hevc_job_payload(api, title, ladder), ENCODING_ENGINEER
        ),
        err.ERR_REPROCESS_NO_SOURCE_ASSET,
        422,
    )

    rows, meta = validate_paginated(
        api.list_reprocess_jobs(ENCODING_ENGINEER, params={"title_id": title["id"]})
    )
    assert meta["total_count"] == 0, f"a rejected create stored a job: {rows}"


def test_one_ingested_master_flips_the_same_create_to_the_lock_rung(api):
    """Registering a single `INGESTED` master turns the identical create from 422
    into 409 `ERR_LADDER_NOT_LOCKED`, and still stores no job.

    PRD §3.9: "And there must be something to re-encode: a title whose every
    master is `QC_REJECTED`, or which owns no master at all, is
    `ERR_REPROCESS_NO_SOURCE_ASSET`, which as §2.6 explains wins over
    `ERR_LADDER_NOT_LOCKED` even when the named source ladder is also not
    `LOCKED`."

    Design: Corner/validations/reprocess_source_checks_cascade_from_asset_pool_to_ladder_state
    """
    title, ladder = _title_with_a_draft_source_ladder(api)
    validate_error(
        api.create_reprocess_job(
            _hevc_job_payload(api, title, ladder), ENCODING_ENGINEER
        ),
        err.ERR_REPROCESS_NO_SOURCE_ASSET,
        422,
    )

    asset = validate_success(
        api.create_mezzanine_asset(
            f.mezzanine_asset_payload(
                title["id"], source_uri="s3://mez/cascade.mxf", duration_seconds=3600
            ),
            CONTENT_OPS,
        ),
        201,
    )
    assert asset["qc_state"] == "INGESTED", asset

    validate_error(
        api.create_reprocess_job(
            _hevc_job_payload(api, title, ladder), ENCODING_ENGINEER
        ),
        err.ERR_LADDER_NOT_LOCKED,
        409,
    )

    rows, meta = validate_paginated(
        api.list_reprocess_jobs(ENCODING_ENGINEER, params={"title_id": title["id"]})
    )
    assert meta["total_count"] == 0, f"a rejected create stored a job: {rows}"


# ---------------------------------------------------------------------------
# Rung 14 — a ladder from another title's catalog
# ---------------------------------------------------------------------------


def _two_titles_one_ladder(api):
    """Titles A and B, with the only `DRAFT` H264 ladder belonging to B."""
    title_a = fx.create_title(
        api,
        external_ref="TTL-MISMATCH-A",
        title_name="Mismatch A",
        content_type="MOVIE",
        studio_code="NOVAPIC",
    )
    title_b = fx.create_title(
        api,
        external_ref="TTL-MISMATCH-B",
        title_name="Mismatch B",
        content_type="MOVIE",
        studio_code="NOVAPIC",
    )
    ladder_b = fx.create_ladder(api, title_b["id"], codec_family="H264")
    return title_a, title_b, ladder_b


def test_binding_a_package_across_titles_is_refused_and_leaves_a_unpackaged(api):
    """A bindable `DRAFT` ladder owned by title B cannot carry a package created
    for title A, and title A stays `UNPACKAGED`.

    PRD §3.5: "The payload names the `title_id` and the `ladder_id`, and that
    ladder must belong to the same title — a ladder from another title's catalog
    is `ERR_LADDER_TITLE_MISMATCH`."

    Design: Corner/validations/package_bound_to_another_titles_ladder_is_rejected
    """
    title_a, _title_b, ladder_b = _two_titles_one_ladder(api)
    validate_error(
        api.create_drm_package(
            f.drm_package_payload(
                title_a["id"],
                ladder_b["id"],
                drm_systems=["WIDEVINE"],
                license_server_url="https://lic.novapic.example/wv",
            ),
            DRM_OPERATOR,
        ),
        err.ERR_LADDER_TITLE_MISMATCH,
        422,
    )
    assert fx.read_title(api, title_a["id"])["packaging_state"] == "UNPACKAGED"


def test_the_same_package_against_the_ladders_own_title_is_created_pending(api):
    """The identical payload naming title B answers 201 in `PENDING`, with an
    `hdcp_floor` of `NONE` derived from the 720p peak.

    PRD §3.5: "The package's `hdcp_floor` is derived, not supplied: it reads
    `TYPE_1` when the bound ladder's `peak_height_px` is 2160 or greater,
    `TYPE_0` when that height is 1080 or greater but below 2160, and `NONE`
    otherwise."

    Design: Corner/validations/package_bound_to_another_titles_ladder_is_rejected
    """
    _title_a, title_b, ladder_b = _two_titles_one_ladder(api)
    package = validate_success(
        api.create_drm_package(
            f.drm_package_payload(
                title_b["id"],
                ladder_b["id"],
                drm_systems=["WIDEVINE"],
                license_server_url="https://lic.novapic.example/wv",
            ),
            DRM_OPERATOR,
        ),
        201,
    )
    assert package["state"] == "PENDING", package
    assert package["hdcp_floor"] == "NONE", package


# ---------------------------------------------------------------------------
# Rung 13 — offline playback against a non-persistent package
# ---------------------------------------------------------------------------


def _pending_package_without_persistent_licences(api):
    """A `PENDING` package on a 720p `DRAFT` ladder, created without
    `persistent_license_allowed` and therefore at its false default."""
    title = fx.create_title(
        api,
        external_ref="TTL-OFFLINE",
        title_name="Offline Rule Cut",
        content_type="MOVIE",
        studio_code="NOVAPIC",
    )
    ladder = fx.create_ladder(api, title["id"], codec_family="H264")
    package = fx.create_package(
        api,
        title["id"],
        ladder["id"],
        drm_systems=["WIDEVINE"],
        license_server_url="https://lic.novapic.example/wv",
    )
    return title, ladder, package


def _offline_rule_payload(offline_playback_allowed):
    return f.entitlement_rule_payload(
        region_code="*",
        subscription_tier="PREMIUM",
        max_concurrent_streams=3,
        max_playback_height_px=720,
        hdcp_level="NONE",
        offline_playback_allowed=offline_playback_allowed,
        priority=70,
    )


def test_an_offline_rule_on_a_non_persistent_package_is_refused(api):
    """Asking for offline playback on a package that forbids persistent licences
    answers 422 and attaches nothing.

    PRD §3.5: "A rule may not set `offline_playback_allowed` to true against a
    package whose `persistent_license_allowed` is false, otherwise
    `ERR_OFFLINE_NOT_LICENSED`."

    Design: Corner/validations/offline_rule_on_a_non_persistent_package_is_rejected
    """
    _title, _ladder, package = _pending_package_without_persistent_licences(api)
    validate_error(
        api.create_entitlement_rule(
            package["id"], _offline_rule_payload(True), DRM_OPERATOR
        ),
        err.ERR_OFFLINE_NOT_LICENSED,
        422,
    )
    assert fx.read_package(api, package["id"])["entitlement_rule_count"] == 0


def test_the_same_rule_without_offline_playback_is_attached(api):
    """The identical rule with `offline_playback_allowed` false answers 201 and
    lifts `entitlement_rule_count` to 1.

    PRD §3.5: "A successful attachment increments the package's
    `entitlement_rule_count` by one."

    Design: Corner/validations/offline_rule_on_a_non_persistent_package_is_rejected
    """
    _title, _ladder, package = _pending_package_without_persistent_licences(api)
    rule = validate_success(
        api.create_entitlement_rule(
            package["id"], _offline_rule_payload(False), DRM_OPERATOR
        ),
        201,
    )
    assert rule["offline_playback_allowed"] is False, rule
    assert fx.read_package(api, package["id"])["entitlement_rule_count"] == 1


# ---------------------------------------------------------------------------
# Rung 20 — the encode budget at one cent and at equality
# ---------------------------------------------------------------------------

_FOUR_RUNG_H264 = [
    f.rung("240p", 240, 400),
    f.rung("480p", 480, 1200),
    f.rung("720p", 720, 2500),
    f.rung("1080p", 1080, 5000),
]


def _budget_world(api, encode_budget_usd=229.31):
    """A title budgeted one cent short of its own queued AV1 job: one `ACTIVE`
    MOBILE_HIGH profile, one `QC_PASSED` ten-hour master, one `LOCKED` four-rung
    H264 ladder and one `QUEUED` `CODEC_DEPRECATION` job."""
    _register_mobile_high_profile(api)
    title = fx.create_title(
        api,
        external_ref="TTL-BUDGET-EQ",
        title_name="Budget Equality Cut",
        content_type="MOVIE",
        studio_code="NOVAPIC",
        encode_budget_usd=encode_budget_usd,
    )
    fx.create_passed_asset(
        api, title["id"], source_uri="s3://mez/budget.mxf", duration_seconds=36000
    )
    ladder = fx.create_locked_ladder(
        api, title["id"], codec_family="H264", rungs=[dict(r) for r in _FOUR_RUNG_H264]
    )
    job = fx.create_job(
        api,
        title["id"],
        ladder["id"],
        trigger_reason="CODEC_DEPRECATION",
        target_codec_family="AV1",
    )
    return title, ladder, job


def test_the_queued_job_freezes_its_cost_at_229_32_without_debiting(api):
    """Ten billable hours of AV1 over rungs of 400, 1200, 2500 and 5000 kilobits
    freeze at 229.32, with nothing committed yet.

    PRD §3.9: "A job that clears all four is stored in `state` `QUEUED` with
    `result_ladder_id` null, `committed_usd` 0.00, `abort_reason` `NONE`, and the
    title's `version` incremented by one."

    Design: Corner/validations/encode_budget_debit_rejected_one_cent_short_then_accepted_at_equality
    """
    title, _ladder, job = _budget_world(api)
    assert_money(job["cost_estimate_usd"], 229.32, "cost_estimate_usd")
    assert job["state"] == "QUEUED", job
    assert_money(job["committed_usd"], 0.00, "committed_usd")
    assert_money(
        fx.read_title(api, title["id"])["encode_budget_remaining_usd"],
        229.31,
        "encode_budget_remaining_usd",
    )


def test_a_cost_one_cent_above_the_remaining_budget_is_refused(api):
    """Running the job against a 229.31 budget answers 422 and leaves the job
    `QUEUED` with nothing debited.

    PRD §3.9: "The fit is generous at the boundary: a cost exactly equal to the
    remaining budget is accepted, and a cost one cent above it is refused with
    `ERR_ENCODE_BUDGET_EXCEEDED`."

    Design: Corner/validations/encode_budget_debit_rejected_one_cent_short_then_accepted_at_equality
    """
    title, _ladder, job = _budget_world(api)
    validate_error(
        api.run_reprocess_job(job["id"], ENCODING_ENGINEER),
        err.ERR_ENCODE_BUDGET_EXCEEDED,
        422,
    )

    stored_job = fx.read_job(api, job["id"])
    assert stored_job["state"] == "QUEUED", stored_job
    assert_money(stored_job["committed_usd"], 0.00, "committed_usd")
    assert_money(
        fx.read_title(api, title["id"])["encode_budget_remaining_usd"],
        229.31,
        "encode_budget_remaining_usd",
    )


def test_raising_the_budget_by_one_cent_admits_the_run_at_equality(api):
    """A budget PATCHed to exactly 229.32 admits the run, spends the budget to
    0.00, and leaves the frozen estimate untouched.

    PRD §3.9: "The **cost estimate** is computed once at creation and frozen onto
    `cost_estimate_usd`, `per_rung_cost_usd` and `priority_rank`; it is never
    recomputed, not when the source ladder changes, not when the title's budget
    changes, and not when the job runs."

    PRD §3.9: "On success the job's `state` becomes `RUNNING`, its `committed_usd`
    becomes its `cost_estimate_usd`, the title's `encode_budget_remaining_usd`
    falls by that amount and the title's `version` increments by one."

    Design: Corner/validations/encode_budget_debit_rejected_one_cent_short_then_accepted_at_equality
    """
    title, _ladder, job = _budget_world(api)
    validate_error(
        api.run_reprocess_job(job["id"], ENCODING_ENGINEER),
        err.ERR_ENCODE_BUDGET_EXCEEDED,
        422,
    )

    patched = validate_success(
        api.patch_title(
            title["id"],
            f.title_patch_payload(title_name=None, encode_budget_usd=229.32),
            CONTENT_OPS,
        ),
        200,
    )
    assert_money(patched["encode_budget_usd"], 229.32, "encode_budget_usd")
    assert_money(
        patched["encode_budget_remaining_usd"], 229.32, "encode_budget_remaining_usd"
    )

    ran = validate_success(api.run_reprocess_job(job["id"], ENCODING_ENGINEER), 200)
    assert ran["state"] == "RUNNING", ran
    assert_money(ran["committed_usd"], 229.32, "committed_usd")
    assert_money(ran["cost_estimate_usd"], 229.32, "cost_estimate_usd")
    assert_money(
        fx.read_title(api, title["id"])["encode_budget_remaining_usd"],
        0.00,
        "encode_budget_remaining_usd",
    )
