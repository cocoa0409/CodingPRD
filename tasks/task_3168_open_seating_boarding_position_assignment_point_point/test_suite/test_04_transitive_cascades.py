"""Transitive cascades: delay propagation (depth 3) and cancellation (depth 2).

Covers Difficulty/transitive_cascade instances:
- delay_propagates_aircraft_then_crew_depth3
- flight_cancellation_cascade_depth2
"""
from test_helpers import (
    TEST_USERS, api_client, get_success_data, validate_paginated,
    validate_success,
    book_journey, create_aircraft, create_crew_member, create_fare_class,
    create_leg, create_pairing, create_passenger, create_routing,
    create_station, set_clock,
)

OPS = TEST_USERS["ops_headers"]
GATE = TEST_USERS["gate_agent_headers"]


def _three_station_line():
    """Stations DAL/HOU/AUS, aircraft N100, legs L1 DAL->HOU (12:00-13:00),
    L2 HOU->AUS (13:35-14:35, slack 0), L3 AUS->DAL (15:10-16:10)."""
    station_dal = create_station(iata_code="DAL", min_connection_minutes=30)
    station_hou = create_station(iata_code="HOU", min_connection_minutes=30)
    station_aus = create_station(iata_code="AUS", min_connection_minutes=30)
    aircraft = create_aircraft(tail_number="N100", seat_count=143)
    l1 = create_leg(station_dal["id"], station_hou["id"],
                    scheduled_departure_utc="2026-10-01T12:00:00Z",
                    scheduled_arrival_utc="2026-10-01T13:00:00Z",
                    capacity_seats=143)
    l2 = create_leg(station_hou["id"], station_aus["id"],
                    scheduled_departure_utc="2026-10-01T13:35:00Z",
                    scheduled_arrival_utc="2026-10-01T14:35:00Z",
                    capacity_seats=143)
    l3 = create_leg(station_aus["id"], station_dal["id"],
                    scheduled_departure_utc="2026-10-01T15:10:00Z",
                    scheduled_arrival_utc="2026-10-01T16:10:00Z",
                    capacity_seats=143)
    return station_dal, station_hou, station_aus, aircraft, l1, l2, l3


def _propagation_setup():
    """R1 = [L1, L2] on the tail; CP1 = [L2, L3] for a HOU-based captain."""
    set_clock("2026-09-30T12:00:00Z")
    _dal, _hou, _aus, aircraft, l1, l2, l3 = _three_station_line()
    routing = create_routing("2026-10-01", aircraft["id"],
                             [l1["id"], l2["id"]])
    crew = create_crew_member(employee_ref="C100", crew_role="CAPTAIN",
                              base_station_code="HOU")
    pairing = create_pairing("2026-10-01", crew["id"],
                             [l2["id"], l3["id"]])
    return aircraft, l1, l2, l3, routing, pairing


def test_delay_cascades_aircraft_hop_then_crew_hop(api):
    """PRD §3.7: "When the follower's available slack — its scheduled
    departure minus the delayed leg's scheduled arrival minus the follower's
    own `turn_target_minutes` — is smaller than the posted delay, a system
    `DisruptionEvent` is posted on the follower leg with `cause`
    `INBOUND_DELAY`, `delay_propagated` true, and `propagation_depth` one
    greater than the parent's; this drives the follower leg from `SCHEDULED`
    to `DELAYED` with a propagated delay equal to the parent's delay minus
    the consumed slack."

    PRD §3.7: "If the new departure time makes the next covered leg's
    scheduled departure unreachable given the connection station's
    `min_connection_minutes` buffer, the pairing transitions to `BROKEN`, and
    the pairing's next covered leg — if it is still `SCHEDULED` — receives a
    system `DELAY` event with `cause` `CREW` and `propagation_depth` one
    greater, driving it to `DELAYED`."

    Design: Difficulty/transitive_cascade/delay_propagates_aircraft_then_crew_depth3
    """
    _ac, l1, l2, l3, _r, pairing = _propagation_setup()

    validate_success(api.post_disruption(
        l1["id"], {"disruption_type": "DELAY", "cause": "WEATHER",
                   "delay_minutes": 50}, OPS), 201)

    leg1 = validate_success(api.get_flight_leg(l1["id"], OPS), 200)
    assert leg1["leg_status"] == "DELAYED"
    assert leg1["delay_minutes"] == 50
    assert leg1["delay_propagated"] is False, (
        "the directly-posted event has propagation_depth zero")

    leg2 = validate_success(api.get_flight_leg(l2["id"], OPS), 200)
    assert leg2["leg_status"] == "DELAYED", (
        "slack 0 < 50: the aircraft hop pushes L2 to DELAYED")
    assert leg2["delay_propagated"] is True
    assert leg2["delay_cause"] == "INBOUND_DELAY"
    assert leg2["delay_minutes"] == 50, (
        "propagated delay = parent delay 50 minus consumed slack 0")

    pairing_now = validate_success(api.get_pairing(pairing["id"], OPS), 200)
    assert pairing_now["pairing_status"] == "BROKEN", (
        "L2's pushed departure makes L3 unreachable inside the crew buffer")

    leg3 = validate_success(api.get_flight_leg(l3["id"], OPS), 200)
    assert leg3["leg_status"] == "DELAYED", (
        "the crew hop posts a CREW delay on the pairing's next covered leg")
    assert leg3["delay_cause"] == "CREW"
    assert leg3["delay_propagated"] is True


