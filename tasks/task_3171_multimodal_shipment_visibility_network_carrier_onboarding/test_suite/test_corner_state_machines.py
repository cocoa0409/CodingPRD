"""Corner probes over the state machines: invalid transitions, preconditions,
terminal lockdowns, cancel cascades and event replay."""

from prd_bench_local_runner.testing import (
    get_success_data,
    validate_error,
    validate_paginated,
)

from test_helpers import ApiErrorId, assert_instant_equal, fixtures
from test_helpers import factories as f
from test_helpers.test_users import (
    CUSTOMER_SERVICE_HEADERS,
    NETWORK_OPS_HEADERS,
    make_carrier_rep_headers,
    make_shipper_rep_headers,
)


def _testing_world(api):
    fixtures.set_clock(api, fixtures.BASE_CLOCK)
    carrier = fixtures.create_carrier(api)
    connection = fixtures.create_testing_connection(api, carrier, channel="TMS")
    shipper = fixtures.create_shipper(api)
    return carrier, connection, shipper


def _active_world(api):
    fixtures.set_clock(api, fixtures.BASE_CLOCK)
    carrier = fixtures.create_carrier(api)
    connection = fixtures.create_active_connection(api, carrier)
    shipper = fixtures.create_shipper(api)
    return carrier, connection, shipper


def test_activate_from_draft_returns_connection_invalid_state(api):
    """Activation is only valid out of TESTING.

    PRD: "Activation is the quality gate of the whole onboarding flow:
    `NetworkOps` may transition a `TESTING` connection to `ACTIVE` only when
    its authoritative `data_quality_score` is at least 70."
    PRD: "Either way, the transition from `ACTIVE` to `SUSPENDED` requires
    the connection to actually be `ACTIVE` (`ERR_CONNECTION_INVALID_STATE`
    otherwise), records `suspended_at` as the current logical time, and fires
    the three-link staleness cascade described in §3.5 and §3.7: every
    shipment fed by this connection whose `tracking_status` is `IN_TRANSIT` or
    `EXCEPTION` has its `data_freshness` set to `STALE`; each such
    shipment's ETA is recomputed with the stale confidence multiplier; and the
    delay-risk assessment runs per affected shipment, opening an alert where
    warranted."
    Design: Corner/state_machines/activate_from_draft_returns_connection_invalid_state
    """
    fixtures.set_clock(api, fixtures.BASE_CLOCK)
    carrier = fixtures.create_carrier(api)
    connection = fixtures.create_connection(api, carrier, channel="TMS")

    response = api.activate_connection(connection["id"], NETWORK_OPS_HEADERS)
    validate_error(response, ApiErrorId.ERR_CONNECTION_INVALID_STATE)
    assert fixtures.read_connection(api, connection["id"])["status"] == "DRAFT"


def test_resume_without_remediation_heartbeat_rejected(api):
    """Resume needs a heartbeat strictly newer than the suspension.

    PRD: "Resuming a `SUSPENDED` connection requires proof of remediation: the
    carrier must have posted a heartbeat *after* the suspension — concretely,
    the connection's `last_heartbeat_at` must be strictly later than its
    `suspended_at` — or the resume is rejected with
    `ERR_REMEDIATION_NOT_PROVEN` (HTTP 409)."
    Design: Corner/state_machines/resume_without_remediation_heartbeat_rejected
    """
    carrier, connection, shipper = _active_world(api)
    # The only heartbeat was recorded at the base clock, before suspension.
    fixtures.set_clock(api, "2026-09-02T00:00:00Z")
    get_success_data(
        api.suspend_connection(connection["id"], f.suspend_payload(), NETWORK_OPS_HEADERS)
    )

    response = api.resume_connection(connection["id"], NETWORK_OPS_HEADERS)
    validate_error(response, ApiErrorId.ERR_REMEDIATION_NOT_PROVEN)
    assert fixtures.read_connection(api, connection["id"])["status"] == "SUSPENDED"


def _proposed_link(api):
    fixtures.set_clock(api, fixtures.BASE_CLOCK)
    carrier = fixtures.create_carrier(api)
    connection = fixtures.create_testing_connection(api, carrier, channel="TMS")
    shipper = fixtures.create_shipper(api)
    po = fixtures.create_purchase_order(
        api, shipper, po_number="PO-L", destination_code="LAX", booking_reference="BK-L"
    )
    shipment = fixtures.create_shipment(
        api,
        shipper,
        carrier,
        connection,
        tracking_reference="BK-L",
        destination_code="LAX",
        po_reference_claim="PO-L",
    )
    link = fixtures.propose_identity_link(api, shipment, po)
    return shipper, shipment, po, link


