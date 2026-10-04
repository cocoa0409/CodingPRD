"""Validation corner tests: windows, duplicates, floors, expiry, and fees.

Covers Corner/validations instances:
- checkin_window_too_early_rejected
- early_bird_cutoff_enforced
- duplicate_upgrade_same_type_rejected
- fare_inactive_rejects_new_booking
- delay_below_floor_rejected
- credit_expired_redeem_rejected
- upgrade_not_refundable_early_bird
- routing_chain_broken_station_mismatch
- bag_limit_ten_cap
- change_non_flexible_fee_unpaid
"""
from test_helpers import (
    TEST_USERS, api_client, get_success_data, validate_error,
    validate_paginated, validate_success,
    ApiErrorId,
    book_journey, check_in_journey, create_aircraft, create_fare_class,
    create_leg, create_passenger, create_station, leg_check_in,
    purchase_upgrade, set_clock, setup_basic_network,
    setup_checked_in_journey, setup_credit_scenario,
)

OPS = TEST_USERS["ops_headers"]
GATE = TEST_USERS["gate_agent_headers"]


def test_checkin_before_the_window_opens_is_rejected(api):
    """PRD §3.4: "Both paths require that the acting passenger own the
    journey (else `ERR_FORBIDDEN`), that the journey currently be in `BOOKED`
    (else `ERR_INVALID_STATE`, HTTP 409), that the leg be in `SCHEDULED` or
    `DELAYED`, and that the logical clock sit inside the check-in window: no
    earlier than 24 hours before the scheduled departure, and no later than
    30 minutes before it, with both bounds shifted by any posted
    `delay_minutes`. Outside the window the request is rejected with
    `ERR_CHECKIN_WINDOW_CLOSED` (HTTP 409)."

    Design: Corner/validations/checkin_window_too_early_rejected
    """
    net = setup_basic_network()
    leg = net["leg"]
    set_clock("2026-09-30T11:59:00Z")  # STD - 24h - 1min
    passenger, p_h = create_passenger(full_name="P A")
    _bk, journey_id = book_journey(p_h, passenger["id"], leg["id"],
                                   net["fare"]["id"], base_fare_cents=10000)

    res = api.leg_check_in(
        leg["id"], {"journey_id": journey_id,
                    "expected_leg_version": leg["version"]}, p_h)
    err = validate_error(res, ApiErrorId.ERR_CHECKIN_WINDOW_CLOSED)
    assert err["error_id"] == "ERR_CHECKIN_WINDOW_CLOSED"

    journey = validate_success(api.get_journey(journey_id, p_h), 200)
    assert journey["journey_status"] == "BOOKED"
    assignments, meta = validate_paginated(
        api.list_journey_assignments(journey_id, p_h))
    assert meta["total_count"] == 0


def test_early_bird_cutoff_is_enforced_asymmetrically(api):
    """PRD §3.5: "`EARLY_BIRD` is the auto-check-in product and may be
    purchased only while the logical clock is still at least 36 hours before
    scheduled departure. `UPGRADED_BOARDING` is the day-of-travel A1-A15
    purchase and may be purchased only once the logical clock has reached 24
    hours before scheduled departure. A purchase outside its window is
    rejected with `ERR_UPGRADE_WINDOW_CLOSED` (HTTP 409)."

    Design: Corner/validations/early_bird_cutoff_enforced
    """
    net = setup_basic_network()
    leg = net["leg"]
    set_clock("2026-09-29T23:00:00Z")  # STD - 37h
    p1, p1_h = create_passenger(full_name="P 1")
    p2, p2_h = create_passenger(full_name="P 2")
    _bk, j1 = book_journey(p1_h, p1["id"], leg["id"], net["fare"]["id"],
                           base_fare_cents=10000)
    _bk, j2 = book_journey(p2_h, p2["id"], leg["id"], net["fare"]["id"],
                           base_fare_cents=10000)

    # P2 buys at STD-37h: inside the window.
    eb, leg_v = purchase_upgrade(leg["id"], j2, p2_h, "EARLY_BIRD",
                                 expected_leg_version=leg["version"])
    assert eb["upgrade_type"] == "EARLY_BIRD"

    # P1 buys at STD-35h: past the cutoff.
    set_clock("2026-09-30T01:00:00Z")
    res = api.purchase_upgrade(
        leg["id"], {"journey_id": j1, "upgrade_type": "EARLY_BIRD",
                    "expected_leg_version": leg_v}, p1_h)
    err = validate_error(res, ApiErrorId.ERR_UPGRADE_WINDOW_CLOSED)
    assert err["error_id"] == "ERR_UPGRADE_WINDOW_CLOSED"


