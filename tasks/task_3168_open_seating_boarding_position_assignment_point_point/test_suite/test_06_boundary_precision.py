"""Boundary precision: strict thresholds at exact equality.

Covers Difficulty/boundary_precision_check instances:
- staffing_bags_per_agent_strict_greater_boundary
- a1_a15_pool_exhaustion_at_capacity
"""
from test_helpers import (
    TEST_USERS, api_client, get_success_data, validate_error,
    validate_success,
    ApiErrorId,
    book_journey, check_in_journey, create_aircraft, create_fare_class,
    create_leg, create_passenger, create_routing, create_station,
    leg_check_in, purchase_upgrade, set_clock, setup_basic_network,
)

OPS = TEST_USERS["ops_headers"]
GATE = TEST_USERS["gate_agent_headers"]


def _staffing_leg_with_bags(bag_count):
    """90 checked-in journeys on a 100-seat leg with `bag_count` ACCEPTED
    bags spread across them (one per journey)."""
    net = setup_basic_network(fare_overrides={"change_fee_cents": 0,
                                              "included_bags": 2},
                              capacity_seats=100,
                              leg_overrides={"gate_agent_count": 3,
                                             "ramp_agent_count": 4})
    leg = net["leg"]
    set_clock("2026-09-30T12:00:00Z")
    journeys = []
    for i in range(90):
        passenger, p_h = create_passenger(
            full_name=f"P {i + 1:02d}", date_of_birth="1990-01-01")
        _bk, journey_id = book_journey(p_h, passenger["id"], leg["id"],
                                       net["fare"]["id"],
                                       base_fare_cents=10000)
        check_in_journey(journey_id, p_h)
        journeys.append(journey_id)
    for journey_id in journeys[:bag_count]:
        validate_success(api_client.check_bag(journey_id, {"weight_lbs": 20},
                                              GATE), 201)
    return leg


def test_exactly_15_bags_per_ramp_agent_is_adequate(api):
    """PRD §3.10: "The leg is flagged `understaffed` when either condition
    holds: `staff_units` falls below the required 5 units (so exactly 5 units
    is adequate), or the load factor reaches at least 0.90 — the 0.90
    boundary itself triggers — while at the same time `bags_per_ramp_agent`
    exceeds 15 (so exactly 15.0 bags per ramp agent is adequate)."

    Design: Difficulty/boundary_precision_check/staffing_bags_per_agent_strict_greater_boundary
    """
    leg = _staffing_leg_with_bags(60)

    check = validate_success(api.get_staffing_check(leg["id"], GATE), 200)
    assert check["load_factor"] == 0.9, (
        "90 booked journeys on 100 seats rounds to 0.90, which satisfies the "
        ">= co-condition at its own boundary")
    assert check["bags_per_ramp_agent"] == 15.0, (
        "60 ACCEPTED bags over 4 ramp agents is exactly 15.0")
    assert check["understaffed"] is False, (
        "the clause uses a strict > against 15: equality is adequate")
    assert check["staff_units"] == 7


def test_one_more_bag_crosses_the_bags_per_agent_threshold(api):
    """PRD §3.10: "The leg is flagged `understaffed` when either condition
    holds: `staff_units` falls below the required 5 units (so exactly 5 units
    is adequate), or the load factor reaches at least 0.90 — the 0.90
    boundary itself triggers — while at the same time `bags_per_ramp_agent`
    exceeds 15 (so exactly 15.0 bags per ramp agent is adequate)."

    Design: Difficulty/boundary_precision_check/staffing_bags_per_agent_strict_greater_boundary
    """
    leg = _staffing_leg_with_bags(61)

    check = validate_success(api.get_staffing_check(leg["id"], GATE), 200)
    assert check["load_factor"] == 0.9
    assert check["bags_per_ramp_agent"] == 15.3, (
        "61 / 4 = 15.25 rounds half-up to 15.3 at one decimal place")
    assert check["understaffed"] is True, (
        "0.90 >= 0.90 and 15.3 > 15: one bag flips the predicate")


