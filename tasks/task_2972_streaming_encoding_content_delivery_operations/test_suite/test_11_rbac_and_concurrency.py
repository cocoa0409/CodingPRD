"""Role-based access control and optimistic concurrency tests (PRD §2.1, §2.4, §2.6, §2.7).

Every test in this module starts from an empty database with the logical clock at
its startup default `2026-08-01T00:00:00Z` (PRD §2.5).  Two contracts are under
test here.  The first is the peer-role cut of §2.1: seven exact, case-sensitive
role names, six of them carrying an opaque operator identity and one — the
`VendorOperator` — entity-backed and scoped to its own vendor row, with rungs 3,
4 and 5 of the §2.6 ladder answering `ERR_ROLE_NOT_PERMITTED`,
`ERR_VENDOR_IDENTITY_UNKNOWN` and `ERR_VENDOR_SCOPE_VIOLATION`.  The second is
the optimistic-concurrency token of §2.7: `expected_title_version` on exactly
the two creates that take it, the `Title.version` counter it is compared
against, and the guarantee that a rejected write leaves the aggregate untouched.
"""

from prd_bench_local_runner.testing import validate_error, validate_success
from test_helpers import api_errors as err
from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.assertions import (
    assert_money,
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
    VENDOR_OPERATOR_UNKNOWN,
    make_vendor_operator_headers,
)

# ---------------------------------------------------------------------------
# Shared setup chains
# ---------------------------------------------------------------------------


def _peer_role_setup(api):
    """One title with one INGESTED master, one DRAFT ladder and one PENDING package.

    Each row is authored by the one desk §2.1 says owns it, so every later call
    is a genuine cross-desk attempt rather than a payload problem.
    """
    title = fx.create_title(
        api,
        external_ref="TTL-RBAC-PEER",
        title_name="Peer Roles Cut",
        content_type="MOVIE",
        studio_code="NOVAPIC",
    )
    asset = fx.create_asset(api, title["id"], source_uri="s3://mez/peer.mxf")
    ladder = fx.create_ladder(
        api, title["id"], codec_family="H264", rungs=[dict(r) for r in f.RUNGS_TWO_H264]
    )
    package = fx.create_package(
        api,
        title["id"],
        ladder["id"],
        drm_systems=["WIDEVINE"],
        license_server_url="https://lic.novapic.example/wv",
    )
    return title, asset, ladder, package


def _shared_reads_setup(api):
    """One title with one INGESTED master, ready for the shared read surface."""
    title = fx.create_title(
        api,
        external_ref="TTL-RBAC-SHARED",
        title_name="Shared Reads Cut",
        content_type="MOVIE",
        studio_code="NOVAPIC",
    )
    asset = fx.create_asset(api, title["id"], source_uri="s3://mez/shared.mxf")
    return title, asset


# ---------------------------------------------------------------------------
# §2.1 / §2.6 rung 3 — no role may perform a peer role's exclusive operation
# ---------------------------------------------------------------------------


def test_qc_desk_cannot_register_a_master_and_catalog_desk_cannot_judge_one(api):
    """A QcAnalyst registering a master, and a ContentOps running QC or requesting remediation, all answer 403 ERR_ROLE_NOT_PERMITTED with the master untouched.

    PRD §2.1: "`QcAnalyst` is the quality-control desk. It alone runs QC on an
    ingested master and requests remediation of a failure, and deliberately cannot
    register or edit the masters it judges."

    PRD §2.1: "It alone registers titles, edits title metadata and budget, issues
    legal takedowns, schedules and cancels licensing windows, registers source
    masters, and re-ingests corrected masters."

    Design: Corner/rbac/roles_cannot_perform_a_peer_roles_exclusive_operation
    """
    title, asset, _ladder, _package = _peer_role_setup(api)

    qc_authored = api.create_mezzanine_asset(
        f.mezzanine_asset_payload(
            title["id"], source_uri="s3://mez/qc-authored.mxf", duration_seconds=600
        ),
        QC_ANALYST,
    )
    validate_error(qc_authored, err.ERR_ROLE_NOT_PERMITTED, 403)

    ops_ran_qc = api.run_qc(asset["id"], CONTENT_OPS)
    validate_error(ops_ran_qc, err.ERR_ROLE_NOT_PERMITTED, 403)

    ops_remediation = api.request_remediation(asset["id"], CONTENT_OPS)
    validate_error(ops_remediation, err.ERR_ROLE_NOT_PERMITTED, 403)

    rows, meta = validate_paginated(api.list_title_mezzanine_assets(title["id"], CONTENT_OPS))
    assert meta["total_count"] == 1, meta
    assert rows[0]["id"] == asset["id"], rows

    stored = validate_success(api.get_mezzanine_asset(asset["id"], QC_ANALYST), 200)
    assert stored["qc_state"] == "INGESTED", stored
    assert stored["qc_attempt_count"] == 0, stored

    reports, report_meta = validate_paginated(api.list_qc_reports(asset["id"], QC_ANALYST))
    assert report_meta["total_count"] == 0, report_meta
    assert reports == [], reports


def test_platform_admin_cannot_register_a_title_or_author_a_ladder(api):
    """A PlatformAdmin registering a title or authoring an encoding ladder answers 403 ERR_ROLE_NOT_PERMITTED, leaving exactly one title and one ladder stored.

    PRD §2.1: "`PlatformAdmin` is emphatically **not** an override role: it cannot
    create titles, ladders, packages, policies or reservations."

    PRD §2.1: "They are **peer** roles, not a hierarchy: each owns a different
    slice of the pipeline and no role is a superset of another."

    Design: Corner/rbac/roles_cannot_perform_a_peer_roles_exclusive_operation
    """
    title, _asset, ladder, _package = _peer_role_setup(api)
    version_before = fx.title_version(api, title["id"])

    admin_title = api.create_title(
        f.title_payload(
            external_ref="TTL-RBAC-ADMIN",
            title_name="Admin Authored Cut",
            content_type="MOVIE",
            studio_code="NOVAPIC",
        ),
        PLATFORM_ADMIN,
    )
    validate_error(admin_title, err.ERR_ROLE_NOT_PERMITTED, 403)

    admin_ladder = api.create_encoding_ladder(
        f.encoding_ladder_payload(
            title["id"],
            version_before,
            codec_family="HEVC",
            rungs=[dict(r) for r in f.RUNGS_TWO_H264],
        ),
        PLATFORM_ADMIN,
    )
    validate_error(admin_ladder, err.ERR_ROLE_NOT_PERMITTED, 403)

    _rows, title_meta = validate_paginated(api.list_titles(CONTENT_OPS))
    assert title_meta["total_count"] == 1, title_meta

    ladder_rows, ladder_meta = validate_paginated(
        api.list_encoding_ladders(ENCODING_ENGINEER, {"title_id": title["id"]})
    )
    assert ladder_meta["total_count"] == 1, ladder_meta
    assert ladder_rows[0]["id"] == ladder["id"], ladder_rows

    stored_title = validate_success(api.get_title(title["id"], CONTENT_OPS), 200)
    assert stored_title["version"] == version_before, stored_title


