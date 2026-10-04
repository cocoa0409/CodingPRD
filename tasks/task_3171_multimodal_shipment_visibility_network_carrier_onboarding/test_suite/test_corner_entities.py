"""Corner probes over the resource surface: creation, retrieval, listing,
not-found, required fields, defaults, computed fields, immutability and type
constraints."""

from prd_bench_local_runner.testing import (
    get_success_data,
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import (
    ApiErrorId,
    assert_carrier,
    assert_connection,
    assert_instant_equal,
    assert_tracking_event,
    fixtures,
)
from test_helpers import factories as f
from test_helpers.test_users import (
    NETWORK_OPS_HEADERS,
    PLATFORM_ADMIN_HEADERS,
    make_shipper_rep_headers,
)


def test_carrier_create_returns_system_fields_and_version_one(api):
    """A created carrier carries only what was supplied plus the system fields.

    PRD: "A `NetworkOps` operator registers a carrier organization by supplying
    its `carrier_name` and its Standard Carrier Alpha Code, `scac_code`; the
    carrier's `version` starts at 1."
    Design: Corner/entities/carrier_create_returns_system_fields_and_version_one
    """
    fixtures.set_clock(api, fixtures.BASE_CLOCK)

    response = api.create_carrier(
        f.carrier_payload(carrier_name="Corner Freight", scac_code="CRNF"), NETWORK_OPS_HEADERS
    )
    data = validate_success(response, 201)
    assert_carrier(data)
    assert data["carrier_name"] == "Corner Freight"
    assert data["scac_code"] == "CRNF"
    assert data["version"] == 1

    read = get_success_data(api.get_carrier(data["id"], NETWORK_OPS_HEADERS))
    assert read["id"] == data["id"]


def test_connection_get_round_trips_stored_and_computed_fields(api):
    """A DRAFT connection shows its derived cadence and null quality views.

    PRD: "The new connection starts in `DRAFT` with its cadence derived from
    the channel (§2.10), its `credential_ref`, `testing_window_start`,
    `testing_window_end`, both quality scores, `last_heartbeat_at`, and
    `suspended_at` all null, and `missed_heartbeat_streak` at 0."
    Design: Corner/entities/connection_get_round_trips_stored_and_computed_fields
    """
    fixtures.set_clock(api, fixtures.BASE_CLOCK)
    carrier = fixtures.create_carrier(api)
    connection = fixtures.create_connection(
        api, carrier, channel="TMS", supported_modes=["TRUCKLOAD", "RAIL"]
    )

    read = fixtures.read_connection(api, connection["id"])
    assert_connection(read)
    assert read["channel"] == "TMS"
    assert read["cadence_minutes"] == 240
    assert read["status"] == "DRAFT"
    assert read["credential_ref"] is None
    assert read["data_quality_score"] is None
    assert read["instantaneous_quality_score"] is None
    assert read["last_heartbeat_at"] is None
    assert read["suspended_at"] is None
    assert read["missed_heartbeat_streak"] == 0


def test_shipments_list_paginates_and_reports_total_count_and_has_more(api):
    """limit/offset slice the list; total_count and has_more describe the whole.

    PRD: "The `limit` parameter caps the number of items returned; it defaults
    to 10, accepts a minimum of 1 and a maximum of 100. The `offset` parameter
    skips a number of items from the front of the result set and defaults to 0.
    Unless otherwise specified, every list endpoint returns resources sorted by
    `created_at` in ascending order. The `meta` object of a list response
    carries `limit`, `offset`, `total_count`, and `has_more`."
    Design: Corner/entities/shipments_list_paginates_and_reports_total_count_and_has_more
    """
    fixtures.set_clock(api, fixtures.BASE_CLOCK)
    carrier = fixtures.create_carrier(api)
    connection = fixtures.create_testing_connection(api, carrier, channel="TMS")
    shipper = fixtures.create_shipper(api)
    fixtures.create_shipment(api, shipper, carrier, connection, tracking_reference="PG-1")
    fixtures.create_shipment(api, shipper, carrier, connection, tracking_reference="PG-2")

    page1, meta1 = validate_paginated(
        api.list_shipments(
            NETWORK_OPS_HEADERS, params={"connection_id": connection["id"], "limit": 1, "offset": 0}
        )
    )
    assert len(page1) == 1
    assert meta1["total_count"] == 2
    assert meta1["has_more"] is True

    page2, meta2 = validate_paginated(
        api.list_shipments(
            NETWORK_OPS_HEADERS, params={"connection_id": connection["id"], "limit": 1, "offset": 1}
        )
    )
    assert len(page2) == 1
    assert meta2["has_more"] is False
    assert page1[0]["id"] != page2[0]["id"]

    all_rows, meta_all = validate_paginated(
        api.list_shipments(NETWORK_OPS_HEADERS, params={"connection_id": connection["id"]})
    )
    assert len(all_rows) == 2
    assert meta_all["limit"] == 10
    assert meta_all["offset"] == 0


def test_shipment_get_unknown_id_returns_shipment_not_found(api):
    """A syntactically valid but unallocated id is a 404, not a generic error.

    PRD: "The per-entity not-found errors are `ERR_CARRIER_NOT_FOUND`,
    `ERR_SHIPPER_NOT_FOUND`, `ERR_CONSIGNEE_NOT_FOUND`,
    `ERR_CONNECTION_NOT_FOUND`, `ERR_PURCHASE_ORDER_NOT_FOUND`,
    `ERR_FACILITY_NOT_FOUND`, `ERR_SHIPMENT_NOT_FOUND`, `ERR_EVENT_NOT_FOUND`,
    `ERR_IDENTITY_LINK_NOT_FOUND`, `ERR_ALERT_NOT_FOUND`,
    `ERR_APPOINTMENT_NOT_FOUND`, and `ERR_DATA_SHARE_GRANT_NOT_FOUND`, each
    with HTTP status 404."
    Design: Corner/entities/shipment_get_unknown_id_returns_shipment_not_found
    """
    fixtures.set_clock(api, fixtures.BASE_CLOCK)

    response = api.get_shipment(
        "11111111-2222-4333-8444-555555555555", NETWORK_OPS_HEADERS
    )
    validate_error(response, ApiErrorId.ERR_SHIPMENT_NOT_FOUND)


def test_purchase_order_missing_po_number_rejected(api):
    """The required po_number must be present at creation.

    PRD: "A shipper's `ShipperRep` first creates purchase orders under their
    own shipper, each with a `po_number`, a `destination_code`, and the
    carrier-side `booking_reference`; each order's `confirmed_link_count`
    starts at 0."
    PRD: "(5) request-shape validity — required fields, enum membership,
    interval ordering, and mode-configuration rules; (6) state preconditions of
    the target resource; (7) interval-occupation conflicts (appointment windows
    and testing windows); (8) threshold gates (the activation quality gate and
    the identity-match confirm gate); and (9) optimistic-concurrency and
    grantee referential checks."
    Design: Corner/entities/purchase_order_missing_po_number_rejected
    """
    fixtures.set_clock(api, fixtures.BASE_CLOCK)
    shipper = fixtures.create_shipper(api)

    response = api.create_purchase_order(
        shipper["id"],
        {"destination_code": "LAX", "booking_reference": "BK-R"},
        make_shipper_rep_headers(shipper["id"]),
    )
    validate_error(response, ApiErrorId.ERR_INVALID_REQUEST)

    rows, meta = validate_paginated(
        api.list_shipper_purchase_orders(shipper["id"], NETWORK_OPS_HEADERS)
    )
    assert meta["total_count"] == 0


def test_shipment_po_reference_claim_defaults_to_empty_string(api):
    """A shipment without a claim stores the empty string and stays UNRESOLVED.

    PRD: "an optional `po_reference_claim` (the carrier-claimed purchase-order
    number used later for identity matching; it defaults to the empty string
    when unknown), and the planned `planned_departure_at` and
    `planned_arrival_at` timestamps, with arrival strictly after departure
    (`ERR_INVALID_REQUEST` otherwise)."
    PRD: "A new shipment starts with `tracking_status` `BOOKED`,
    `identity_state` `UNRESOLVED`, `data_freshness` `FRESH`, and
    `actual_delay_minutes` 0; creation immediately runs the ETA prediction in
    its baseline variant (§3.5) and computes the confidence halfwidth."
    Design: Corner/entities/shipment_po_reference_claim_defaults_to_empty_string
    """
    fixtures.set_clock(api, fixtures.BASE_CLOCK)
    carrier = fixtures.create_carrier(api)
    connection = fixtures.create_testing_connection(api, carrier, channel="TMS")
    shipper = fixtures.create_shipper(api)

    shipment = fixtures.create_shipment(api, shipper, carrier, connection)
    assert shipment["po_reference_claim"] == ""
    assert shipment["identity_state"] == "UNRESOLVED"
    assert shipment["eta_variant"] == "SCHEDULED_BASELINE"


def test_connection_cadence_minutes_computed_from_channel(api):
    """The cadence follows the channel, whatever the client supplies.

    PRD: "a `TELEMATICS` connection must report every 15 minutes, a `TMS`
    connection every 240 minutes (4 hours), and a `MANUAL` connection every
    1440 minutes (once a day)."
    Design: Corner/entities/connection_cadence_minutes_computed_from_channel
    """
    fixtures.set_clock(api, fixtures.BASE_CLOCK)
    carrier = fixtures.create_carrier(api)

    connection = get_success_data(
        api.create_connection(
            carrier["id"],
            {
                "channel": "MANUAL",
                "supported_modes": ["TRUCKLOAD", "OCEAN"],
            },
            NETWORK_OPS_HEADERS,
        )
    )
    assert connection["cadence_minutes"] == 1440
    assert connection["supported_modes"] == ["TRUCKLOAD", "OCEAN"]


def test_tracking_event_immutable_no_version_field(api):
    """Tracking events are append-only: no version, no updated_at.

    PRD: "Two entity kinds are deliberately lighter. `TrackingEvent` and
    `HeartbeatRecord` are append-only child records: each carries `id` and
    `created_at` only — both `updated_at` and `version` are absent from them."
    Design: Corner/entities/tracking_event_immutable_no_version_field
    """
    fixtures.set_clock(api, fixtures.BASE_CLOCK)
    carrier = fixtures.create_carrier(api)
    connection = fixtures.create_active_connection(api, carrier)
    shipper = fixtures.create_shipper(api)
    shipment = fixtures.create_shipment(api, shipper, carrier, connection)

    event = fixtures.ingest_event(api, shipment, "2026-09-01T06:00:00Z", "DEPARTED")
    assert_tracking_event(event)
    assert event["is_late"] is False
    assert event["voided"] is False
    assert_instant_equal(event["event_time"], "2026-09-01T06:00:00Z", "event_time")


def test_manual_channel_with_parcel_mode_rejected(api):
    """MANUAL cannot serve PARCEL; TELEMATICS can.

    PRD: "a `MANUAL` connection must not include `PARCEL` among its supported
    modes (manual entry cannot keep pace with parcel scan volume), and every
    mode list must be a non-empty subset of the four mode enums. Violations of
    either rule are rejected with `ERR_INVALID_MODE_CONFIG` (HTTP 400)."
    Design: Corner/entities/manual_channel_with_parcel_mode_rejected
    """
    fixtures.set_clock(api, fixtures.BASE_CLOCK)
    carrier = fixtures.create_carrier(api)

    manual = api.create_connection(
        carrier["id"],
        f.connection_payload(channel="MANUAL", supported_modes=["PARCEL"]),
        NETWORK_OPS_HEADERS,
    )
    validate_error(manual, ApiErrorId.ERR_INVALID_MODE_CONFIG)

    telematics = get_success_data(
        api.create_connection(
            carrier["id"],
            f.connection_payload(channel="TELEMATICS", supported_modes=["PARCEL"]),
            NETWORK_OPS_HEADERS,
        )
    )
    assert telematics["channel"] == "TELEMATICS"
    assert telematics["supported_modes"] == ["PARCEL"]
