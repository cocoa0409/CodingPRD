"""State-machine corner tests: terminal lockdowns, invalid transitions, and
the family-accommodation side effect.

Covers Corner/state_machines instances:
- flight_leg_arrived_terminal_lockdown
- bag_load_only_from_accepted
- journey_initial_state_is_booked
- upgrade_refund_from_refunded_rejected
- family_min_pair_consecutive_positions
- preboard_accommodation_requires_eligible_fare
"""
from test_helpers import (
    TEST_USERS, api_client, get_success_data, validate_error,
    validate_paginated, validate_success,
    ApiErrorId,
    book_journey, check_in_journey, create_aircraft, create_fare_class,
    create_leg, create_passenger, create_station, fly_leg, leg_check_in,
    purchase_upgrade, set_clock, setup_basic_network, setup_flyable_leg,
)

OPS = TEST_USERS["ops_headers"]
GATE = TEST_USERS["gate_agent_headers"]


def test_arrived_leg_rejects_a_further_disruption(api):
    """PRD §3.6: "`ARRIVED` and `CANCELLED` are the terminal states of a
    leg."

    Design: Corner/state_machines/flight_leg_arrived_terminal_lockdown
    """
    fx = setup_flyable_leg()
    leg = fx["leg"]
    fly_leg(leg["id"])

    leg_now = validate_success(api.get_flight_leg(leg["id"], OPS), 200)
    assert leg_now["leg_status"] == "ARRIVED"

    res = api.post_disruption(
        leg["id"], {"disruption_type": "DELAY", "cause": "WEATHER",
                    "delay_minutes": 30}, OPS)
    err = validate_error(res, ApiErrorId.ERR_INVALID_STATE)
    assert err["error_id"] == "ERR_INVALID_STATE", (
        "a terminal leg accepts no further transitions")

    leg_after = validate_success(api.get_flight_leg(leg["id"], OPS), 200)
    assert leg_after["leg_status"] == "ARRIVED"


def test_offloading_a_loaded_bag_is_rejected(api):
    """PRD §3.6: "A `GateAgent` may offload an accepted bag before the leg
    has departed, moving it to `OFFLOADED`; a manual offload against a leg
    that has already departed is rejected."

    PRD §3.6: "Bags also follow the leg's lifecycle automatically: at
    departure every `ACCEPTED` bag on the leg moves to `LOADED`; at arrival
    every `LOADED` bag moves to `DELIVERED`; on cancellation every `ACCEPTED`
    bag moves to `OFFLOADED`."

    Design: Corner/state_machines/bag_load_only_from_accepted
    """
    fx = setup_flyable_leg()
    leg = fx["leg"]
    set_clock("2026-09-30T12:00:00Z")
    passenger, p_h = create_passenger(full_name="P A")
    _bk, journey_id = book_journey(p_h, passenger["id"], leg["id"],
                                   fx["fare"]["id"], base_fare_cents=10000)
    check_in_journey(journey_id, p_h)
    bag = validate_success(api.check_bag(journey_id, {"weight_lbs": 30},
                                         GATE), 201)
    validate_success(api.scan_boarding(journey_id, GATE), 200)
    set_clock("2026-10-01T12:00:00Z")
    validate_success(api.depart_leg(leg["id"], GATE), 200)

    bag_now = validate_success(api.get_bag(bag["id"], GATE), 200)
    assert bag_now["bag_status"] == "LOADED"

    res = api.offload_bag(bag["id"], GATE)
    err = validate_error(res, ApiErrorId.ERR_INVALID_STATE)
    assert err["error_id"] == "ERR_INVALID_STATE", (
        "OFFLOADED is reachable only from ACCEPTED, and the leg has departed")

    bag_after = validate_success(api.get_bag(bag["id"], GATE), 200)
    assert bag_after["bag_status"] == "LOADED"


def test_a_new_journey_is_booked_with_no_assignment(api):
    """PRD §3.3: "Journeys are born with `journey_status` `BOOKED` and
    `accommodation` `NONE`, and the parent booking begins with
    `booking_status` `ACTIVE`, with its `journey_count` and `journey_ids`
    derived from the journeys under it, ordered by journey creation time
    ascending."

    Design: Corner/state_machines/journey_initial_state_is_booked
    """
    net = setup_basic_network()
    passenger, p_h = create_passenger(full_name="P A")
    _booking, journey_id = book_journey(p_h, passenger["id"],
                                        net["leg"]["id"], net["fare"]["id"],
                                        base_fare_cents=10000)

    journey = validate_success(api.get_journey(journey_id, p_h), 200)
    assert journey["journey_status"] == "BOOKED"
    assert journey["accommodation"] == "NONE"

    assignments, meta = validate_paginated(
        api.list_journey_assignments(journey_id, p_h))
    assert meta["total_count"] == 0, (
        "no boarding assignment exists until check-in")


def _journey_with_active_upgraded_boarding():
    """Checked-in journey holding one ACTIVE UPGRADED_BOARDING (position 1)."""
    net = setup_basic_network(fare_overrides={"change_fee_cents": 0,
                                              "included_bags": 2})
    leg = net["leg"]
    set_clock("2026-09-30T12:00:00Z")
    passenger, p_h = create_passenger(full_name="P 1")
    _bk, journey_id = book_journey(p_h, passenger["id"], leg["id"],
                                   net["fare"]["id"], base_fare_cents=10000)
    _j, leg_v = leg_check_in(leg["id"], journey_id, p_h,
                             expected_leg_version=leg["version"])
    upgrade, _v = purchase_upgrade(leg["id"], journey_id, p_h,
                                   "UPGRADED_BOARDING",
                                   expected_leg_version=leg_v)
    return upgrade, p_h


