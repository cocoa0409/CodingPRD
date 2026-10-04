"""Composite setup helpers for multi-step test prerequisites.

Every helper builds its preconditions from scratch out of public endpoints,
because each individual test starts against an empty database. Setup steps use
``get_success_data()`` so a broken precondition reports itself as a setup
failure rather than as a confusing assertion failure in the test body.

Identity threading: after a helper creates a ``Passenger``, every
ownership-gated call in that helper uses ``make_passenger_headers`` with the
real entity id — never the shared role constant.
"""
from prd_bench_local_runner.testing import get_success_data, validate_paginated

from .api_client import api_client
from .constants import TEST_DEFAULTS
from .factories import (
    create_aircraft_payload, create_booking_payload, create_crew_member_payload,
    create_fare_class_payload, create_flight_leg_payload,
    create_journey_payload, create_pairing_payload, create_passenger_payload,
    create_routing_payload, create_station_payload,
)
from .test_users import TEST_USERS, make_passenger_headers

OPS = TEST_USERS["ops_headers"]
GATE = TEST_USERS["gate_agent_headers"]

CHECKIN_CLOCK = "2026-09-30T12:00:00Z"  # exactly STD - 24h: the check-in window-open boundary (PRD §3.4)
STD = TEST_DEFAULTS["STD"]
STA = TEST_DEFAULTS["STA"]


# ═══════════════════════════════════════════════════════
# Tier 1: single-entity creation
# ═══════════════════════════════════════════════════════

def set_clock(to_iso8601):
    """Advance the logical clock; returns the reported current_utc."""
    res = api_client.set_clock(to_iso8601, OPS)
    return get_success_data(res)["current_utc"]


def create_station(**overrides):
    """Register a station; returns the created Station (ACTIVE)."""
    res = api_client.create_station(create_station_payload(**overrides), OPS)
    return get_success_data(res)


def create_fare_class(**overrides):
    """Register a fare class; returns the created FareClass."""
    res = api_client.create_fare_class(
        create_fare_class_payload(**overrides), OPS)
    return get_success_data(res)


def create_passenger(**overrides):
    """Register a passenger; returns (passenger, ownership-bound headers)."""
    res = api_client.create_passenger(
        create_passenger_payload(**overrides),
        make_passenger_headers("self-register"))
    passenger = get_success_data(res)
    return passenger, make_passenger_headers(passenger["id"])


def create_aircraft(**overrides):
    """Register an aircraft tail; returns the created Aircraft (SERVICEABLE)."""
    res = api_client.create_aircraft(create_aircraft_payload(**overrides), OPS)
    return get_success_data(res)


def create_crew_member(**overrides):
    """Register a crew member; returns the created CrewMember (AVAILABLE)."""
    res = api_client.create_crew_member(
        create_crew_member_payload(**overrides), OPS)
    return get_success_data(res)


def create_leg(origin_station_id, destination_station_id, **overrides):
    """Create a flight leg; returns the created FlightLeg (SCHEDULED)."""
    res = api_client.create_flight_leg(
        create_flight_leg_payload(origin_station_id, destination_station_id,
                                  **overrides), OPS)
    return get_success_data(res)


def create_routing(routing_date, aircraft_id, leg_ids):
    """Create an aircraft routing; returns the created AircraftRouting."""
    res = api_client.create_routing(
        create_routing_payload(routing_date, aircraft_id, leg_ids), OPS)
    return get_success_data(res)


def create_pairing(pairing_date, crew_member_id, leg_ids):
    """Create a crew pairing; returns the created CrewPairing."""
    res = api_client.create_pairing(
        create_pairing_payload(pairing_date, crew_member_id, leg_ids), OPS)
    return get_success_data(res)


def fresh_leg_version(leg_id):
    """Re-read a leg and return its current version (for OCC writes)."""
    return get_success_data(api_client.get_flight_leg(leg_id, OPS))["version"]


def fresh_credit_version(credit_id, passenger_headers):
    """Re-read a credit and return its current version (for OCC writes)."""
    return get_success_data(
        api_client.get_credit(credit_id, passenger_headers))["version"]


# ═══════════════════════════════════════════════════════
# Tier 2: network + leg bundles
# ═══════════════════════════════════════════════════════

def setup_basic_network(fare_overrides=None, capacity_seats=143,
                        seat_count=143, leg_overrides=None):
    """Stations DAL+HOU, one fare class, one aircraft, one leg L1.

    Returns dict(station_dal, station_hou, fare, aircraft, leg).
    """
    station_dal = create_station(iata_code="DAL")
    station_hou = create_station(iata_code="HOU")
    fare = create_fare_class(**(fare_overrides or {}))
    aircraft = create_aircraft(seat_count=seat_count)
    leg_kw = {"capacity_seats": capacity_seats}
    leg_kw.update(leg_overrides or {})
    leg = create_leg(station_dal["id"], station_hou["id"], **leg_kw)
    return {"station_dal": station_dal, "station_hou": station_hou,
            "fare": fare, "aircraft": aircraft, "leg": leg}


def create_booking_with_journeys(passenger_headers, journey_payloads):
    """Create a booking; returns the created Booking."""
    res = api_client.create_booking(
        create_booking_payload(journey_payloads), passenger_headers)
    return get_success_data(res)


def book_journey(passenger_headers, passenger_id, leg_id, fare_class_id,
                 **journey_overrides):
    """Book a single-journey booking; returns (booking, journey)."""
    booking = create_booking_with_journeys(
        passenger_headers,
        [create_journey_payload(passenger_id, leg_id, fare_class_id,
                                **journey_overrides)])
    return booking, booking["journey_ids"][0]


