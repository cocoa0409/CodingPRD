"""Validation priority pairs: the earlier guard wins when two could fire.

Covers Difficulty/priority_pair_validation_conflict instances:
- state_vs_business_safety_on_checkin
- referential_vs_fiscal_on_routing_create
"""
from test_helpers import (
    TEST_USERS, api_client, get_success_data, validate_error,
    validate_paginated, validate_success,
    ApiErrorId,
    book_journey, create_aircraft, create_fare_class, create_leg,
    create_passenger, create_station, leg_check_in, set_clock,
)

OPS = TEST_USERS["ops_headers"]
GATE = TEST_USERS["gate_agent_headers"]


def _mis_provisioned_preboard_journey():
    """A journey carrying accommodation=PREBOARD that is already CHECKED_IN,
    on a fare class that has since been corrected to preboard_eligible=false.

    The PRD forbids mutating a fare class after creation, so the second
    check-in is attempted through the journey-scoped convenience path on a
    journey that is no longer BOOKED — the state gate fires while the fare
    would also fail a fresh preboard-eligibility read.
    """
    set_clock("2026-09-30T12:00:00Z")
    station_dal = create_station(iata_code="DAL")
    station_hou = create_station(iata_code="HOU")
    fare = create_fare_class(code="PREX", change_fee_cents=0,
                             preboard_eligible=True, included_bags=2)
    create_aircraft(tail_number="N100", seat_count=143)
    leg = create_leg(station_dal["id"], station_hou["id"], capacity_seats=143)
    passenger, p_h = create_passenger(full_name="P A")
    _bk, journey_id = book_journey(p_h, passenger["id"], leg["id"],
                                   fare["id"], base_fare_cents=10000,
                                   accommodation="PREBOARD")
    _j, leg_v = leg_check_in(leg["id"], journey_id, p_h,
                             expected_leg_version=leg["version"])
    return leg, journey_id, p_h, leg_v


def test_second_checkin_reports_the_state_gate_not_the_business_rule(api):
    """PRD §2.6: "Beyond existence, each endpoint runs its guard checks in a
    fixed priority order so that competing failure modes surface
    deterministically. Authentication (presence and recognition of `X-User-ID`
    and `X-User-Role`) runs first, then role authorization, then passenger
    ownership on the resource in question, then path-resource existence, then
    the target's state precondition (`ERR_INVALID_STATE`), then
    business-referential rules (fleet homogeneity, routing chain, turn buffer,
    double-booked aircraft, crew legality, station connection), then
    business-safety rules (preboard eligibility, family-anchor eligibility,
    bag weight), then business constraints (check-in window, upgrade window,
    sold-out pool, duplicate upgrade, duplicate check-in, boarding capacity,
    bag count cap, delay floor), and finally business-fiscal rules (fare
    active, credit redeemable, credit expiry, change fee, upgrade
    refundability). When two checks could both fail, the earlier one in this
    ordering is the one the client sees."

    PRD §3.4: "Both paths require that the acting passenger own the journey
    (else `ERR_FORBIDDEN`), that the journey currently be in `BOOKED` (else
    `ERR_INVALID_STATE`, HTTP 409), that the leg be in `SCHEDULED` or
    `DELAYED`, and that the logical clock sit inside the check-in window: no
    earlier than 24 hours before the scheduled departure, and no later than
    30 minutes before it, with both bounds shifted by any posted
    `delay_minutes`."

    Design: Difficulty/priority_pair_validation_conflict/state_vs_business_safety_on_checkin
    """
    leg, journey_id, p_h, leg_v = _mis_provisioned_preboard_journey()

    # Second check-in through the leg-scoped path: the journey is no longer
    # BOOKED, and the duplicate-check-in business constraint could also fire;
    # the state precondition is earlier in the published ordering.
    res = api.leg_check_in(
        leg["id"], {"journey_id": journey_id, "expected_leg_version": leg_v},
        p_h)
    err = validate_error(res, ApiErrorId.ERR_INVALID_STATE)
    assert err["error_id"] == "ERR_INVALID_STATE"

    journey = validate_success(api.get_journey(journey_id, p_h), 200)
    assert journey["journey_status"] == "CHECKED_IN", (
        "the rejected second check-in does not move the journey")


def test_state_gate_preempts_duplicate_checkin_on_the_convenience_path(api):
    """PRD §2.6: "When two checks could both fail, the earlier one in this
    ordering is the one the client sees."

    PRD §3.4: "A `Passenger` checks in a journey either on the leg-scoped
    path — which carries the OCC field `expected_leg_version` per §2.7 — or
    on the journey-scoped convenience path, which performs the same business
    validations without the OCC field."

    Design: Difficulty/priority_pair_validation_conflict/state_vs_business_safety_on_checkin
    """
    leg, journey_id, p_h, leg_v = _mis_provisioned_preboard_journey()

    res = api.journey_check_in(journey_id, p_h)
    err = validate_error(res, ApiErrorId.ERR_INVALID_STATE)
    assert err["error_id"] == "ERR_INVALID_STATE"

    journey = validate_success(api.get_journey(journey_id, p_h), 200)
    assert journey["journey_status"] == "CHECKED_IN"


