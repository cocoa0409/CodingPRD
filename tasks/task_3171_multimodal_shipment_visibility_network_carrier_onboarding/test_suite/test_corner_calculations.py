"""Corner probes over the calculations: baseline ETA, evaluation order,
identity match weights, the strict delay boundary and escalation timing."""

from prd_bench_local_runner.testing import validate_paginated, validate_success

from test_helpers import assert_instant_equal, fixtures
from test_helpers.test_users import NETWORK_OPS_HEADERS


def _active_world(api):
    fixtures.set_clock(api, fixtures.BASE_CLOCK)
    carrier = fixtures.create_carrier(api)
    connection = fixtures.create_active_connection(api, carrier)
    shipper = fixtures.create_shipper(api)
    return carrier, connection, shipper


def test_eta_baseline_computed_at_creation_without_events(api):
    """A fresh shipment's ETA is its planned arrival, with the neutral-quality CI.

    PRD: "A new shipment starts with `tracking_status` `BOOKED`,
    `identity_state` `UNRESOLVED`, `data_freshness` `FRESH`, and
    `actual_delay_minutes` 0; creation immediately runs the ETA prediction in
    its baseline variant (§3.5) and computes the confidence halfwidth."
    PRD: "a connection that has never been scored contributes a neutral 50."
    Design: Corner/calculations/eta_baseline_computed_at_creation_without_events
    """
    fixtures.set_clock(api, fixtures.BASE_CLOCK)
    carrier = fixtures.create_carrier(api)
    connection = fixtures.create_testing_connection(api, carrier, channel="TMS")
    shipper = fixtures.create_shipper(api)

    shipment = fixtures.create_shipment(api, shipper, carrier, connection)
    assert shipment["eta_variant"] == "SCHEDULED_BASELINE"
    assert_instant_equal(shipment["eta_at"], "2026-09-03T00:00:00Z", "baseline eta")
    # BASE 120 * (1 + (100 - 50)/100) = 180 for the unscored connection.
    assert shipment["eta_confidence_halfwidth_minutes"] == 180


def test_eta_confidence_uses_prior_epoch_quality_not_current_run(api):
    """The current run's fresh score never feeds the same run's intervals.

    PRD: "The quality input is the feed connection's authoritative
    `data_quality_score` **as of the last completed ops-run checkpoint** — the
    evaluation order is pinned so that the quality computed in the current run
    never feeds the same run's confidence intervals — and a connection that has
    never been scored contributes a neutral 50."
    PRD: "A window with zero heartbeats also increments the connection's
    `missed_heartbeat_streak`; any window with at least one heartbeat resets
    the streak to 0."
    Design: Corner/calculations/eta_confidence_uses_prior_epoch_quality_not_current_run
    """
    fixtures.set_clock(api, fixtures.BASE_CLOCK)
    carrier = fixtures.create_carrier(api)
    connection = fixtures.create_testing_connection(api, carrier, channel="TMS")
    fixtures.set_clock(api, "2026-09-01T10:00:00Z")
    fixtures.post_heartbeat(api, connection, "2026-09-01T10:00:00Z", completeness=100)
    fixtures.set_clock(api, "2026-09-01T12:00:00Z")
    fixtures.run_checkpoint(api)
    fixtures.activate_connection(api, connection)
    shipper = fixtures.create_shipper(api)
    shipment = fixtures.create_shipment(api, shipper, carrier, connection, destination_code="MEM")
    fixtures.ingest_event(api, shipment, "2026-09-01T12:30:00Z", "DEPARTED")

    # Run 2: the window (12:00, next day 12:00] holds no heartbeats.
    fixtures.set_clock(api, "2026-09-02T12:00:00Z")
    fixtures.run_checkpoint(api)

    read_connection = fixtures.read_connection(api, connection["id"])
    assert read_connection["data_quality_score"] == 0
    assert read_connection["health_status"] == "CRITICAL"
    assert read_connection["missed_heartbeat_streak"] == 1
    # 1440 minutes since the last heartbeat exceeds 2 * 240: auto-suspended.
    assert read_connection["status"] == "SUSPENDED"

    read_shipment = fixtures.read_shipment(api, shipment["id"])
    assert read_shipment["data_freshness"] == "STALE"
    # Prior-epoch quality 83 (not the current run's 0): round(120*1.17*1.5) = 211.
    assert read_shipment["eta_confidence_halfwidth_minutes"] == 211


def _link_world_with_four_shipments(api):
    fixtures.set_clock(api, fixtures.BASE_CLOCK)
    carrier = fixtures.create_carrier(api)
    connection = fixtures.create_testing_connection(api, carrier, channel="TMS")
    shipper = fixtures.create_shipper(api)
    po = fixtures.create_purchase_order(
        api, shipper, po_number="PO-W", destination_code="LAX", booking_reference="BK-W"
    )
    shipments = {
        "po_only": fixtures.create_shipment(
            api, shipper, carrier, connection,
            tracking_reference="XX-1", destination_code="ORD", po_reference_claim="PO-W",
        ),
        "booking_only": fixtures.create_shipment(
            api, shipper, carrier, connection,
            tracking_reference="BK-W", destination_code="ORD",
        ),
        "destination_only": fixtures.create_shipment(
            api, shipper, carrier, connection,
            tracking_reference="XX-3", destination_code="LAX",
        ),
        "no_match": fixtures.create_shipment(
            api, shipper, carrier, connection,
            tracking_reference="XX-4", destination_code="ORD",
        ),
    }
    return po, shipments


