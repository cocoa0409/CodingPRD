"""Bag acceptance: required fields, enum constraints, server-minted tag, interline."""
import re

import pytest

from test_helpers import (
    validate_success, validate_error, get_success_data, validate_paginated,
    create_bag_payload, create_airline_payload, create_flight_payload,
    create_station_payload, assert_bag, ApiErrorId, TEST_USERS,
    set_clock, base_scenario, list_rows,
)


def test_bag_create_requires_the_passenger_name(api):
    """PRD §3.1: "supplying the `station_id` where custody begins, the
    `passenger_name` as printed on the tag, the `passenger_ref` locator the bag
    is attached to, the `itinerary_type` as one of `DOMESTIC`, `INTERNATIONAL`
    or `INTERLINE`, the declared `weight_lb`, and the three declared dimensions
    `length_in`, `width_in` and `height_in`."
    PRD §2.14: "A malformed body, an unknown enum member, a missing required
    field, or a re-accommodation naming the connection's existing onward flight
    all yield `ERR_INVALID_REQUEST` with HTTP 400."

    Design: Corner/entities/bag_create_requires_passenger_name_and_weight
    """
    scenario = base_scenario()
    payload = create_bag_payload(scenario["st"])
    del payload["passenger_name"]
    response = api.create_bag(payload, TEST_USERS["acceptance_agent_headers"])
    validate_error(response, ApiErrorId.ERR_INVALID_REQUEST, 400)


def test_bag_create_requires_the_declared_weight(api):
    """PRD §3.1: "the declared `weight_lb`, and the three declared dimensions
    `length_in`, `width_in` and `height_in`."
    PRD §2.14: "A malformed body, an unknown enum member, a missing required
    field, or a re-accommodation naming the connection's existing onward flight
    all yield `ERR_INVALID_REQUEST` with HTTP 400."

    Design: Corner/entities/bag_create_requires_passenger_name_and_weight
    """
    scenario = base_scenario()
    payload = create_bag_payload(scenario["st"])
    del payload["weight_lb"]
    response = api.create_bag(payload, TEST_USERS["acceptance_agent_headers"])
    validate_error(response, ApiErrorId.ERR_INVALID_REQUEST, 400)

    rows = list_rows(api.list_bags(TEST_USERS["acceptance_agent_headers"],
                                   {"station_id": scenario["st"]}))
    assert rows == [], "no partial bag may be persisted by a rejected acceptance"


def test_rejected_acceptance_leaves_the_station_population_at_zero(api):
    """PRD §2.6: "The bag count that drives this rule is the count of the
    station's bags whose custody status is one of `ACCEPTED`, `SCREENING`,
    `SORTED`, `IN_MAKEUP`, `LOADED` or `HELD`."

    Design: Corner/entities/bag_create_requires_passenger_name_and_weight
    """
    scenario = base_scenario()
    payload = create_bag_payload(scenario["st"])
    del payload["passenger_name"]
    api.create_bag(payload, TEST_USERS["acceptance_agent_headers"])

    station = get_success_data(api.get_station(
        scenario["st"], TEST_USERS["platform_admin_headers"]))
    assert station["active_bag_count"] == 0


def test_bag_envelope_constrains_the_itinerary_enum(api):
    """PRD §2.14: "an enum member outside a field's declared value set yields
    `ERR_INVALID_ENUM_VALUE`, also HTTP 400."

    Design: Corner/entities/bag_envelope_and_itinerary_enum_are_constrained
    """
    scenario = base_scenario()
    response = api.create_bag(
        create_bag_payload(scenario["st"], itinerary_type="CODESHARE"),
        TEST_USERS["acceptance_agent_headers"])
    validate_error(response, ApiErrorId.ERR_INVALID_ENUM_VALUE, 400)


def test_linear_measure_of_exactly_130_inches_is_accepted(api):
    """PRD §3.1: "the declared `linear_in` may not exceed 130 inches; the first
    failure is `ERR_BAG_OVERWEIGHT` and the second `ERR_BAG_OVERSIZE`, both HTTP
    422."
    PRD §3.1: "The baggage linear measure `linear_in` is derived at acceptance as the sum of the three declared dimensions, and it is the figure every oversize test later consults."

    Design: Corner/entities/bag_envelope_and_itinerary_enum_are_constrained
    """
    scenario = base_scenario()
    response = api.create_bag(
        create_bag_payload(scenario["st"], length_in=50, width_in=40, height_in=40),
        TEST_USERS["acceptance_agent_headers"])
    data = validate_success(response, 201)
    assert data["linear_in"] == 130


def test_linear_measure_of_131_inches_is_rejected_as_oversize(api):
    """PRD §3.1: "the declared `linear_in` may not exceed 130 inches; the first
    failure is `ERR_BAG_OVERWEIGHT` and the second `ERR_BAG_OVERSIZE`, both HTTP
    422."

    Design: Corner/entities/bag_envelope_and_itinerary_enum_are_constrained
    """
    scenario = base_scenario()
    response = api.create_bag(
        create_bag_payload(scenario["st"], length_in=41, width_in=40, height_in=50),
        TEST_USERS["acceptance_agent_headers"])
    validate_error(response, ApiErrorId.ERR_BAG_OVERSIZE, 422)