def test_action_endpoints_reject_the_neighbouring_desks_role(api):
    """A DeliveryEngineer locking a ladder, an EncodingEngineer packaging a DRM package and a DrmOperator creating a routing policy each answer 403 with nothing transitioned.

    PRD §2.1: "It alone authors, validates and locks encoding ladders and creates,
    runs and aborts reprocessing jobs."

    PRD §2.1: "It alone creates DRM packages, packages and revokes them, and
    attaches entitlement rules."

    PRD §2.1: "It alone creates routing policies and re-steers them, and alone
    creates, arms, fails over and cancels live-event reservations."

    Design: Corner/rbac/roles_cannot_perform_a_peer_roles_exclusive_operation
    """
    title, _asset, ladder, package = _peer_role_setup(api)

    delivery_locked = api.lock_encoding_ladder(ladder["id"], DELIVERY_ENGINEER)
    validate_error(delivery_locked, err.ERR_ROLE_NOT_PERMITTED, 403)

    encoder_packaged = api.package_drm_package(package["id"], ENCODING_ENGINEER)
    validate_error(encoder_packaged, err.ERR_ROLE_NOT_PERMITTED, 403)

    drm_policy = api.create_routing_policy(
        f.routing_policy_payload(title["id"], region_code="US", steering_mode="COST"),
        DRM_OPERATOR,
    )
    validate_error(drm_policy, err.ERR_ROLE_NOT_PERMITTED, 403)

    stored_ladder = validate_success(api.get_encoding_ladder(ladder["id"], ENCODING_ENGINEER), 200)
    assert stored_ladder["state"] == "DRAFT", stored_ladder

    stored_package = validate_success(api.get_drm_package(package["id"], DRM_OPERATOR), 200)
    assert stored_package["state"] == "PENDING", stored_package

    policy_rows, policy_meta = validate_paginated(api.list_routing_policies(DELIVERY_ENGINEER))
    assert policy_meta["total_count"] == 0, policy_meta
    assert policy_rows == [], policy_rows


def test_content_ops_cannot_register_a_device_profile(api):
    """A ContentOps operator registering a device profile answers 403 ERR_ROLE_NOT_PERMITTED and the matrix stays empty.

    PRD §2.1: "It alone sets the logical clock, registers device profiles and
    registers CDN vendors."

    PRD §2.6: "The caller's role appears in the endpoint's authorised-role list;
    otherwise `ERR_ROLE_NOT_PERMITTED` (403)."

    Design: Corner/rbac/roles_cannot_perform_a_peer_roles_exclusive_operation
    """
    _peer_role_setup(api)

    response = api.create_device_profile(
        f.device_profile_payload(
            device_class="MOBILE_LOW",
            max_height_px=480,
            supported_codecs=["H264"],
            min_bitrate_kbps=200,
            max_bitrate_kbps=2000,
            hdcp_required=False,
            required_drm_system="NONE",
            market_share_pct=10.00,
            quality_normalization_factor=0.60,
        ),
        CONTENT_OPS,
    )
    validate_error(response, err.ERR_ROLE_NOT_PERMITTED, 403)

    rows, meta = validate_paginated(api.list_device_profiles(PLATFORM_ADMIN))
    assert meta["total_count"] == 0, meta
    assert rows == [], rows


def test_qc_analyst_cannot_list_the_catalog(api):
    """A QcAnalyst listing the catalog answers 403 ERR_ROLE_NOT_PERMITTED, because the catalog list's authorised-role list omits that desk.

    PRD §2.1: "Only once the role is recognised does the system ask whether that
    role is authorised for the requested operation; when it is not, the answer is
    `ERR_ROLE_NOT_PERMITTED` (HTTP 403)."

    PRD §2.6: "The caller's role appears in the endpoint's authorised-role list;
    otherwise `ERR_ROLE_NOT_PERMITTED` (403)."

    Design: Corner/rbac/roles_cannot_perform_a_peer_roles_exclusive_operation
    """
    _peer_role_setup(api)

    response = api.list_titles(QC_ANALYST)
    validate_error(response, err.ERR_ROLE_NOT_PERMITTED, 403)


# ---------------------------------------------------------------------------
# §2.1 — the shared surface answers for every role that lists it
# ---------------------------------------------------------------------------


def test_single_title_read_answers_for_all_six_opaque_roles(api):
    """GET /titles/{id} answers 200 with the same title id for ContentOps, QcAnalyst, EncodingEngineer, DrmOperator, DeliveryEngineer and PlatformAdmin alike.

    PRD §2.1: "Six of the seven roles carry an **opaque** identity: when
    `X-User-Role` is `ContentOps`, `QcAnalyst`, `EncodingEngineer`, `DrmOperator`,
    `DeliveryEngineer` or `PlatformAdmin`, the accompanying `X-User-ID` is an
    operator identifier that is not tied to any persisted entity."

    PRD §2.1: "Every read endpoint listed for the other roles is also readable by
    `PlatformAdmin`, including the per-asset QC report list, which is readable by
    exactly `ContentOps`, `QcAnalyst` and `PlatformAdmin`."

    Design: Corner/rbac/shared_operations_work_for_every_role_that_lists_them
    """
    title, _asset = _shared_reads_setup(api)

    for headers in (
        CONTENT_OPS,
        QC_ANALYST,
        ENCODING_ENGINEER,
        DRM_OPERATOR,
        DELIVERY_ENGINEER,
        PLATFORM_ADMIN,
    ):
        response = api.get_title(title["id"], headers)
        data = validate_unpaginated(response, 200)
        assert data["id"] == title["id"], (headers, data)
        assert response.json()["response_type"] == "object", response.json()