def test_second_upgrade_of_the_same_type_is_rejected(api):
    """PRD §3.5: "A journey may hold at most one `ACTIVE` upgrade of each
    type; a second purchase of the same type is rejected with
    `ERR_DUPLICATE_UPGRADE` (HTTP 409)."

    Design: Corner/validations/duplicate_upgrade_same_type_rejected
    """
    fx = setup_checked_in_journey(
        fare_overrides={"change_fee_cents": 0, "included_bags": 2})
    leg = fx["leg"]
    journey_id = fx["journey_id"]
    p_h = fx["passenger_headers"]

    fresh_leg = validate_success(api.get_flight_leg(leg["id"], OPS), 200)
    _upgrade, leg_v = purchase_upgrade(leg["id"], journey_id, p_h,
                                       "UPGRADED_BOARDING",
                                       expected_leg_version=fresh_leg["version"])

    res = api.purchase_upgrade(
        leg["id"], {"journey_id": journey_id,
                    "upgrade_type": "UPGRADED_BOARDING",
                    "expected_leg_version": leg_v}, p_h)
    err = validate_error(res, ApiErrorId.ERR_DUPLICATE_UPGRADE)
    assert err["error_id"] == "ERR_DUPLICATE_UPGRADE"

    upgrades, meta = validate_paginated(
        api.list_journey_upgrades(journey_id, p_h,
                                  params={"upgrade_status": "ACTIVE"}))
    assert meta["total_count"] == 1


def test_booking_on_an_inactive_fare_class_is_rejected(api):
    """PRD §3.1: "An inactive fare class rejects new bookings with
    `ERR_FARE_INACTIVE` (HTTP 422); journeys already booked on it are
    unaffected."

    Design: Corner/validations/fare_inactive_rejects_new_booking
    """
    net = setup_basic_network(fare_overrides={"code": "DEAD",
                                              "is_active": False})
    passenger, p_h = create_passenger(full_name="P A")

    res = api.create_booking(
        {"record_locator": "BKF",
         "journeys": [{"passenger_id": passenger["id"],
                       "flight_leg_id": net["leg"]["id"],
                       "fare_class_id": net["fare"]["id"],
                       "base_fare_cents": 10000}]}, p_h)
    err = validate_error(res, ApiErrorId.ERR_FARE_INACTIVE)
    assert err["error_id"] == "ERR_FARE_INACTIVE"


def test_a_delay_below_the_floor_is_rejected(api):
    """PRD §3.7: "The posted delay must be at least 15 minutes (the
    `DELAY_FLOOR_MINUTES` floor); anything shorter is rejected with
    `ERR_DELAY_BELOW_FLOOR` (HTTP 422)."

    Design: Corner/validations/delay_below_floor_rejected
    """
    station_dal = create_station(iata_code="DAL")
    station_hou = create_station(iata_code="HOU")
    leg = create_leg(station_dal["id"], station_hou["id"], capacity_seats=143)

    res = api.post_disruption(
        leg["id"], {"disruption_type": "DELAY", "cause": "WEATHER",
                    "delay_minutes": 14}, OPS)
    err = validate_error(res, ApiErrorId.ERR_DELAY_BELOW_FLOOR)
    assert err["error_id"] == "ERR_DELAY_BELOW_FLOOR"

    leg_now = validate_success(api.get_flight_leg(leg["id"], OPS), 200)
    assert leg_now["leg_status"] == "SCHEDULED"
    assert leg_now["delay_minutes"] == 0


