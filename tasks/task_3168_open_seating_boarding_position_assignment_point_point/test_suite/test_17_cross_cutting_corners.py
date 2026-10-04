"""Cross-cutting corners: optimistic concurrency, compound booking state, and
immediate consistency.

Covers Corner/cross_cutting_layers instances:
- occ_stale_leg_version_checkin
- occ_stale_credit_version_redeem
- cascading_side_effects_mixed_2_journey_booking_cancel

Covers Corner/consistency_model instances:
- immediate_visibility_of_checkin_assignment
"""
from test_helpers import (
    TEST_USERS, api_client, get_success_data, validate_error,
    validate_paginated, validate_success,
    ApiErrorId,
    book_journey, create_journey_payload, create_passenger, leg_check_in,
    set_clock, setup_basic_network, setup_credit_scenario,
)

OPS = TEST_USERS["ops_headers"]
GATE = TEST_USERS["gate_agent_headers"]


def test_checkin_with_a_stale_leg_version_is_rejected(api):
    """PRD §2.7: "The leg-scoped check-in write requires the request to carry
    `expected_leg_version`, the client-observed `version` of the parent
    `FlightLeg`. If the leg's version has advanced since the client read it —
    for example because a delay cascade or a retime recompute bumped the leg
    — the request is rejected with `ERR_STALE_VERSION` (HTTP 412). The client
    must re-read the leg, re-derive the boarding window, and resubmit against
    the current version."

    Design: Corner/cross_cutting_layers/occ_stale_leg_version_checkin
    """
    net = setup_basic_network()
    leg = net["leg"]
    set_clock("2026-09-30T12:00:00Z")
    p1, p1_h = create_passenger(full_name="P 1")
    p2, p2_h = create_passenger(full_name="P 2")
    _bk, j1 = book_journey(p1_h, p1["id"], leg["id"], net["fare"]["id"],
                           base_fare_cents=10000)
    _bk, j2 = book_journey(p2_h, p2["id"], leg["id"], net["fare"]["id"],
                           base_fare_cents=10000)

    # P2 checks in against the version both clients observed; P1's copy is
    # now stale.
    _j, _v = leg_check_in(leg["id"], j2, p2_h,
                          expected_leg_version=leg["version"])

    res = api.leg_check_in(
        leg["id"], {"journey_id": j1,
                    "expected_leg_version": leg["version"]}, p1_h)
    err = validate_error(res, ApiErrorId.ERR_STALE_VERSION)
    assert err["error_id"] == "ERR_STALE_VERSION"

    journey = validate_success(api.get_journey(j1, p1_h), 200)
    assert journey["journey_status"] == "BOOKED"
    assignments, meta = validate_paginated(
        api.list_journey_assignments(j1, p1_h))
    assert meta["total_count"] == 0


def test_redeem_with_a_stale_credit_version_is_rejected(api):
    """PRD §2.7: "Credit redemption requires `expected_credit_version`, the
    client-observed `version` of the parent `TravelCredit`. If a compensating
    void or another redemption has advanced the credit's version, the request
    is rejected with `ERR_STALE_VERSION` (HTTP 412), forcing the client to
    re-read the credit's current `remaining_amount_cents`."

    Design: Corner/cross_cutting_layers/occ_stale_credit_version_redeem
    """
    sc = setup_credit_scenario(source_fare_cents=20000, new_fare_cents=10000)
    p_h = sc["passenger_headers"]
    credit = sc["credit"]
    j_new = sc["j_new"]

    validate_success(api.redeem_credit(
        credit["id"], {"journey_id": j_new, "amount_cents": 5000,
                       "expected_credit_version": credit["version"]}, p_h),
        201)

    res = api.redeem_credit(
        credit["id"], {"journey_id": j_new, "amount_cents": 5000,
                       "expected_credit_version": credit["version"]}, p_h)
    err = validate_error(res, ApiErrorId.ERR_STALE_VERSION)
    assert err["error_id"] == "ERR_STALE_VERSION", (
        "the first redemption bumped the credit's version")

    credit_now = validate_success(api.get_credit(credit["id"], p_h), 200)
    assert credit_now["remaining_amount_cents"] == 15000, (
        "only the first redemption applied")


def test_booking_flips_to_cancelled_only_when_every_journey_is_terminal(api):
    """PRD §3.3: "The booking transitions to `CANCELLED` automatically when
    every journey under it has reached `CANCELLED` or `NO_SHOW`."

    Design: Corner/cross_cutting_layers/cascading_side_effects_mixed_2_journey_booking_cancel
    """
    net = setup_basic_network(fare_overrides={"change_fee_cents": 0})
    set_clock("2026-09-30T12:00:00Z")
    passenger, p_h = create_passenger(full_name="P A")
    booking = validate_success(api.create_booking(
        {"record_locator": "BK2C",
         "journeys": [
             create_journey_payload(passenger["id"], net["leg"]["id"],
                                    net["fare"]["id"], base_fare_cents=10000),
             create_journey_payload(passenger["id"], net["leg"]["id"],
                                    net["fare"]["id"], base_fare_cents=12000),
         ]}, p_h), 201)
    j_a, j_b = booking["journey_ids"]

    validate_success(api.cancel_journey(j_a, p_h), 200)
    mid = validate_success(api.get_booking(booking["id"], p_h), 200)
    assert mid["booking_status"] == "ACTIVE", (
        "one journey is still BOOKED, so the booking stays ACTIVE")

    validate_success(api.cancel_journey(j_b, p_h), 200)
    done = validate_success(api.get_booking(booking["id"], p_h), 200)
    assert done["booking_status"] == "CANCELLED", (
        "every journey is now CANCELLED, so the booking flips")


def test_checkin_assignment_is_visible_immediately(api):
    """PRD §3.4: "Successful check-in stamps `checked_in_at` from the logical
    clock, moves the journey to `CHECKED_IN`, bumps the parent leg's
    `version`, and creates a `BoardingAssignment` via the boarding position
    algorithm."

    PRD §2.10: "The platform's consistency model is immediate."

    Design: Corner/consistency_model/immediate_visibility_of_checkin_assignment
    """
    net = setup_basic_network()
    leg = net["leg"]
    set_clock("2026-09-30T12:00:00Z")
    passenger, p_h = create_passenger(full_name="P A")
    _bk, journey_id = book_journey(p_h, passenger["id"], leg["id"],
                                   net["fare"]["id"], base_fare_cents=10000)

    validate_success(api.leg_check_in(
        leg["id"], {"journey_id": journey_id,
                    "expected_leg_version": leg["version"]}, p_h), 201)

    assignments, meta = validate_paginated(
        api.list_journey_assignments(journey_id, p_h))
    assert meta["total_count"] == 1, (
        "the assignment is visible on the same request stream")
    assert assignments[0]["boarding_group"] == "A", (
        "the first regular passenger boards in group A")
    assert assignments[0]["assignment_source"] == "CHECKIN_TIME"

    journey = validate_success(api.get_journey(journey_id, p_h), 200)
    assert journey["journey_status"] == "CHECKED_IN"
    assert journey["checked_in_at"] == "2026-09-30T12:00:00.000Z", (
        "checked_in_at is stamped from the logical clock")