def test_qc_report_list_answers_for_exactly_the_three_roles_that_own_it(api):
    """The per-asset QC report list answers 200 with zero reports for ContentOps, QcAnalyst and PlatformAdmin.

    PRD §2.1: "Every read endpoint listed for the other roles is also readable by
    `PlatformAdmin`, including the per-asset QC report list, which is readable by
    exactly `ContentOps`, `QcAnalyst` and `PlatformAdmin`."

    PRD §3.2: "The per-attempt evidence is only observable through a master's
    report list, which returns its reports ordered by `attempt_number` ascending."

    Design: Corner/rbac/shared_operations_work_for_every_role_that_lists_them
    """
    _title, asset = _shared_reads_setup(api)

    for headers in (QC_ANALYST, CONTENT_OPS, PLATFORM_ADMIN):
        rows, meta = validate_paginated(api.list_qc_reports(asset["id"], headers))
        assert meta["total_count"] == 0, (headers, meta)
        assert rows == [], (headers, rows)


def test_availability_sweep_answers_for_both_platform_admin_and_content_ops(api):
    """POST /availability-sweep answers 200 with all nine counters at zero for a PlatformAdmin and then for a ContentOps.

    PRD §2.5: "The consequences of time passing are applied by the **availability
    sweep**, an operations checkpoint runnable by `PlatformAdmin` or `ContentOps`."

    PRD §2.5: "The sweep is idempotent for a fixed clock value: running it a second
    time without moving the clock transitions nothing and returns all nine counts as
    zero."

    Design: Corner/rbac/shared_operations_work_for_every_role_that_lists_them
    """
    _shared_reads_setup(api)

    admin_counters = validate_unpaginated(api.run_availability_sweep(PLATFORM_ADMIN), 200)
    assert_sweep_counters(admin_counters)

    ops_counters = validate_unpaginated(api.run_availability_sweep(CONTENT_OPS), 200)
    assert_sweep_counters(ops_counters)


def test_metric_ingest_answers_for_both_delivery_engineer_and_platform_admin(api):
    """Two clean measurement windows ingested by a DeliveryEngineer and then by a PlatformAdmin each answer 201 with quality_index 100.00, leaving both vendor health variants at 100.00.

    PRD §2.1: "It shares the availability sweep with `ContentOps`, metric ingestion
    with `DeliveryEngineer`, and vendor updates with `VendorOperator`."

    PRD §3.7: "Finally the `quality_index` is 100.00 reduced by that penalty,
    clamped into the range 0.00 to 100.00, and rounded half up to two decimals, and
    the `breach_flag` is true exactly when `quality_index` is strictly below 70.00;
    a `quality_index` of exactly 70.00 is not a breach while 69.99 is."

    PRD §3.7: "The `health_score_contract` variant instead takes every row and
    computes a `play_attempts`-weighted mean: the sum over all rows of
    `quality_index` multiplied by `play_attempts`, divided by the sum of
    `play_attempts` across those rows, rounded half up to two decimals, and again
    100.00 when no rows exist."

    Design: Corner/rbac/shared_operations_work_for_every_role_that_lists_them
    """
    title, _asset = _shared_reads_setup(api)
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
        api, vendor_code="SHAREDCDN", regions=["US"], committed_gbps=60.00, cost_per_gb_usd=0.0200
    )

    window_one = f.playback_metric_payload(
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
    )
    delivery_metric = validate_success(
        api.create_playback_metric(window_one, DELIVERY_ENGINEER), 201
    )
    assert_score(delivery_metric["quality_index"], 100.00, "quality_index")
    assert delivery_metric["breach_flag"] is False, delivery_metric
    assert_ratio_4dp(delivery_metric["rebuffer_ratio"], 0.0000, "rebuffer_ratio")

    window_two = f.playback_metric_payload(
        title["id"],
        profile["id"],
        vendor["id"],
        region_code="US",
        window_start_at="2026-07-01T01:00:00Z",
        window_end_at="2026-07-01T02:00:00Z",
        play_attempts=100,
        rebuffer_events=0,
        startup_ms_p95=1500,
        error_count=0,
    )
    admin_metric = validate_success(api.create_playback_metric(window_two, PLATFORM_ADMIN), 201)
    assert_score(admin_metric["quality_index"], 100.00, "quality_index")
    assert admin_metric["breach_flag"] is False, admin_metric

    stored_vendor = validate_success(api.get_cdn_vendor(vendor["id"], PLATFORM_ADMIN), 200)
    assert_score(stored_vendor["health_score_rolling"], 100.00, "health_score_rolling")
    assert_score(stored_vendor["health_score_contract"], 100.00, "health_score_contract")
    assert stored_vendor["breach_window_count"] == 0, stored_vendor
    assert stored_vendor["state"] == "ACTIVE", stored_vendor


# ---------------------------------------------------------------------------
# §2.1 / §2.6 rung 4 — a VendorOperator identity that was never issued
# ---------------------------------------------------------------------------


