"""Corner probes over the validation surface: feed-state gates, mode
configuration, interval ordering and data-share visibility timing."""

from prd_bench_local_runner.testing import (
    get_success_data,
    validate_error,
    validate_paginated,
)

from test_helpers import ApiErrorId, fixtures
from test_helpers import factories as f
from test_helpers.test_users import (
    NETWORK_OPS_HEADERS,
    PLATFORM_ADMIN_HEADERS,
    make_carrier_rep_headers,
    make_shipper_rep_headers,
)


def _active_world(api):
    fixtures.set_clock(api, fixtures.BASE_CLOCK)
    carrier = fixtures.create_carrier(api)
    connection = fixtures.create_active_connection(api, carrier)
    shipper = fixtures.create_shipper(api)
    return carrier, connection, shipper


def test_event_ingest_on_suspended_connection_rejected(api):
    """A suspended feed stops carrying live traffic until it resumes.

    PRD: "requires the feed connection to be `ACTIVE` (a `TESTING` feed can
    certify but not carry live traffic, and any other state also fails with
    `ERR_CONNECTION_NOT_ACTIVE`), and requires the shipment not to be
    terminal — ingesting an event onto a `DELIVERED` or `CANCELLED` shipment is
    rejected with `ERR_SHIPMENT_NOT_TRACKABLE` (HTTP 409)."
    Design: Corner/validations/event_ingest_on_suspended_connection_rejected
    """
    carrier, connection, shipper = _active_world(api)
    shipment = fixtures.create_shipment(api, shipper, carrier, connection)

    get_success_data(
        api.suspend_connection(connection["id"], f.suspend_payload(), NETWORK_OPS_HEADERS)
    )

    response = api.ingest_event(
        shipment["id"],
        f.event_payload("2026-09-01T06:00:00Z", "DEPARTED"),
        make_carrier_rep_headers(carrier["id"]),
    )
    validate_error(response, ApiErrorId.ERR_CONNECTION_NOT_ACTIVE)

    rows, meta = validate_paginated(api.list_events(shipment["id"], NETWORK_OPS_HEADERS))
    assert meta["total_count"] == 0


def test_shipment_mode_not_supported_by_connection_rejected(api):
    """The shipment's mode must be one the connection can feed.

    PRD: "the shipment's `mode` must appear among the connection's
    `supported_modes` (`ERR_INVALID_MODE_CONFIG` otherwise)."
    Design: Corner/validations/shipment_mode_not_supported_by_connection_rejected
    """
    fixtures.set_clock(api, fixtures.BASE_CLOCK)
    carrier = fixtures.create_carrier(api)
    connection = fixtures.create_testing_connection(
        api, carrier, channel="TMS", supported_modes=["TRUCKLOAD"]
    )
    shipper = fixtures.create_shipper(api)

    response = api.create_shipment(
        shipper["id"],
        f.shipment_payload(
            carrier["id"],
            connection["id"],
            mode="OCEAN",
            mode_reference="CONT-1",
            planned_arrival_at="2026-09-20T00:00:00Z",
        ),
        make_shipper_rep_headers(shipper["id"]),
    )
    validate_error(response, ApiErrorId.ERR_INVALID_MODE_CONFIG)

    rows, meta = validate_paginated(
        api.list_shipper_shipments(shipper["id"], NETWORK_OPS_HEADERS)
    )
    assert meta["total_count"] == 0


