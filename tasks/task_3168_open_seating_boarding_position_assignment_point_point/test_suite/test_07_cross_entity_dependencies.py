"""Cross-entity state dependencies: one entity's state gates another's action.

Covers Difficulty/cross_entity_state_dependency instances:
- depart_blocked_by_broken_crew_pairing
- journey_checkin_blocked_by_leg_cancelled
"""
from test_helpers import (
    TEST_USERS, api_client, get_success_data, validate_error,
    validate_success,
    ApiErrorId,
    book_journey, create_aircraft, create_crew_member, create_fare_class,
    create_leg, create_pairing, create_passenger, create_routing,
    create_station, set_clock, setup_flyable_leg,
)

OPS = TEST_USERS["ops_headers"]
GATE = TEST_USERS["gate_agent_headers"]


def test_depart_is_rejected_while_the_covering_pairing_is_broken(api):
    """PRD §3.6: "A `GateAgent` may depart a `SCHEDULED` leg only when
    boarding has been opened, when no `ACTIVE` assignment on the leg still
    belongs to a journey stuck in `CHECKED_IN` (such journeys block departure
    — run the no-show sweep first to convert them), when no `CrewPairing`
    covering the leg is `BROKEN`, and when the aircraft assigned via an
    `ACTIVE` routing is `SERVICEABLE`."

    PRD §3.7: "Marking a crew member unavailable — availability `action`
    `MARK_UNAVAILABLE`, moving `crew_status` from `AVAILABLE` to
    `UNAVAILABLE` — similarly breaks every `ACTIVE` pairing they hold, with
    crew-cause propagation to the next covered leg; `action` `MARK_AVAILABLE`
    reverses only the crew member's own status, returning them to
    `AVAILABLE`."

    Design: Difficulty/cross_entity_state_dependency/depart_blocked_by_broken_crew_pairing
    """
    fx = setup_flyable_leg()
    leg = fx["leg"]
    crew = fx["crew_member"]
    pairing = fx["pairing"]

    validate_success(api.set_crew_availability(crew["id"], "MARK_UNAVAILABLE",
                                               OPS), 200)
    pairing_now = validate_success(api.get_pairing(pairing["id"], OPS), 200)
    assert pairing_now["pairing_status"] == "BROKEN"

    res = api.depart_leg(leg["id"], GATE)
    err = validate_error(res, ApiErrorId.ERR_INVALID_STATE)
    assert err["error_id"] == "ERR_INVALID_STATE"

    leg_now = validate_success(api.get_flight_leg(leg["id"], OPS), 200)
    assert leg_now["leg_status"] == "SCHEDULED", (
        "the rejected depart leaves the leg untouched")


def test_marking_available_does_not_heal_the_broken_pairing(api):
    """PRD §3.7: "Marking a crew member unavailable — availability `action`
    `MARK_UNAVAILABLE`, moving `crew_status` from `AVAILABLE` to
    `UNAVAILABLE` — similarly breaks every `ACTIVE` pairing they hold, with
    crew-cause propagation to the next covered leg; `action` `MARK_AVAILABLE`
    reverses only the crew member's own status, returning them to
    `AVAILABLE`."

    PRD §3.7: "A routing or pairing that has reached `BROKEN` is terminal."

    Design: Difficulty/cross_entity_state_dependency/depart_blocked_by_broken_crew_pairing
    """
    fx = setup_flyable_leg()
    crew = fx["crew_member"]
    pairing = fx["pairing"]

    validate_success(api.set_crew_availability(crew["id"], "MARK_UNAVAILABLE",
                                               OPS), 200)
    validate_success(api.set_crew_availability(crew["id"], "MARK_AVAILABLE",
                                               OPS), 200)

    crew_now = validate_success(api.get_crew_member(crew["id"], OPS), 200)
    assert crew_now["crew_status"] == "AVAILABLE", (
        "MARK_AVAILABLE reverses the crew member's own status")
    pairing_now = validate_success(api.get_pairing(pairing["id"], OPS), 200)
    assert pairing_now["pairing_status"] == "BROKEN", (
        "BROKEN is terminal: the pairing does not auto-restore, so a fresh "
        "pairing is required before departure")