def test_tag_number_is_server_minted_ten_digits(api):
    """PRD §3.1: "The server mints the `tag_number` itself as a unique ten-digit
    string; the client never supplies it and may not influence it."

    Design: Corner/entities/bag_tag_number_is_server_minted_and_ignored_from_input
    """
    scenario = base_scenario()
    data = get_success_data(api.create_bag(
        create_bag_payload(scenario["st"]), TEST_USERS["acceptance_agent_headers"]))

    assert re.fullmatch(r"[0-9]{10}", data["tag_number"]), \
        "tag_number must be a ten-digit string"
    assert_bag(data)
    assert data["version"] == 1, "a freshly accepted bag is at version 1"
    assert data["custody_status"] == "ACCEPTED"
    assert data["screening_status"] == "PENDING"

    reread = get_success_data(api.get_bag(data["id"],
                                          TEST_USERS["acceptance_agent_headers"]))
    assert reread["tag_number"] == data["tag_number"]


def test_tracking_lookup_resolves_the_minted_tag_number(api):
    """PRD §3.7: "Passengers see the journey through a read-only tracking lookup
    addressed by the ten-digit tag number rather than by the bag's identifier."

    Design: Corner/entities/bag_tag_number_is_server_minted_and_ignored_from_input
    """
    from test_helpers import make_passenger_headers

    scenario = base_scenario()
    bag = get_success_data(api.create_bag(
        create_bag_payload(scenario["st"]), TEST_USERS["acceptance_agent_headers"]))

    response = api.tracking_lookup(
        bag["tag_number"], make_passenger_headers(bag["passenger_ref"]))
    bundle = validate_success(response, 200)
    assert bundle["tag_number"] == bag["tag_number"]
    assert bundle["custody_status"] == "ACCEPTED"


def test_a_second_bag_carries_a_different_tag_number(api):
    """PRD §3.1: "The server mints the `tag_number` itself as a unique ten-digit
    string"

    Design: Corner/entities/bag_tag_number_is_server_minted_and_ignored_from_input
    """
    scenario = base_scenario()
    first = get_success_data(api.create_bag(
        create_bag_payload(scenario["st"]), TEST_USERS["acceptance_agent_headers"]))
    second = get_success_data(api.create_bag(
        create_bag_payload(scenario["st"], passenger_name="Okafor, Ben",
                           passenger_ref="PNR4M1T"),
        TEST_USERS["acceptance_agent_headers"]))
    assert first["tag_number"] != second["tag_number"]


def test_interline_bag_without_an_active_agreement_is_rejected(api):
    """PRD §3.1: "A bag declaring `INTERLINE` itinerary type additionally
    requires a carrier whose `interline_agreement_active` is true — a false
    agreement is rejected with `ERR_INTERLINE_AGREEMENT_INACTIVE` and HTTP 422"

    Design: Corner/validations/interline_itinerary_without_an_active_agreement_is_rejected
    """
    set_clock()
    station = get_success_data(api.create_station(
        create_station_payload(), TEST_USERS["platform_admin_headers"]))
    dl = get_success_data(api.create_airline(
        create_airline_payload(), TEST_USERS["platform_admin_headers"]))
    zz = get_success_data(api.create_airline(
        create_airline_payload(code="ZZ", name="Zephyr Airways",
                               interline_agreement_active=False,
                               compensation_cap_cents=200000),
        TEST_USERS["platform_admin_headers"]))
    zz_flight = get_success_data(api.create_flight(
        create_flight_payload(station["id"], zz["id"], flight_number="ZZ700",
                              bank_code="B9",
                              scheduled_departure_utc="2026-09-01T16:00:00Z"),
        TEST_USERS["platform_admin_headers"]))
    dl_flight = get_success_data(api.create_flight(
        create_flight_payload(station["id"], dl["id"]),
        TEST_USERS["platform_admin_headers"]))

    rejected = api.create_bag(
        create_bag_payload(station["id"], flight_id=zz_flight["id"],
                           itinerary_type="INTERLINE", passenger_ref="PNR6D5P"),
        TEST_USERS["acceptance_agent_headers"])
    validate_error(rejected, ApiErrorId.ERR_INTERLINE_AGREEMENT_INACTIVE, 422)

    accepted = api.create_bag(
        create_bag_payload(station["id"], flight_id=dl_flight["id"],
                           itinerary_type="INTERLINE", passenger_ref="PNR6D5P"),
        TEST_USERS["acceptance_agent_headers"])
    data = validate_success(accepted, 201)
    assert data["itinerary_type"] == "INTERLINE"


def test_domestic_bag_on_the_same_carrier_is_accepted(api):
    """PRD §3.1: "A bag declaring `INTERLINE` itinerary type additionally
    requires a carrier whose `interline_agreement_active` is true"
    PRD §2.13: "A bag declaring `INTERLINE` itinerary type requires a carrier
    whose `interline_agreement_active` is true, else
    `ERR_INTERLINE_AGREEMENT_INACTIVE` (422)."

    Design: Corner/validations/interline_itinerary_without_an_active_agreement_is_rejected
    """
    set_clock()
    station = get_success_data(api.create_station(
        create_station_payload(), TEST_USERS["platform_admin_headers"]))
    zz = get_success_data(api.create_airline(
        create_airline_payload(code="ZZ", name="Zephyr Airways",
                               interline_agreement_active=False),
        TEST_USERS["platform_admin_headers"]))
    zz_flight = get_success_data(api.create_flight(
        create_flight_payload(station["id"], zz["id"], flight_number="ZZ700",
                              bank_code="B9"),
        TEST_USERS["platform_admin_headers"]))

    data = get_success_data(api.create_bag(
        create_bag_payload(station["id"], flight_id=zz_flight["id"],
                           itinerary_type="DOMESTIC"),
        TEST_USERS["acceptance_agent_headers"]))
    assert data["itinerary_type"] == "DOMESTIC"

    rows = list_rows(api.list_bags(TEST_USERS["acceptance_agent_headers"],
                                   {"flight_id": zz_flight["id"]}))
    assert len(rows) == 1, "the guard keys on itinerary type, not the carrier alone"