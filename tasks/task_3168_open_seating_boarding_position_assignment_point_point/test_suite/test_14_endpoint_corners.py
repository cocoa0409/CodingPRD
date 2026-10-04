"""Endpoint corner tests: reverse-reachability reads and conditional actions.

Covers Corner/endpoints instances:
- fk_reverse_reachability_journeys_under_booking
- filtered_list_credits_by_passenger
- credit_void_with_active_redemption_blocked
"""
from test_helpers import (
    TEST_USERS, api_client, get_success_data, validate_error,
    validate_paginated, validate_success,
    ApiErrorId,
    book_journey, create_journey_payload, create_passenger, set_clock,
    setup_basic_network, setup_credit_scenario,
)

OPS = TEST_USERS["ops_headers"]
GATE = TEST_USERS["gate_agent_headers"]


def test_booking_journeys_reverse_read_returns_exactly_its_children(api):
    """PRD §3.3: "The booking's `booking_id` becomes the parent reference on
    each journey's `booking_id` field, and the booking list read under a
    booking accepts a `journey_status` filter."

    Design: Corner/endpoints/fk_reverse_reachability_journeys_under_booking
    """
    net = setup_basic_network()
    passenger, p_h = create_passenger(full_name="P A")
    booking = validate_success(api.create_booking(
        {"record_locator": "BKV",
         "journeys": [
             create_journey_payload(passenger["id"], net["leg"]["id"],
                                    net["fare"]["id"], base_fare_cents=10000),
             create_journey_payload(passenger["id"], net["leg"]["id"],
                                    net["fare"]["id"], base_fare_cents=12000),
         ]}, p_h), 201)

    journeys, meta = validate_paginated(
        api.list_booking_journeys(booking["id"], p_h))
    assert meta["total_count"] == 2
    assert all(j["booking_id"] == booking["id"] for j in journeys)
    assert {j["id"] for j in journeys} == set(booking["journey_ids"])


def test_credit_list_filters_by_passenger(api):
    """PRD §4 endpoint table row: "| GET | `/ops/credits` | List credits
    (filter by passenger, status, source journey) | Passenger, OpsController
    |".

    PRD §3.8: "A `TravelCredit` is minted with a `passenger_id` owner, a
    `source_journey_id` identifying the journey whose cancellation, no-show,
    or change produced it, an `initial_amount_cents` greater than zero, and a
    `remaining_amount_cents` that begins equal to the initial amount and is
    decremented by redemptions, never below zero."

    Design: Corner/endpoints/filtered_list_credits_by_passenger
    """
    net = setup_basic_network(fare_overrides={"change_fee_cents": 0})
    set_clock("2026-09-30T12:00:00Z")
    pa, pa_h = create_passenger(full_name="P A")
    pb, pb_h = create_passenger(full_name="P B")
    _bk, j_a = book_journey(pa_h, pa["id"], net["leg"]["id"],
                            net["fare"]["id"], base_fare_cents=10000)
    validate_success(api.cancel_journey(j_a, pa_h), 200)

    b_credits, b_meta = validate_paginated(
        api.list_credits(pb_h, params={"passenger_id": pb["id"]}))
    assert b_meta["total_count"] == 0, (
        "passenger B has no credits; A's credit never leaks")

    a_credits, a_meta = validate_paginated(
        api.list_credits(pa_h, params={"passenger_id": pa["id"]}))
    assert a_meta["total_count"] == 1
    assert a_credits[0]["remaining_amount_cents"] == 10000
    assert a_credits[0]["source_journey_id"] == j_a


def test_voiding_a_credit_with_an_active_redemption_is_rejected(api):
    """PRD §3.8: "An `OpsController` may claw back a credit by voiding it,
    but only when no `ACTIVE` redemptions exist against it; the credit moves
    to `VOID`."

    Design: Corner/endpoints/credit_void_with_active_redemption_blocked
    """
    sc = setup_credit_scenario(source_fare_cents=20000, new_fare_cents=10000)
    p_h = sc["passenger_headers"]
    credit = sc["credit"]

    validate_success(api.redeem_credit(
        credit["id"], {"journey_id": sc["j_new"], "amount_cents": 5000,
                       "expected_credit_version": credit["version"]}, p_h),
        201)

    res = api.void_credit(credit["id"], OPS)
    err = validate_error(res, ApiErrorId.ERR_INVALID_STATE)
    assert err["error_id"] == "ERR_INVALID_STATE", (
        "an ACTIVE redemption blocks the admin clawback")

    credit_now = validate_success(api.get_credit(credit["id"], p_h), 200)
    assert credit_now["credit_status"] == "PARTIALLY_REDEEMED"
    assert credit_now["remaining_amount_cents"] == 15000