def _tiny_pool_leg():
    """A 3-seat aircraft caps the purchasable pool at min(15, 3) == 3, with
    four checked-in journeys competing for it. The leg's boarding capacity
    is 4 so all four journeys can be checked in (PRD §3.4 caps boarding at
    `capacity_seats`); only the A1-A15 pool is shrunk by the tail's
    `seat_count`."""
    net = setup_basic_network(fare_overrides={"change_fee_cents": 0,
                                              "included_bags": 2},
                              capacity_seats=4, seat_count=3)
    leg = net["leg"]
    # The pool is "the smaller of 15 and the assigned aircraft's seat_count"
    # (PRD §3.4/§3.5), so the tail must actually be assigned to the leg via
    # an ACTIVE routing for the 3-seat cap to apply.
    create_routing("2026-10-01", net["aircraft"]["id"], [leg["id"]])
    set_clock("2026-09-30T12:00:00Z")
    passengers = []
    journeys = []
    leg_v = leg["version"]
    for i in range(4):
        passenger, p_h = create_passenger(full_name=f"P {i + 1}")
        _bk, journey_id = book_journey(p_h, passenger["id"], leg["id"],
                                       net["fare"]["id"],
                                       base_fare_cents=10000)
        _j, leg_v = leg_check_in(leg["id"], journey_id, p_h,
                                 expected_leg_version=leg_v)
        passengers.append((passenger, p_h))
        journeys.append(journey_id)
    return net, leg, passengers, journeys, leg_v


def test_a1_a15_pool_grants_up_to_the_seat_count_cap(api):
    """PRD §3.4: "The pool's size is the smaller of 15 and the assigned
    aircraft's `seat_count`, so a tail with fewer than 15 physical seats
    shrinks the purchasable pool accordingly."

    PRD §3.5: "For `UPGRADED_BOARDING`, the purchasable pool is capped at the
    smaller of 15 and the aircraft's `seat_count`: when the count of `ACTIVE`
    `UPGRADED_BOARDING` upgrades on the leg already equals that cap, the
    purchase is rejected with `ERR_UPGRADE_SOLD_OUT` (HTTP 409)."

    Design: Difficulty/boundary_precision_check/a1_a15_pool_exhaustion_at_capacity
    """
    _net, leg, passengers, journeys, leg_v = _tiny_pool_leg()

    positions = []
    for i in range(3):
        upgrade, leg_v = purchase_upgrade(
            leg["id"], journeys[i], passengers[i][1], "UPGRADED_BOARDING",
            expected_leg_version=leg_v)
        positions.append(upgrade["position_granted"])
    assert positions == [1, 2, 3], (
        "the third purchase succeeds because the pre-grant count 2 < 3")

    res = api.purchase_upgrade(
        leg["id"], {"journey_id": journeys[3],
                    "upgrade_type": "UPGRADED_BOARDING",
                    "expected_leg_version": leg_v}, passengers[3][1])
    err = validate_error(res, ApiErrorId.ERR_UPGRADE_SOLD_OUT)
    assert err["error_id"] == "ERR_UPGRADE_SOLD_OUT", (
        "the fourth purchase hits exact equality: count 3 < 3 is false")


def test_pool_grants_positions_in_purchase_order_until_the_cap(api):
    """PRD §3.5: "A successful purchase creates the `BoardingUpgrade` row
    with `upgrade_status` `ACTIVE`, computes `price_cents`, and — for
    `UPGRADED_BOARDING` — grants the next A-position, records it on the
    upgrade as `position_granted`, and bumps the parent leg's `version`."

    Design: Difficulty/boundary_precision_check/a1_a15_pool_exhaustion_at_capacity
    """
    _net, leg, passengers, journeys, leg_v = _tiny_pool_leg()

    upgrades = []
    for i in range(3):
        upgrade, leg_v = purchase_upgrade(
            leg["id"], journeys[i], passengers[i][1], "UPGRADED_BOARDING",
            expected_leg_version=leg_v)
        upgrades.append(upgrade)

    for i, upgrade in enumerate(upgrades):
        assert upgrade["position_granted"] == i + 1
        assert upgrade["upgrade_status"] == "ACTIVE"

    leg_now = validate_success(api.get_flight_leg(leg["id"], OPS), 200)
    assert leg_now["version"] >= leg_v, (
        "each granted purchase bumps the parent leg's version; the pool "
        "writes are serialized through it")

    res = api.purchase_upgrade(
        leg["id"], {"journey_id": journeys[3],
                    "upgrade_type": "UPGRADED_BOARDING",
                    "expected_leg_version": leg_v}, passengers[3][1])
    assert res.status_code == 409
    assert res.json()["data"]["error_id"] == "ERR_UPGRADE_SOLD_OUT"
