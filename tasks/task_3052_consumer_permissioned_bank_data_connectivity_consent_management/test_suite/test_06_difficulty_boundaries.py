"""Difficulty queue A — boundary_precision_check instances."""

from test_helpers import (
    ApiErrorId,
    assert_instants_equal,
    setup_active_stack,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_refresh_at_rate_limit_boundary_rejected(api):
    """PRD §3.7: "count all refresh executions — of any job status — across
    every connection of the institution whose `executed_at` falls within the
    trailing 3600 seconds; if that count has reached the governing agreement's
    `rate_limit_per_hour` (equality counts), the refresh is rejected with
    `ERR_RATE_LIMITED` (HTTP 429) and no attempt is recorded."

    Design: Difficulty/boundary_precision_check/boundary_rate_limit_count_at_limit_rejected
    """
    stack = setup_active_stack(
        api,
        institution_name="Rate Bank",
        recipient_name="RateApp",
        consumer_ref="cons_j",
        rate_limit_per_hour=3,
    )
    conn_id = stack["connection"]["id"]
    consumer = stack["consumer"]

    # complete_auth consumed execution 1; two more fill the window to exactly 3.
    job2 = validate_success(api.refresh_connection(conn_id, {"kind": "FULL"}, consumer))
    job3 = validate_success(api.refresh_connection(conn_id, {"kind": "FULL"}, consumer))
    assert job2["status"] == "SUCCEEDED"
    assert job3["status"] == "SUCCEEDED"

    resp = api.refresh_connection(conn_id, {"kind": "FULL"}, consumer)
    validate_error(resp, ApiErrorId.ERR_RATE_LIMITED)


def test_rate_limited_refresh_records_no_attempt(api):
    """PRD §3.7: "if that count has reached the governing agreement's
    `rate_limit_per_hour` (equality counts), the refresh is rejected with
    `ERR_RATE_LIMITED` (HTTP 429) and no attempt is recorded."

    Design: Difficulty/boundary_precision_check/boundary_rate_limit_count_at_limit_rejected
    """
    stack = setup_active_stack(
        api,
        institution_name="Rate Bank",
        recipient_name="RateApp",
        consumer_ref="cons_j",
        rate_limit_per_hour=3,
    )
    conn_id = stack["connection"]["id"]
    consumer = stack["consumer"]

    validate_success(api.refresh_connection(conn_id, {"kind": "FULL"}, consumer))
    validate_success(api.refresh_connection(conn_id, {"kind": "FULL"}, consumer))
    validate_error(
        api.refresh_connection(conn_id, {"kind": "FULL"}, consumer),
        ApiErrorId.ERR_RATE_LIMITED,
    )

    jobs, meta = validate_paginated(api.list_refresh_jobs(conn_id, stack["admin"]))
    assert meta["total_count"] == 3, (
        f"the rejected refresh must not record a job; expected 3 jobs, got {meta['total_count']}"
    )


def test_incremental_refresh_at_3599_seconds_too_soon(api):
    """PRD §3.7: "if the connection's `last_refreshed_at` is set, the elapsed
    time since it must be at least 3600 seconds — an elapsed interval of
    exactly 3600 seconds passes, 3599 fails with `ERR_REFRESH_TOO_SOON`."

    Design: Difficulty/boundary_precision_check/boundary_cadence_elapsed_exactly_3600_passes
    """
    stack = setup_active_stack(
        api,
        institution_name="Cadence Bank",
        recipient_name="CadenceApp",
        consumer_ref="cons_k",
    )
    conn_id = stack["connection"]["id"]
    consumer = stack["consumer"]
    admin = stack["admin"]

    # complete_auth's initial FULL refresh stamped last_refreshed_at at the
    # default clock; advance to 3599 seconds later.
    validate_success(api.set_clock({"to_iso8601": "2026-09-01T00:59:59Z"}, admin))

    resp = api.refresh_connection(conn_id, {"kind": "INCREMENTAL"}, consumer)
    validate_error(resp, ApiErrorId.ERR_REFRESH_TOO_SOON)


def test_incremental_refresh_at_exactly_3600_seconds_passes(api):
    """PRD §3.7: "an elapsed interval of exactly 3600 seconds passes, 3599
    fails with `ERR_REFRESH_TOO_SOON`."
    PRD §3.7: "A successful job is stamped `executed_at` with the clock, its
    `attempt_count` increments by one, its `status` becomes `SUCCEEDED`, the
    connection's `last_refreshed_at` is set to the clock."

    Design: Difficulty/boundary_precision_check/boundary_cadence_elapsed_exactly_3600_passes
    """
    stack = setup_active_stack(
        api,
        institution_name="Cadence Bank",
        recipient_name="CadenceApp",
        consumer_ref="cons_k",
    )
    conn_id = stack["connection"]["id"]
    consumer = stack["consumer"]
    admin = stack["admin"]

    validate_success(api.set_clock({"to_iso8601": "2026-09-01T00:59:59Z"}, admin))
    validate_error(
        api.refresh_connection(conn_id, {"kind": "INCREMENTAL"}, consumer),
        ApiErrorId.ERR_REFRESH_TOO_SOON,
    )

    validate_success(api.set_clock({"to_iso8601": "2026-09-01T01:00:00Z"}, admin))
    job = validate_success(api.refresh_connection(conn_id, {"kind": "INCREMENTAL"}, consumer))
    assert job["status"] == "SUCCEEDED", (
        f"elapsed exactly 3600 seconds must pass the cadence gate, got {job['status']}"
    )

    connection = validate_success(api.get_connection(conn_id, consumer))
    assert_instants_equal(
        connection["last_refreshed_at"], "2026-09-01T01:00:00Z", "last_refreshed_at"
    )