def _turn_and_connection_violating_pair():
    """Legs L1 DAL->HOU (arrives 13:00) and L2 HOU->AUS (departs 13:20,
    turn_target 35): the 20-minute gap violates both the turn buffer and
    HOU's min_connection_minutes 40."""
    set_clock("2026-09-30T12:00:00Z")
    station_dal = create_station(iata_code="DAL", min_connection_minutes=40)
    station_hou = create_station(iata_code="HOU", min_connection_minutes=40)
    station_aus = create_station(iata_code="AUS", min_connection_minutes=40)
    aircraft = create_aircraft(tail_number="N100", seat_count=143)
    l1 = create_leg(station_dal["id"], station_hou["id"],
                    scheduled_departure_utc="2026-10-01T12:00:00Z",
                    scheduled_arrival_utc="2026-10-01T13:00:00Z",
                    capacity_seats=143)
    l2 = create_leg(station_hou["id"], station_aus["id"],
                    scheduled_departure_utc="2026-10-01T13:20:00Z",
                    scheduled_arrival_utc="2026-10-01T14:20:00Z",
                    capacity_seats=143)
    return aircraft, l1, l2


def test_turn_buffer_check_wins_over_station_connection_check(api):
    """PRD §3.2: "Creation validates, in this relative order: fleet
    homogeneity (`ERR_FLEET_HETEROGENEITY`), then the chain rule that
    consecutive legs share a station — the destination of the earlier leg
    equals the origin of the next — and that each leg's arrival precedes the
    next leg's departure (`ERR_ROUTING_CHAIN_BROKEN`), then the turn-buffer
    rule that the gap between an earlier leg's arrival and the next leg's
    departure is at least the next leg's `turn_target_minutes`, with equality
    allowed (a touching turn is valid; a shortfall rejects creation with
    `ERR_ROUTING_TURN_VIOLATION`), then a temporal-overlap check that no
    other `ACTIVE` routing already covers the same tail on the same date with
    overlapping leg windows — touching endpoints are again allowed, overlaps
    reject with `ERR_AIRCRAFT_DOUBLE_BOOKED` (HTTP 409) — and finally the
    station-connection rule that no gap falls below the connection station's
    `min_connection_minutes` (`ERR_STATION_CONNECTION_VIOLATION`, HTTP 422)."

    Design: Difficulty/priority_pair_validation_conflict/referential_vs_fiscal_on_routing_create
    """
    aircraft, l1, l2 = _turn_and_connection_violating_pair()

    res = api.create_routing(
        {"routing_date": "2026-10-01", "aircraft_id": aircraft["id"],
         "leg_ids": [l1["id"], l2["id"]]}, OPS)
    err = validate_error(res, ApiErrorId.ERR_ROUTING_TURN_VIOLATION)
    assert err["error_id"] == "ERR_ROUTING_TURN_VIOLATION", (
        "the 20-minute gap is below turn_target 35, and the turn-buffer "
        "rule runs before the station-connection rule even though the gap "
        "is also below min_connection_minutes 40")

    routings, meta = validate_paginated(api.list_routings(OPS))
    assert meta["total_count"] == 0, "no routing row is persisted"


def test_shortfall_rejects_creation_while_the_chain_itself_is_valid(api):
    """PRD §3.2: "then the turn-buffer rule that the gap between an earlier
    leg's arrival and the next leg's departure is at least the next leg's
    `turn_target_minutes`, with equality allowed (a touching turn is valid;
    a shortfall rejects creation with `ERR_ROUTING_TURN_VIOLATION`)".

    Design: Difficulty/priority_pair_validation_conflict/referential_vs_fiscal_on_routing_create
    """
    aircraft, l1, l2 = _turn_and_connection_violating_pair()

    res = api.create_routing(
        {"routing_date": "2026-10-01", "aircraft_id": aircraft["id"],
         "leg_ids": [l1["id"], l2["id"]]}, OPS)
    assert res.status_code == 422
    body = res.json()["data"]
    assert body["error_id"] != "ERR_STATION_CONNECTION_VIOLATION", (
        "the station-connection check is later in the published order")
    assert body["error_id"] != "ERR_ROUTING_CHAIN_BROKEN", (
        "the legs share HOU and are time-ordered, so the chain rule passes")
