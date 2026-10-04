"""Combinatorial formulas: multi-input boarding assignment and nested pricing.

Covers Difficulty/combinatorial_formula instances:
- boarding_assignment_tiered_mode_a
- upgrade_price_nested_rounding_mode_b
"""
from test_helpers import (
    TEST_USERS, api_client, get_success_data, validate_paginated,
    validate_success,
    book_journey, create_aircraft, create_fare_class, create_leg,
    create_passenger, create_station, leg_check_in, purchase_upgrade,
    set_clock, setup_basic_network,
)

OPS = TEST_USERS["ops_headers"]
GATE = TEST_USERS["gate_agent_headers"]


def _six_passenger_leg():
    """Leg with PREBOARD, UB-purchaser, A_LIST_PREFERRED, A_LIST and two
    NONE-tier passengers, checked in in a controlled order."""
    station_dal = create_station(iata_code="DAL")
    station_hou = create_station(iata_code="HOU")
    fc_pre = create_fare_class(code="PRE", change_fee_cents=0,
                               preboard_eligible=True, included_bags=2)
    fc_flex = create_fare_class(code="FLEX", change_fee_cents=0,
                                included_bags=2)
    create_aircraft(tail_number="N100", seat_count=143)
    leg = create_leg(station_dal["id"], station_hou["id"], capacity_seats=143)
    leg_v = leg["version"]

    people = {}
    people["pre"] = create_passenger(full_name="P PRE")
    people["upg"] = create_passenger(full_name="P UPG")
    people["alp"] = create_passenger(full_name="P ALP",
                                     status_tier="A_LIST_PREFERRED")
    people["al"] = create_passenger(full_name="P AL", status_tier="A_LIST")
    people["n1"] = create_passenger(full_name="P N1")
    people["n2"] = create_passenger(full_name="P N2")

    journeys = {}
    _bk, journeys["pre"] = book_journey(
        people["pre"][1], people["pre"][0]["id"], leg["id"], fc_pre["id"],
        base_fare_cents=10000, accommodation="PREBOARD")
    for key in ("upg", "alp", "al", "n1", "n2"):
        _bk, journeys[key] = book_journey(
            people[key][1], people[key][0]["id"], leg["id"], fc_flex["id"],
            base_fare_cents=10000)

    set_clock("2026-09-30T12:00:00Z")
    _j, leg_v = leg_check_in(leg["id"], journeys["upg"], people["upg"][1],
                             expected_leg_version=leg_v)
    upgrade, leg_v = purchase_upgrade(
        leg["id"], journeys["upg"], people["upg"][1], "UPGRADED_BOARDING",
        expected_leg_version=leg_v)

    for clock, key in (("2026-09-30T12:00:01Z", "n2"),
                       ("2026-09-30T12:00:05Z", "n1"),
                       ("2026-09-30T12:00:10Z", "al"),
                       ("2026-09-30T12:00:20Z", "alp"),
                       ("2026-09-30T12:00:30Z", "pre")):
        set_clock(clock)
        _j, leg_v = leg_check_in(leg["id"], journeys[key], people[key][1],
                                 expected_leg_version=leg_v)

    return leg, people, journeys, upgrade


def test_phases_order_across_accommodation_upgrade_tier_and_checkin(api):
    """PRD §3.4: "The algorithm runs in ordered phases; every passenger
    appears in exactly one phase, and the global boarding sequence is
    determined by group rank first (PREBOARD, then A, then FAMILY, then B,
    then C), then `boarding_position` ascending within the group, then
    `checked_in_at` ascending, then journey `created_at` ascending as the
    final tiebreak."

    Design: Difficulty/combinatorial_formula/boarding_assignment_tiered_mode_a
    """
    leg, _people, journeys, upgrade = _six_passenger_leg()

    assignments, meta = validate_paginated(
        api.list_leg_boarding_assignments(
            leg["id"], GATE, params={"assignment_status": "ACTIVE"}))
    assert meta["total_count"] == 6
    order = [a["journey_id"] for a in assignments]
    assert order == [journeys["pre"], journeys["upg"], journeys["alp"],
                     journeys["al"], journeys["n2"], journeys["n1"]], (
        f"boarding order must follow the phase interaction, got {order}")
    assert assignments[0]["boarding_group"] == "PREBOARD"
    assert assignments[1]["assignment_source"] == "UPGRADE_PURCHASE"
    assert assignments[2]["assignment_source"] == "STATUS_PRIORITY"
    assert assignments[3]["assignment_source"] == "STATUS_PRIORITY"
    assert assignments[4]["assignment_source"] == "CHECKIN_TIME"
    assert upgrade["position_granted"] == 1