def test_unresolvable_vendor_operator_cannot_read_a_vendor_record(api):
    """A VendorOperator whose X-User-ID names no stored CdnVendor is refused 403 ERR_VENDOR_IDENTITY_UNKNOWN when reading a vendor that does exist, and that vendor stays at version 1.

    PRD §2.1: "First, that identifier must resolve: if no stored `CdnVendor` has
    that `id`, the request fails with `ERR_VENDOR_IDENTITY_UNKNOWN` (HTTP 403), and
    this check applies to every endpoint whose authorised-role list contains
    `VendorOperator`."

    PRD §2.6: "When the role is `VendorOperator`, `X-User-ID` equals the `id` of an
    existing `CdnVendor`; otherwise `ERR_VENDOR_IDENTITY_UNKNOWN` (403)."

    Design: Corner/rbac/vendor_operator_with_an_unknown_identity_is_forbidden
    """
    vendor = fx.create_vendor(
        api, vendor_code="REALCDN", regions=["US"], committed_gbps=60.00, cost_per_gb_usd=0.0200
    )

    response = api.get_cdn_vendor(vendor["id"], VENDOR_OPERATOR_UNKNOWN)
    validate_error(response, err.ERR_VENDOR_IDENTITY_UNKNOWN, 403)

    stored = validate_success(api.get_cdn_vendor(vendor["id"], PLATFORM_ADMIN), 200)
    assert stored["version"] == 1, stored


def test_unresolvable_vendor_identity_outranks_the_scope_check_on_a_metric_list(api):
    """A VendorOperator whose identity does not resolve is refused ERR_VENDOR_IDENTITY_UNKNOWN — not ERR_VENDOR_SCOPE_VIOLATION — when it lists playback metrics filtered to somebody else's vendor id.

    PRD §2.6: "The **first** rule violated determines the single error returned, and
    no later rule is evaluated once a rule has fired — even when a later rule's
    condition also holds."

    PRD §2.6: "When the role is `VendorOperator`, `X-User-ID` equals the `id` of an
    existing `CdnVendor`; otherwise `ERR_VENDOR_IDENTITY_UNKNOWN` (403)."

    Design: Corner/rbac/vendor_operator_with_an_unknown_identity_is_forbidden
    """
    vendor = fx.create_vendor(
        api, vendor_code="REALCDN", regions=["US"], committed_gbps=60.00, cost_per_gb_usd=0.0200
    )

    response = api.list_playback_metrics(
        VENDOR_OPERATOR_UNKNOWN, {"vendor_id": vendor["id"]}
    )
    validate_error(response, err.ERR_VENDOR_IDENTITY_UNKNOWN, 403)

    stored = validate_success(api.get_cdn_vendor(vendor["id"], PLATFORM_ADMIN), 200)
    assert stored["version"] == 1, stored


# ---------------------------------------------------------------------------
# §2.1 / §2.6 rung 5 — a resolvable VendorOperator is scoped to its own row
# ---------------------------------------------------------------------------


def _two_vendors(api):
    """Two ACTIVE vendors, ALPHACDN at 0.0200 per GB and BRAVOCDN at 0.0300."""
    alpha = fx.create_vendor(
        api, vendor_code="ALPHACDN", regions=["US"], committed_gbps=60.00, cost_per_gb_usd=0.0200
    )
    bravo = fx.create_vendor(
        api, vendor_code="BRAVOCDN", regions=["US"], committed_gbps=60.00, cost_per_gb_usd=0.0300
    )
    return alpha, bravo


def test_vendor_operator_reads_its_own_row_but_not_its_neighbours(api):
    """ALPHACDN's operator reading BRAVOCDN's record is refused 403 ERR_VENDOR_SCOPE_VIOLATION, while the same operator reading its own record answers 200 with reserved_gbps 0.00.

    PRD §2.1: "A `VendorOperator` addressing another vendor's record, or listing any
    of those three collections without the required self-scoping filter, is rejected
    with `ERR_VENDOR_SCOPE_VIOLATION` (HTTP 403)."

    PRD §3.7: "A new vendor's `state` is `ACTIVE`, its `reserved_gbps` is 0.00, its
    `breach_window_count` is 0, and **both** health figures —
    `health_score_rolling` and `health_score_contract` — are seeded at 100.00, which
    is the value the health calculation yields when no measurement rows exist yet."

    Design: Corner/rbac/vendor_operator_cannot_read_another_vendors_row_or_an_unfiltered_list
    """
    alpha, bravo = _two_vendors(api)
    alpha_headers = make_vendor_operator_headers(alpha["id"])

    cross_read = api.get_cdn_vendor(bravo["id"], alpha_headers)
    validate_error(cross_read, err.ERR_VENDOR_SCOPE_VIOLATION, 403)

    own = validate_success(api.get_cdn_vendor(alpha["id"], alpha_headers), 200)
    assert own["id"] == alpha["id"], own
    assert own["state"] == "ACTIVE", own
    assert_money(own["reserved_gbps"], 0.00, "reserved_gbps")
    assert_ratio_4dp(own["cost_per_gb_usd"], 0.0200, "cost_per_gb_usd")


def test_vendor_operator_metric_list_needs_a_matching_self_scoping_filter(api):
    """ALPHACDN's operator listing playback metrics unfiltered, and then filtered to BRAVOCDN, is refused 403 ERR_VENDOR_SCOPE_VIOLATION both times, while the self-filtered list answers 200 with zero rows.

    PRD §2.1: "Second, the vendor's reach is scoped to itself: reading or updating a
    single vendor record requires the path identifier to equal `X-User-ID`; listing
    playback metrics requires a `vendor_id` filter equal to `X-User-ID`; listing live
    reservations requires one of `primary_vendor_id`, `failover_vendor_id` or
    `active_vendor_id` to be supplied and equal to `X-User-ID`; and listing routing
    policies requires `primary_vendor_id` or `backup_vendor_id` to be supplied and
    equal to `X-User-ID`."

    PRD §2.6: "Applies to exactly five operations: reading one CDN vendor, updating
    one CDN vendor, listing playback metrics, listing live reservations, and listing
    routing policies."

    Design: Corner/rbac/vendor_operator_cannot_read_another_vendors_row_or_an_unfiltered_list
    """
    alpha, bravo = _two_vendors(api)
    alpha_headers = make_vendor_operator_headers(alpha["id"])

    unfiltered = api.list_playback_metrics(alpha_headers)
    validate_error(unfiltered, err.ERR_VENDOR_SCOPE_VIOLATION, 403)

    cross_filtered = api.list_playback_metrics(alpha_headers, {"vendor_id": bravo["id"]})
    validate_error(cross_filtered, err.ERR_VENDOR_SCOPE_VIOLATION, 403)

    rows, meta = validate_paginated(
        api.list_playback_metrics(alpha_headers, {"vendor_id": alpha["id"]})
    )
    assert meta["total_count"] == 0, meta
    assert rows == [], rows


