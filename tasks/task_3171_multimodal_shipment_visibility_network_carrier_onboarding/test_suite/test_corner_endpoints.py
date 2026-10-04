"""Corner probes over the ops endpoints: the checkpoint's run record and the
logical clock, plus the alert queue's filters."""

from prd_bench_local_runner.testing import (
    get_success_data,
    validate_error,
    validate_paginated,
)

from test_helpers import ApiErrorId, assert_ops_run, fixtures
from test_helpers.test_users import (
    CUSTOMER_SERVICE_HEADERS,
    PLATFORM_ADMIN_HEADERS,
)


def test_ops_run_checkpoint_reports_per_run_counters(api):
    """Idle runs report all-zero counters and the run_index still advances.

    PRD: "Each invocation produces an `OpsRun` record carrying a monotonic
    `run_index` starting at 1, the logical-clock `executed_at` timestamp, and
    per-run counters: `connections_degraded` (connections auto-suspended for
    staleness in this run), `testing_connections_reset` (testing connections
    reset for expired windows), `etas_recomputed` (shipments whose ETA was
    recomputed), `alerts_created` (exception alerts created), and
    `alerts_escalated` (open high-severity alerts escalated)."
    Design: Corner/endpoints/ops_run_checkpoint_reports_per_run_counters
    """
    fixtures.set_clock(api, fixtures.BASE_CLOCK)

    first = get_success_data(api.run_checkpoint(PLATFORM_ADMIN_HEADERS))
    assert_ops_run(first)
    assert first["run_index"] == 1

    second = get_success_data(api.run_checkpoint(PLATFORM_ADMIN_HEADERS))
    assert_ops_run(second)
    assert second["run_index"] == 2
    assert second["connections_degraded"] == 0
    assert second["testing_connections_reset"] == 0
    assert second["etas_recomputed"] == 0
    assert second["alerts_created"] == 0
    assert second["alerts_escalated"] == 0


def test_clock_rejects_backwards_time(api):
    """The logical clock never moves backwards.

    PRD: "A `PlatformAdmin` may advance the logical clock to a supplied
    `to_iso8601` instant through an admin-only test-driving capability; the
    clock never moves backwards, and attempting to set it to an instant earlier
    than the current logical time is rejected with `ERR_INVALID_REQUEST`."
    Design: Corner/endpoints/clock_rejects_backwards_time
    """
    fixtures.set_clock(api, "2026-09-05T00:00:00Z")

    response = api.set_clock({"to_iso8601": "2026-09-01T00:00:00Z"}, PLATFORM_ADMIN_HEADERS)
    validate_error(response, ApiErrorId.ERR_INVALID_REQUEST)

    # A forward move still succeeds afterwards.
    forward = get_success_data(
        api.set_clock({"to_iso8601": "2026-09-06T00:00:00Z"}, PLATFORM_ADMIN_HEADERS)
    )
    assert forward["current_utc"].startswith("2026-09-06")


def test_alerts_queue_filters_by_status_and_severity(api):
    """The queue's two filters compose: only matching alerts are returned.

    PRD: "Customer-service agents work the queue through two filters —
    `status` and `severity` — alongside the usual pagination."
    Design: Corner/endpoints/alerts_queue_filters_by_status_and_severity
    """
    fixtures.set_clock(api, fixtures.BASE_CLOCK)
    carrier = fixtures.create_carrier(api)
    connection = fixtures.create_active_connection(api, carrier)
    shipper = fixtures.create_shipper(api)
    plan = {"planned_arrival_at": "2026-09-02T00:00:00Z"}
    ship_high = fixtures.create_shipment(
        api, shipper, carrier, connection, tracking_reference="Q-HI", **plan
    )
    ship_medium = fixtures.create_shipment(
        api, shipper, carrier, connection, tracking_reference="Q-MD", **plan
    )
    fixtures.ingest_event(api, ship_high, "2026-09-01T06:00:00Z", "DELAY_REPORTED", delay_minutes=300)
    fixtures.ingest_event(api, ship_medium, "2026-09-01T06:00:00Z", "DELAY_REPORTED", delay_minutes=61)

    rows, meta = validate_paginated(
        api.list_alerts(CUSTOMER_SERVICE_HEADERS, params={"status": "OPEN", "severity": "HIGH"})
    )
    assert meta["total_count"] == 1
    assert rows[0]["severity"] == "HIGH"
    assert rows[0]["assigned_queue"] == "CS_TIER2"
    assert rows[0]["shipment_id"] == ship_high["id"]

    _rows, meta_open = validate_paginated(
        api.list_alerts(CUSTOMER_SERVICE_HEADERS, params={"status": "OPEN"})
    )
    assert meta_open["total_count"] == 2

    rows_medium, meta_medium = validate_paginated(
        api.list_alerts(CUSTOMER_SERVICE_HEADERS, params={"severity": "MEDIUM"})
    )
    assert meta_medium["total_count"] == 1
    assert rows_medium[0]["shipment_id"] == ship_medium["id"]
