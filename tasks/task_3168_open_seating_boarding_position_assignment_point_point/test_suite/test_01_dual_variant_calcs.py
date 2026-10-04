"""Dual-variant calculations: the same surface answers differently in two modes.

Covers Difficulty/dual_variant_calc instances:
- credit_mint_full_vs_no_show_forfeit
- turn_projection_forward_vs_realized
"""
import pytest

from test_helpers import (
    TEST_USERS, api_client, get_success_data, validate_error,
    validate_paginated, validate_success,
    book_journey, check_in_journey, create_aircraft, create_fare_class,
    create_leg, create_passenger, create_station, leg_check_in,
    make_passenger_headers, set_clock, setup_basic_network,
)

OPS = TEST_USERS["ops_headers"]
GATE = TEST_USERS["gate_agent_headers"]


def _dual_fare_network():
    """Stations, FLEX (change_fee 0) and WGA (change_fee 5000) fares, leg L1."""
    station_dal = create_station(iata_code="DAL")
    station_hou = create_station(iata_code="HOU")
    fc_flex = create_fare_class(code="FLEX", change_fee_cents=0,
                                included_bags=2, credit_validity_days=365)
    fc_wga = create_fare_class(code="WGA", change_fee_cents=5000,
                               included_bags=2, credit_validity_days=365)
    leg = create_leg(station_dal["id"], station_hou["id"], capacity_seats=143)
    return station_dal, station_hou, fc_flex, fc_wga, leg


def test_cancelling_a_flexible_fare_journey_mints_full_credit(api):
    """PRD §3.8: "Step two: the minted amount is computed from the journey's
    own fields only — the `base_fare_cents` plus the sum of `price_cents`
    across the journey's `ACTIVE` upgrades — and the new credit never draws
    from the balances restored in step one."

    PRD §3.8: "A fresh credit starts in `OPEN` status."

    Design: Difficulty/dual_variant_calc/credit_mint_full_vs_no_show_forfeit
    """
    set_clock("2026-09-30T12:00:00Z")
    _dal, _hou, fc_flex, _wga, leg = _dual_fare_network()
    passenger, p_h = create_passenger(full_name="P A")
    _bk, j_flex = book_journey(p_h, passenger["id"], leg["id"],
                               fc_flex["id"], base_fare_cents=20000)

    validate_success(api.cancel_journey(j_flex, p_h), 200)

    credits, meta = validate_paginated(
        api.list_credits(p_h, params={"passenger_id": passenger["id"]}))
    assert meta["total_count"] == 1, "exactly one credit is minted"
    credit = credits[0]
    assert credit["initial_amount_cents"] == 20000
    assert credit["remaining_amount_cents"] == 20000
    assert credit["source_journey_id"] == j_flex
    assert credit["credit_status"] == "OPEN"
    # No upgrades and no redemptions on the cancelled journey: the minted
    # amount is exactly the base fare.
    journey = validate_success(api.get_journey(j_flex, p_h), 200)
    assert journey["journey_status"] == "CANCELLED"


def test_non_flexible_no_show_forfeits_fare_and_mints_no_credit(api):
    """PRD §3.6: "For a non-flexible fare, no credit is minted; instead the
    journey's `no_show_penalty_cents` is set equal to its `base_fare_cents`."

    PRD §3.6: "The sweep converts every journey still in `CHECKED_IN` to
    `NO_SHOW`."

    Design: Difficulty/dual_variant_calc/credit_mint_full_vs_no_show_forfeit
    """
    set_clock("2026-09-30T12:00:00Z")
    _dal, _hou, _flex, fc_wga, leg = _dual_fare_network()
    passenger, p_h = create_passenger(full_name="P A")
    _bk, j_wga = book_journey(p_h, passenger["id"], leg["id"],
                              fc_wga["id"], base_fare_cents=20000)
    check_in_journey(j_wga, p_h)
    validate_success(api.open_boarding(leg["id"], GATE), 200)
    set_clock("2026-10-01T12:00:00Z")
    validate_success(api.no_show_sweep(leg["id"], GATE), 200)

    journey = validate_success(api.get_journey(j_wga, p_h), 200)
    assert journey["journey_status"] == "NO_SHOW"
    assert journey["no_show_penalty_cents"] == 20000, (
        "the forfeited fare rides on no_show_penalty_cents")

    credits, meta = validate_paginated(
        api.list_credits(p_h, params={"passenger_id": passenger["id"]}))
    assert meta["total_count"] == 0, "a non-flexible no-show mints no credit"


