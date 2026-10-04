"""Seed-train stage ordering, transfer/inoculation windows, and expiry recovery."""
from test_helpers import (
    ApiErrorId, FIXTURE_CLOCK_START,
    validate_success, validate_error, validate_paginated,
    setup_campaign, setup_allocated_campaign,
    add_seed_stage, advance_campaign, advance_seed_stage,
    run_seed_stage_to_completed, set_logical_clock,
)


def _stage_status(api, campaign_id, stage_id, headers):
    rows, _meta = validate_paginated(api.list_seed_stages(campaign_id, headers))
    return next(row["status"] for row in rows if row["id"] == stage_id)


def test_seed_stage_failed_retry_cycle_succeeds(api):
    """PRD §3.3: "Advancing a stage to `RUNNING` — including a retry from `FAILED` or `EXPIRED` — requires the stage to currently be `PENDING`, `FAILED`, or `EXPIRED` (`ERR_INVALID_SEED_STAGE_STATE`)"
    PRD §3.3: "Entering `RUNNING` stamps `started_at` with the logical clock and clears `completed_at` to null."

    Design: Corner/state_machines/seed_stage_failed_retry_cycle_succeeds
    """
    env = setup_allocated_campaign()
    stage = add_seed_stage(env["campaign"]["id"], 1, 10)
    advance_campaign(env["campaign"]["id"], "SEED_IN_PROGRESS")
    advance_seed_stage(stage["id"], "RUNNING")
    advance_seed_stage(stage["id"], "FAILED")
    set_logical_clock("2026-10-01T02:00:00Z")
    restarted = advance_seed_stage(stage["id"], "RUNNING")
    assert restarted["started_at"].startswith("2026-10-01T02:00:00"), "started_at refreshed"
    set_logical_clock("2026-10-01T12:00:00Z")
    assert advance_seed_stage(stage["id"], "COMPLETED")["status"] == "COMPLETED"


def test_seed_transfer_window_exact_36h_allowed(api, platform_admin_headers,
                                                process_engineer_headers):
    """PRD §3.3: "no more than thirty-six hours to have elapsed between the previous stage's `completed_at` and the logical clock — exactly thirty-six hours is allowed, and a longer gap is rejected with `ERR_SEED_TRANSFER_WINDOW_EXPIRED` (HTTP 409)."

    Design: Corner/calculations/seed_transfer_window_exact_36h_allowed
    """
    env = setup_allocated_campaign()
    camp_id = env["campaign"]["id"]
    stage1 = add_seed_stage(camp_id, 1, 10)
    advance_campaign(camp_id, "SEED_IN_PROGRESS")
    run_seed_stage_to_completed(stage1["id"], 10, FIXTURE_CLOCK_START)  # done 10-01T10:00Z
    stage2 = add_seed_stage(camp_id, 2, 8)
    set_logical_clock("2026-10-02T22:00:00Z")  # exactly 36 hours later
    data = validate_success(
        api.advance_seed_stage(stage2["id"], "RUNNING", process_engineer_headers))
    assert data["status"] == "RUNNING"
    assert _stage_status(api, camp_id, stage1["id"], platform_admin_headers) == "COMPLETED"


def test_seed_transfer_window_expired_flips_predecessor_and_recovers(
        api, platform_admin_headers, process_engineer_headers):
    """PRD §3.3: "A stage in `COMPLETED` flips to `EXPIRED` by system action in exactly two situations: when a `RUNNING` attempt on the stage with the next `stage_index` of the same campaign is being rejected with `ERR_SEED_TRANSFER_WINDOW_EXPIRED` (the failed successor keeps its own status; only the predecessor expires)"
    PRD §3.3: "An `EXPIRED` stage may re-enter `RUNNING` through the normal retry path, so an expiry costs a re-run of the stage rather than the campaign."

    Design: Corner/calculations/seed_transfer_window_expired_flips_predecessor_and_recovers
    """
    env = setup_allocated_campaign()
    camp_id = env["campaign"]["id"]
    stage1 = add_seed_stage(camp_id, 1, 10)
    advance_campaign(camp_id, "SEED_IN_PROGRESS")
    run_seed_stage_to_completed(stage1["id"], 10, FIXTURE_CLOCK_START)
    stage2 = add_seed_stage(camp_id, 2, 8)
    set_logical_clock("2026-10-02T22:00:01Z")  # 36 hours + 1 second
    resp = api.advance_seed_stage(stage2["id"], "RUNNING", process_engineer_headers)
    validate_error(resp, ApiErrorId.ERR_SEED_TRANSFER_WINDOW_EXPIRED)
    assert _stage_status(api, camp_id, stage1["id"], platform_admin_headers) == "EXPIRED"
    advance_seed_stage(stage1["id"], "RUNNING")
    set_logical_clock("2026-10-03T06:00:01Z")
    advance_seed_stage(stage1["id"], "COMPLETED")
    data = validate_success(
        api.advance_seed_stage(stage2["id"], "RUNNING", process_engineer_headers))
    assert data["status"] == "RUNNING", "0 h elapsed after the retried completion"


