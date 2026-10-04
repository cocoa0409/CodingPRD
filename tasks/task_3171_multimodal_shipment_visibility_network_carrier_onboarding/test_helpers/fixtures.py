"""Composite fixtures that walk the public API to a wanted state.

Every test starts against an empty deployment, so each test has to build the
world it needs from scratch. These helpers do that walking through the public
API only - no direct data writes - and return the resources, headers and
observed versions the test then asserts against.

They are organised from the simplest to the most far-reaching:

  Tier 1  the clock, and single-resource creators
  Tier 2  the carrier/connection onboarding walk (DRAFT -> TESTING -> ACTIVE)
  Tier 3  the shipper-side graph (consignees, purchase orders, shipments)
  Tier 4  event ingest, alerts, and appointment booking
  Tier 5  delay-risk cascades and delay-confirmed resolution chains

Setup calls use the lenient success reader, so a failure inside a fixture is
reported as a setup failure rather than as a mysterious assertion error.
"""

from typing import Any, Dict, List, Optional, Tuple

from prd_bench_local_runner.testing import get_success_data, validate_paginated

from .api_client import ApiClient
from . import factories as f
from .test_users import (
    CUSTOMER_SERVICE_HEADERS,
    NETWORK_OPS_HEADERS,
    PLATFORM_ADMIN_HEADERS,
    make_carrier_rep_headers,
    make_shipper_rep_headers,
)

BASE_CLOCK = "2026-09-01T00:00:00Z"
DEFAULT_TEST_WINDOW = ("2026-09-01T00:00:00Z", "2026-09-10T00:00:00Z")


# ═══ Tier 1: clock and single-resource creators ════════════════════════════


def set_clock(api: ApiClient, to_iso8601: str) -> Dict[str, Any]:
    """Move the logical clock and return what the write reported."""
    return get_success_data(api.set_clock(f.clock_payload(to_iso8601), PLATFORM_ADMIN_HEADERS))


def run_checkpoint(api: ApiClient) -> Dict[str, Any]:
    """Run one ops-run checkpoint and return the OpsRun record."""
    return get_success_data(api.run_checkpoint(PLATFORM_ADMIN_HEADERS))


def create_carrier(api: ApiClient, **overrides: Any) -> Dict[str, Any]:
    return get_success_data(api.create_carrier(f.carrier_payload(**overrides), NETWORK_OPS_HEADERS))


def create_shipper(api: ApiClient, **overrides: Any) -> Dict[str, Any]:
    return get_success_data(
        api.create_shipper(f.shipper_payload(**overrides), PLATFORM_ADMIN_HEADERS)
    )


def create_consignee(api: ApiClient, shipper: Dict[str, Any], **overrides: Any) -> Dict[str, Any]:
    return get_success_data(
        api.create_consignee(
            shipper["id"],
            f.consignee_payload(**overrides),
            make_shipper_rep_headers(shipper["id"]),
        )
    )


def create_facility(api: ApiClient, **overrides: Any) -> Dict[str, Any]:
    return get_success_data(
        api.create_facility(f.facility_payload(**overrides), PLATFORM_ADMIN_HEADERS)
    )


# ═══ Tier 2: carrier/connection onboarding walk ════════════════════════════