def _turn_projection_leg(api):
    """Leg with 1 CHECKED_IN journey carrying 2 ACCEPTED bags and 1 BOOKED
    journey, at capacity 100 with turn_target 35."""
    net = setup_basic_network(fare_overrides={"change_fee_cents": 0,
                                              "included_bags": 2},
                              capacity_seats=100)
    leg = net["leg"]
    fare = net["fare"]
    set_clock("2026-09-30T12:00:00Z")
    pk, pk_h = create_passenger(full_name="P K")
    pb, pb_h = create_passenger(full_name="P B")
    _bk1, j_k = book_journey(pk_h, pk["id"], leg["id"], fare["id"],
                             base_fare_cents=10000)
    _bk2, j_b = book_journey(pb_h, pb["id"], leg["id"], fare["id"],
                             base_fare_cents=10000)
    check_in_journey(j_k, pk_h)
    validate_success(api.check_bag(j_k, {"weight_lbs": 30}, GATE), 201)
    validate_success(api.check_bag(j_k, {"weight_lbs": 30}, GATE), 201)
    set_clock("2026-10-01T11:00:00Z")
    return net, pk, pk_h, j_k, j_b


def test_forward_projection_counts_expected_bags_for_booked_journeys(api):
    """PRD §3.10: "Projected bags are the sum of two parts: for each such
    journey, the count of that journey's currently `ACCEPTED` bags, plus — for
    each `BOOKED` journey — the fare class's `included_bags` as an
    expected-but-not-yet-checked allowance; the total is capped at twice the
    leg's `capacity_seats`."

    PRD §3.10: "The projected turn in minutes is the base plus bag minutes
    plus pax minutes plus the buffer, and the projection reports `turns_slip`
    true when that total exceeds the leg's `turn_target_minutes`."

    Design: Difficulty/dual_variant_calc/turn_projection_forward_vs_realized
    """
    net, _pk, _pk_h, _j_k, _j_b = _turn_projection_leg(api)
    leg = net["leg"]

    proj = validate_success(api.get_turn_projection(leg["id"], GATE), 200)
    assert proj["projected_bags"] == 4, (
        "2 ACCEPTED bags plus 1 BOOKED journey x included_bags 2")
    assert proj["pax_minutes"] == 1, "ceil(2 journeys * 18s / 60) rounds up"
    assert proj["projected_turn_minutes"] == 17, (
        "12 base + 4 bag minutes + 1 pax minute + 0 buffer on an on-time leg")
    assert proj["turns_slip"] is False, "17 does not exceed turn_target 35"


def test_realized_projection_counts_only_what_actually_flew(api):
    """PRD §3.10: "Once the leg has departed, the same read switches to a
    realized view: actual `LOADED` bag count and actual `BOARDED` passenger
    count replace the projections, and no buffer is applied — the realized
    view answers \"did we make the turn\" rather than \"will we\"."

    Design: Difficulty/dual_variant_calc/turn_projection_forward_vs_realized
    """
    net, pk, pk_h, j_k, j_b = _turn_projection_leg(api)
    leg = net["leg"]

    validate_success(api.open_boarding(leg["id"], GATE), 200)
    validate_success(api.scan_boarding(j_k, GATE), 200)
    set_clock("2026-10-01T12:00:00Z")
    validate_success(api.depart_leg(leg["id"], GATE), 200)

    realized = validate_success(api.get_turn_projection(leg["id"], GATE), 200)
    assert realized["projected_bags"] == 2, (
        "only the 2 actually-LOADED bags count once the leg has departed")
    assert realized["pax_minutes"] == 1, (
        "ceil(1 BOARDED passenger * 18s / 60)")
    assert realized["projected_turn_minutes"] == 15, (
        "12 base + 2 bag minutes + 1 pax minute; no buffer, no projection")
    assert realized["turns_slip"] is False