def test_redeeming_an_expired_credit_is_rejected(api):
    """PRD §3.8: "Separately, if the logical date has passed `expires_on`,
    the redemption is rejected with `ERR_CREDIT_EXPIRED` (HTTP 410)."

    PRD §2.4: "Advancing the clock has one automatic side effect: every
    `TravelCredit` whose `credit_status` is `OPEN` or `PARTIALLY_REDEEMED`
    and whose `expires_on` is strictly earlier than the new logical date
    transitions to `EXPIRED`, and its remaining balance is forfeited."

    Design: Corner/validations/credit_expired_redeem_rejected
    """
    sc = setup_credit_scenario(source_fare_cents=10000, new_fare_cents=9000,
                               credit_validity_days=30)
    p_h = sc["passenger_headers"]
    credit = sc["credit"]
    assert credit["expires_on"] == "2026-10-31", (
        "service date 2026-10-01 plus 30 credit_validity_days")

    set_clock("2026-11-01T00:00:00Z")
    expired = validate_success(api.get_credit(credit["id"], p_h), 200)
    assert expired["credit_status"] == "EXPIRED", (
        "the clock-set sweep has already flipped the credit")

    res = api.redeem_credit(
        credit["id"], {"journey_id": sc["j_new"], "amount_cents": 5000,
                       "expected_credit_version": expired["version"]}, p_h)
    assert res.status_code == 410
    error_id = res.json()["data"]["error_id"]
    assert error_id in ("ERR_CREDIT_EXPIRED", "ERR_CREDIT_EXHAUSTED"), (
        "the credit is expired and therefore not redeemable")


def test_early_bird_is_never_refundable(api):
    """PRD §3.5: "A passenger may refund an `UPGRADED_BOARDING` upgrade on
    their own journey, but only while boarding has not yet opened on the
    leg; `EARLY_BIRD` is never refundable. A refund request against
    `EARLY_BIRD`, or after boarding has opened, is rejected with
    `ERR_UPGRADE_NOT_REFUNDABLE` (HTTP 422)."

    Design: Corner/validations/upgrade_not_refundable_early_bird
    """
    net = setup_basic_network()
    leg = net["leg"]
    set_clock("2026-09-29T20:00:00Z")  # STD - 40h, inside the EB window
    passenger, p_h = create_passenger(full_name="P 1")
    _bk, journey_id = book_journey(p_h, passenger["id"], leg["id"],
                                   net["fare"]["id"], base_fare_cents=10000)
    upgrade, _v = purchase_upgrade(leg["id"], journey_id, p_h, "EARLY_BIRD",
                                   expected_leg_version=leg["version"])

    res = api.refund_upgrade(upgrade["id"], p_h)
    err = validate_error(res, ApiErrorId.ERR_UPGRADE_NOT_REFUNDABLE)
    assert err["error_id"] == "ERR_UPGRADE_NOT_REFUNDABLE"

    upgrade_now = validate_success(api.get_upgrade(upgrade["id"], p_h), 200)
    assert upgrade_now["upgrade_status"] == "ACTIVE"