def create_connection(
    api: ApiClient,
    carrier: Dict[str, Any],
    channel: str = "TMS",
    supported_modes: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """A DRAFT connection under the given carrier."""
    modes = supported_modes if supported_modes is not None else ["TRUCKLOAD"]
    return get_success_data(
        api.create_connection(
            carrier["id"],
            f.connection_payload(channel=channel, supported_modes=modes),
            NETWORK_OPS_HEADERS,
        )
    )


def walk_to_testing(
    api: ApiClient,
    connection: Dict[str, Any],
    window: Tuple[str, str] = DEFAULT_TEST_WINDOW,
    credential_ref: str = "vault://fixture",
) -> Dict[str, Any]:
    """DRAFT -> CREDENTIALS_SUBMITTED -> TESTING. Returns the TESTING connection."""
    carrier_id = connection["carrier_id"]
    get_success_data(
        api.submit_credentials(
            connection["id"],
            f.credentials_payload(credential_ref),
            make_carrier_rep_headers(carrier_id),
        )
    )
    return get_success_data(
        api.begin_testing(
            connection["id"],
            f.begin_testing_payload(window[0], window[1]),
            NETWORK_OPS_HEADERS,
        )
    )


def create_testing_connection(
    api: ApiClient,
    carrier: Dict[str, Any],
    channel: str = "TMS",
    supported_modes: Optional[List[str]] = None,
    window: Tuple[str, str] = DEFAULT_TEST_WINDOW,
) -> Dict[str, Any]:
    """Carrier-scoped helper: DRAFT -> TESTING in one call."""
    connection = create_connection(api, carrier, channel=channel, supported_modes=supported_modes)
    return walk_to_testing(api, connection, window=window)


def post_heartbeat(
    api: ApiClient,
    connection: Dict[str, Any],
    reported_at: str,
    completeness: int = 100,
) -> Dict[str, Any]:
    """Post one heartbeat as the owning carrier's representative."""
    return get_success_data(
        api.post_heartbeat(
            connection["id"],
            f.heartbeat_payload(reported_at, completeness),
            make_carrier_rep_headers(connection["carrier_id"]),
        )
    )


def activate_connection(api: ApiClient, connection: Dict[str, Any]) -> Dict[str, Any]:
    """TESTING -> ACTIVE. Returns the ACTIVE connection."""
    return get_success_data(api.activate_connection(connection["id"], NETWORK_OPS_HEADERS))


def create_active_connection(
    api: ApiClient,
    carrier: Dict[str, Any],
    channel: str = "TELEMATICS",
    supported_modes: Optional[List[str]] = None,
    heartbeat_at: str = "2026-09-01T00:05:00Z",
    checkpoint_at: str = "2026-09-01T00:15:00Z",
    window: Tuple[str, str] = DEFAULT_TEST_WINDOW,
) -> Dict[str, Any]:
    """Walk a connection to ACTIVE with a single perfect heartbeat.

    One on-time, completeness-100 heartbeat inside a checkpoint window whose
    expected count is 1 scores the authoritative quality at 100: timeliness
    100, completeness 100, cadence 100. That comfortably clears the activation
    gate. Returns the ACTIVE connection.

    The heartbeat defaults to 00:05, strictly after the connection's
    `created_at` (00:00), because the PRD pins the scoring window as "from
    just after the later of the connection's `created_at` and the previous
    run's execution time, up to and including now" — a heartbeat recorded at
    exactly `created_at` falls outside the half-open window.
    """
    connection = create_testing_connection(
        api, carrier, channel=channel, supported_modes=supported_modes, window=window
    )
    # Advance the clock to the heartbeat instant so the heartbeat's
    # `recorded_at` lands strictly after the connection's `created_at`.
    set_clock(api, heartbeat_at)
    post_heartbeat(api, connection, heartbeat_at, completeness=100)
    set_clock(api, checkpoint_at)
    run_checkpoint(api)
    return activate_connection(api, connection)


# ═══ Tier 3: shipper-side graph ════════════════════════════════════════════


def create_purchase_order(
    api: ApiClient,
    shipper: Dict[str, Any],
    po_number: str = "PO-1",
    destination_code: str = "LAX",
    booking_reference: str = "BK-1",
) -> Dict[str, Any]:
    return get_success_data(
        api.create_purchase_order(
            shipper["id"],
            f.purchase_order_payload(
                po_number=po_number,
                destination_code=destination_code,
                booking_reference=booking_reference,
            ),
            make_shipper_rep_headers(shipper["id"]),
        )
    )


def create_shipment(
    api: ApiClient,
    shipper: Dict[str, Any],
    carrier: Dict[str, Any],
    connection: Dict[str, Any],
    **overrides: Any,
) -> Dict[str, Any]:
    return get_success_data(
        api.create_shipment(
            shipper["id"],
            f.shipment_payload(carrier["id"], connection["id"], **overrides),
            make_shipper_rep_headers(shipper["id"]),
        )
    )


def read_shipment(api: ApiClient, shipment_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_shipment(shipment_id, NETWORK_OPS_HEADERS))


def read_connection(api: ApiClient, connection_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_connection(connection_id, NETWORK_OPS_HEADERS))


def read_facility(api: ApiClient, facility_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_facility(facility_id, PLATFORM_ADMIN_HEADERS))


def read_purchase_order(api: ApiClient, purchase_order_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_purchase_order(purchase_order_id, NETWORK_OPS_HEADERS))


def read_appointment(api: ApiClient, appointment_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_appointment(appointment_id, NETWORK_OPS_HEADERS))


# ═══ Tier 4: events, alerts, appointments ══════════════════════════════════


def ingest_event(
    api: ApiClient,
    shipment: Dict[str, Any],
    event_time: str,
    event_type: str,
    delay_minutes: Optional[int] = None,
) -> Dict[str, Any]:
    """Ingest one tracking event as the carrying carrier's representative."""
    return get_success_data(
        api.ingest_event(
            shipment["id"],
            f.event_payload(event_time, event_type, delay_minutes),
            make_carrier_rep_headers(shipment["carrier_id"]),
        )
    )


def list_shipment_alerts(api: ApiClient, shipment_id: str) -> List[Dict[str, Any]]:
    rows, _meta = validate_paginated(api.list_shipment_alerts(shipment_id, NETWORK_OPS_HEADERS))
    return rows


def list_facility_appointments(api: ApiClient, facility_id: str) -> List[Dict[str, Any]]:
    rows, _meta = validate_paginated(api.list_facility_appointments(facility_id, PLATFORM_ADMIN_HEADERS))
    return rows


def propose_identity_link(
    api: ApiClient,
    shipment: Dict[str, Any],
    purchase_order: Dict[str, Any],
    expected_po_version: Optional[int] = None,
) -> Dict[str, Any]:
    """Propose a link; re-reads the order's version when none is supplied."""
    version = (
        expected_po_version
        if expected_po_version is not None
        else read_purchase_order(api, purchase_order["id"])["version"]
    )
    return get_success_data(
        api.propose_identity_link(
            shipment["id"],
            f.identity_link_payload(purchase_order["id"], version),
            NETWORK_OPS_HEADERS,
        )
    )


def book_appointment(
    api: ApiClient,
    facility: Dict[str, Any],
    shipment: Dict[str, Any],
    window_start: str,
    window_end: str,
) -> Dict[str, Any]:
    """Book an appointment, reading the facility's current version first."""
    current = read_facility(api, facility["id"])
    return get_success_data(
        api.book_appointment(
            facility["id"],
            f.appointment_payload(shipment["id"], window_start, window_end, current["version"]),
            make_carrier_rep_headers(shipment["carrier_id"]),
        )
    )


def complete_appointment(
    api: ApiClient,
    appointment: Dict[str, Any],
    shipment_carrier_id: str,
    actual_arrival_at: str,
    actual_departure_at: str,
) -> Dict[str, Any]:
    return get_success_data(
        api.complete_appointment(
            appointment["id"],
            f.complete_appointment_payload(actual_arrival_at, actual_departure_at),
            make_carrier_rep_headers(shipment_carrier_id),
        )
    )


# ═══ Tier 5: cascades and delay-confirmed chains ═══════════════════════════


def setup_delayed_shipment_with_open_alert(
    api: ApiClient,
    delay_minutes: int = 180,
    planned_arrival_at: str = "2026-09-03T00:00:00Z",
) -> Dict[str, Any]:
    """ACTIVE connection, a TRUCKLOAD shipment with DEPARTED + DELAY_REPORTED events.

    With quality 100 and a planned run of 2026-09-01T00:00 -> 2026-09-03T00:00,
    the blended ETA lands at planned_arrival_at + delay_minutes; any delay
    above the TRUCKLOAD tolerance of 60 opens a DELAY_RISK alert. Returns the
    world: carrier, connection, shipper, shipment and the OPEN alert.
    """
    set_clock(api, BASE_CLOCK)
    carrier = create_carrier(api)
    connection = create_active_connection(api, carrier)
    shipper = create_shipper(api)
    shipment = create_shipment(api, shipper, carrier, connection, planned_arrival_at=planned_arrival_at)
    ingest_event(api, shipment, "2026-09-01T12:00:00Z", "DEPARTED")
    ingest_event(api, shipment, "2026-09-01T18:00:00Z", "DELAY_REPORTED", delay_minutes=delay_minutes)
    alerts = list_shipment_alerts(api, shipment["id"])
    assert len(alerts) == 1, f"expected one OPEN alert, got {len(alerts)}"
    return {
        "carrier": carrier,
        "connection": connection,
        "shipper": shipper,
        "shipment": shipment,
        "alert": alerts[0],
    }


def acknowledge_and_resolve(
    api: ApiClient,
    alert_id: str,
    resolution: str,
) -> Dict[str, Any]:
    """OPEN -> ACKNOWLEDGED -> RESOLVED. Returns the resolved alert."""
    get_success_data(api.acknowledge_alert(alert_id, CUSTOMER_SERVICE_HEADERS))
    return get_success_data(
        api.resolve_alert(alert_id, f.resolve_payload(resolution), CUSTOMER_SERVICE_HEADERS)
    )
