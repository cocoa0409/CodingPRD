"""Venue systems and maintenance: render-wall exclusion at dispatch, the
failure-counter health transitions, and the OFFLINE cascade into active batches."""
import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    capture_asset,
    create_maintenance_window_payload,
    create_production,
    create_render_batch_payload,
    create_venue_system,
    degrade_venue_system,
    fail_one_window,
    get_success_data,
    set_clock,
    setup_active_production_with_approved_asset,
    setup_show_in_rehearsal,
    validate_error,
    validate_success,
)

PD = TEST_USERS["production_director_headers"]
CP = TEST_USERS["content_producer_headers"]
VO = TEST_USERS["venue_ops_engineer_headers"]
VS = TEST_USERS["venue_scheduler_headers"]


class TestDispatchBlockedByMaintenance:

    def test_dispatch_blocked_by_overlapping_envfx_window(self, api):
        """PRD: "Third, the render wall must be free of environmental effects
        maintenance: no `ENV_FX` maintenance window may be `SCHEDULED` or
        `ACTIVE` overlapping the projected render window from the dispatch
        instant through the computed render duration. A violation is rejected
        with `ERR_RENDER_BLOCKED_BY_MAINTENANCE` (HTTP 422)."

        Design: Difficulty/cross_entity_state_dependency/batch_dispatch_blocked_by_envfx_maintenance
        """
        system = create_venue_system(name="EnvFX-2", kind="ENV_FX")
        prod = create_production(title="YP", production_type="ORIGINAL", base_price_cents=10000)
        asset = capture_asset(prod["id"], title="YA", render_hours_base=2)
        get_success_data(
            api.create_maintenance_window(
                create_maintenance_window_payload(
                    system["id"],
                    start_time="2026-09-01T01:00:00Z",
                    end_time="2026-09-01T02:00:00Z",
                    buffer_minutes=15,
                ),
                VO,
            )
        )
        batch = get_success_data(api.create_render_batch(create_render_batch_payload([asset["id"]]), CP))
        # Clock 00:30 -> projected render window [00:30, 02:00) overlaps the window.
        set_clock("2026-09-01T00:30:00Z")
        resp = api.dispatch_render_batch(batch["id"], CP)
        validate_error(resp, ApiErrorId.ERR_RENDER_BLOCKED_BY_MAINTENANCE)
        after = get_success_data(api.get_render_batch(batch["id"], CP))
        assert after["status"] == "OPEN", "the batch must remain OPEN after the blocked dispatch"

    def test_dispatch_allowed_once_blocking_window_passes(self, api):
        """PRD: "Third, the render wall must be free of environmental effects
        maintenance: no `ENV_FX` maintenance window may be `SCHEDULED` or
        `ACTIVE` overlapping the projected render window from the dispatch
        instant through the computed render duration. A violation is rejected
        with `ERR_RENDER_BLOCKED_BY_MAINTENANCE` (HTTP 422)."

        Design: Difficulty/cross_entity_state_dependency/batch_dispatch_blocked_by_envfx_maintenance
        """
        system = create_venue_system(name="EnvFX-2b", kind="ENV_FX")
        prod = create_production(title="YP2", production_type="ORIGINAL", base_price_cents=10000)
        asset = capture_asset(prod["id"], title="YB", render_hours_base=2)
        get_success_data(
            api.create_maintenance_window(
                create_maintenance_window_payload(
                    system["id"],
                    start_time="2026-09-01T01:00:00Z",
                    end_time="2026-09-01T02:00:00Z",
                    buffer_minutes=15,
                ),
                VO,
            )
        )
        batch = get_success_data(api.create_render_batch(create_render_batch_payload([asset["id"]]), CP))
        # Clock 02:30 -> projected render window [02:30, 04:00) clears the window.
        set_clock("2026-09-01T02:30:00Z")
        data = validate_success(api.dispatch_render_batch(batch["id"], CP))
        assert data["status"] == "RENDERING"


