"""The two interval geometries (PRD §2.10) and the two conserved quantities (PRD §2.9).

Licensing intervals are half-open and buffer-free, so abutting windows are legal
and a true overlap is rejected outright; capacity intervals are closed and
inflated by each side's own `buffer_minutes`, so merely touching inflated
endpoints collides and the overlap is aggregated against the vendor's ceiling.
Bandwidth moves between vendors on a failover without changing in total, and an
aborted run returns `encode_budget_remaining_usd` to exactly its pre-run value.
"""

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import api_errors as err
from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.assertions import (
    assert_instant_equals,
    assert_money,
    validate_paginated,
)
from test_helpers.constants import INITIAL_CLOCK
from test_helpers.test_users import (
    CONTENT_OPS,
    DELIVERY_ENGINEER,
    ENCODING_ENGINEER,
    PLATFORM_ADMIN,
)


# ---------------------------------------------------------------------------
# Scenario builders (setup only; every assertion lives in a test)
# ---------------------------------------------------------------------------


def _build_buffer_geometry_scenario(api) -> dict:
    """Vendor ALPHA committed at 60.00 Gbps, a LIVE_EVENT title licensed in US
    from 2026-09-01 to 2026-11-01, and an incumbent reservation holding all
    60.00 Gbps over 18:00..22:00 with `buffer_minutes` 15."""
    vendor = fx.create_vendor(
        api,
        vendor_code="ALPHA",
        regions=["US"],
        committed_gbps=60.00,
        cost_per_gb_usd=0.0250,
    )
    title = fx.create_live_event_title(
        api,
        external_ref="TTL-BUFFER-01",
        title_name="Buffer Geometry Event",
        studio_code="NOVASPORT",
    )
    fx.create_window(
        api,
        title["id"],
        region_code="US",
        window_start_at="2026-09-01T00:00:00Z",
        window_end_at="2026-11-01T00:00:00Z",
        license_tier="STANDARD",
    )
    incumbent = fx.create_reservation(
        api,
        title["id"],
        vendor["id"],
        window_start_at="2026-09-10T18:00:00Z",
        window_end_at="2026-09-10T22:00:00Z",
        reserved_gbps=60.00,
        buffer_minutes=15,
    )
    return {
        "vendor_id": vendor["id"],
        "title_id": title["id"],
        "incumbent_id": incumbent["id"],
    }


def _touching_reservation_payload(scenario: dict) -> dict:
    """A booking whose inflated start 22:15 exactly touches the incumbent's
    inflated end 22:15."""
    return f.live_reservation_payload(
        scenario["title_id"],
        scenario["vendor_id"],
        window_start_at="2026-09-10T22:30:00Z",
        window_end_at="2026-09-11T00:30:00Z",
        reserved_gbps=20.00,
        buffer_minutes=15,
    )


def _clear_reservation_payload(scenario: dict) -> dict:
    """The same booking one minute later, whose inflated start 22:16 clears the
    incumbent's inflated end 22:15."""
    return f.live_reservation_payload(
        scenario["title_id"],
        scenario["vendor_id"],
        window_start_at="2026-09-10T22:31:00Z",
        window_end_at="2026-09-11T00:31:00Z",
        reserved_gbps=20.00,
        buffer_minutes=15,
    )


# ---------------------------------------------------------------------------
# Geometry A: closed, buffer-inflated capacity intervals
# ---------------------------------------------------------------------------


def test_touching_inflated_reservation_intervals_exceed_vendor_capacity(api):
    """A booking whose inflated start touches the incumbent's inflated end is aggregated against it and refused.

    PRD §2.10: "A stored reservation collides with the request when its inflated
    interval starts at or before the request's inflated end and ends at or after
    the request's inflated start — closed comparison, so merely *touching*
    inflated endpoints counts as colliding."

    PRD §3.8: "The booking is accepted when that held figure plus the requested
    `reserved_gbps` is less than **or equal to** the vendor's `committed_gbps`,
    and refused with `ERR_VENDOR_CAPACITY_EXCEEDED` only when it strictly
    exceeds it: exact equality is a legal, fully-booked vendor, and one
    hundredth of a Gbps beyond equality is a rejection."

    Design: Difficulty/resource_temporal_overlap/live_reservation_buffer_closed_interval_capacity
    """
    scenario = _build_buffer_geometry_scenario(api)

    response = api.create_live_reservation(
        _touching_reservation_payload(scenario), DELIVERY_ENGINEER
    )
    validate_error(response, err.ERR_VENDOR_CAPACITY_EXCEEDED, 422)

    vendor = fx.read_vendor(api, scenario["vendor_id"])
    assert_money(vendor["reserved_gbps"], 60.00, "CdnVendor.reserved_gbps")