def test_vendor_operator_updates_only_its_own_commercial_terms(api):
    """ALPHACDN's operator repricing BRAVOCDN is refused 403 ERR_VENDOR_SCOPE_VIOLATION, while repricing its own row answers 200 with cost_per_gb_usd 0.0250 and version 2, leaving BRAVOCDN at 0.0300 and version 1.

    PRD §3.7: "Commercial terms are editable by `PlatformAdmin` or by the vendor's
    own `VendorOperator`, covering `committed_gbps`, `cost_per_gb_usd` and `regions`,
    and each successful update increments the vendor's `version`."

    PRD §2.1: "A `VendorOperator` addressing another vendor's record, or listing any
    of those three collections without the required self-scoping filter, is rejected
    with `ERR_VENDOR_SCOPE_VIOLATION` (HTTP 403)."

    Design: Corner/rbac/vendor_operator_cannot_read_another_vendors_row_or_an_unfiltered_list
    """
    alpha, bravo = _two_vendors(api)
    alpha_headers = make_vendor_operator_headers(alpha["id"])

    cross_patch = api.patch_cdn_vendor(
        bravo["id"], f.vendor_patch_payload(cost_per_gb_usd=0.0250), alpha_headers
    )
    validate_error(cross_patch, err.ERR_VENDOR_SCOPE_VIOLATION, 403)

    own_patch = validate_success(
        api.patch_cdn_vendor(
            alpha["id"], f.vendor_patch_payload(cost_per_gb_usd=0.0250), alpha_headers
        ),
        200,
    )
    assert_ratio_4dp(own_patch["cost_per_gb_usd"], 0.0250, "cost_per_gb_usd")
    assert own_patch["version"] == 2, own_patch

    untouched = validate_success(api.get_cdn_vendor(bravo["id"], PLATFORM_ADMIN), 200)
    assert_ratio_4dp(untouched["cost_per_gb_usd"], 0.0300, "cost_per_gb_usd")
    assert untouched["version"] == 1, untouched


# ---------------------------------------------------------------------------
# §2.7 / §2.6 rung 12 — the ladder-create concurrency token
# ---------------------------------------------------------------------------


def test_ladder_create_with_a_token_captured_before_an_edit_is_rejected(api):
    """A title metadata edit bumps version from 1 to 2, after which a ladder create carrying the pre-edit token 1 answers 412 ERR_STALE_TITLE_VERSION with no ladder stored and the version still 2.

    PRD §2.7: "Creating an `EncodingLadder` requires the non-optional input field
    `expected_title_version`, carrying the `version` the client last read from the
    target `Title`. If that value does not equal the title's current `version`, the
    create is rejected with `ERR_STALE_TITLE_VERSION` and HTTP 412, and nothing is
    stored."

    PRD §3.1: "`ContentOps` may later edit `title_name`, `studio_code` and
    `encode_budget_usd`; every successful edit increments the title's `version` and
    refreshes its `updated_at`, which is precisely what invalidates a previously
    captured `expected_title_version`."

    Design: Corner/cross_cutting_complexity_layers/stale_expected_title_version_on_ladder_create_is_rejected
    """
    title = fx.create_title(
        api,
        external_ref="TTL-OCC-LADDER",
        title_name="OCC Ladder Cut",
        content_type="MOVIE",
        studio_code="NOVAPIC",
    )
    version_old = title["version"]
    assert version_old == 1, title

    edited = validate_success(
        api.patch_title(
            title["id"],
            f.title_patch_payload(title_name="OCC Ladder Cut (edited)"),
            CONTENT_OPS,
        ),
        200,
    )
    version_new = edited["version"]
    assert version_new == version_old + 1, edited

    stale = api.create_encoding_ladder(
        f.encoding_ladder_payload(
            title["id"],
            version_old,
            codec_family="H264",
            rungs=[dict(r) for r in f.RUNGS_TWO_H264],
        ),
        ENCODING_ENGINEER,
    )
    validate_error(stale, err.ERR_STALE_TITLE_VERSION, 412)

    rows, meta = validate_paginated(
        api.list_encoding_ladders(ENCODING_ENGINEER, {"title_id": title["id"]})
    )
    assert meta["total_count"] == 0, meta
    assert rows == [], rows

    stored = validate_success(api.get_title(title["id"], CONTENT_OPS), 200)
    assert stored["version"] == version_new, stored


def test_ladder_create_with_the_re_read_token_succeeds_and_bumps_the_version_again(api):
    """Resubmitting the same ladder with the version re-read after the edit answers 201 with a DRAFT two-rung ladder and drives the title's version one further, its packaging_state still UNPACKAGED.

    PRD §2.7: "What makes a captured token go stale is any mutation that bumps
    `Title.version`: editing title metadata or budget, scheduling a licensing window,
    taking a title down manually, creating a ladder, locking a ladder, creating a
    reprocessing job, running one, and aborting a running one."

    PRD §3.4: "Otherwise, if any package is `PACKAGED`, it reads `PACKAGED`.
    Otherwise, if `locked_ladder_count` is 1 or more, it reads `PACKAGING`. Otherwise
    it reads `UNPACKAGED`."

    Design: Corner/cross_cutting_complexity_layers/stale_expected_title_version_on_ladder_create_is_rejected
    """
    title = fx.create_title(
        api,
        external_ref="TTL-OCC-LADDER",
        title_name="OCC Ladder Cut",
        content_type="MOVIE",
        studio_code="NOVAPIC",
    )
    edited = validate_success(
        api.patch_title(
            title["id"],
            f.title_patch_payload(title_name="OCC Ladder Cut (edited)"),
            CONTENT_OPS,
        ),
        200,
    )
    version_new = edited["version"]

    ladder = validate_success(
        api.create_encoding_ladder(
            f.encoding_ladder_payload(
                title["id"],
                version_new,
                codec_family="H264",
                rungs=[dict(r) for r in f.RUNGS_TWO_H264],
            ),
            ENCODING_ENGINEER,
        ),
        201,
    )
    assert ladder["state"] == "DRAFT", ladder
    assert ladder["rung_count"] == 2, ladder

    stored = validate_success(api.get_title(title["id"], CONTENT_OPS), 200)
    assert stored["version"] == version_new + 1, stored
    assert stored["packaging_state"] == "UNPACKAGED", stored


