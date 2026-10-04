"""RBAC corner tests: peer-role isolation and passenger ownership scoping.

Covers Corner/rbac instances:
- passenger_cannot_post_disruption
- gate_agent_cannot_create_pairing
- passenger_ownership_scope_enforced
- ops_controller_cannot_scan_boarding
"""
from test_helpers import (
    TEST_USERS, api_client, get_success_data, validate_error,
    validate_success,
    ApiErrorId,
    book_journey, check_in_journey, create_aircraft, create_crew_member,
    create_fare_class, create_leg, create_passenger, create_station,
    set_clock, setup_basic_network,
)

OPS = TEST_USERS["ops_headers"]
GATE = TEST_USERS["gate_agent_headers"]
PASSENGER_FALLBACK = TEST_USERS["passenger_headers"]


def test_passenger_cannot_post_a_disruption(api):
    """PRD §2.1: "Any request whose role is recognized but not authorized for
    the requested endpoint is rejected with `ERR_FORBIDDEN` (HTTP 403)."

    PRD §4: "| POST | `/ops/flight-legs/{leg_id}/disruptions` | Post a DELAY
    or CANCELLATION; triggers propagation and cancellation cascades |
    OpsController |".

    Design: Corner/rbac/passenger_cannot_post_disruption
    """
    station_dal = create_station(iata_code="DAL")
    station_hou = create_station(iata_code="HOU")
    leg = create_leg(station_dal["id"], station_hou["id"], capacity_seats=143)
    passenger, p_h = create_passenger(full_name="P A")

    res = api.post_disruption(
        leg["id"], {"disruption_type": "DELAY", "cause": "WEATHER",
                    "delay_minutes": 30}, p_h)
    err = validate_error(res, ApiErrorId.ERR_FORBIDDEN)
    assert err["error_id"] == "ERR_FORBIDDEN"

    leg_now = validate_success(api.get_flight_leg(leg["id"], OPS), 200)
    assert leg_now["leg_status"] == "SCHEDULED"


def test_gate_agent_cannot_create_a_crew_pairing(api):
    """PRD §2.1: "Any request whose role is recognized but not authorized for
    the requested endpoint is rejected with `ERR_FORBIDDEN` (HTTP 403)."

    PRD §4: "| POST | `/ops/crew-pairings` | Create a crew pairing over
    ordered legs | OpsController |".

    Design: Corner/rbac/gate_agent_cannot_create_pairing
    """
    create_station(iata_code="DAL")
    crew = create_crew_member(employee_ref="C1", base_station_code="DAL")

    res = api.create_pairing(
        {"pairing_date": "2026-10-01", "crew_member_id": crew["id"],
         "leg_ids": []}, GATE)
    err = validate_error(res, ApiErrorId.ERR_FORBIDDEN)
    assert err["error_id"] == "ERR_FORBIDDEN"


def test_a_passenger_cannot_cancel_another_passengers_journey(api):
    """PRD §2.1: "When `X-User-Role` is `Passenger`, `X-User-ID` is the `id`
    of the acting `Passenger` entity. Ownership checks on any resource that
    references a `Passenger` — a journey, a credit, an upgrade — compare the
    resource's `passenger_id` (or the owning journey's passenger chain)
    against `X-User-ID`. A passenger acting on another passenger's journey,
    credit, or upgrade is rejected with `ERR_FORBIDDEN`."

    Design: Corner/rbac/passenger_ownership_scope_enforced
    """
    net = setup_basic_network()
    pa, pa_h = create_passenger(full_name="P A")
    pb, pb_h = create_passenger(full_name="P B")
    _bk, journey_id = book_journey(pa_h, pa["id"], net["leg"]["id"],
                                   net["fare"]["id"], base_fare_cents=10000)

    res = api.cancel_journey(journey_id, pb_h)
    err = validate_error(res, ApiErrorId.ERR_FORBIDDEN)
    assert err["error_id"] == "ERR_FORBIDDEN", (
        "cancel is a Passenger operation, but B does not own A's journey")

    journey = validate_success(api.get_journey(journey_id, pa_h), 200)
    assert journey["journey_status"] == "BOOKED"


def test_ops_controller_cannot_scan_boarding(api):
    """PRD §2.1: "Any request whose role is recognized but not authorized for
    the requested endpoint is rejected with `ERR_FORBIDDEN` (HTTP 403)."

    PRD §4: "| POST | `/ops/boarding/scan` | Gate scan: mark a checked-in
    journey BOARDED | GateAgent |".

    Design: Corner/rbac/ops_controller_cannot_scan_boarding
    """
    fx_net = setup_basic_network()
    set_clock("2026-09-30T12:00:00Z")
    passenger, p_h = create_passenger(full_name="P A")
    _bk, journey_id = book_journey(p_h, passenger["id"],
                                   fx_net["leg"]["id"], fx_net["fare"]["id"],
                                   base_fare_cents=10000)
    check_in_journey(journey_id, p_h)

    res = api.scan_boarding(journey_id, OPS)
    err = validate_error(res, ApiErrorId.ERR_FORBIDDEN)
    assert err["error_id"] == "ERR_FORBIDDEN"

    journey = validate_success(api.get_journey(journey_id, p_h), 200)
    assert journey["journey_status"] == "CHECKED_IN"
