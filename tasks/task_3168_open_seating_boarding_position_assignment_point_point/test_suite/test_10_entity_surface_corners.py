"""Entity-surface corner tests: defaults, not-found, booking shape, pagination.

Covers Corner/entities instances:
- station_creation_defaults_applied
- station_not_found_returns_404
- journey_required_field_missing_rejected
- leg_invalid_enum_rejected
- booking_computed_journey_count_ignores_input
- list_pagination_defaults_envelope
"""
from test_helpers import (
    NON_EXISTENT_UUID, TEST_USERS, api_client, get_success_data,
    validate_error, validate_error_is_one_of, validate_paginated,
    validate_success,
    ApiErrorId,
    assert_station,
    book_journey, create_booking_with_journeys, create_fare_class,
    create_journey_payload, create_leg, create_passenger, create_station,
    create_station_payload, set_clock, setup_basic_network,
)

OPS = TEST_USERS["ops_headers"]
GATE = TEST_USERS["gate_agent_headers"]


def test_station_creation_applies_documented_defaults(api):
    """PRD §3.1: "A station is identified by its three-letter `iata_code`,
    unique across the network, and carries a per-bag `bag_weight_limit_lbs`
    (default 50), a `min_connection_minutes` connection buffer (default 40)
    consulted by routings and pairings that connect at this station, and an
    informational `time_zone_offset_minutes`. On creation a station's
    `station_status` is `ACTIVE`."

    Design: Corner/entities/station_creation_defaults_applied
    """
    station = validate_success(api.create_station({"iata_code": "DAL"}, OPS),
                               201)
    assert_station(station)
    assert station["bag_weight_limit_lbs"] == 50
    assert station["min_connection_minutes"] == 40
    assert station["station_status"] == "ACTIVE"


def test_get_station_with_unknown_id_returns_not_found(api):
    """PRD §2.6: "Endpoints that address a nested path validate path
    identifiers from left to right. The first identifier that does not
    correspond to an existing resource short-circuits the request with
    `ERR_NOT_FOUND` (HTTP 404); later identifiers are not consulted."

    Design: Corner/entities/station_not_found_returns_404
    """
    res = api.get_station(NON_EXISTENT_UUID, OPS)
    err = validate_error(res, ApiErrorId.ERR_NOT_FOUND)
    assert err["error_id"] == "ERR_NOT_FOUND"


def test_booking_with_a_journey_missing_base_fare_is_rejected(api):
    """PRD §3.3: "Each journey pins a `passenger_id`, a `flight_leg_id`, a
    `fare_class_id`, and a `base_fare_cents` amount that must be
    non-negative."

    Design: Corner/entities/journey_required_field_missing_rejected
    """
    net = setup_basic_network()
    passenger, p_h = create_passenger(full_name="P A")

    res = api.create_booking(
        {"record_locator": "BKX",
         "journeys": [{"passenger_id": passenger["id"],
                       "flight_leg_id": net["leg"]["id"],
                       "fare_class_id": net["fare"]["id"]}]}, p_h)
    assert res.status_code == 400, (
        "a journey payload missing its required base_fare_cents is a "
        "malformed body")
    error_id = validate_error_is_one_of(res, [ApiErrorId.ERR_VALIDATION.value])
    assert error_id == "ERR_VALIDATION"

    journeys, meta = validate_paginated(
        api.list_journeys(OPS, params={"passenger_id": passenger["id"]}))
    assert meta["total_count"] == 0, "no journey row is persisted"


def test_disruption_with_unknown_type_is_rejected_as_malformed(api):
    """PRD §3.7: "An `OpsController` posts a disruption against a leg,
    choosing a `disruption_type` of `DELAY` or `CANCELLATION`, a `cause` of
    `WEATHER`, `INBOUND_DELAY`, `CREW`, or `MAINTENANCE`, and — for a delay —
    a `delay_minutes` value."

    Design: Corner/entities/leg_invalid_enum_rejected
    """
    station_dal = create_station(iata_code="DAL")
    station_hou = create_station(iata_code="HOU")
    leg = create_leg(station_dal["id"], station_hou["id"], capacity_seats=143)

    res = api.post_disruption(
        leg["id"], {"disruption_type": "DIVERSION", "cause": "WEATHER",
                    "delay_minutes": 30}, OPS)
    assert res.status_code == 400, (
        "DIVERSION is not one of the two disruption types")
    error_id = validate_error_is_one_of(res, [ApiErrorId.ERR_VALIDATION.value])
    assert error_id == "ERR_VALIDATION"

    leg_now = validate_success(api.get_flight_leg(leg["id"], OPS), 200)
    assert leg_now["leg_status"] == "SCHEDULED"


def test_booking_journey_count_is_derived_from_created_journeys(api):
    """PRD §3.3: "Journeys are born with `journey_status` `BOOKED` and
    `accommodation` `NONE`, and the parent booking begins with
    `booking_status` `ACTIVE`, with its `journey_count` and `journey_ids`
    derived from the journeys under it, ordered by journey creation time
    ascending."

    Design: Corner/entities/booking_computed_journey_count_ignores_input
    """
    net = setup_basic_network()
    passenger, p_h = create_passenger(full_name="P A")

    booking = validate_success(api.create_booking(
        {"record_locator": "BK2J",
         "journey_count": 99,
         "journeys": [
             create_journey_payload(passenger["id"], net["leg"]["id"],
                                    net["fare"]["id"], base_fare_cents=10000),
             create_journey_payload(passenger["id"], net["leg"]["id"],
                                    net["fare"]["id"], base_fare_cents=10000),
         ]}, p_h), 201)
    assert booking["journey_count"] == 2, (
        "the count is computed from the created journeys, not from any "
        "client-supplied value")
    assert len(booking["journey_ids"]) == 2
    assert booking["booking_status"] == "ACTIVE"


def test_station_list_paginates_with_default_limit_and_offset(api):
    """PRD §2.3: "List endpoints accept two query parameters. `limit` caps
    the page size: if omitted it defaults to 10, with a minimum accepted
    value of 1 and a maximum accepted value of 100. `offset` skips leading
    rows: if omitted it defaults to 0."

    PRD §2.3: "The `meta` block of any list response includes exactly the
    pagination fields `limit`, `offset`, `total_count`, and `has_more`."

    Design: Corner/entities/list_pagination_defaults_envelope
    """
    for i in range(12):
        validate_success(
            api.create_station({"iata_code": f"S{i + 1:02d}"}, OPS), 201)

    first, meta = validate_paginated(api.list_stations(OPS))
    assert len(first) == 10, "the default limit is 10"
    assert meta["total_count"] == 12
    assert meta["has_more"] is True
    assert meta["limit"] == 10
    assert meta["offset"] == 0

    second, meta2 = validate_paginated(
        api.list_stations(OPS, params={"offset": 10}))
    assert len(second) == 2
    assert meta2["has_more"] is False
    assert meta2["total_count"] == 12