# ---------------------------------------------------------------------------
# §2.7 / §2.6 rung 12 — the reprocess-create concurrency token
# ---------------------------------------------------------------------------


def _occ_job_setup(api):
    """A title with a QC_PASSED master and one LOCKED H264 ladder, plus the
    version captured before the ladder was ever authored."""
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
        external_ref="TTL-OCC-JOB",
        title_name="OCC Job Cut",
        content_type="MOVIE",
        studio_code="NOVAPIC",
    )
    version_old = title["version"]
    fx.create_passed_asset(api, title["id"], source_uri="s3://mez/occjob.mxf")
    ladder = fx.create_locked_ladder(
        api,
        title["id"],
        expected_title_version=version_old,
        codec_family="H264",
        rungs=[dict(r) for r in f.RUNGS_TWO_H264],
    )
    version_new = fx.title_version(api, title["id"])
    return title, ladder, version_old, version_new


def test_reprocess_create_with_a_pre_lock_token_is_rejected_despite_a_locked_source(api):
    """The lock cascade has already bumped the title's version, so a reprocessing job carrying the pre-ladder token answers 412 ERR_STALE_TITLE_VERSION with no job stored and the budget still 5000.00.

    PRD §2.7: "Creating a `ReprocessJob` likewise requires `expected_title_version`
    as a non-optional input field carrying the client's last observed `Title`
    `version`, and likewise rejects a mismatch with `ERR_STALE_TITLE_VERSION` (HTTP
    412) without persisting anything."

    PRD §2.6: "Where a concurrency rule requires it, `expected_title_version` equals
    the current `version` of the target `Title`; otherwise `ERR_STALE_TITLE_VERSION`
    (412)."

    Design: Corner/cross_cutting_complexity_layers/stale_expected_title_version_on_reprocess_create_is_rejected
    """
    title, ladder, version_old, version_new = _occ_job_setup(api)
    assert version_new > version_old, (version_old, version_new)

    stale = api.create_reprocess_job(
        f.reprocess_job_payload(
            title["id"],
            ladder["id"],
            version_old,
            trigger_reason="STANDARD_UPDATE",
            target_codec_family="HEVC",
        ),
        ENCODING_ENGINEER,
    )
    validate_error(stale, err.ERR_STALE_TITLE_VERSION, 412)

    rows, meta = validate_paginated(
        api.list_reprocess_jobs(ENCODING_ENGINEER, {"title_id": title["id"]})
    )
    assert meta["total_count"] == 0, meta
    assert rows == [], rows

    stored = validate_success(api.get_title(title["id"], CONTENT_OPS), 200)
    assert_money(stored["encode_budget_remaining_usd"], 5000.00, "encode_budget_remaining_usd")
    assert stored["version"] == version_new, stored