def test_group_a_positions_number_after_the_purchased_pool(api):
    """PRD §3.4: "Positions in group A continue numbering after the A1-A15
    pool."

    PRD §3.4: "Remaining `A_LIST_PREFERRED` journeys are placed into group A
    first, then remaining `A_LIST` journeys, each ordered by `checked_in_at`
    ascending with `created_at` ascending as tiebreak."

    Design: Difficulty/combinatorial_formula/boarding_assignment_tiered_mode_a
    """
    leg, _people, journeys, _upgrade = _six_passenger_leg()

    assignments, _meta = validate_paginated(
        api.list_leg_boarding_assignments(
            leg["id"], GATE, params={"assignment_status": "ACTIVE"}))
    by_journey = {a["journey_id"]: a for a in assignments}
    assert by_journey[journeys["upg"]]["boarding_position"] == 1
    assert by_journey[journeys["alp"]]["boarding_position"] == 16, (
        "status-priority positions continue after the 15-slot pool")
    assert by_journey[journeys["al"]]["boarding_position"] == 17
    assert by_journey[journeys["n2"]]["boarding_position"] == 18, (
        "among NONE-tier regulars, the earlier check-in sorts first")
    assert by_journey[journeys["n1"]]["boarding_position"] == 19
    for jid in ("upg", "alp", "al", "n2", "n1"):
        assert by_journey[journeys[jid]]["boarding_group"] == "A"


def _d10_upgrade_setup():
    """A_LIST_PREFERRED passenger with a checked-in journey on fare D10
    (upgrade_discount_pct=10)."""
    net = setup_basic_network(fare_overrides={"code": "D10",
                                              "change_fee_cents": 0,
                                              "upgrade_discount_pct": 10,
                                              "included_bags": 2})
    leg = net["leg"]
    set_clock("2026-09-30T12:00:00Z")
    passenger, p_h = create_passenger(full_name="P ALP",
                                      status_tier="A_LIST_PREFERRED")
    _bk, journey_id = book_journey(p_h, passenger["id"], leg["id"],
                                   net["fare"]["id"], base_fare_cents=10000)
    _j, leg_v = leg_check_in(leg["id"], journey_id, p_h,
                             expected_leg_version=leg["version"])
    return net, leg, passenger, p_h, journey_id, leg_v


def test_early_bird_price_excludes_the_status_tier_discount(api):
    """PRD §3.5: "For `EARLY_BIRD`, only the fare-class discount ever applies
    — the status-tier discount never touches it, regardless of the
    passenger's tier."

    Design: Difficulty/combinatorial_formula/upgrade_price_nested_rounding_mode_b
    """
    net, leg, _pax, p_h, journey_id, leg_v = _d10_upgrade_setup()

    set_clock("2026-09-29T20:00:00Z")
    eb, _v = purchase_upgrade(leg["id"], journey_id, p_h, "EARLY_BIRD",
                              expected_leg_version=leg_v)
    assert eb["price_cents"] == 1350, (
        "floor(1500 * (100 - 10) / 100) == 1350; applying the 25% tier "
        "discount would yield 1013")
    assert eb["upgrade_type"] == "EARLY_BIRD"
    assert eb["upgrade_status"] == "ACTIVE"


def test_upgraded_boarding_price_floors_fare_discount_then_tier(api):
    """PRD §3.5: "For `UPGRADED_BOARDING`, the fare-class discount is applied
    first: the base is multiplied by one hundred minus the fare's
    `upgrade_discount_pct`, divided by one hundred, and the result is rounded
    down to a whole cent. The status-tier discount is then applied to that
    intermediate: a passenger of `A_LIST` tier receives a 10 percent discount,
    `A_LIST_PREFERRED` receives 25 percent, and `NONE` receives no discount;
    this second multiplication is likewise rounded down to a whole cent."

    Design: Difficulty/combinatorial_formula/upgrade_price_nested_rounding_mode_b
    """
    net, leg, _pax, p_h, journey_id, leg_v = _d10_upgrade_setup()

    set_clock("2026-09-30T12:00:00Z")
    ub, _v = purchase_upgrade(leg["id"], journey_id, p_h, "UPGRADED_BOARDING",
                              expected_leg_version=leg_v)
    assert ub["price_cents"] == 2700, (
        "floor(floor(4000 * 0.90) = 3600 * 0.75) == 2700 under the pinned "
        "fare-first nested floor")
    assert ub["position_granted"] == 1
    assert ub["upgrade_status"] == "ACTIVE"

    upgrades, meta = validate_paginated(
        api.list_journey_upgrades(journey_id, p_h))
    assert meta["total_count"] == 1