def test_reservation_one_minute_clear_of_the_inflated_endpoint_is_accepted(api):
    """Starting one minute later, the inflated intervals no longer touch and the booking is stored.

    PRD §2.10: "A `LiveEventReservation` occupies its `window_start_at` through
    `window_end_at` inclusive, and each side of a comparison is inflated by its
    *own* `buffer_minutes` — the request's interval is widened by subtracting
    its `buffer_minutes` from its start and adding its `buffer_minutes` to its
    end, and each stored reservation's interval is widened by its own
    `buffer_minutes` in the same way."

    Design: Difficulty/resource_temporal_overlap/live_reservation_buffer_closed_interval_capacity
    """
    scenario = _build_buffer_geometry_scenario(api)

    response = api.create_live_reservation(
        _clear_reservation_payload(scenario), DELIVERY_ENGINEER
    )
    reservation = validate_success(response, 201)

    assert_money(reservation["reserved_gbps"], 20.00, "LiveEventReservation.reserved_gbps")
    assert reservation["buffer_minutes"] == 15, reservation
    assert reservation["state"] == "RESERVED", reservation


def test_disjoint_inflated_holds_aggregate_past_the_vendors_committed_ceiling(api):
    """Two holds on disjoint inflated intervals sum to 80.00 on a vendor committed at 60.00.

    PRD §3.8: "That figure is always the rounded sum of `reserved_gbps` over
    every reservation charged to the vendor through `active_vendor_id` in
    `RESERVED`, `ARMED`, `LIVE` or `FAILED_OVER` — it is a derived ledger, never
    an incrementally patched counter, and §2.9's bandwidth invariant holds over
    it at every observable moment."

    Design: Difficulty/resource_temporal_overlap/live_reservation_buffer_closed_interval_capacity
    """
    scenario = _build_buffer_geometry_scenario(api)

    validate_error(
        api.create_live_reservation(_touching_reservation_payload(scenario), DELIVERY_ENGINEER),
        err.ERR_VENDOR_CAPACITY_EXCEEDED,
        422,
    )
    accepted = validate_success(
        api.create_live_reservation(_clear_reservation_payload(scenario), DELIVERY_ENGINEER),
        201,
    )

    vendor = fx.read_vendor(api, scenario["vendor_id"])
    assert_money(vendor["reserved_gbps"], 80.00, "CdnVendor.reserved_gbps")
    assert_money(vendor["committed_gbps"], 60.00, "CdnVendor.committed_gbps")

    incumbent = fx.read_reservation(api, scenario["incumbent_id"])
    assert incumbent["state"] == "RESERVED", incumbent
    assert_money(incumbent["reserved_gbps"], 60.00, "LiveEventReservation.reserved_gbps")
    assert_money(accepted["reserved_gbps"], 20.00, "LiveEventReservation.reserved_gbps")


# ---------------------------------------------------------------------------
# Geometry B: half-open, buffer-free licensing intervals
# ---------------------------------------------------------------------------


def _build_window_geometry_scenario(api) -> dict:
    """A title owning one SCHEDULED US window covering [2026-09-01, 2026-10-01)
    while the logical clock still reads its startup default, so every window
    below starts in the future."""
    title = fx.create_title(
        api,
        external_ref="TTL-WINDOW-01",
        title_name="Window Geometry Subject",
        content_type="EPISODE",
        studio_code="NOVAPIC",
    )
    first = fx.create_window(
        api,
        title["id"],
        region_code="US",
        window_start_at="2026-09-01T00:00:00Z",
        window_end_at="2026-10-01T00:00:00Z",
        license_tier="STANDARD",
    )
    return {"title_id": title["id"], "first_window_id": first["id"]}


