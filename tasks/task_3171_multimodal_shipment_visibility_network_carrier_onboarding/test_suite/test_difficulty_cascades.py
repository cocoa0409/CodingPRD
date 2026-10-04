"""The two transitive cascades: checkpoint staleness and delay confirmation."""

from prd_bench_local_runner.testing import get_success_data

from test_helpers import assert_instant_equal, fixtures
from test_helpers import factories as f
from test_helpers.test_users import (
    CUSTOMER_SERVICE_HEADERS,
    NETWORK_OPS_HEADERS,
)


def _tms_world_with_delayed_in_transit_shipment(api):
    """Score a TMS connection 83, activate it, and put a delayed shipment in transit.

    One on-time completeness-100 heartbeat in a 720-minute window scores
    t = 100, c = 100, d = 33 -> 83, HEALTHY. The shipment's blended ETA lands
    at 2026-09-03T03:00 after a 180-minute delay report.
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
    shipment = fixtures.create_shipment(
        api, shipper, carrier, connection, destination_code="MEM"
    )
    fixtures.ingest_event(api, shipment, "2026-09-01T12:00:00Z", "DEPARTED")
    # The delay report lands shortly before the suspending checkpoint so the
    # alert it opens is younger than the 240-minute escalation horizon when
    # that checkpoint runs (PRD §3.7: "any `HIGH`-severity alert still `OPEN`
    # whose age exceeds 240 minutes (four hours) moves to `ESCALATED`").
    fixtures.set_clock(api, "2026-09-05T03:30:00Z")
    fixtures.ingest_event(api, shipment, "2026-09-05T03:30:00Z", "DELAY_REPORTED", delay_minutes=180)
    return carrier, connection, shipper, shipment


# ═══ transitive_cascade / checkpoint_stale_connection_suspension_alert_chain ═


def test_checkpoint_staleness_suspends_and_cascades_to_stale_shipments(api):
    """The checkpoint's staleness hop STALEs the shipment and recomputes its CI.

    PRD: "at each ops-run checkpoint, any `ACTIVE` connection whose most
    recent heartbeat is more than twice its cadence old — that is, the gap
    between now and `last_heartbeat_at` exceeds two times `cadence_minutes` —
    is suspended, and the run's `connections_degraded` counter is
    incremented."
    PRD: "every shipment fed by this connection whose `tracking_status` is
    `IN_TRANSIT` or `EXCEPTION` has its `data_freshness` set to `STALE`; each
    such shipment's ETA is recomputed with the stale confidence multiplier; and
    the delay-risk assessment runs per affected shipment, opening an alert
    where warranted."
    PRD: "When the shipment's `data_freshness` is `STALE`, the whole halfwidth
    is then multiplied by 1.5."
    Design: Difficulty/transitive_cascade/checkpoint_stale_connection_suspension_alert_chain
    """
    carrier, connection, shipper, shipment = _tms_world_with_delayed_in_transit_shipment(api)

    fixtures.set_clock(api, "2026-09-05T04:00:00Z")
    run = fixtures.run_checkpoint(api)

    assert run["connections_degraded"] == 1
    read_connection = fixtures.read_connection(api, connection["id"])
    assert read_connection["status"] == "SUSPENDED"

    read_shipment = fixtures.read_shipment(api, shipment["id"])
    assert read_shipment["data_freshness"] == "STALE"
    # The blended ETA survived the original delay: the effective event is the
    # 09-05T03:30 delay report, p clamps to 1, and the open delay of 180
    # minutes lands the ETA at 09-05T06:30; staleness widens only the interval.
    assert_instant_equal(read_shipment["eta_at"], "2026-09-05T06:30:00Z", "stale eta")
    # Prior-epoch quality 83: round(120 * 1.17 * 1.5) = round(210.6) = 211.
    assert read_shipment["eta_confidence_halfwidth_minutes"] == 211


def test_checkpoint_staleness_opens_a_delay_risk_alert_per_affected_shipment(api):
    """The recompute hop runs the delay-risk assessment and opens the alert.

    PRD: "the delay-risk assessment runs per affected shipment, opening an
    alert where warranted."
    PRD: "an alert is created only when the projected delay is **strictly
    greater** than the mode tolerance, while the shipment's `tracking_status`
    is `BOOKED`, `IN_TRANSIT`, `EXCEPTION`, or `OUT_FOR_DELIVERY`, and no
    `DELAY_RISK` alert for the shipment is already sitting in `OPEN`,
    `ESCALATED`, or `ACKNOWLEDGED`."
    PRD: "its `severity` is `HIGH` when the projected delay is strictly
    greater than twice the mode tolerance and `MEDIUM` otherwise, and its
    `assigned_queue` follows severity — `CS_TIER2` for `HIGH`, `CS_TIER1` for
    `MEDIUM`."
    Design: Difficulty/transitive_cascade/checkpoint_stale_connection_suspension_alert_chain
    """
    carrier, connection, shipper, shipment = _tms_world_with_delayed_in_transit_shipment(api)

    # The 180-minute delay already opened one alert at ingest.
    assert len(fixtures.list_shipment_alerts(api, shipment["id"])) == 1

    fixtures.set_clock(api, "2026-09-05T04:00:00Z")
    run = fixtures.run_checkpoint(api)

    # The already-open alert suppresses a duplicate, so no new alert is created.
    assert run["alerts_created"] == 0
    alerts = fixtures.list_shipment_alerts(api, shipment["id"])
    assert len(alerts) == 1
    alert = alerts[0]
    assert alert["alert_type"] == "DELAY_RISK"
    assert alert["severity"] == "HIGH"  # 180 > 2 * 60
    assert alert["assigned_queue"] == "CS_TIER2"
    assert alert["status"] == "OPEN"


# ═══ transitive_cascade / delay_confirmation_appointment_miss_adherence_chain ═


def _delay_confirmation_world(api):
    """A delayed shipment, one completed adherent appointment, one late SCHEDULED."""
    fixtures.set_clock(api, fixtures.BASE_CLOCK)
    carrier = fixtures.create_carrier(api)
    connection = fixtures.create_active_connection(api, carrier)
    shipper = fixtures.create_shipper(api)
    shipment = fixtures.create_shipment(
        api, shipper, carrier, connection, destination_code="ATL"
    )
    facility = fixtures.create_facility(api, facility_name="Atlanta DC")

    done = fixtures.book_appointment(
        api, facility, shipment, "2026-09-01T08:00:00Z", "2026-09-01T09:00:00Z"
    )
    fixtures.complete_appointment(
        api, done, carrier["id"], "2026-09-01T08:30:00Z", "2026-09-01T09:30:00Z"
    )
    late = fixtures.book_appointment(
        api, facility, shipment, "2026-09-03T01:00:00Z", "2026-09-03T02:00:00Z"
    )

    fixtures.ingest_event(api, shipment, "2026-09-01T12:00:00Z", "DEPARTED")
    fixtures.ingest_event(api, shipment, "2026-09-01T18:00:00Z", "DELAY_REPORTED", delay_minutes=180)
    alert = fixtures.list_shipment_alerts(api, shipment["id"])[0]
    get_success_data(api.acknowledge_alert(alert["id"], CUSTOMER_SERVICE_HEADERS))
    return carrier, shipment, facility, done, late, alert


def test_delay_confirmed_marks_the_late_appointment_missed_and_recomputes_adherence(api):
    """Resolve DELAY_CONFIRMED: delay recorded, late appointment MISSED, adherence halves.

    PRD: "First, the shipment's `actual_delay_minutes` is recorded as the
    ETA's overrun beyond `planned_arrival_at`, floored at zero. Second, every
    `SCHEDULED` appointment of that shipment whose `window_end` is earlier than
    the shipment's `eta_at` — the truck can no longer make the window —
    transitions to `MISSED`. Third, each affected appointment's facility has
    its `appointment_adherence_pct` recomputed with the miss counted
    (§3.8)."
    Design: Difficulty/transitive_cascade/delay_confirmation_appointment_miss_adherence_chain
    """
    carrier, shipment, facility, done, late, alert = _delay_confirmation_world(api)

    resolved = get_success_data(
        api.resolve_alert(alert["id"], f.resolve_payload("DELAY_CONFIRMED"), CUSTOMER_SERVICE_HEADERS)
    )
    assert resolved["status"] == "RESOLVED"
    assert resolved["resolved_at"] is not None

    read_shipment = fixtures.read_shipment(api, shipment["id"])
    assert read_shipment["actual_delay_minutes"] == 180

    read_late = fixtures.read_appointment(api, late["id"])
    assert read_late["status"] == "MISSED"

    read_facility = fixtures.read_facility(api, facility["id"])
    # 1 adherent completion over 1 completed + 1 missed.
    assert read_facility["appointment_adherence_pct"] == 50


def test_delay_confirmed_leaves_on_time_appointments_scheduled(api):
    """Only appointments whose window ends before the ETA are missed.

    PRD: "Second, every `SCHEDULED` appointment of that shipment whose
    `window_end` is earlier than the shipment's `eta_at` — the truck can no
    longer make the window — transitions to `MISSED`."
    Design: Difficulty/transitive_cascade/delay_confirmation_appointment_miss_adherence_chain
    """
    fixtures.set_clock(api, fixtures.BASE_CLOCK)
    carrier = fixtures.create_carrier(api)
    connection = fixtures.create_active_connection(api, carrier)
    shipper = fixtures.create_shipper(api)
    shipment = fixtures.create_shipment(api, shipper, carrier, connection)
    facility = fixtures.create_facility(api)
    # Window ends at 04:00, strictly after the blended ETA 2026-09-03T03:00.
    on_time = fixtures.book_appointment(
        api, facility, shipment, "2026-09-03T02:30:00Z", "2026-09-03T04:00:00Z"
    )

    fixtures.ingest_event(api, shipment, "2026-09-01T12:00:00Z", "DEPARTED")
    fixtures.ingest_event(api, shipment, "2026-09-01T18:00:00Z", "DELAY_REPORTED", delay_minutes=180)
    alert = fixtures.list_shipment_alerts(api, shipment["id"])[0]
    get_success_data(api.acknowledge_alert(alert["id"], CUSTOMER_SERVICE_HEADERS))
    get_success_data(
        api.resolve_alert(alert["id"], f.resolve_payload("DELAY_CONFIRMED"), CUSTOMER_SERVICE_HEADERS)
    )

    read_on_time = fixtures.read_appointment(api, on_time["id"])
    assert read_on_time["status"] == "SCHEDULED"
    assert fixtures.read_facility(api, facility["id"])["appointment_adherence_pct"] is None