def _cancelled_leg_with_journey(api):
    """A BOOKED journey whose leg is cancelled by a disruption post (the
    cascade flips the journey too)."""
    set_clock("2026-09-30T12:00:00Z")
    station_dal = create_station(iata_code="DAL")
    station_hou = create_station(iata_code="HOU")
    fare = create_fare_class(code="FLEX", change_fee_cents=0, included_bags=2)
    create_aircraft(tail_number="N100", seat_count=143)
    leg = create_leg(station_dal["id"], station_hou["id"], capacity_seats=143)
    passenger, p_h = create_passenger(full_name="P A")
    _bk, journey_id = book_journey(p_h, passenger["id"], leg["id"],
                                   fare["id"], base_fare_cents=10000)
    validate_success(api.post_disruption(
        leg["id"], {"disruption_type": "CANCELLATION", "cause": "WEATHER"},
        OPS), 201)
    leg_now = validate_success(api.get_flight_leg(leg["id"], OPS), 200)
    return leg_now, journey_id, passenger, p_h


def test_checkin_on_a_cancelled_leg_is_rejected_by_state(api):
    """PRD §3.4: "Both paths require that the acting passenger own the
    journey (else `ERR_FORBIDDEN`), that the journey currently be in `BOOKED`
    (else `ERR_INVALID_STATE`, HTTP 409), that the leg be in `SCHEDULED` or
    `DELAYED`, and that the logical clock sit inside the check-in window: no
    earlier than 24 hours before the scheduled departure, and no later than
    30 minutes before it, with both bounds shifted by any posted
    `delay_minutes`."

    PRD §3.7: "Cancelling a leg, whether it is `SCHEDULED` or `DELAYED`, runs
    a wider cascade. Every journey on the leg in `BOOKED` or `CHECKED_IN`
    moves to `CANCELLED`, and for each a `TravelCredit` is minted covering
    the `base_fare_cents` plus the `price_cents` of any `ACTIVE` upgrades on
    the journey — those upgrades move to `REFUNDED`."

    Design: Difficulty/cross_entity_state_dependency/journey_checkin_blocked_by_leg_cancelled
    """
    leg, journey_id, _passenger, p_h = _cancelled_leg_with_journey(api)

    assert leg["leg_status"] == "CANCELLED"
    journey = validate_success(api.get_journey(journey_id, p_h), 200)
    assert journey["journey_status"] == "CANCELLED", (
        "the cancellation cascade already flipped the journey")

    res = api.leg_check_in(
        leg["id"], {"journey_id": journey_id,
                    "expected_leg_version": leg["version"]}, p_h)
    err = validate_error(res, ApiErrorId.ERR_INVALID_STATE)
    assert err["error_id"] == "ERR_INVALID_STATE", (
        "check-in requires the leg in SCHEDULED or DELAYED; CANCELLED is a "
        "state precondition failure")


def test_journey_scoped_checkin_on_a_cancelled_leg_is_also_rejected(api):
    """PRD §3.4: "A `Passenger` checks in a journey either on the leg-scoped
    path — which carries the OCC field `expected_leg_version` per §2.7 — or
    on the journey-scoped convenience path, which performs the same business
    validations without the OCC field."

    PRD §3.4: "Both paths require that the acting passenger own the journey
    (else `ERR_FORBIDDEN`), that the journey currently be in `BOOKED` (else
    `ERR_INVALID_STATE`, HTTP 409), that the leg be in `SCHEDULED` or
    `DELAYED`, and that the logical clock sit inside the check-in window: no
    earlier than 24 hours before the scheduled departure, and no later than
    30 minutes before it, with both bounds shifted by any posted
    `delay_minutes`."

    Design: Difficulty/cross_entity_state_dependency/journey_checkin_blocked_by_leg_cancelled
    """
    leg, journey_id, _passenger, p_h = _cancelled_leg_with_journey(api)

    res = api.journey_check_in(journey_id, p_h)
    err = validate_error(res, ApiErrorId.ERR_INVALID_STATE)
    assert err["error_id"] == "ERR_INVALID_STATE"

    journey = validate_success(api.get_journey(journey_id, p_h), 200)
    assert journey["journey_status"] == "CANCELLED", (
        "the rejected check-in does not move the journey")