def test_reject_confirmed_link_terminal_lockdown(api):
    """REJECTED is terminal: a second reject is refused.

    PRD: "The same `ShipperRep` may reject a link in `PROPOSED` or `CONFIRMED`
    status (any other status draws `ERR_LINK_NOT_PROPOSED`), moving it to the
    terminal `REJECTED` state."
    Design: Corner/state_machines/reject_confirmed_link_terminal_lockdown
    """
    shipper, shipment, po, link = _proposed_link(api)
    headers = make_shipper_rep_headers(shipper["id"])

    rejected = get_success_data(api.reject_identity_link(link["id"], headers))
    assert rejected["status"] == "REJECTED"

    response = api.reject_identity_link(link["id"], headers)
    validate_error(response, ApiErrorId.ERR_LINK_NOT_PROPOSED)


def test_resolve_from_open_requires_acknowledge_first(api):
    """The workflow cannot skip acknowledgement.

    PRD: "Resolution requires the alert to be `ACKNOWLEDGED` and carries a
    mandatory `resolution` — one of `DELAY_CONFIRMED`, `FALSE_ALARM`, or
    `DELIVERY_OBSERVED`; a missing or invalid resolution value is
    `ERR_INVALID_REQUEST`, and resolving from a non-acknowledged status is
    `ERR_ALERT_INVALID_STATE`."
    Design: Corner/state_machines/resolve_from_open_requires_acknowledge_first
    """
    world = fixtures.setup_delayed_shipment_with_open_alert(api, delay_minutes=300)
    alert = world["alert"]
    assert alert["status"] == "OPEN"

    response = api.resolve_alert(
        alert["id"], f.resolve_payload("FALSE_ALARM"), CUSTOMER_SERVICE_HEADERS
    )
    validate_error(response, ApiErrorId.ERR_ALERT_INVALID_STATE)

    rows = fixtures.list_shipment_alerts(api, world["shipment"]["id"])
    assert rows[0]["status"] == "OPEN"


def test_cancel_delivered_shipment_rejected(api):
    """Cancelling a DELIVERED shipment is refused.

    PRD: "A shipper's `ShipperRep` may cancel their own shipment while its
    `tracking_status` is `BOOKED`, `IN_TRANSIT`, or `EXCEPTION`, moving it to
    the terminal `CANCELLED` state; cancelling from `OUT_FOR_DELIVERY` or from
    a terminal state is rejected with `ERR_SHIPMENT_NOT_CANCELLABLE` (HTTP
    409)."
    Design: Corner/state_machines/cancel_delivered_shipment_rejected
    """
    carrier, connection, shipper = _active_world(api)
    shipment = fixtures.create_shipment(api, shipper, carrier, connection)
    fixtures.ingest_event(api, shipment, "2026-09-01T06:00:00Z", "DEPARTED")
    fixtures.ingest_event(api, shipment, "2026-09-01T20:00:00Z", "DELIVERED")
    assert fixtures.read_shipment(api, shipment["id"])["tracking_status"] == "DELIVERED"

    response = api.cancel_shipment(shipment["id"], make_shipper_rep_headers(shipper["id"]))
    validate_error(response, ApiErrorId.ERR_SHIPMENT_NOT_CANCELLABLE)
    assert fixtures.read_shipment(api, shipment["id"])["tracking_status"] == "DELIVERED"


def test_cancel_in_transit_shipment_auto_resolves_open_alert(api):
    """Cancelling cascades to the alert queue as FALSE_ALARM resolutions.

    PRD: "Cancellation cascades to the alert queue: every `OPEN` or `ESCALATED`
    exception alert on the shipment auto-transitions to `RESOLVED` with
    `resolution` `FALSE_ALARM`."
    Design: Corner/state_machines/cancel_in_transit_shipment_auto_resolves_open_alert
    """
    carrier, connection, shipper = _active_world(api)
    shipment = fixtures.create_shipment(
        api, shipper, carrier, connection, planned_arrival_at="2026-09-02T00:00:00Z"
    )
    fixtures.ingest_event(api, shipment, "2026-09-01T06:00:00Z", "DEPARTED")
    fixtures.ingest_event(api, shipment, "2026-09-01T09:00:00Z", "DELAY_REPORTED", delay_minutes=300)
    alert = fixtures.list_shipment_alerts(api, shipment["id"])[0]
    assert alert["status"] == "OPEN"

    cancelled = get_success_data(
        api.cancel_shipment(shipment["id"], make_shipper_rep_headers(shipper["id"]))
    )
    assert cancelled["tracking_status"] == "CANCELLED"

    rows = fixtures.list_shipment_alerts(api, shipment["id"])
    assert rows[0]["status"] == "RESOLVED"
    assert rows[0]["resolution"] == "FALSE_ALARM"
    assert rows[0]["resolved_at"] is not None


