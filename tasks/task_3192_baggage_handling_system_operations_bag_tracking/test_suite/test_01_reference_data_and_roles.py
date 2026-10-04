"""Reference data: carriers, stations and the operation-scoped role guard."""
import pytest

from test_helpers import (
    validate_success, validate_error, get_success_data,
    create_airline_payload, create_station_payload,
    assert_airline, assert_station, ApiErrorId, NON_EXISTENT_UUID,
    TEST_USERS, set_clock, base_scenario, make_flight,
)


def test_airline_create_returns_the_declared_carrier_fields(api):
    """PRD §2.2: "Unless otherwise noted, operations that create or modify a
    resource will return the created or updated resource object in the data
    field."
    PRD §2.4: "`id` (string) — a unique, server-minted UUID."

    Design: Corner/entities/airline_create_returns_declared_fields_immutable
    """
    set_clock()
    response = api.create_airline(
        create_airline_payload(), TEST_USERS["platform_admin_headers"])
    data = validate_success(response, 201)

    assert_airline(data)
    assert data["code"] == "DL"
    assert data["max_excess_weight_lb"] == 50
    assert data["excess_weight_fee_cents"] == 7500
    assert data["compensation_cap_cents"] == 300000
    assert data["interline_agreement_active"] is True
    assert data["id"] not in (None, "")
    assert "api_request_id" in response.json()["meta"]
    assert "api_request_timestamp" in response.json()["meta"]


def test_airline_duplicate_code_is_rejected(api):
    """PRD §2.13: "the station `code` and airline `code` are unique. Duplicate
    airline codes yield `ERR_DUPLICATE_AIRLINE` and duplicate connections yield
    `ERR_DUPLICATE_CONNECTION`, both HTTP 409."

    Design: Corner/entities/airline_create_returns_declared_fields_immutable
    """
    set_clock()
    api.create_airline(create_airline_payload(), TEST_USERS["platform_admin_headers"])
    response = api.create_airline(
        create_airline_payload(name="Delta Again"),
        TEST_USERS["platform_admin_headers"])
    validate_error(response, ApiErrorId.ERR_DUPLICATE_AIRLINE, 409)


def test_station_get_round_trips_every_configuration_field(api):
    """PRD §2.6: "`outage_started_utc` records the instant it was declared,
    remaining null while no outage is active."
    PRD §2.14: "The open figure is the sum of `final_liability_cents` across the
    station's mishandled reports whose status is one of `REPORTED`,
    `INVESTIGATING`, `DELIVERY_ARRANGED` or `REOPENED`."

    Design: Corner/entities/station_get_round_trips_every_configuration_field
    """
    set_clock()
    created = assert_reference_station(api)
    response = api.get_station(created["id"], TEST_USERS["platform_admin_headers"])
    data = validate_success(response, 200)

    assert_station(data)
    assert data["code"] == "SEA"
    assert data["name"] == "Seattle-Tacoma"
    assert data["sorter_capacity_bags"] == 60
    assert data["posture"] == "OPEN"
    assert data["outage_active"] is False
    assert data.get("outage_started_utc") is None
    assert data["active_bag_count"] == 0
    assert data["manual_queue_depth"] == 0
    assert data["open_liability_cents"] == 0
    assert data["settled_liability_cents"] == 0
    assert data["ops_run_index"] == 0


def assert_reference_station(api) -> dict:
    created = get_success_data(api.create_station(
        create_station_payload(), TEST_USERS["platform_admin_headers"]))
    return created


def test_station_get_with_an_unknown_id_returns_not_found(api):
    """PRD §2.5: "When a request path carries more than one resource
    identifier, the server validates them left to right and rejects immediately
    on the first identifier that does not resolve."
    PRD §2.13: "The identifiers in the path, and then the foreign keys in the
    body, must resolve, else `ERR_BAG_NOT_FOUND`, `ERR_REPORT_NOT_FOUND` or
    `ERR_FLIGHT_NOT_FOUND` (404)."

    Design: Corner/entities/station_get_with_an_unknown_id_returns_not_found
    """
    set_clock()
    response = api.get_station(NON_EXISTENT_UUID, TEST_USERS["platform_admin_headers"])

    assert response.status_code == 404, \
        f"an unallocated id must produce 404, got {response.status_code}"
    body = response.json()
    assert body["response_type"] == "error"
    assert set(body["data"].keys()) == {"error_id", "message"}, \
        "the error envelope carries exactly error_id and message"
    assert body["data"]["error_id"].strip() != ""
    assert body["data"]["message"].strip() != ""


def test_baggage_service_agent_cannot_cancel_a_flight(api):
    """PRD §2.1: "A request whose role does not permit the requested operation,
    or an entity-backed role acting on a resource it does not own, is rejected
    with `ERR_FORBIDDEN_ROLE` and HTTP 403."

    Design: Corner/endpoints/baggage_service_agent_cannot_cancel_a_flight
    """
    scenario = base_scenario()
    denied = api.cancel_flight(scenario["f1"], TEST_USERS["baggage_service_agent_headers"])
    validate_error(denied, ApiErrorId.ERR_FORBIDDEN_ROLE, 403)

    still_scheduled = get_success_data(api.get_flight(
        scenario["f1"], TEST_USERS["platform_admin_headers"]))
    assert still_scheduled["status"] == "SCHEDULED"

    allowed = api.cancel_flight(scenario["f1"], TEST_USERS["platform_admin_headers"])
    cancelled = validate_success(allowed, 200)
    assert cancelled["status"] == "CANCELLED"


def test_sortation_agent_cannot_cancel_a_flight_either(api):
    """PRD §4: "| POST | `/baggage/flights/{id}/cancel` | Cancel a flight and
    release its sorted bags back to the sortation pool | PlatformAdmin |"

    Design: Corner/endpoints/baggage_service_agent_cannot_cancel_a_flight
    """
    scenario = base_scenario()
    denied = api.cancel_flight(scenario["f1"], TEST_USERS["sortation_agent_headers"])
    validate_error(denied, ApiErrorId.ERR_FORBIDDEN_ROLE, 403)


def test_sortation_agent_is_allowed_to_assign_a_makeup_interval(api):
    """PRD §4: "| POST | `/baggage/bags/{id}/assign-makeup` | Assign a make-up
    interval to a sorted bag | SortationAgent |"

    Design: Corner/endpoints/baggage_service_agent_cannot_cancel_a_flight
    """
    from test_helpers import make_sorted_bag, create_assign_makeup_payload

    scenario = base_scenario()
    bag = make_sorted_bag(scenario)
    set_clock("2026-09-01T13:12:00Z")
    bag = get_success_data(api.get_bag(bag["id"], TEST_USERS["sortation_agent_headers"]))
    response = api.assign_makeup(
        bag["id"],
        create_assign_makeup_payload(bag["version"], scenario["ma"], "2026-09-01T13:12:00Z"),
        TEST_USERS["sortation_agent_headers"])
    data = validate_success(response, 200)
    assert data["custody_status"] == "IN_MAKEUP"