def test_reprocess_create_with_the_current_token_queues_the_job_and_bumps_the_version(api):
    """The same reprocessing job resubmitted with the current token answers 201 in state QUEUED with committed_usd 0.00, and the title's version advances by exactly one.

    PRD §3.9: "A job that clears all four is stored in `state` `QUEUED` with
    `result_ladder_id` null, `committed_usd` 0.00, `abort_reason` `NONE`, and the
    title's `version` incremented by one."

    PRD §2.9: "A title's `encode_budget_remaining_usd` is always its
    `encode_budget_usd` minus the sum, rounded to two decimals, of
    `cost_estimate_usd` over that title's reprocessing jobs whose `state` is
    `RUNNING` or `COMPLETED`; jobs in `QUEUED`, `ABORTED` or `FAILED` contribute
    nothing and carry `committed_usd` of 0.00."

    Design: Corner/cross_cutting_complexity_layers/stale_expected_title_version_on_reprocess_create_is_rejected
    """
    title, ladder, _version_old, version_new = _occ_job_setup(api)

    job = validate_success(
        api.create_reprocess_job(
            f.reprocess_job_payload(
                title["id"],
                ladder["id"],
                version_new,
                trigger_reason="STANDARD_UPDATE",
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

    stored = validate_success(api.get_title(title["id"], CONTENT_OPS), 200)
    assert stored["version"] == version_new + 1, stored
    assert_money(stored["encode_budget_remaining_usd"], 5000.00, "encode_budget_remaining_usd")


# ---------------------------------------------------------------------------
# §2.4 / §2.7 — one version counter per aggregate, advanced only by a success
# ---------------------------------------------------------------------------


def test_title_and_vendor_version_counters_advance_independently(api):
    """A title edit takes the title from version 1 to 2 and a ladder create takes it to 3, while a vendor reprice moves that vendor from version 1 to 2 and touches no title counter.

    PRD §2.7: "What makes a captured token go stale is any mutation that bumps
    `Title.version`: editing title metadata or budget, scheduling a licensing window,
    taking a title down manually, creating a ladder, locking a ladder, creating a
    reprocessing job, running one, and aborting a running one."

    PRD §3.7: "Commercial terms are editable by `PlatformAdmin` or by the vendor's
    own `VendorOperator`, covering `committed_gbps`, `cost_per_gb_usd` and `regions`,
    and each successful update increments the vendor's `version`."

    Design: Corner/cross_cutting_complexity_layers/version_increments_on_every_successful_write_and_never_on_a_rejected_one
    """
    title = fx.create_title(
        api,
        external_ref="TTL-VER-CHAIN",
        title_name="Version Chain Cut",
        content_type="MOVIE",
        studio_code="NOVAPIC",
    )
    vendor = fx.create_vendor(
        api, vendor_code="VERCDN", regions=["US"], committed_gbps=30.00, cost_per_gb_usd=0.0200
    )
    assert title["version"] == 1, title
    assert vendor["version"] == 1, vendor

    edited = validate_success(
        api.patch_title(title["id"], f.title_patch_payload(studio_code="LUMEN"), CONTENT_OPS), 200
    )
    assert edited["version"] == 2, edited

    ladder = validate_success(
        api.create_encoding_ladder(
            f.encoding_ladder_payload(
                title["id"],
                edited["version"],
                codec_family="AV1",
                rungs=[
                    {"label": "480p", "height_px": 480, "bitrate_kbps": 900},
                    {"label": "1080p", "height_px": 1080, "bitrate_kbps": 3600},
                ],
            ),
            ENCODING_ENGINEER,
        ),
        201,
    )
    assert ladder["state"] == "DRAFT", ladder

    after_ladder = validate_success(api.get_title(title["id"], CONTENT_OPS), 200)
    assert after_ladder["version"] == 3, after_ladder

    repriced = validate_success(
        api.patch_cdn_vendor(
            vendor["id"], f.vendor_patch_payload(cost_per_gb_usd=0.0400), PLATFORM_ADMIN
        ),
        200,
    )
    assert repriced["version"] == 2, repriced
    assert_ratio_4dp(repriced["cost_per_gb_usd"], 0.0400, "cost_per_gb_usd")
    assert_money(repriced["reserved_gbps"], 0.00, "reserved_gbps")

    unmoved = validate_success(api.get_title(title["id"], CONTENT_OPS), 200)
    assert unmoved["version"] == 3, unmoved


def test_manual_takedown_is_one_more_increment_on_the_same_counter(api):
    """A manual takedown of a PUBLISHED title answers 200, advances the title's version by exactly one, and lands it in TAKEN_DOWN with takedown_reason MANUAL_LEGAL.

    PRD §3.6: "A manual takedown moves `availability_state` from `PUBLISHED` to
    `TAKEN_DOWN`, sets `takedown_reason` to `MANUAL_LEGAL`, increments the title's
    `version` by one, and closes every one of the title's `ACTIVE` windows with
    `closed_at` set to the logical clock's current instant."

    PRD §3.6: "The request carries `takedown_reason`, and only the value
    `MANUAL_LEGAL` is accepted here — `CONTRACT_END` belongs to the sweep and
    `PACKAGING_STALE` belongs to the packaging cascade, and neither may be asserted by
    an operator."

    Design: Corner/cross_cutting_complexity_layers/version_increments_on_every_successful_write_and_never_on_a_rejected_one
    """
    pipeline = fx.build_published_title(api)
    before = validate_success(api.get_title(pipeline.title_id, CONTENT_OPS), 200)
    assert before["availability_state"] == "PUBLISHED", before

    taken_down = validate_success(
        api.takedown_title(
            pipeline.title_id, f.takedown_payload(takedown_reason="MANUAL_LEGAL"), CONTENT_OPS
        ),
        200,
    )
    assert taken_down["availability_state"] == "TAKEN_DOWN", taken_down
    assert taken_down["takedown_reason"] == "MANUAL_LEGAL", taken_down
    assert taken_down["version"] == before["version"] + 1, (before, taken_down)


def test_a_rejected_write_advances_neither_version_counter(api):
    """A ladder create carrying a token that never existed is refused 412 and a vendor reprice by an unauthorised desk is refused 403, leaving the title and the vendor both at version 1.

    PRD §2.9: "The rule is that **every consequence is applied inside the originating
    request**, transitively, and each affected row's `updated_at` is refreshed and its
    `version` incremented, exactly as if it had been mutated directly."

    PRD §2.7: "Creating an `EncodingLadder` requires the non-optional input field
    `expected_title_version`, carrying the `version` the client last read from the
    target `Title`. If that value does not equal the title's current `version`, the
    create is rejected with `ERR_STALE_TITLE_VERSION` and HTTP 412, and nothing is
    stored."

    Design: Corner/cross_cutting_complexity_layers/version_increments_on_every_successful_write_and_never_on_a_rejected_one
    """
    title = fx.create_title(
        api,
        external_ref="TTL-VER-CHAIN",
        title_name="Version Chain Cut",
        content_type="MOVIE",
        studio_code="NOVAPIC",
    )
    vendor = fx.create_vendor(
        api, vendor_code="VERCDN", regions=["US"], committed_gbps=30.00, cost_per_gb_usd=0.0200
    )

    stale_ladder = api.create_encoding_ladder(
        f.encoding_ladder_payload(
            title["id"],
            99,
            codec_family="AV1",
            rungs=[
                {"label": "480p", "height_px": 480, "bitrate_kbps": 900},
                {"label": "1080p", "height_px": 1080, "bitrate_kbps": 3600},
            ],
        ),
        ENCODING_ENGINEER,
    )
    validate_error(stale_ladder, err.ERR_STALE_TITLE_VERSION, 412)

    forbidden_reprice = api.patch_cdn_vendor(
        vendor["id"], f.vendor_patch_payload(cost_per_gb_usd=0.0400), QC_ANALYST
    )
    validate_error(forbidden_reprice, err.ERR_ROLE_NOT_PERMITTED, 403)

    stored_title = validate_success(api.get_title(title["id"], CONTENT_OPS), 200)
    assert stored_title["version"] == 1, stored_title

    stored_vendor = validate_success(api.get_cdn_vendor(vendor["id"], PLATFORM_ADMIN), 200)
    assert stored_vendor["version"] == 1, stored_vendor
    assert_ratio_4dp(stored_vendor["cost_per_gb_usd"], 0.0200, "cost_per_gb_usd")


# ---------------------------------------------------------------------------
# §3.4 — the lock cascade steps over a REVOKED child
# ---------------------------------------------------------------------------


def _partial_cascade_setup(api):
    """A title with a LOCKED H264 ladder carrying one PACKAGED and one REVOKED
    package, plus a second VALIDATED H264 ladder waiting to be locked."""
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
        external_ref="TTL-PARTIAL-CASCADE",
        title_name="Partial Cascade Cut",
        content_type="MOVIE",
        studio_code="NOVAPIC",
    )
    fx.create_passed_asset(api, title["id"], source_uri="s3://mez/partial.mxf")
    ladder_one = fx.create_locked_ladder(
        api, title["id"], codec_family="H264", rungs=[dict(r) for r in f.RUNGS_TWO_H264]
    )
    keep = fx.create_packaged_package(
        api,
        title["id"],
        ladder_one["id"],
        drm_systems=["WIDEVINE"],
        license_server_url="https://lic.novapic.example/wv",
    )
    gone = fx.create_packaged_package(
        api,
        title["id"],
        ladder_one["id"],
        drm_systems=["PLAYREADY"],
        license_server_url="https://lic.novapic.example/pr",
    )
    fx.revoke_package(api, gone["id"])
    ladder_two = fx.create_ladder(
        api,
        title["id"],
        codec_family="H264",
        rungs=[
            {"label": "480p", "height_px": 480, "bitrate_kbps": 1500},
            {"label": "720p", "height_px": 720, "bitrate_kbps": 3000},
        ],
    )
    fx.validate_ladder(api, ladder_two["id"])
    return title, ladder_one, ladder_two, keep, gone


def test_locking_the_second_ladder_supersedes_the_first_of_the_same_codec_family(api):
    """Locking a second VALIDATED H264 ladder answers 200 with that ladder LOCKED and drives the first ladder to the terminal SUPERSEDED pointing back at its replacement.

    PRD §3.4: "Because this ladder locked, any *other* ladder of the same `title_id`
    **and** the same `codec_family` that was in `LOCKED` moves to the terminal
    `SUPERSEDED`, with its `superseded_by_ladder_id` pointing at the ladder that just
    locked."

    PRD §3.4: "The ladder moves from `VALIDATED` to `LOCKED`, the title's
    `locked_ladder_count` is recomputed as the number of that title's ladders in
    `LOCKED`, and the title's `version` increments by one."

    Design: Corner/cross_cutting_complexity_layers/cascade_skips_a_revoked_package_when_the_ladder_is_superseded
    """
    _title, ladder_one, ladder_two, _keep, _gone = _partial_cascade_setup(api)

    locked = validate_success(api.lock_encoding_ladder(ladder_two["id"], ENCODING_ENGINEER), 200)
    assert locked["state"] == "LOCKED", locked

    superseded = validate_success(
        api.get_encoding_ladder(ladder_one["id"], ENCODING_ENGINEER), 200
    )
    assert superseded["state"] == "SUPERSEDED", superseded
    assert superseded["superseded_by_ladder_id"] == ladder_two["id"], superseded


def test_only_the_packaged_child_goes_stale_while_the_revoked_one_is_untouched(api):
    """Of the two packages bound to the superseded ladder, the PACKAGED one becomes STALE with stale_reason LADDER_SUPERSEDED while the REVOKED one stays REVOKED with stale_reason NONE.

    PRD §3.4: "Because that ladder became `SUPERSEDED`, every DRM package bound to it
    whose `state` was `PACKAGED` moves to `STALE` with `stale_reason` of
    `LADDER_SUPERSEDED`."

    PRD §3.5: "Revocation from `PACKAGED` and from `STALE` recomputes
    `readiness_score_certified`; a `REVOKED` package is invisible to the entitlement
    selector, to compatibility scoring and to both readiness variants alike."

    Design: Corner/cross_cutting_complexity_layers/cascade_skips_a_revoked_package_when_the_ladder_is_superseded
    """
    _title, _ladder_one, ladder_two, keep, gone = _partial_cascade_setup(api)

    before_keep = validate_success(api.get_drm_package(keep["id"], DRM_OPERATOR), 200)
    assert before_keep["state"] == "PACKAGED", before_keep
    before_gone = validate_success(api.get_drm_package(gone["id"], DRM_OPERATOR), 200)
    assert before_gone["state"] == "REVOKED", before_gone

    validate_success(api.lock_encoding_ladder(ladder_two["id"], ENCODING_ENGINEER), 200)

    after_keep = validate_success(api.get_drm_package(keep["id"], DRM_OPERATOR), 200)
    assert after_keep["state"] == "STALE", after_keep
    assert after_keep["stale_reason"] == "LADDER_SUPERSEDED", after_keep

    after_gone = validate_success(api.get_drm_package(gone["id"], DRM_OPERATOR), 200)
    assert after_gone["state"] == "REVOKED", after_gone
    assert after_gone["stale_reason"] == "NONE", after_gone


def test_one_stale_package_is_enough_to_make_the_titles_packaging_dimension_stale(api):
    """The title's packaging_state moves from PACKAGED to STALE on the strength of the single STALE package, its locked_ladder_count is recomputed to 1, and availability_state stays DRAFT because hop 5 has no PUBLISHED title to take down.

    PRD §3.4: "If any DRM package of the title is `STALE`, the dimension reads
    `STALE`."

    PRD §3.4: "Packages in `REVOKED` are ignored by every branch of that precedence,
    as though they had never existed."

    PRD §3.4: "Whichever cause applies, the `SUPERSEDED` transition always carries
    the same two consequences beyond the state change itself: the ladder's
    `superseded_by_ladder_id` is set to the replacing ladder, every `PACKAGED` DRM
    package bound to the superseded ladder goes `STALE` with `stale_reason` of
    `LADDER_SUPERSEDED`, and the title's `locked_ladder_count` is recomputed."

    Design: Corner/cross_cutting_complexity_layers/cascade_skips_a_revoked_package_when_the_ladder_is_superseded
    """
    title, _ladder_one, ladder_two, _keep, _gone = _partial_cascade_setup(api)

    before = validate_success(api.get_title(title["id"], CONTENT_OPS), 200)
    assert before["packaging_state"] == "PACKAGED", before
    assert before["availability_state"] == "DRAFT", before

    validate_success(api.lock_encoding_ladder(ladder_two["id"], ENCODING_ENGINEER), 200)

    after = validate_success(api.get_title(title["id"], CONTENT_OPS), 200)
    assert after["packaging_state"] == "STALE", after
    assert after["availability_state"] == "DRAFT", after
    assert after["takedown_reason"] == "NONE", after
    assert after["locked_ladder_count"] == 1, after