def test_inoculation_window_expiry_flips_last_stage_and_exact_24h_boundary(
        api, platform_admin_headers, process_engineer_headers):
    """PRD §3.3: "no more than twenty-four hours have elapsed between the latest stage `completed_at` and the logical clock; exactly twenty-four hours is allowed, and a longer gap is rejected with `ERR_SEED_INOCULATION_WINDOW_EXPIRED` (HTTP 409), with the highest-indexed completed stage flipping to `EXPIRED` as described above so the seed train can be retried instead of stranding the campaign."

    Design: Corner/calculations/inoculation_window_expiry_flips_last_stage_and_exact_24h_boundary
    """
    env = setup_allocated_campaign()
    camp_id = env["campaign"]["id"]
    stage1 = add_seed_stage(camp_id, 1, 10)
    advance_campaign(camp_id, "SEED_IN_PROGRESS")
    run_seed_stage_to_completed(stage1["id"], 10, FIXTURE_CLOCK_START)  # done 10-01T10:00Z
    set_logical_clock("2026-10-02T10:00:01Z")  # 24 hours + 1 second
    resp = api.advance_campaign(camp_id, "PRODUCTION_IN_PROGRESS", process_engineer_headers)
    validate_error(resp, ApiErrorId.ERR_SEED_INOCULATION_WINDOW_EXPIRED)
    assert _stage_status(api, camp_id, stage1["id"], platform_admin_headers) == "EXPIRED"
    advance_seed_stage(stage1["id"], "RUNNING")
    set_logical_clock("2026-10-02T20:00:01Z")
    advance_seed_stage(stage1["id"], "COMPLETED")
    set_logical_clock("2026-10-03T20:00:01Z")  # exactly 24 hours after the retried completion
    data = validate_success(
        api.advance_campaign(camp_id, "PRODUCTION_IN_PROGRESS", process_engineer_headers))
    assert data["status"] == "PRODUCTION_IN_PROGRESS"


def test_seed_stage_order_violation_rejected(api, process_engineer_headers):
    """PRD §3.3: "Stages then execute strictly in `stage_index` order, as a chronological chain."
    PRD §3.3: "every lower-indexed stage of the same campaign to be `COMPLETED` (`ERR_SEED_STAGE_ORDER_VIOLATION`)"

    Design: Corner/validations/seed_stage_order_violation_rejected
    """
    env = setup_allocated_campaign()
    camp_id = env["campaign"]["id"]
    add_seed_stage(camp_id, 1, 10)
    stage2 = add_seed_stage(camp_id, 2, 8)
    advance_campaign(camp_id, "SEED_IN_PROGRESS")
    resp = api.advance_seed_stage(stage2["id"], "RUNNING", process_engineer_headers)
    validate_error(resp, ApiErrorId.ERR_SEED_STAGE_ORDER_VIOLATION)


def test_seed_stage_complete_twice_rejected(api, process_engineer_headers):
    """PRD §3.3: "A `RUNNING` stage may be advanced to `COMPLETED`, which stamps `completed_at` with the logical clock, or to `FAILED`; requesting either transition while the stage is not `RUNNING` is rejected with `ERR_INVALID_SEED_STAGE_STATE`"

    Design: Corner/validations/seed_stage_complete_twice_rejected
    """
    env = setup_allocated_campaign()
    stage1 = add_seed_stage(env["campaign"]["id"], 1, 10)
    advance_campaign(env["campaign"]["id"], "SEED_IN_PROGRESS")
    run_seed_stage_to_completed(stage1["id"], 10, FIXTURE_CLOCK_START)
    resp = api.advance_seed_stage(stage1["id"], "COMPLETED", process_engineer_headers)
    validate_error(resp, ApiErrorId.ERR_INVALID_SEED_STAGE_STATE)


def test_seed_start_without_stages_rejected(api, process_engineer_headers):
    """PRD §3.3: "At least one seed stage must be defined, else `ERR_NO_SEED_STAGES_DEFINED` (HTTP 409)."

    Design: Corner/validations/seed_start_without_stages_rejected
    """
    env = setup_allocated_campaign()
    resp = api.advance_campaign(env["campaign"]["id"], "SEED_IN_PROGRESS",
                                process_engineer_headers)
    validate_error(resp, ApiErrorId.ERR_NO_SEED_STAGES_DEFINED)


def test_production_start_with_stage_still_running_rejected(api, process_engineer_headers):
    """PRD §3.3: "Production may begin — advancing the campaign from `SEED_IN_PROGRESS` to `PRODUCTION_IN_PROGRESS` — only when every seed stage of the campaign is `COMPLETED` (`ERR_SEED_STAGES_INCOMPLETE`, HTTP 409)"

    Design: Corner/validations/production_start_with_stage_still_running_rejected
    """
    env = setup_allocated_campaign()
    stage1 = add_seed_stage(env["campaign"]["id"], 1, 10)
    advance_campaign(env["campaign"]["id"], "SEED_IN_PROGRESS")
    advance_seed_stage(stage1["id"], "RUNNING")
    resp = api.advance_campaign(env["campaign"]["id"], "PRODUCTION_IN_PROGRESS",
                                process_engineer_headers)
    validate_error(resp, ApiErrorId.ERR_SEED_STAGES_INCOMPLETE)


def test_campaign_seed_start_before_planned_window_rejected(api, process_engineer_headers,
                                                            platform_admin_headers):
    """PRD §3.3: "The logical clock must be at or after `planned_start_utc`; a clock still before the window's start is rejected with `ERR_CAMPAIGN_START_TOO_EARLY` (HTTP 409)."
    PRD §2.4: "Before any client call sets it, the logical clock reads exactly 2026-09-01T00:00:00Z, and it never falls back to wall-clock time at any point afterward."

    Design: Corner/validations/campaign_seed_start_before_planned_window_rejected
    """
    env = setup_campaign(set_clock=False)  # logical clock never set: default 2026-09-01
    camp_id = env["campaign"]["id"]
    advance_campaign(camp_id, "ALLOCATED")
    add_seed_stage(camp_id, 1, 10)
    resp = api.advance_campaign(camp_id, "SEED_IN_PROGRESS", process_engineer_headers)
    validate_error(resp, ApiErrorId.ERR_CAMPAIGN_START_TOO_EARLY)
    reread = validate_success(api.get_campaign(camp_id, platform_admin_headers))
    assert reread["status"] == "ALLOCATED"
