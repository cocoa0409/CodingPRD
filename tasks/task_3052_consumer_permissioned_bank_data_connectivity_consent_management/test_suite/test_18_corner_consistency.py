"""Corner queue B — consistency_model section instances."""

from test_helpers import (
    assert_instants_equal,
    setup_active_stack,
    validate_success,
)


def test_immediate_consistency_refresh_effects_visible_in_same_response(api):
    """PRD §3.7: "Refreshing is synchronous: each refresh request executes one
    `RefreshJob` immediately, so a job is created in `QUEUED` state and
    resolved to a terminal state — `SUCCEEDED` or `FAILED` — within the same
    request."
    PRD §3.7: "A successful job is stamped `executed_at` with the clock, its
    `attempt_count` increments by one, its `status` becomes `SUCCEEDED`, the
    connection's `last_refreshed_at` is set to the clock, and
    `consecutive_failures` resets to 0."

    Design: Corner/consistency_model/immediate_consistency_refresh_effects_visible_in_same_response
    """
    stack = setup_active_stack(
        api,
        institution_name="ImmedBank",
        recipient_name="ImmedApp",
        consumer_ref="cons_aj",
    )
    conn_id = stack["connection"]["id"]
    consumer = stack["consumer"]

    job = validate_success(api.refresh_connection(conn_id, {"kind": "FULL"}, consumer))
    assert job["status"] == "SUCCEEDED", (
        "the refresh response itself must carry the resolved terminal state"
    )
    assert job["attempt_count"] == 1
    assert_instants_equal(job["executed_at"], "2026-09-01T00:00:00Z", "executed_at")

    connection = validate_success(api.get_connection(conn_id, consumer))
    assert_instants_equal(
        connection["last_refreshed_at"], "2026-09-01T00:00:00Z", "last_refreshed_at"
    )
    assert connection["consecutive_failures"] == 0