def test_routing_legs_must_share_a_station(api):
    """PRD §3.2: "Creation validates, in this relative order: fleet
    homogeneity (`ERR_FLEET_HETEROGENEITY`), then the chain rule that
    consecutive legs share a station — the destination of the earlier leg
    equals the origin of the next — and that each leg's arrival precedes the
    next leg's departure (`ERR_ROUTING_CHAIN_BROKEN`)".

    Design: Corner/validations/routing_chain_broken_station_mismatch
    """
    set_clock("2026-09-30T12:00:00Z")
    station_dal = create_station(iata_code="DAL")
    station_hou = create_station(iata_code="HOU")
    station_aus = create_station(iata_code="AUS")
    aircraft = create_aircraft(tail_number="N100", seat_count=143)
    l1 = create_leg(station_dal["id"], station_hou["id"],
                    scheduled_departure_utc="2026-10-01T12:00:00Z",
                    scheduled_arrival_utc="2026-10-01T13:00:00Z",
                    capacity_seats=143)
    l2 = create_leg(station_aus["id"], station_dal["id"],
                    scheduled_departure_utc="2026-10-01T14:00:00Z",
                    scheduled_arrival_utc="2026-10-01T15:00:00Z",
                    capacity_seats=143)

    res = api.create_routing(
        {"routing_date": "2026-10-01", "aircraft_id": aircraft["id"],
         "leg_ids": [l1["id"], l2["id"]]}, OPS)
    err = validate_error(res, ApiErrorId.ERR_ROUTING_CHAIN_BROKEN)
    assert err["error_id"] == "ERR_ROUTING_CHAIN_BROKEN", (
        "L1 arrives at HOU but L2 departs from AUS: the chain is broken")


def test_the_eleventh_bag_exceeds_the_per_journey_cap(api):
    """PRD §3.6: "A per-journey cap of `MAX_BAGS_PER_JOURNEY` — 10 bags —
    applies: if the journey already holds 10 bags in `ACCEPTED` or `LOADED`
    status, the next acceptance is rejected with `ERR_BAG_LIMIT_EXCEEDED`
    (HTTP 409); the comparison runs against the pre-acceptance count."

    Design: Corner/validations/bag_limit_ten_cap
    """
    fx = setup_checked_in_journey(
        fare_overrides={"change_fee_cents": 0, "included_bags": 2})
    journey_id = fx["journey_id"]

    bags = []
    for _ in range(10):
        bags.append(validate_success(
            api.check_bag(journey_id, {"weight_lbs": 10}, GATE), 201))
    for bag in bags[2:]:
        assert bag["bag_fee_cents"] == 7500, (
            "bags 3..10 are beyond the included allotment of 2")

    res = api.check_bag(journey_id, {"weight_lbs": 10}, GATE)
    err = validate_error(res, ApiErrorId.ERR_BAG_LIMIT_EXCEEDED)
    assert err["error_id"] == "ERR_BAG_LIMIT_EXCEEDED", (
        "the 11th bag is rejected against the pre-acceptance count of 10")


def test_changing_a_non_flexible_fare_without_the_fee_is_rejected(api):
    """PRD §3.9: "Non-flexible fares require the change fee to be payable; a
    change attempted without satisfying the fee is rejected with
    `ERR_CHANGE_FEE_UNPAID` (HTTP 422), and on a non-flexible fare a
    downgrade residual — the difference when the new fare is lower than the
    old — is forfeited rather than credited."

    Design: Corner/validations/change_non_flexible_fee_unpaid
    """
    net = setup_basic_network(
        fare_overrides={"code": "WGA", "change_fee_cents": 5000})
    set_clock("2026-09-30T12:00:00Z")
    leg2 = create_leg(net["station_dal"]["id"], net["station_hou"]["id"],
                      scheduled_departure_utc="2026-10-02T12:00:00Z",
                      scheduled_arrival_utc="2026-10-02T13:00:00Z",
                      capacity_seats=143)
    passenger, p_h = create_passenger(full_name="P A")
    _bk, journey_id = book_journey(p_h, passenger["id"], net["leg"]["id"],
                                   net["fare"]["id"], base_fare_cents=10000)

    res = api.change_journey(
        journey_id, {"new_flight_leg_id": leg2["id"],
                     "new_fare_class_id": net["fare"]["id"],
                     "new_base_fare_cents": 10000}, p_h)
    err = validate_error(res, ApiErrorId.ERR_CHANGE_FEE_UNPAID)
    assert err["error_id"] == "ERR_CHANGE_FEE_UNPAID"

    journey = validate_success(api.get_journey(journey_id, p_h), 200)
    assert journey["journey_status"] == "BOOKED"
    assert journey["flight_leg_id"] == net["leg"]["id"], (
        "the rejected change leaves the journey on its original leg")