def test_refunding_an_already_refunded_upgrade_is_rejected(api):
    """PRD §3.5: "A successful refund moves the upgrade to `REFUNDED`, voids
    the granted assignment with `release_reason` `UPGRADE`, and reverts the
    journey's boarding assignment to its original `CHECKIN_TIME` position,
    re-issued with `assignment_source` `CHECKIN_TIME` (a retime-sourced
    position is not reused here)."

    Design: Corner/state_machines/upgrade_refund_from_refunded_rejected
    """
    upgrade, p_h = _journey_with_active_upgraded_boarding()
    validate_success(api.refund_upgrade(upgrade["id"], p_h), 200)

    res = api.refund_upgrade(upgrade["id"], p_h)
    err = validate_error(res, ApiErrorId.ERR_INVALID_STATE)
    assert err["error_id"] == "ERR_INVALID_STATE", (
        "REFUNDED is terminal: a second refund is a state precondition "
        "failure")

    upgrade_now = validate_success(api.get_upgrade(upgrade["id"], p_h), 200)
    assert upgrade_now["upgrade_status"] == "REFUNDED"


def _family_pair_leg(api):
    """Child anchor + accompanying adult + one regular passenger, checked
    in with the regular passenger between the two family members in
    time."""
    net = setup_basic_network(fare_overrides={"change_fee_cents": 0,
                                              "included_bags": 2})
    leg = net["leg"]
    set_clock("2026-09-30T12:00:00Z")
    kid, kid_h = create_passenger(full_name="Kid C",
                                  date_of_birth="2022-06-01")
    adult, adult_h = create_passenger(full_name="Adult A",
                                      date_of_birth="1990-01-01",
                                      is_min_eligible=True)
    norm, norm_h = create_passenger(full_name="Norm N",
                                    date_of_birth="1985-01-01")

    # PRD §3.3: the family accommodation is expressed by the accompanying
    # adult journey pointing at the child journey via
    # `family_anchor_journey_id`; the child is the anchor passenger (under 6
    # on the flight date) and the adult carries `is_min_eligible` true.
    booking = validate_success(api.create_booking(
        {"record_locator": "BKFAM",
         "journeys": [
             {"passenger_id": kid["id"], "flight_leg_id": leg["id"],
              "fare_class_id": net["fare"]["id"], "base_fare_cents": 8000},
             {"passenger_id": adult["id"], "flight_leg_id": leg["id"],
              "fare_class_id": net["fare"]["id"], "base_fare_cents": 12000,
              "family_anchor_journey_id": 0},
         ]}, adult_h), 201)
    j_kid, j_adult = booking["journey_ids"][0], booking["journey_ids"][1]

    _bk, j_norm = book_journey(norm_h, norm["id"], leg["id"],
                               net["fare"]["id"], base_fare_cents=10000)

    set_clock("2026-09-30T12:00:00Z")
    check_in_journey(j_kid, kid_h)
    set_clock("2026-09-30T12:05:00Z")
    check_in_journey(j_norm, norm_h)
    set_clock("2026-09-30T12:10:00Z")
    check_in_journey(j_adult, adult_h)
    return leg, j_kid, j_adult, j_norm


def test_min_pair_receives_consecutive_family_positions(api):
    """PRD §3.4: "A MIN pair — the child anchor and the accompanying adult —
    receives **consecutive** positions: the pair takes the position of
    whichever member sorts earlier by `checked_in_at` then `created_at`, and
    the trailing member is shifted so the two stay adjacent."

    PRD §3.4: "**Phase 5 — FAMILY.** Journeys with `accommodation` `FAMILY`,
    plus the child-and-adult pairs participating in the family accommodation,
    are placed in group `FAMILY`, which sits between A and B in the boarding
    sequence."

    Design: Corner/state_machines/family_min_pair_consecutive_positions
    """
    leg, j_kid, j_adult, j_norm = _family_pair_leg(api)

    assignments, _meta = validate_paginated(
        api.list_leg_boarding_assignments(leg["id"], GATE))
    assert len(assignments) == 3
    groups = [a["boarding_group"] for a in assignments]
    assert groups[0] == "A", "the only regular passenger boards in group A"
    assert groups[1:] == ["FAMILY", "FAMILY"], (
        "FAMILY sits between A and B in the boarding sequence")

    family_rows = assignments[1:]
    assert family_rows[0]["journey_id"] == j_kid, (
        "the earlier-sorted member anchors the pair")
    assert family_rows[1]["journey_id"] == j_adult
    assert (family_rows[1]["boarding_position"]
            == family_rows[0]["boarding_position"] + 1), (
        "MIN adult+child positions are consecutive even though the adult "
        "checked in ten minutes after the child")


def test_booking_preboard_on_a_non_eligible_fare_is_rejected(api):
    """PRD §3.3: "A journey may carry `accommodation` `PREBOARD` only when
    its fare class is `preboard_eligible`; otherwise creation is rejected
    with `ERR_PREBOARD_NOT_ELIGIBLE` (HTTP 422)."

    Design: Corner/state_machines/preboard_accommodation_requires_eligible_fare
    """
    net = setup_basic_network(fare_overrides={"preboard_eligible": False})
    passenger, p_h = create_passenger(full_name="P A")

    res = api.create_booking(
        {"record_locator": "BKPB",
         "journeys": [{"passenger_id": passenger["id"],
                       "flight_leg_id": net["leg"]["id"],
                       "fare_class_id": net["fare"]["id"],
                       "base_fare_cents": 10000,
                       "accommodation": "PREBOARD"}]}, p_h)
    err = validate_error(res, ApiErrorId.ERR_PREBOARD_NOT_ELIGIBLE)
    assert err["error_id"] == "ERR_PREBOARD_NOT_ELIGIBLE"