class TestEnvFxOfflineCascade:

    def test_third_failed_window_offlines_system_and_fails_active_batch(self, api):
        """PRD: "When the counter reaches 3, the system goes `OFFLINE`; this
        transition additionally aborts any `RENDERING` render batch, cascading
        its assets into `QC_FAILED` per §3.2."
        PRD: "or marks it `FAILED`, which leaves the window in `FAILED`,
        increments the parent system's `consecutive_failed_windows` by 1, and
        does not change the system's current status by itself."

        Design: Difficulty/transitive_cascade/envfx_offline_cascades_batch_then_asset
        """
        system = create_venue_system(name="EnvFX-1", kind="ENV_FX")
        prod = create_production(title="FP", production_type="ORIGINAL", base_price_cents=10000)
        asset = capture_asset(prod["id"], title="FA", render_hours_base=2)

        fail_one_window(system["id"], "2026-09-01T00:30:00Z", "2026-09-01T01:00:00Z", fail_clock="2026-09-01T00:45:00Z")
        fail_one_window(system["id"], "2026-09-01T01:15:00Z", "2026-09-01T01:45:00Z", fail_clock="2026-09-01T01:30:00Z")

        batch = get_success_data(api.create_render_batch(create_render_batch_payload([asset["id"]]), CP))
        set_clock("2026-09-01T01:50:00Z")
        validate_success(api.dispatch_render_batch(batch["id"], CP))

        w3 = get_success_data(
            api.create_maintenance_window(
                create_maintenance_window_payload(
                    system["id"],
                    start_time="2026-09-01T02:30:00Z",
                    end_time="2026-09-01T03:00:00Z",
                    buffer_minutes=15,
                ),
                VO,
            )
        )
        # Clock 02:45 -> third window ACTIVE, batch still RENDERING.
        set_clock("2026-09-01T02:45:00Z")
        validate_success(api.fail_maintenance_window(w3["id"], VO))

        system_after = get_success_data(api.get_venue_system(system["id"], VO))
        assert system_after["consecutive_failed_windows"] == 3
        assert system_after["status"] == "OFFLINE"
        batch_after = get_success_data(api.get_render_batch(batch["id"], CP))
        assert batch_after["status"] == "FAILED", "the OFFLINE transition must abort the active batch"
        asset_after = get_success_data(api.get_asset(asset["id"], CP))
        assert asset_after["status"] == "QC_FAILED", "batch failure must cascade the asset to QC_FAILED"

    def test_offline_cascade_leaves_captured_assets_untouched(self, api):
        """PRD: "When the counter reaches 3, the system goes `OFFLINE`; this
        transition additionally aborts any `RENDERING` render batch, cascading
        its assets into `QC_FAILED` per §3.2."
        PRD: "Finally, a batch may be aborted while `OPEN`, `RENDERING`, or
        `SETTLING`; aborting moves it to `FAILED`, transitions any assets still
        in `RENDERING` to `QC_FAILED`, and leaves any `CAPTURED` assets
        untouched in `CAPTURED`."

        Design: Difficulty/transitive_cascade/envfx_offline_cascades_batch_then_asset
        """
        system = create_venue_system(name="EnvFX-1b", kind="ENV_FX")
        prod = create_production(title="FP2", production_type="ORIGINAL", base_price_cents=10000)
        asset_rendering = capture_asset(prod["id"], title="FA-R", render_hours_base=2)
        asset_captured = capture_asset(prod["id"], title="FA-C", render_hours_base=2)

        fail_one_window(system["id"], "2026-09-01T00:30:00Z", "2026-09-01T01:00:00Z", fail_clock="2026-09-01T00:45:00Z")
        fail_one_window(system["id"], "2026-09-01T01:15:00Z", "2026-09-01T01:45:00Z", fail_clock="2026-09-01T01:30:00Z")

        batch = get_success_data(api.create_render_batch(create_render_batch_payload([asset_rendering["id"]]), CP))
        set_clock("2026-09-01T01:50:00Z")
        validate_success(api.dispatch_render_batch(batch["id"], CP))

        w3 = get_success_data(
            api.create_maintenance_window(
                create_maintenance_window_payload(
                    system["id"],
                    start_time="2026-09-01T02:30:00Z",
                    end_time="2026-09-01T03:00:00Z",
                    buffer_minutes=15,
                ),
                VO,
            )
        )
        set_clock("2026-09-01T02:45:00Z")
        validate_success(api.fail_maintenance_window(w3["id"], VO))

        asset_captured_after = get_success_data(api.get_asset(asset_captured["id"], CP))
        assert asset_captured_after["status"] == "CAPTURED", (
            "assets never submitted to the failed batch must remain CAPTURED"
        )
        asset_rendering_after = get_success_data(api.get_asset(asset_rendering["id"], CP))
        assert asset_rendering_after["status"] == "QC_FAILED"