def test_identity_match_score_weighted_components(api):
    """Each of the three weighted signals is verified in isolation.

    PRD: "half of the weight goes to whether the shipment's
    `po_reference_claim` equals the order's `po_number` while being non-empty
    (an empty claim contributes nothing); two-fifths go to whether the
    shipment's `tracking_reference` equals the order's `booking_reference`; and
    one-tenth goes to whether the shipment's `destination_code` equals the
    order's `destination_code`."
    Design: Corner/calculations/identity_match_score_weighted_components
    """
    po, shipments = _link_world_with_four_shipments(api)

    expected = {
        "po_only": 0.5,
        "booking_only": 0.4,
        "destination_only": 0.1,
        "no_match": 0.0,
    }
    for key, shipment in shipments.items():
        link = fixtures.propose_identity_link(api, shipment, po)
        assert link["match_score"] == expected[key], (
            f"{key}: expected {expected[key]}, got {link['match_score']}"
        )
        assert link["status"] == "PROPOSED"

    assert fixtures.read_purchase_order(api, po["id"])["confirmed_link_count"] == 0


def test_delay_risk_boundary_at_exactly_tolerance_no_alert(api):
    """Exactly the tolerance opens nothing; one minute more opens a MEDIUM alert.

    PRD: "an alert is created only when the projected delay is **strictly
    greater** than the mode tolerance, while the shipment's `tracking_status`
    is `BOOKED`, `IN_TRANSIT`, `EXCEPTION`, or `OUT_FOR_DELIVERY`, and no
    `DELAY_RISK` alert for the shipment is already sitting in `OPEN`,
    `ESCALATED`, or `ACKNOWLEDGED`."
    PRD: "its `severity` is `HIGH` when the projected delay is strictly greater
    than twice the mode tolerance and `MEDIUM` otherwise, and its
    `assigned_queue` follows severity — `CS_TIER2` for `HIGH`, `CS_TIER1` for
    `MEDIUM`."
    Design: Corner/calculations/delay_risk_boundary_at_exactly_tolerance_no_alert
    """
    carrier, connection, shipper = _active_world(api)
    plan = {"planned_arrival_at": "2026-09-02T00:00:00Z"}
    ship_a = fixtures.create_shipment(
        api, shipper, carrier, connection, tracking_reference="TL-A", **plan
    )
    ship_b = fixtures.create_shipment(
        api, shipper, carrier, connection, tracking_reference="TL-B", **plan
    )

    fixtures.ingest_event(api, ship_a, "2026-09-01T12:00:00Z", "DELAY_REPORTED", delay_minutes=60)
    fixtures.ingest_event(api, ship_b, "2026-09-01T12:00:00Z", "DELAY_REPORTED", delay_minutes=61)

    read_a = fixtures.read_shipment(api, ship_a["id"])
    assert_instant_equal(read_a["eta_at"], "2026-09-02T01:00:00Z", "eta at exactly tolerance")
    _rows_a, meta_a = validate_paginated(
        api.list_shipment_alerts(ship_a["id"], NETWORK_OPS_HEADERS)
    )
    assert meta_a["total_count"] == 0

    read_b = fixtures.read_shipment(api, ship_b["id"])
    assert_instant_equal(read_b["eta_at"], "2026-09-02T01:01:00Z", "eta one over tolerance")
    alerts_b = fixtures.list_shipment_alerts(api, ship_b["id"])
    assert len(alerts_b) == 1
    assert alerts_b[0]["severity"] == "MEDIUM"
    assert alerts_b[0]["assigned_queue"] == "CS_TIER1"


def test_alert_escalation_at_checkpoint_after_sla(api):
    """A HIGH alert escalates only once its age strictly exceeds 240 minutes.

    PRD: "An alert may be escalated by the system: at each ops-run checkpoint,
    any `HIGH`-severity alert still `OPEN` whose age exceeds 240 minutes (four
    hours) moves to `ESCALATED`, counted in the run's `alerts_escalated`."
    Design: Corner/calculations/alert_escalation_at_checkpoint_after_sla
    """
    carrier, connection, shipper = _active_world(api)
    shipment = fixtures.create_shipment(
        api, shipper, carrier, connection, planned_arrival_at="2026-09-02T00:00:00Z"
    )
    # Ingested at 00:15, so the alert's opened_at is 00:15; 300 > 2*60 = HIGH.
    fixtures.ingest_event(api, shipment, "2026-09-01T00:15:00Z", "DELAY_REPORTED", delay_minutes=300)
    alert = fixtures.list_shipment_alerts(api, shipment["id"])[0]
    assert alert["severity"] == "HIGH"

    # Age 225 minutes at 04:00: still OPEN.
    fixtures.set_clock(api, "2026-09-01T04:00:00Z")
    run = fixtures.run_checkpoint(api)
    assert run["alerts_escalated"] == 0
    assert fixtures.list_shipment_alerts(api, shipment["id"])[0]["status"] == "OPEN"

    # Age 241 minutes at 04:16: escalates.
    fixtures.set_clock(api, "2026-09-01T04:16:00Z")
    run2 = fixtures.run_checkpoint(api)
    assert run2["alerts_escalated"] == 1
    assert fixtures.list_shipment_alerts(api, shipment["id"])[0]["status"] == "ESCALATED"