def _schedule_window(api, title_id, **overrides):
    return api.create_availability_window(
        title_id, f.availability_window_payload(**overrides), CONTENT_OPS
    )


def test_abutting_licensing_windows_in_the_same_region_do_not_overlap(api):
    """A window starting exactly where the stored window ends is stored SCHEDULED.

    PRD §2.10: "Under this geometry abutting windows are legal — a window ending
    at an instant and another beginning at that same instant do not conflict —
    while a single millisecond of true overlap is rejected outright with
    `ERR_WINDOW_OVERLAP` rather than aggregated."

    Design: Difficulty/resource_temporal_overlap/availability_window_half_open_adjacency
    """
    scenario = _build_window_geometry_scenario(api)

    response = _schedule_window(
        api,
        scenario["title_id"],
        region_code="US",
        window_start_at="2026-10-01T00:00:00Z",
        window_end_at="2026-11-01T00:00:00Z",
        license_tier="STANDARD",
    )
    abutting = validate_success(response, 201)

    assert abutting["state"] == "SCHEDULED", abutting
    assert_instant_equals(abutting["window_start_at"], "2026-10-01T00:00:00Z")
    assert_instant_equals(abutting["window_end_at"], "2026-11-01T00:00:00Z")


def test_a_truly_overlapping_licensing_window_is_rejected_outright(api):
    """[Sep 15, Oct 15) genuinely overlaps the stored [Sep 1, Oct 1) in the same region.

    PRD §2.10: "Two windows of the same title and the same `region_code` conflict
    when the stored window's `window_start_at` is strictly before the requested
    `window_end_at` **and** the requested `window_start_at` is strictly before
    the stored window's `window_end_at`; only windows in `SCHEDULED` or `ACTIVE`
    are considered, because `CLOSED` and `CANCELLED` windows free their interval
    for reuse."

    Design: Difficulty/resource_temporal_overlap/availability_window_half_open_adjacency
    """
    scenario = _build_window_geometry_scenario(api)

    response = _schedule_window(
        api,
        scenario["title_id"],
        region_code="US",
        window_start_at="2026-09-15T00:00:00Z",
        window_end_at="2026-10-15T00:00:00Z",
        license_tier="PREMIUM",
    )
    validate_error(response, err.ERR_WINDOW_OVERLAP, 409)


def test_the_same_overlapping_interval_in_another_region_is_accepted(api):
    """The overlap predicate is scoped to one `region_code`, so CA is free.

    PRD §2.6: "A new licensing window must not overlap any `SCHEDULED` or
    `ACTIVE` window of the same title and the same `region_code` under half-open
    comparison; abutting endpoints do not overlap."

    Design: Difficulty/resource_temporal_overlap/availability_window_half_open_adjacency
    """
    scenario = _build_window_geometry_scenario(api)

    response = _schedule_window(
        api,
        scenario["title_id"],
        region_code="CA",
        window_start_at="2026-09-15T00:00:00Z",
        window_end_at="2026-10-15T00:00:00Z",
        license_tier="PREMIUM",
    )
    other_region = validate_success(response, 201)

    assert other_region["region_code"] == "CA", other_region
    assert other_region["state"] == "SCHEDULED", other_region


def test_cancelling_a_window_frees_its_interval_for_immediate_reuse(api):
    """Once [Sep 1, Oct 1) is CANCELLED, a new US window may start at Sep 1 again.

    PRD §3.6: "Cancellation moves the window to the terminal `CANCELLED`, records
    `closed_at` at the logical clock's current instant, and releases the interval
    so a later window may legally occupy it."

    Design: Difficulty/resource_temporal_overlap/availability_window_half_open_adjacency
    """
    scenario = _build_window_geometry_scenario(api)

    cancelled = validate_success(
        api.cancel_availability_window(scenario["first_window_id"], CONTENT_OPS), 200
    )
    assert cancelled["state"] == "CANCELLED", cancelled
    assert_instant_equals(cancelled["closed_at"], INITIAL_CLOCK)

    reused = validate_success(
        _schedule_window(
            api,
            scenario["title_id"],
            region_code="US",
            window_start_at="2026-09-01T00:00:00Z",
            window_end_at="2026-09-20T00:00:00Z",
            license_tier="BASIC",
        ),
        201,
    )
    assert reused["state"] == "SCHEDULED", reused
    assert_instant_equals(reused["window_start_at"], "2026-09-01T00:00:00Z")


