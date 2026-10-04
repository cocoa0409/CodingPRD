"""Difficulty queue A: resource temporal overlap (maintenance hour, blackout)."""
from test_helpers import (
    api_client,
    get_success_data,
    validate_error,
    admin_of,
    op_headers,
    ApiErrorId,
    create_active_connector,
    create_prod_sandbox_pair,
    create_run,
    create_tenant,
    set_clock,
)


def test_refresh_scheduled_outside_maintenance_hour_rejected(api):
    """PRD §3.9: "`scheduled_at` must fall inside the target tenant's
    maintenance hour — refreshes execute only in that hour".
    PRD §3.9: "A scheduling miss on the maintenance hour surfaces
    `ERR_SCHEDULE_CONFLICT` (HTTP 422)".

    Design: Difficulty/resource_temporal_overlap/refresh_window_vs_weekly_update_window_exclusion
    """
    src, tgt = create_prod_sandbox_pair("T-TO1S", "T-TO1T")
    admin = admin_of(tgt)
    set_clock("2026-09-02T00:00:00Z")

    # Hour 5, but the target's maintenance_slot_utc is 2.
    resp = api_client.create_refresh_job(
        tgt["id"],
        {"source_tenant_id": src["id"], "scheduled_at": "2026-09-05T05:00:00Z",
         "migration_mode": "FULL_COPY"},
        admin,
    )
    validate_error(resp, ApiErrorId.ERR_SCHEDULE_CONFLICT)


def test_refresh_scheduled_inside_maintenance_hour_planned(api):
    """PRD §3.9: "`scheduled_at` must fall inside the target tenant's
    maintenance hour — refreshes execute only in that hour".
    PRD §3.9: "At plan time the job is `PLANNED` and the server quotes a
    provisional `config_drift_score`."

    Design: Difficulty/resource_temporal_overlap/refresh_window_vs_weekly_update_window_exclusion
    """
    src, tgt = create_prod_sandbox_pair("T-TO1S2", "T-TO1T2")
    admin = admin_of(tgt)
    set_clock("2026-09-02T00:00:00Z")

    # Hour 2 equals the maintenance slot: accepted.
    resp = api_client.create_refresh_job(
        tgt["id"],
        {"source_tenant_id": src["id"], "scheduled_at": "2026-09-05T02:00:00Z",
         "migration_mode": "FULL_COPY"},
        admin,
    )
    job = get_success_data(resp, 201)
    assert job["status"] == "PLANNED"
    assert job["config_drift_score"] == 0, (
        "the empty source contributes no drift"
    )


def test_scheduled_run_suppressed_inside_blackout_manual_bypasses(api):
    """PRD §3.8: "a daily blackout window given as `blackout_window_start_utc`
    and `blackout_window_end_utc` — hours 0 to 23 UTC forming a half-open
    interval, start inclusive and end exclusive, during which scheduled runs
    are suppressed."
    PRD §3.8: "A `MANUAL` run bypasses the blackout window and dispatches
    immediately, transitioning from `QUEUED` to `RUNNING` within the same
    request; `SCHEDULE` and `EVENT` runs stay `QUEUED` until dispatcher
    conditions hold."

    Design: Difficulty/resource_temporal_overlap/scheduled_run_suppressed_in_half_open_blackout
    """
    tenant = create_tenant("T-TO2")
    connector = create_active_connector(tenant["id"], "C1", blackout=(3, 4))
    set_clock("2026-09-02T03:30:00Z")  # inside [3, 4)

    scheduled = create_run(tenant["id"], connector["id"], "SCHEDULE",
                           as_operator=True)
    assert scheduled["status"] == "QUEUED", (
        "a SCHEDULE run fired inside the blackout window is suppressed"
    )

    manual = create_run(tenant["id"], connector["id"], "MANUAL")
    assert manual["status"] == "RUNNING", (
        "a MANUAL run bypasses the blackout window and dispatches immediately"
    )


def test_scheduled_run_suppressed_at_blackout_start_inclusive(api):
    """PRD §3.8: "a daily blackout window given as `blackout_window_start_utc`
    and `blackout_window_end_utc` — hours 0 to 23 UTC forming a half-open
    interval, start inclusive and end exclusive, during which scheduled runs
    are suppressed."
    PRD §3.8: "`SCHEDULE` and `EVENT` runs stay `QUEUED` until dispatcher
    conditions hold."

    At exactly blackout_window_start_utc the window already contains the
    current hour (start inclusive), so the run stays QUEUED.

    Design: Difficulty/resource_temporal_overlap/scheduled_run_suppressed_in_half_open_blackout
    """
    tenant = create_tenant("T-TO2B")
    connector = create_active_connector(tenant["id"], "C1", blackout=(3, 4))
    set_clock("2026-09-02T03:00:00Z")  # exactly the inclusive blackout start

    scheduled = create_run(tenant["id"], connector["id"], "SCHEDULE",
                           as_operator=True)
    assert scheduled["status"] == "QUEUED", (
        "the blackout start hour is inclusive: the run is suppressed"
    )