def test_propagation_depths_increment_along_the_chain(api):
    """PRD §3.7: "Propagation is depth-capped at 3 (`PROPAGATION_DEPTH_CAP`):
    a leg whose propagated event would exceed depth 3 is skipped, and a leg
    already `DELAYED` by an earlier event is not re-propagated — the first
    posted delay wins for propagation bookkeeping, while later direct posts
    use the delayed-to-delayed transition described above."

    Design: Difficulty/transitive_cascade/delay_propagates_aircraft_then_crew_depth3
    """
    _ac, l1, l2, l3, _r, _p = _propagation_setup()

    validate_success(api.post_disruption(
        l1["id"], {"disruption_type": "DELAY", "cause": "WEATHER",
                   "delay_minutes": 50}, OPS), 201)

    l2_events, _m = validate_paginated(
        api.list_leg_disruptions(l2["id"], OPS))
    assert len(l2_events) == 1
    assert l2_events[0]["propagation_depth"] == 1, (
        "the aircraft-hop event is one deeper than the direct post")
    assert l2_events[0]["cause"] == "INBOUND_DELAY"

    l3_events, _m = validate_paginated(
        api.list_leg_disruptions(l3["id"], OPS))
    assert len(l3_events) == 1
    assert l3_events[0]["propagation_depth"] == 2, (
        "the crew-hop event is caused by L2's mutation, not by the original "
        "post")
    assert l3_events[0]["cause"] == "CREW"


def _cancellation_setup():
    """One FLEX booking with one journey (base 15000) on L1."""
    set_clock("2026-09-30T12:00:00Z")
    station_dal = create_station(iata_code="DAL")
    station_hou = create_station(iata_code="HOU")
    fare = create_fare_class(code="FLEX", change_fee_cents=0,
                             included_bags=2, credit_validity_days=365)
    create_aircraft(tail_number="N100", seat_count=143)
    leg = create_leg(station_dal["id"], station_hou["id"], capacity_seats=143)
    passenger, p_h = create_passenger(full_name="P A")
    booking, journey_id = book_journey(p_h, passenger["id"], leg["id"],
                                       fare["id"], base_fare_cents=15000)
    return leg, passenger, p_h, booking, journey_id


def test_cancellation_cascades_leg_to_journey_to_booking(api):
    """PRD §3.7: "Cancelling a leg, whether it is `SCHEDULED` or `DELAYED`,
    runs a wider cascade. Every journey on the leg in `BOOKED` or
    `CHECKED_IN` moves to `CANCELLED`, and for each a `TravelCredit` is
    minted covering the `base_fare_cents` plus the `price_cents` of any
    `ACTIVE` upgrades on the journey — those upgrades move to `REFUNDED`."

    PRD §3.3: "The booking transitions to `CANCELLED` automatically when
    every journey under it has reached `CANCELLED` or `NO_SHOW`."

    Design: Difficulty/transitive_cascade/flight_cancellation_cascade_depth2
    """
    leg, passenger, p_h, booking, journey_id = _cancellation_setup()

    validate_success(api.post_disruption(
        leg["id"], {"disruption_type": "CANCELLATION", "cause": "WEATHER"},
        OPS), 201)

    leg_now = validate_success(api.get_flight_leg(leg["id"], OPS), 200)
    assert leg_now["leg_status"] == "CANCELLED"

    journey = validate_success(api.get_journey(journey_id, p_h), 200)
    assert journey["journey_status"] == "CANCELLED", (
        "hop 1: the leg cancellation cancels the journey")

    booking_now = validate_success(api.get_booking(booking["id"], p_h), 200)
    assert booking_now["booking_status"] == "CANCELLED", (
        "hop 2: the booking flips when every journey under it is terminal")


def test_cancellation_mints_credit_with_expiry_from_service_date(api):
    """PRD §3.8: "The credit's `expires_on` is the flight leg's service date
    plus the fare class's `credit_validity_days`."

    PRD §3.7: "Cancelling a leg, whether it is `SCHEDULED` or `DELAYED`, runs
    a wider cascade. Every journey on the leg in `BOOKED` or `CHECKED_IN`
    moves to `CANCELLED`, and for each a `TravelCredit` is minted covering
    the `base_fare_cents` plus the `price_cents` of any `ACTIVE` upgrades on
    the journey — those upgrades move to `REFUNDED`."

    Design: Difficulty/transitive_cascade/flight_cancellation_cascade_depth2
    """
    leg, passenger, p_h, booking, journey_id = _cancellation_setup()

    validate_success(api.post_disruption(
        leg["id"], {"disruption_type": "CANCELLATION", "cause": "WEATHER"},
        OPS), 201)

    credits, meta = validate_paginated(
        api.list_credits(p_h, params={"passenger_id": passenger["id"]}))
    assert meta["total_count"] == 1
    credit = credits[0]
    assert credit["initial_amount_cents"] == 15000
    assert credit["source_journey_id"] == journey_id
    assert credit["expires_on"] == "2027-10-01", (
        "service date 2026-10-01 plus 365 credit_validity_days")
    assert credit["credit_status"] == "OPEN"