def test_the_full_window_chain_leaves_four_windows_and_a_scheduled_title(api):
    """Three accepted schedules plus one cancellation leave 4 rows, exactly 1 CANCELLED.

    PRD §3.6: "Scheduling the **first** window of a title that is still in
    `DRAFT` also advances the title's `availability_state` from `DRAFT` to
    `SCHEDULED` and increments the title's `version` by one; windows added while
    the title is already `SCHEDULED`, `PUBLISHED` or `TAKEN_DOWN` leave
    `availability_state` exactly as it was."

    Design: Difficulty/resource_temporal_overlap/availability_window_half_open_adjacency
    """
    scenario = _build_window_geometry_scenario(api)
    title_id = scenario["title_id"]

    validate_success(
        _schedule_window(
            api,
            title_id,
            region_code="US",
            window_start_at="2026-10-01T00:00:00Z",
            window_end_at="2026-11-01T00:00:00Z",
            license_tier="STANDARD",
        ),
        201,
    )
    validate_error(
        _schedule_window(
            api,
            title_id,
            region_code="US",
            window_start_at="2026-09-15T00:00:00Z",
            window_end_at="2026-10-15T00:00:00Z",
            license_tier="PREMIUM",
        ),
        err.ERR_WINDOW_OVERLAP,
        409,
    )
    validate_success(
        _schedule_window(
            api,
            title_id,
            region_code="CA",
            window_start_at="2026-09-15T00:00:00Z",
            window_end_at="2026-10-15T00:00:00Z",
            license_tier="PREMIUM",
        ),
        201,
    )
    validate_success(
        api.cancel_availability_window(scenario["first_window_id"], CONTENT_OPS), 200
    )
    validate_success(
        _schedule_window(
            api,
            title_id,
            region_code="US",
            window_start_at="2026-09-01T00:00:00Z",
            window_end_at="2026-09-20T00:00:00Z",
            license_tier="BASIC",
        ),
        201,
    )

    title = fx.read_title(api, title_id)
    assert title["availability_state"] == "SCHEDULED", title

    rows, meta = validate_paginated(api.list_availability_windows(title_id, CONTENT_OPS))
    assert meta["total_count"] == 4, meta
    assert len(rows) == 4, rows
    cancelled = [row for row in rows if row["state"] == "CANCELLED"]
    assert len(cancelled) == 1, rows
    assert cancelled[0]["id"] == scenario["first_window_id"], cancelled


# ---------------------------------------------------------------------------
# Conserved quantity 1: bandwidth across a failover
# ---------------------------------------------------------------------------


def _build_failover_scenario(api) -> dict:
    """A LIVE_EVENT title with a PACKAGED DRM package, an ACTIVE US routing
    policy, and an ARMED reservation holding 30.00 Gbps on ALPHA with BRAVO
    named as its failover vendor."""
    fx.create_device_profile(api)
    alpha = fx.create_vendor(
        api,
        vendor_code="ALPHA",
        regions=["US"],
        committed_gbps=100.00,
        cost_per_gb_usd=0.0250,
    )
    bravo = fx.create_vendor(
        api,
        vendor_code="BRAVO",
        regions=["US"],
        committed_gbps=80.00,
        cost_per_gb_usd=0.0300,
    )
    title = fx.create_live_event_title(
        api,
        external_ref="TTL-FAILOVER-01",
        title_name="Failover Ledger Event",
        studio_code="NOVASPORT",
    )
    fx.create_window(
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
        source_uri="s3://mez/failover-01.mxf",
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
        rungs=[
            f.rung("720p", 720, 2500),
            f.rung("1080p", 1080, 5000),
        ],
    )
    package = fx.create_package(
        api,
        title["id"],
        ladder["id"],
        drm_systems=["WIDEVINE"],
        license_server_url="https://lic.novasport.example/v1",
        persistent_license_allowed=False,
    )
    fx.add_entitlement_rule(
        api,
        package["id"],
        region_code="US",
        subscription_tier="ANY",
        device_class_scope="ALL",
        max_concurrent_streams=2,
        max_playback_height_px=1080,
        hdcp_level="TYPE_0",
        offline_playback_allowed=False,
        priority=60,
    )
    fx.package_package(api, package["id"])
    fx.create_policy(api, title["id"], region_code="US", steering_mode="COST")
    reservation = fx.create_reservation(
        api,
        title["id"],
        alpha["id"],
        failover_vendor_id=bravo["id"],
        window_start_at="2026-09-10T00:00:00Z",
        window_end_at="2026-09-10T04:00:00Z",
        reserved_gbps=30.00,
    )
    fx.arm_reservation(api, reservation["id"])
    return {
        "alpha_id": alpha["id"],
        "bravo_id": bravo["id"],
        "title_id": title["id"],
        "reservation_id": reservation["id"],
    }