def test_inverted_appointment_window_rejected(api):
    """A zero-length appointment window is invalid before any overlap check.

    PRD: "The end must be strictly after the start (`ERR_INVALID_REQUEST`)."
    Design: Corner/validations/inverted_appointment_window_rejected
    """
    fixtures.set_clock(api, fixtures.BASE_CLOCK)
    carrier = fixtures.create_carrier(api)
    connection = fixtures.create_testing_connection(api, carrier, channel="TMS")
    shipper = fixtures.create_shipper(api)
    shipment = fixtures.create_shipment(api, shipper, carrier, connection)
    facility = fixtures.create_facility(api)

    response = api.book_appointment(
        facility["id"],
        f.appointment_payload(
            shipment["id"],
            "2026-09-01T10:00:00Z",
            "2026-09-01T10:00:00Z",
            facility["version"],
        ),
        make_carrier_rep_headers(carrier["id"]),
    )
    validate_error(response, ApiErrorId.ERR_INVALID_REQUEST)

    rows, meta = validate_paginated(
        api.list_facility_appointments(facility["id"], PLATFORM_ADMIN_HEADERS)
    )
    assert meta["total_count"] == 0


def test_grant_expired_window_blocks_read(api):
    """An expired grant no longer authorizes reads even while still ACTIVE.

    PRD: "A `CarrierRep` or `ConsigneeRep` reading another shipper's shipment
    detail, tracking events, or alerts must be covered by an `ACTIVE` grant
    whose `grantee_id` matches their `X-User-ID` and whose window contains the
    current logical time; otherwise the read fails with
    `ERR_DATA_SHARE_FORBIDDEN` (HTTP 403)."
    Design: Corner/validations/grant_expired_window_blocks_read
    """
    fixtures.set_clock(api, fixtures.BASE_CLOCK)
    carrier = fixtures.create_carrier(api)
    connection = fixtures.create_testing_connection(api, carrier, channel="TMS")
    shipper = fixtures.create_shipper(api)
    shipment = fixtures.create_shipment(api, shipper, carrier, connection)
    other_carrier = fixtures.create_carrier(
        api, carrier_name="Second Carrier", scac_code="SECC"
    )

    grant = get_success_data(
        api.create_data_share_grant(
            shipper["id"],
            f.data_share_grant_payload(
                "CARRIER",
                other_carrier["id"],
                scope="FULL_TRACE",
                effective_from="2026-09-01T00:00:00Z",
                expires_at="2026-09-02T00:00:00Z",
            ),
            make_shipper_rep_headers(shipper["id"]),
        )
    )
    assert grant["status"] == "ACTIVE"

    fixtures.set_clock(api, "2026-09-03T00:00:00Z")

    response = api.get_shipment(
        shipment["id"], make_carrier_rep_headers(other_carrier["id"])
    )
    validate_error(response, ApiErrorId.ERR_DATA_SHARE_FORBIDDEN)

    rows, _meta = validate_paginated(
        api.list_shipper_data_share_grants(shipper["id"], NETWORK_OPS_HEADERS)
    )
    assert rows[0]["status"] == "ACTIVE"


def test_revoke_active_grant_then_revoke_again_rejected(api):
    """Revoke is not idempotent: the second revoke is refused.

    PRD: "Revoking it — again only by the granting shipper's own
    representative — requires it still be `ACTIVE`; revoking an
    already-revoked grant is rejected with `ERR_GRANT_ALREADY_REVOKED` (HTTP
    409), and revocation cuts access immediately, so the next read by the
    former grantee fails with `ERR_DATA_SHARE_FORBIDDEN`."
    Design: Corner/validations/revoke_active_grant_then_revoke_again_rejected
    """
    fixtures.set_clock(api, fixtures.BASE_CLOCK)
    carrier = fixtures.create_carrier(api)
    shipper = fixtures.create_shipper(api)
    headers = make_shipper_rep_headers(shipper["id"])

    grant = get_success_data(
        api.create_data_share_grant(
            shipper["id"], f.data_share_grant_payload("CARRIER", carrier["id"]), headers
        )
    )

    revoked = get_success_data(api.revoke_data_share_grant(grant["id"], headers))
    assert revoked["status"] == "REVOKED"

    response = api.revoke_data_share_grant(grant["id"], headers)
    validate_error(response, ApiErrorId.ERR_GRANT_ALREADY_REVOKED)
