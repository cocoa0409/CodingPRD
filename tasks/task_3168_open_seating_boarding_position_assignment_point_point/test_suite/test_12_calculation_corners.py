"""Calculation corner tests: bag fee waterfall, overweight gate, routing slack.

Covers Corner/calculations instances:
- bag_fee_third_bag_charged
- bag_overweight_rejected_before_fee
- routing_slack_min_over_pairs
- routing_turn_equality_allowed
"""
from test_helpers import (
    TEST_USERS, api_client, get_success_data, validate_error,
    validate_paginated, validate_success,
    ApiErrorId,
    create_aircraft, create_fare_class, create_leg, create_routing,
    create_station, set_clock, setup_checked_in_journey,
)

OPS = TEST_USERS["ops_headers"]
GATE = TEST_USERS["gate_agent_headers"]


def test_third_bag_carries_the_flat_fee(api):
    """PRD §3.6: "The fee waterfall then computes the ordinal bag index as
    the count of the journey's prior bags in `ACCEPTED` or `LOADED` status,
    plus one. If that ordinal is at most the fare class's `included_bags`,
    `bag_fee_cents` is zero; beyond the allotment, the bag carries the flat
    `BAG_FEE_CENTS` fee of 7500 cents."

    Design: Corner/calculations/bag_fee_third_bag_charged
    """
    fx = setup_checked_in_journey(
        fare_overrides={"change_fee_cents": 0, "included_bags": 2})
    journey_id = fx["journey_id"]

    bag1 = validate_success(api.check_bag(journey_id, {"weight_lbs": 20},
                                          GATE), 201)
    bag2 = validate_success(api.check_bag(journey_id, {"weight_lbs": 20},
                                          GATE), 201)
    bag3 = validate_success(api.check_bag(journey_id, {"weight_lbs": 20},
                                          GATE), 201)

    assert bag1["bag_fee_cents"] == 0, "bag 1 is inside the allotment"
    assert bag2["bag_fee_cents"] == 0, "bag 2 is inside the allotment"
    assert bag3["bag_fee_cents"] == 7500, (
        "the fee attaches at ordinal k > included_bags, not k >= included_bags")
    for bag in (bag1, bag2, bag3):
        assert bag["bag_status"] == "ACCEPTED"


def test_overweight_bag_is_rejected_before_any_fee_runs(api):
    """PRD §3.6: "The weight is checked first: if it exceeds the origin
    station's `bag_weight_limit_lbs`, acceptance is rejected with
    `ERR_BAG_OVERWEIGHT` (HTTP 422) before any fee assessment runs."

    Design: Corner/calculations/bag_overweight_rejected_before_fee
    """
    fx = setup_checked_in_journey(
        fare_overrides={"change_fee_cents": 0, "included_bags": 2})
    journey_id = fx["journey_id"]

    res = api.check_bag(journey_id, {"weight_lbs": 60}, GATE)
    err = validate_error(res, ApiErrorId.ERR_BAG_OVERWEIGHT)
    assert err["error_id"] == "ERR_BAG_OVERWEIGHT", (
        "60 lb exceeds the default 50-lb station limit")

    bags, meta = validate_paginated(api.list_journey_bags(journey_id, GATE))
    assert meta["total_count"] == 0, "no bag row is persisted"


def _slack_chain():
    """Legs L1 12:00-13:00, L2 13:50-14:50 (turn 35 -> slack 15),
    L3 15:30-16:30 (turn 35 -> slack 5)."""
    set_clock("2026-09-30T12:00:00Z")
    station_dal = create_station(iata_code="DAL", min_connection_minutes=30)
    station_hou = create_station(iata_code="HOU", min_connection_minutes=30)
    station_aus = create_station(iata_code="AUS", min_connection_minutes=30)
    aircraft = create_aircraft(tail_number="N100", seat_count=143)
    l1 = create_leg(station_dal["id"], station_hou["id"],
                    scheduled_departure_utc="2026-10-01T12:00:00Z",
                    scheduled_arrival_utc="2026-10-01T13:00:00Z",
                    capacity_seats=143)
    l2 = create_leg(station_hou["id"], station_aus["id"],
                    scheduled_departure_utc="2026-10-01T13:50:00Z",
                    scheduled_arrival_utc="2026-10-01T14:50:00Z",
                    capacity_seats=143)
    l3 = create_leg(station_aus["id"], station_dal["id"],
                    scheduled_departure_utc="2026-10-01T15:30:00Z",
                    scheduled_arrival_utc="2026-10-01T16:30:00Z",
                    capacity_seats=143)
    return aircraft, l1, l2, l3


def test_routing_slack_is_the_minimum_over_consecutive_pairs(api):
    """PRD §3.2: "For each consecutive pair of legs, the per-pair slack is
    the gap between the next leg's scheduled departure and the previous leg's
    scheduled arrival, minus the next leg's `turn_target_minutes`. Half-open
    semantics apply: a pair whose gap equals the turn target exactly yields a
    slack of zero and is valid; a negative slack rejects creation. The
    routing's `slack_minutes` is the minimum across all consecutive pairs."

    Design: Corner/calculations/routing_slack_min_over_pairs
    """
    aircraft, l1, l2, l3 = _slack_chain()

    routing = validate_success(api.create_routing(
        {"routing_date": "2026-10-01", "aircraft_id": aircraft["id"],
         "leg_ids": [l1["id"], l2["id"], l3["id"]]}, OPS), 201)
    assert routing["slack_minutes"] == 5, (
        "pair 1 slack is 50 - 35 = 15; pair 2 slack is 40 - 35 = 5; the "
        "routing reports the minimum")
    assert routing["routing_status"] == "ACTIVE"


def test_turn_gap_equal_to_the_target_is_valid_with_zero_slack(api):
    """PRD §3.2: "Half-open semantics apply: a pair whose gap equals the turn
    target exactly yields a slack of zero and is valid; a negative slack
    rejects creation."

    Design: Corner/calculations/routing_turn_equality_allowed
    """
    set_clock("2026-09-30T12:00:00Z")
    station_dal = create_station(iata_code="DAL", min_connection_minutes=30)
    station_hou = create_station(iata_code="HOU", min_connection_minutes=30)
    aircraft = create_aircraft(tail_number="N100", seat_count=143)
    l1 = create_leg(station_dal["id"], station_hou["id"],
                    scheduled_departure_utc="2026-10-01T12:00:00Z",
                    scheduled_arrival_utc="2026-10-01T13:00:00Z",
                    capacity_seats=143)
    l2 = create_leg(station_hou["id"], station_dal["id"],
                    scheduled_departure_utc="2026-10-01T13:35:00Z",
                    scheduled_arrival_utc="2026-10-01T14:35:00Z",
                    capacity_seats=143)

    routing = validate_success(api.create_routing(
        {"routing_date": "2026-10-01", "aircraft_id": aircraft["id"],
         "leg_ids": [l1["id"], l2["id"]]}, OPS), 201)
    assert routing["slack_minutes"] == 0, (
        "STD_next - STA_prev == turn_target exactly: equality is allowed "
        "under half-open semantics")
    assert routing["routing_status"] == "ACTIVE"