def test_failover_moves_the_per_vendor_bandwidth_split_without_changing_the_total(api):
    """30.00 Gbps leaves ALPHA and arrives on BRAVO; the global held total is 30.00 before and after.

    PRD §3.8: "This is the compensating action for the primary-side hold: the
    primary vendor's `reserved_gbps` falls by exactly `reserved_gbps` while the
    failover vendor's rises by exactly the same amount, so the per-vendor split
    moves and the global held total is byte-for-byte unchanged."

    Design: Difficulty/compensating_invariant/bandwidth_conserved_across_failover
    """
    scenario = _build_failover_scenario(api)

    alpha_before = fx.read_vendor(api, scenario["alpha_id"])
    bravo_before = fx.read_vendor(api, scenario["bravo_id"])
    assert_money(alpha_before["reserved_gbps"], 30.00, "ALPHA.reserved_gbps")
    assert_money(bravo_before["reserved_gbps"], 0.00, "BRAVO.reserved_gbps")

    validate_success(
        api.failover_live_reservation(scenario["reservation_id"], DELIVERY_ENGINEER), 200
    )

    alpha_after = fx.read_vendor(api, scenario["alpha_id"])
    bravo_after = fx.read_vendor(api, scenario["bravo_id"])
    assert_money(alpha_after["reserved_gbps"], 0.00, "ALPHA.reserved_gbps")
    assert_money(bravo_after["reserved_gbps"], 30.00, "BRAVO.reserved_gbps")

    assert_money(
        alpha_before["reserved_gbps"] + bravo_before["reserved_gbps"],
        30.00,
        "GLOBAL_HELD_GBPS before the failover",
    )
    assert_money(
        alpha_after["reserved_gbps"] + bravo_after["reserved_gbps"],
        30.00,
        "GLOBAL_HELD_GBPS after the failover",
    )


def test_failover_records_the_incoming_vendor_and_the_logical_clock_instant(api):
    """The reservation lands in FAILED_OVER on BRAVO with `failover_at` at the clock.

    PRD §3.8: "On success `active_vendor_id` becomes the `failover_vendor_id`,
    `failover_at` records the logical clock's current instant, and `state`
    becomes `FAILED_OVER`."

    Design: Difficulty/compensating_invariant/bandwidth_conserved_across_failover
    """
    scenario = _build_failover_scenario(api)

    failed_over = validate_success(
        api.failover_live_reservation(scenario["reservation_id"], DELIVERY_ENGINEER), 200
    )

    assert failed_over["state"] == "FAILED_OVER", failed_over
    assert failed_over["active_vendor_id"] == scenario["bravo_id"], failed_over
    assert_instant_equals(failed_over["failover_at"], INITIAL_CLOCK)
    assert_money(failed_over["reserved_gbps"], 30.00, "LiveEventReservation.reserved_gbps")
    assert_money(failed_over["released_gbps"], 0.00, "LiveEventReservation.released_gbps")