class TestTechReadinessGate:

    def test_confirm_rejected_when_required_system_degraded(self, api):
        """PRD: "Third, the show's `tech_readiness` must be `READY`, meaning no
        venue system whose kind the show requires is currently `DEGRADED` or
        `OFFLINE`; otherwise the confirm is rejected with `ERR_TECH_NOT_READY`
        (HTTP 422)."
        PRD: "When `consecutive_failed_windows` reaches 2, the system — whether
        currently `ONLINE` or `MAINTENANCE` — flips to `DEGRADED`, and every
        show whose window requires this system's kind has its `tech_readiness`
        recomputed to `DEGRADED`."

        Design: Corner/errors/error_tech_not_ready_triggerable
        """
        system = create_venue_system(name="AB-9", kind="AUDIO_BEAM")
        prod, asset, show = setup_show_in_rehearsal(
            base_price_cents=10000,
            show_overrides={"show_format": "FILM", "start_time": "2026-09-03T19:00:00Z", "length_minutes": 90},
        )
        fail_one_window(system["id"], "2026-09-01T03:30:00Z", "2026-09-01T04:00:00Z", fail_clock="2026-09-01T03:45:00Z")
        fail_one_window(system["id"], "2026-09-01T04:30:00Z", "2026-09-01T05:00:00Z", fail_clock="2026-09-01T04:45:00Z")
        system_after = get_success_data(api.get_venue_system(system["id"], VO))
        assert system_after["status"] == "DEGRADED"
        prod_now = validate_success(api.get_production(prod["id"], PD))
        resp = api.confirm_show(
            show["id"], {"expected_production_version": prod_now["version"]}, VS
        )
        validate_error(resp, ApiErrorId.ERR_TECH_NOT_READY)

    def test_confirm_succeeds_once_system_repaired(self, api):
        """PRD: "Third, the show's `tech_readiness` must be `READY`, meaning no
        venue system whose kind the show requires is currently `DEGRADED` or
        `OFFLINE`; otherwise the confirm is rejected with `ERR_TECH_NOT_READY`
        (HTTP 422)."
        PRD: "An engineer can also repair a `DEGRADED` system back to `ONLINE`
        directly, which resets `consecutive_failed_windows` to 0."

        Design: Corner/errors/error_tech_not_ready_triggerable
        """
        prod, asset, show = setup_show_in_rehearsal(
            base_price_cents=10000,
            show_overrides={"show_format": "FILM", "start_time": "2026-09-03T19:00:00Z", "length_minutes": 90},
        )
        system = degrade_venue_system(kind="AUDIO_BEAM")
        repaired = validate_success(api.repair_venue_system(system["id"], VO))
        assert repaired["status"] == "ONLINE"
        assert repaired["consecutive_failed_windows"] == 0
        prod_now = validate_success(api.get_production(prod["id"], PD))
        confirmed = validate_success(
            api.confirm_show(show["id"], {"expected_production_version": prod_now["version"]}, VS)
        )
        assert confirmed["status"] == "CONFIRMED"