# ═══════════════════════════════════════════════════════
# Tier 3: check-in and upgrade lifecycle
# ═══════════════════════════════════════════════════════

def check_in_journey(journey_id, passenger_headers):
    """Journey-scoped check-in (non-OCC convenience path). Returns journey."""
    res = api_client.journey_check_in(journey_id, passenger_headers)
    return get_success_data(res)


def leg_check_in(leg_id, journey_id, passenger_headers,
                 expected_leg_version=None):
    """Leg-scoped OCC check-in. Returns (journey, new_leg_version)."""
    version = (expected_leg_version if expected_leg_version is not None
               else fresh_leg_version(leg_id))
    res = api_client.leg_check_in(
        leg_id, {"journey_id": journey_id, "expected_leg_version": version},
        passenger_headers)
    journey = get_success_data(res)
    return journey, fresh_leg_version(leg_id)


def purchase_upgrade(leg_id, journey_id, passenger_headers, upgrade_type,
                     expected_leg_version=None):
    """Leg-scoped OCC upgrade purchase. Returns (upgrade, new_leg_version)."""
    version = (expected_leg_version if expected_leg_version is not None
               else fresh_leg_version(leg_id))
    res = api_client.purchase_upgrade(
        leg_id, {"journey_id": journey_id, "upgrade_type": upgrade_type,
                 "expected_leg_version": version}, passenger_headers)
    upgrade = get_success_data(res)
    return upgrade, fresh_leg_version(leg_id)


def setup_checked_in_journey(fare_overrides=None, capacity_seats=143,
                             seat_count=143, checkin_clock=CHECKIN_CLOCK,
                             leg_overrides=None, base_fare_cents=10000):
    """Basic network + one passenger with a CHECKED_IN journey.

    Returns dict(net..., passenger, passenger_headers, booking, journey).
    """
    net = setup_basic_network(fare_overrides=fare_overrides,
                              capacity_seats=capacity_seats,
                              seat_count=seat_count,
                              leg_overrides=leg_overrides)
    set_clock(checkin_clock)
    passenger, p_headers = create_passenger()
    booking, journey_id = book_journey(
        p_headers, passenger["id"], net["leg"]["id"], net["fare"]["id"],
        base_fare_cents=base_fare_cents)
    check_in_journey(journey_id, p_headers)
    return {**net, "passenger": passenger, "passenger_headers": p_headers,
            "booking": booking, "journey_id": journey_id}


# ═══════════════════════════════════════════════════════
# Tier 4: flyable-leg and terminal-state fixtures
# ═══════════════════════════════════════════════════════

def setup_flyable_leg(capacity_seats=143, seat_count=143, leg_overrides=None):
    """Network + leg covered by an ACTIVE routing and an ACTIVE pairing,
    boarding opened, clock at STD. The leg can be departed.

    Returns dict(net..., routing, pairing, crew_member).
    """
    net = setup_basic_network(capacity_seats=capacity_seats,
                              seat_count=seat_count,
                              leg_overrides=leg_overrides)
    routing = create_routing("2026-10-01", net["aircraft"]["id"],
                             [net["leg"]["id"]])
    crew = create_crew_member()
    pairing = create_pairing("2026-10-01", crew["id"], [net["leg"]["id"]])
    set_clock(CHECKIN_CLOCK)
    get_success_data(api_client.open_boarding(net["leg"]["id"], GATE))
    set_clock(STD)
    return {**net, "routing": routing, "pairing": pairing,
            "crew_member": crew}


def fly_leg(leg_id):
    """Depart and arrive a flyable leg. Returns the arrived FlightLeg."""
    get_success_data(api_client.depart_leg(leg_id, GATE))
    res = api_client.arrive_leg(leg_id, GATE)
    return get_success_data(res)


# ═══════════════════════════════════════════════════════
# Tier 5: credit-ledger fixtures
# ═══════════════════════════════════════════════════════

def setup_credit_scenario(source_fare_cents=20000, new_fare_cents=10000,
                          fare_overrides=None, credit_validity_days=365):
    """Passenger PA; J_SRC cancelled -> TravelCredit; J_NEW BOOKED on L2.

    Returns dict(net..., passenger, passenger_headers, credit, j_new).
    """
    fare_kw = {"change_fee_cents": 0,
               "credit_validity_days": credit_validity_days}
    fare_kw.update(fare_overrides or {})
    net = setup_basic_network(fare_overrides=fare_kw)
    set_clock(CHECKIN_CLOCK)
    leg2 = create_leg(net["station_dal"]["id"], net["station_hou"]["id"],
                      scheduled_departure_utc="2026-10-02T12:00:00Z",
                      scheduled_arrival_utc="2026-10-02T13:00:00Z")
    passenger, p_headers = create_passenger()
    _, j_src = book_journey(p_headers, passenger["id"], net["leg"]["id"],
                            net["fare"]["id"],
                            base_fare_cents=source_fare_cents)
    get_success_data(api_client.cancel_journey(j_src, p_headers))
    credits, _meta = validate_paginated(api_client.list_credits(
        p_headers, params={"passenger_id": passenger["id"]}))
    credit = credits[0]
    _, j_new = book_journey(p_headers, passenger["id"], leg2["id"],
                            net["fare"]["id"],
                            base_fare_cents=new_fare_cents)
    return {**net, "leg2": leg2, "passenger": passenger,
            "passenger_headers": p_headers, "credit": credit,
            "j_src": j_src, "j_new": j_new}