def test_the_failed_over_hold_is_still_counted_once_across_the_vendor_roster(api):
    """A failover neither creates nor destroys held bandwidth: 30.00 Gbps stays counted exactly once.

    PRD §2.9: "A failover is the compensating action for a primary-side hold: it
    debits the outgoing vendor and credits the incoming vendor by the identical
    amount, so the global total is unchanged while the per-vendor split moves."

    Design: Difficulty/compensating_invariant/bandwidth_conserved_across_failover
    """
    scenario = _build_failover_scenario(api)

    validate_success(
        api.failover_live_reservation(scenario["reservation_id"], DELIVERY_ENGINEER), 200
    )

    reservation = fx.read_reservation(api, scenario["reservation_id"])
    alpha = validate_success(api.get_cdn_vendor(scenario["alpha_id"], PLATFORM_ADMIN), 200)
    bravo = validate_success(api.get_cdn_vendor(scenario["bravo_id"], PLATFORM_ADMIN), 200)

    assert reservation["state"] == "FAILED_OVER", reservation
    assert_money(
        alpha["reserved_gbps"] + bravo["reserved_gbps"],
        reservation["reserved_gbps"],
        "roster held total vs the single reservation's hold",
    )
    assert_money(alpha["reserved_gbps"], 0.00, "ALPHA.reserved_gbps")
    assert_money(bravo["reserved_gbps"], 30.00, "BRAVO.reserved_gbps")


# ---------------------------------------------------------------------------
# Conserved quantity 2: encode budget across a run and an abort
# ---------------------------------------------------------------------------


def _build_budget_scenario(api) -> dict:
    """A MOVIE title on the default 5000.00 budget with one QC_PASSED
    6000-second master, one LOCKED H264 ladder of 1150 / 2350 / 4850 / 9650
    kbps rungs, and one QUEUED HEVC reprocessing job."""
    fx.create_device_profile(api)
    fx.create_device_profile(
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
    )
    title = fx.create_title(
        api,
        external_ref="TTL-BUDGET-01",
        title_name="Budget Ledger Subject",
        content_type="MOVIE",
        studio_code="NOVAPIC",
    )
    fx.create_passed_asset(
        api,
        title["id"],
        source_uri="s3://mez/budget-01.mxf",
        duration_seconds=6000,
        frame_rate=24.0,
        peak_audio_lufs=-24.0,
        artifact_defect_count=0,
        caption_languages=["en"],
        audio_language="en",
    )
    ladder = fx.create_locked_ladder(
        api,
        title["id"],
        codec_family="H264",
        rungs=[dict(entry) for entry in f.RUNGS_FOUR_COST_EXAMPLE],
    )
    job = fx.create_job(
        api,
        title["id"],
        ladder["id"],
        trigger_reason="CODEC_DEPRECATION",
        target_codec_family="HEVC",
    )
    return {"title_id": title["id"], "ladder_id": ladder["id"], "job_id": job["id"]}


def test_running_a_job_commits_its_frozen_estimate_against_the_titles_budget(api):
    """A 48.62 estimate is committed and the remaining budget falls to 4951.38.

    PRD §3.9: "On success the job's `state` becomes `RUNNING`, its
    `committed_usd` becomes its `cost_estimate_usd`, the title's
    `encode_budget_remaining_usd` falls by that amount and the title's `version`
    increments by one."

    Design: Difficulty/compensating_invariant/encode_budget_conserved_across_abort
    """
    scenario = _build_budget_scenario(api)

    title_before = fx.read_title(api, scenario["title_id"])
    job_before = fx.read_job(api, scenario["job_id"])
    assert_money(
        title_before["encode_budget_remaining_usd"],
        5000.00,
        "Title.encode_budget_remaining_usd",
    )
    assert_money(job_before["committed_usd"], 0.00, "ReprocessJob.committed_usd")
    assert job_before["state"] == "QUEUED", job_before

    running = validate_success(
        api.run_reprocess_job(scenario["job_id"], ENCODING_ENGINEER), 200
    )
    assert running["state"] == "RUNNING", running
    assert_money(running["committed_usd"], 48.62, "ReprocessJob.committed_usd")

    title_after = fx.read_title(api, scenario["title_id"])
    assert_money(
        title_after["encode_budget_remaining_usd"],
        4951.38,
        "Title.encode_budget_remaining_usd",
    )