def test_appointment_complete_from_missed_rejected(api):
    """Completion requires SCHEDULED; a cascade-missed appointment refuses.

    PRD: "completion requires the appointment still `SCHEDULED`, else
    `ERR_APPOINTMENT_INVALID_STATE`."
    Design: Corner/state_machines/appointment_complete_from_missed_rejected
    """
    fixtures.set_clock(api, fixtures.BASE_CLOCK)
    carrier = fixtures.create_carrier(api)
    connection = fixtures.create_active_connection(api, carrier)
    shipper = fixtures.create_shipper(api)
    shipment = fixtures.create_shipment(api, shipper, carrier, connection)
    facility = fixtures.create_facility(api)
    appointment = fixtures.book_appointment(
        api, facility, shipment, "2026-09-03T01:00:00Z", "2026-09-03T02:00:00Z"
    )

    # Drive the delay-confirmation cascade to flip the appointment to MISSED.
    fixtures.ingest_event(api, shipment, "2026-09-01T12:00:00Z", "DEPARTED")
    fixtures.ingest_event(api, shipment, "2026-09-01T18:00:00Z", "DELAY_REPORTED", delay_minutes=180)
    alert = fixtures.list_shipment_alerts(api, shipment["id"])[0]
    fixtures.acknowledge_and_resolve(api, alert["id"], "DELAY_CONFIRMED")
    assert fixtures.read_appointment(api, appointment["id"])["status"] == "MISSED"

    response = api.complete_appointment(
        appointment["id"],
        f.complete_appointment_payload("2026-09-03T03:30:00Z", "2026-09-03T05:00:00Z"),
        make_carrier_rep_headers(carrier["id"]),
    )
    validate_error(response, ApiErrorId.ERR_APPOINTMENT_INVALID_STATE)

    read = fixtures.read_appointment(api, appointment["id"])
    assert read["status"] == "MISSED"
    assert read["dwell_minutes"] is None


def test_connection_retire_from_draft_valid_terminal(api):
    """Retire from DRAFT succeeds; the terminal state refuses further transitions.

    PRD: "Finally, a connection in `DRAFT` or `SUSPENDED` may be retired by
    `NetworkOps`, moving it to the terminal `RETIRED` state; retirement from
    any other state is rejected with `ERR_CONNECTION_INVALID_STATE`."
    Design: Corner/state_machines/connection_retire_from_draft_valid_terminal
    """
    fixtures.set_clock(api, fixtures.BASE_CLOCK)
    carrier = fixtures.create_carrier(api)
    connection = fixtures.create_connection(api, carrier, channel="TMS")

    retired = get_success_data(api.retire_connection(connection["id"], NETWORK_OPS_HEADERS))
    assert retired["status"] == "RETIRED"

    response = api.submit_credentials(
        connection["id"],
        f.credentials_payload("vault://late"),
        make_carrier_rep_headers(carrier["id"]),
    )
    validate_error(response, ApiErrorId.ERR_CONNECTION_INVALID_STATE)


def test_event_replay_late_arriving_delay_does_not_override_recovery(api):
    """Late telemetry is stored and marked, but replay still picks the latest event.

    PRD: "At ingest, the server flags the event `is_late` when its `event_time`
    is earlier than the greatest `event_time` already applied to the shipment —
    late-arriving telemetry is stored but marked."
    PRD: "It is **derived by replaying** the shipment's non-voided tracking
    events in a pinned order: ascending `event_time`, with ties broken by
    ascending `created_at` of the event record (never by `id`). The latest
    event in that order — the *effective event* — determines the status."
    Design: Corner/state_machines/event_replay_late_arriving_delay_does_not_override_recovery
    """
    carrier, connection, shipper = _active_world(api)
    # The active-world helper leaves the logical clock at 2026-09-01T00:15, and
    # the PRD clamps the elapsed fraction into [0, 1] — an event time before
    # "now" would clamp p at 0. The planned window is moved a day earlier so
    # the 09-01 event times exercise the un-clamped blend.
    shipment = fixtures.create_shipment(
        api,
        shipper,
        carrier,
        connection,
        planned_departure_at="2026-08-31T00:00:00Z",
        planned_arrival_at="2026-09-02T00:00:00Z",
    )
    fixtures.ingest_event(api, shipment, "2026-09-01T06:00:00Z", "DEPARTED")
    fixtures.ingest_event(api, shipment, "2026-09-01T09:00:00Z", "DELAY_REPORTED", delay_minutes=60)
    fixtures.ingest_event(api, shipment, "2026-09-01T12:00:00Z", "RECOVERED", delay_minutes=60)

    late = fixtures.ingest_event(
        api, shipment, "2026-09-01T10:00:00Z", "DELAY_REPORTED", delay_minutes=30
    )
    assert late["is_late"] is True

    read = fixtures.read_shipment(api, shipment["id"])
    assert read["tracking_status"] == "IN_TRANSIT"
    # E = 12:00, p = 720/2880 = 0.25, R*(1-p) = 2160, open delay 60 + 30 - 60 = 30.
    assert_instant_equal(read["eta_at"], "2026-09-02T00:30:00Z", "eta with late event")

    rows, meta = validate_paginated(api.list_events(shipment["id"], NETWORK_OPS_HEADERS))
    assert meta["total_count"] == 4
