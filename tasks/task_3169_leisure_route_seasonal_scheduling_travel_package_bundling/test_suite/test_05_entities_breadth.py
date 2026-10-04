"""Corner queue B — entities section.

Covers instances:
- entities / station_create_returns_defaults_and_system_fields
- entities / route_get_round_trips_configuration
- entities / routes_list_paginates
- entities / flight_instance_get_unknown_id_returns_not_found
- entities / booking_create_missing_booking_kind_returns_invalid_request
- entities / ancillary_kind_out_of_enum_rejected
- entities / seats_sold_is_computed_not_client_settable
"""
from test_helpers import (
    ANONYMOUS_HEADERS,
    TEST_USERS,
    ApiErrorId,
    NON_EXISTENT_UUID,
    activate_route,
    create_air_only_booking,
    create_route,
    create_window,
    set_default_clock,
    setup_published_pipeline,
    setup_route_with_open_window,
    setup_station_pair,
    validate_error,
    validate_paginated,
    validate_success,
)

NP = TEST_USERS["network_planner_headers"]
OC = TEST_USERS["ops_controller_headers"]
CS = TEST_USERS["customer_service_headers"]
FA = TEST_USERS["finance_analyst_headers"]


def test_station_create_defaults_and_system_fields(api):
    """PRD §3.1: "Each station record carries an `iata_code` that is unique
    across the network, a `station_kind` that classifies the airport as either
    `ORIGIN_SMALL_CITY` or `LEISURE_DESTINATION`, an IANA `timezone` such as
    `America/Phoenix`, and a `single_station_flag` that defaults to `false`"
    (PRD §2.5) "`id` (string): a unique, server-minted identifier formatted
    as a UUID, with no type prefix." and "`version` (integer): a
    system-managed integer that increments with every modification to the
    resource; this is the value used by the optimistic concurrency control
    rules described in §2.9."

    Design: Corner/entities/station_create_returns_defaults_and_system_fields
    """
    set_default_clock()
    resp = api.create_station(
        {
            "iata_code": "SCK",
            "station_kind": "ORIGIN_SMALL_CITY",
            "timezone": "America/Los_Angeles",
        },
        NP,
    )
    body = resp.json()
    assert resp.status_code == 201
    assert body["response_type"] == "object"
    assert isinstance(body["meta"].get("api_request_id"), str)
    assert isinstance(body["meta"].get("api_request_timestamp"), str)

    station = body["data"]
    assert station["single_station_flag"] is False
    assert station["version"] == 1
    assert station.get("id")
    assert station.get("created_at")
    assert station.get("updated_at")


def test_route_get_round_trips_configuration(api):
    """PRD §3.1: "A new route begins life in the `PLANNING` posture with its
    `suspended_seasons_count` at zero; the posture field is named
    `route_posture`."

    Design: Corner/entities/route_get_round_trips_configuration
    """
    set_default_clock()
    pair = setup_station_pair()
    created = create_route(
        pair["origin"]["id"], pair["destination"]["id"],
        base_fare_cents=9900, weekly_frequency_cap=2,
    )
    # Reads are available to every role; read back as CustomerService.
    fetched = validate_success(api.get_route(created["id"], CS))
    assert fetched["base_fare_cents"] == 9900
    assert fetched["weekly_frequency_cap"] == 2
    assert fetched["route_posture"] == "PLANNING"
    assert fetched["suspended_seasons_count"] == 0
    assert fetched["origin_station_id"] == pair["origin"]["id"]
    assert fetched["destination_station_id"] == pair["destination"]["id"]


def test_routes_list_paginates(api):
    """PRD §2.3: "The `limit` parameter specifies the maximum number of items
    to return; if not provided, it defaults to 10, with a minimum of 1 and a
    maximum of 100. The `offset` parameter specifies the number of items to
    skip and defaults to 0." and "Paginated list responses include the
    following fields in the `meta` object of the response envelope: `limit`,
    `offset`, `total_count`, and `has_more`."

    Design: Corner/entities/routes_list_paginates
    """
    set_default_clock()
    pair = setup_station_pair()
    for fare, cap in ((9900, 2), (8900, 1), (7900, 4)):
        create_route(
            pair["origin"]["id"], pair["destination"]["id"],
            base_fare_cents=fare, weekly_frequency_cap=cap,
        )

    page1, meta1 = validate_paginated(
        api.list_routes(FA, params={"limit": 2, "offset": 0})
    )
    assert len(page1) == 2
    assert meta1["total_count"] == 3
    assert meta1["has_more"] is True

    page2, meta2 = validate_paginated(
        api.list_routes(FA, params={"limit": 2, "offset": 2})
    )
    assert len(page2) == 1
    assert meta2["total_count"] == 3
    assert meta2["has_more"] is False


def test_flight_instance_get_unknown_id_returns_not_found(api):
    """PRD §2.7: "Each entity family has its own not-found error —
    `ERR_STATION_NOT_FOUND`, `ERR_ROUTE_NOT_FOUND`, `ERR_WINDOW_NOT_FOUND`,
    `ERR_PUBLICATION_NOT_FOUND`, `ERR_FLIGHT_NOT_FOUND`,
    `ERR_AIRCRAFT_NOT_FOUND`, `ERR_CREW_BASE_NOT_FOUND`,
    `ERR_CREW_MEMBER_NOT_FOUND`, `ERR_OFFER_NOT_FOUND`,
    `ERR_BOOKING_NOT_FOUND`, `ERR_BUNDLE_NOT_FOUND`,
    `ERR_ANCILLARY_NOT_FOUND`, `ERR_SETTLEMENT_NOT_FOUND`,
    `ERR_DISRUPTION_NOT_FOUND`, and `ERR_ASSIGNMENT_NOT_FOUND` — and all are
    returned with HTTP 404."

    Design: Corner/entities/flight_instance_get_unknown_id_returns_not_found
    """
    set_default_clock()
    resp = api.get_flight(NON_EXISTENT_UUID, OC)
    body = resp.json()
    assert resp.status_code == 404
    assert body["response_type"] == "error"
    assert body["data"]["error_id"] == "ERR_FLIGHT_NOT_FOUND"
    assert isinstance(body["data"].get("message"), str)
    assert len(body["data"]["message"].strip()) > 0


# ---------------------------------------------------------------------------
# Deleted generated tests (PRD-silence / unique-derivability collapses):
#
# - booking_create_missing_booking_kind_returns_invalid_request: asserted
#   ERR_INVALID_REQUEST (HTTP 400) for a missing booking_kind. PRD §5's error
#   catalogue "enumerates every error identifier the API can return" and
#   contains no ERR_INVALID_REQUEST; PRD never names an error id or status for
#   a missing required payload field. PRD SILENT on the asserted rule.
#
# - ancillary_kind_out_of_enum_rejected: asserted ERR_INVALID_REQUEST (HTTP
#   400) for an out-of-enum ancillary_kind. PRD §3.5 names the enum members
#   but no rejection error; the §5 catalogue is exhaustive and has no such
#   error. PRD SILENT on the asserted rule.
#
# - seats_sold_is_computed_not_client_settable: asserted HTTP 400 when an
#   unknown extra field (seats_sold) is sent in a publication payload. PRD
#   never specifies rejection of unknown request fields; a faithful
#   implementation may ignore them (and still compute seats_sold server-side,
#   which is all PRD §3.2 requires). DEFAULT/REJECTION-BEHAVIOR SILENCE —
#   unique derivability fails.
# ---------------------------------------------------------------------------