def test_aborting_a_running_job_returns_the_budget_with_zero_drift(api):
    """The abort zeroes `committed_usd` and restores `encode_budget_remaining_usd` to 5000.00.

    PRD §3.9: "Aborting from `RUNNING` is the compensating action for the run
    debit: `state` becomes the terminal `ABORTED`, `committed_usd` returns to
    0.00, `encode_budget_remaining_usd` returns to exactly its pre-run value with
    zero drift, and the title's `version` increments by one."

    Design: Difficulty/compensating_invariant/encode_budget_conserved_across_abort
    """
    scenario = _build_budget_scenario(api)

    validate_success(api.run_reprocess_job(scenario["job_id"], ENCODING_ENGINEER), 200)
    aborted = validate_success(
        api.abort_reprocess_job(scenario["job_id"], f.abort_payload(), ENCODING_ENGINEER),
        200,
    )

    assert aborted["state"] == "ABORTED", aborted
    assert aborted["abort_reason"] == "OPERATOR_ABORT", aborted
    assert_money(aborted["committed_usd"], 0.00, "ReprocessJob.committed_usd")

    title = fx.read_title(api, scenario["title_id"])
    assert_money(
        title["encode_budget_remaining_usd"], 5000.00, "Title.encode_budget_remaining_usd"
    )


def test_the_money_identity_holds_at_every_step_of_the_run_and_abort(api):
    """`encode_budget_remaining_usd` plus every job's `committed_usd` equals 5000.00 throughout.

    PRD §2.9: "Equivalently, `encode_budget_remaining_usd` plus the sum of
    `committed_usd` over all of the title's jobs always equals
    `encode_budget_usd`."

    Design: Difficulty/compensating_invariant/encode_budget_conserved_across_abort
    """
    scenario = _build_budget_scenario(api)

    queued = fx.read_job(api, scenario["job_id"])
    title_queued = fx.read_title(api, scenario["title_id"])
    assert_money(
        title_queued["encode_budget_remaining_usd"] + queued["committed_usd"],
        5000.00,
        "remaining + committed while QUEUED",
    )

    running = validate_success(
        api.run_reprocess_job(scenario["job_id"], ENCODING_ENGINEER), 200
    )
    title_running = fx.read_title(api, scenario["title_id"])
    assert_money(
        title_running["encode_budget_remaining_usd"] + running["committed_usd"],
        5000.00,
        "remaining + committed while RUNNING",
    )
    assert_money(
        title_running["encode_budget_remaining_usd"],
        4951.38,
        "Title.encode_budget_remaining_usd",
    )

    aborted = validate_success(
        api.abort_reprocess_job(scenario["job_id"], f.abort_payload(), ENCODING_ENGINEER),
        200,
    )
    title_aborted = fx.read_title(api, scenario["title_id"])
    assert_money(
        title_aborted["encode_budget_remaining_usd"] + aborted["committed_usd"],
        5000.00,
        "remaining + committed after the abort",
    )
    assert_money(aborted["committed_usd"], 0.00, "ReprocessJob.committed_usd")


def test_the_frozen_cost_estimate_survives_both_transitions(api):
    """`cost_estimate_usd` reads 48.62 when QUEUED, when RUNNING and when ABORTED.

    PRD §3.9: "The order is load-bearing: 100 billable minutes of `HEVC` over
    source rungs of 1150, 2350, 4850 and 9650 kilobits per second give per-rung
    costs of 3.11, 6.35, 13.10 and 26.06 and a total of 48.62, whereas summing
    the unrounded products first and rounding once would give 48.60, which is the
    wrong answer."

    Design: Difficulty/compensating_invariant/encode_budget_conserved_across_abort
    """
    scenario = _build_budget_scenario(api)

    queued = fx.read_job(api, scenario["job_id"])
    assert_money(queued["cost_estimate_usd"], 48.62, "ReprocessJob.cost_estimate_usd")

    running = validate_success(
        api.run_reprocess_job(scenario["job_id"], ENCODING_ENGINEER), 200
    )
    assert_money(running["cost_estimate_usd"], 48.62, "ReprocessJob.cost_estimate_usd")

    aborted = validate_success(
        api.abort_reprocess_job(scenario["job_id"], f.abort_payload(), ENCODING_ENGINEER),
        200,
    )
    assert_money(aborted["cost_estimate_usd"], 48.62, "ReprocessJob.cost_estimate_usd")
