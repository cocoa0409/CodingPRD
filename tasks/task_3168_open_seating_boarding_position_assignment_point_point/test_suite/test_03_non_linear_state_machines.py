"""Non-linear state machines: FlightLeg delay re-entry and credit self-loop.

Covers Difficulty/non_linear_state_machine instances:
- flight_leg_delay_cycle_retime
- travel_credit_partial_redeem_cycle
"""
from test_helpers import (
    TEST_USERS, api_client, get_success_data, validate_error,
    validate_paginated, validate_success,
    ApiErrorId,
    book_journey, create_aircraft, create_fare_class, create_leg,
    create_passenger, create_station, leg_check_in, set_clock,
    setup_credit_scenario,
)

OPS = TEST_USERS["ops_headers"]
GATE = TEST_USERS["gate_agent_headers"]


def _delay_cycle_leg():
    """Leg with a PREBOARD journey and a regular journey both CHECKED_IN."""
    station_dal = create_station(iata_code="DAL")
    station_hou = create_station(iata_code="HOU")
    fc_pre = create_fare_class(code="PRE", change_fee_cents=0,
                               preboard_eligible=True, included_bags=2)
    fc_flex = create_fare_class(code="FLEX", change_fee_cents=0,
                                included_bags=2)
    create_aircraft(tail_number="N100", seat_count=143)
    leg = create_leg(station_dal["id"], station_hou["id"], capacity_seats=143)
    leg_v = leg["version"]
    set_clock("2026-09-30T12:00:00Z")

    p_pre, pre_h = create_passenger(full_name="P PRE")
    p_n1, n1_h = create_passenger(full_name="P N1")
    _bk, j_pre = book_journey(pre_h, p_pre["id"], leg["id"], fc_pre["id"],
                              base_fare_cents=10000,
                              accommodation="PREBOARD")
    _bk, j_n1 = book_journey(n1_h, p_n1["id"], leg["id"], fc_flex["id"],
                             base_fare_cents=10000)
    _j, leg_v = leg_check_in(leg["id"], j_pre, pre_h,
                             expected_leg_version=leg_v)
    _j, leg_v = leg_check_in(leg["id"], j_n1, n1_h,
                             expected_leg_version=leg_v)
    return leg, j_pre, j_n1, pre_h, n1_h


def test_first_delay_below_the_retime_threshold_leaves_assignments_alone(api):
    """PRD §3.7: "When the posted `delay_minutes` reaches at least 45 minutes
    — the `RETIME_THRESHOLD_MINUTES` — the boarding position algorithm
    re-runs against the delayed boarding start."

    PRD §3.7: "A `DELAY` post against a `SCHEDULED` leg moves it to `DELAYED`,
    records `delay_minutes` and `delay_cause`, and marks `delay_propagated`
    false (this is a directly-posted event, with `propagation_depth` zero on
    the `DisruptionEvent`)."

    Design: Difficulty/non_linear_state_machine/flight_leg_delay_cycle_retime
    """
    leg, j_pre, j_n1, pre_h, n1_h = _delay_cycle_leg()

    validate_success(api.post_disruption(
        leg["id"], {"disruption_type": "DELAY", "cause": "WEATHER",
                    "delay_minutes": 30}, OPS), 201)

    leg_now = validate_success(api.get_flight_leg(leg["id"], OPS), 200)
    assert leg_now["leg_status"] == "DELAYED"
    assert leg_now["delay_minutes"] == 30
    assert leg_now["delay_propagated"] is False

    assignments, _meta = validate_paginated(
        api.list_journey_assignments(j_n1, n1_h))
    assert assignments[0]["assignment_source"] == "CHECKIN_TIME", (
        "a 30-minute delay is below the 45-minute retime threshold, so the "
        "assignment is not recomputed")


def test_second_strictly_greater_delay_retimes_non_accommodation_rows(api):
    """PRD §3.7: "Phases 2 through 4 are recomputed: the A1-A15 pool, the
    status-priority block, and the regular check-in-time population are
    re-positioned, and the new rows are stamped with `assignment_source`
    `RETIME` while the previous rows move to `RETIMED`. Accommodation rows
    are never recomputed: `PREBOARD` and `FAMILY` assignments are preserved
    unchanged through a retime."

    PRD §3.7: "A subsequent `DELAY` post against an already-`DELAYED` leg is
    allowed only when the new `delay_minutes` is strictly greater than the
    current value; an equal or smaller post is rejected with
    `ERR_DELAY_BELOW_FLOOR`."

    Design: Difficulty/non_linear_state_machine/flight_leg_delay_cycle_retime
    """
    leg, j_pre, j_n1, pre_h, n1_h = _delay_cycle_leg()

    validate_success(api.post_disruption(
        leg["id"], {"disruption_type": "DELAY", "cause": "WEATHER",
                    "delay_minutes": 30}, OPS), 201)
    validate_success(api.post_disruption(
        leg["id"], {"disruption_type": "DELAY", "cause": "WEATHER",
                    "delay_minutes": 60}, OPS), 201)

    leg_now = validate_success(api.get_flight_leg(leg["id"], OPS), 200)
    assert leg_now["leg_status"] == "DELAYED"
    assert leg_now["delay_minutes"] == 60, (
        "DELAYED-to-DELAYED re-entry requires a strictly greater delay")

    n1_rows, _meta = validate_paginated(
        api.list_journey_assignments(j_n1, n1_h))
    assert n1_rows[0]["assignment_source"] == "RETIME", (
        "history is ordered created_at descending: the reissued row is first")
    assert n1_rows[0]["assignment_status"] == "ACTIVE"
    statuses = {r["assignment_status"] for r in n1_rows}
    assert "RETIMED" in statuses, "the prior row moved to RETIMED"

    pre_rows, _meta = validate_paginated(
        api.list_journey_assignments(j_pre, pre_h))
    assert len(pre_rows) == 1, "the PREBOARD row is never recomputed"
    assert pre_rows[0]["boarding_group"] == "PREBOARD"
    assert pre_rows[0]["assignment_source"] == "PREBOARD_ACCOMMODATION"
    assert pre_rows[0]["assignment_status"] == "ACTIVE"


def test_credit_self_loop_and_compensating_back_edge(api):
    """PRD §3.8: "The credit's status tracks the balance: a redemption that
    leaves a positive remainder moves `OPEN` to `PARTIALLY_REDEEMED` (or
    keeps it there), while a redemption that exactly consumes the remaining
    balance moves the credit to `REDEEMED`."

    PRD §3.8: "When a journey change or cancellation voids an `ACTIVE`
    redemption, the redemption moves to `VOIDED` and the source credit's
    `remaining_amount_cents` is restored by the redemption amount, returning
    a `PARTIALLY_REDEEMED` credit to `OPEN` when the restoration covers all
    prior redemptions."

    Design: Difficulty/non_linear_state_machine/travel_credit_partial_redeem_cycle
    """
    sc = setup_credit_scenario(source_fare_cents=20000, new_fare_cents=10000)
    p_h = sc["passenger_headers"]
    credit = sc["credit"]
    j_new = sc["j_new"]

    v = credit["version"]
    r1 = validate_success(api.redeem_credit(
        credit["id"], {"journey_id": j_new, "amount_cents": 5000,
                       "expected_credit_version": v}, p_h), 201)
    assert r1["redemption_status"] == "ACTIVE"

    mid = validate_success(api.get_credit(credit["id"], p_h), 200)
    assert mid["credit_status"] == "PARTIALLY_REDEEMED"
    assert mid["remaining_amount_cents"] == 15000

    r2 = validate_success(api.redeem_credit(
        credit["id"], {"journey_id": j_new, "amount_cents": 5000,
                       "expected_credit_version": mid["version"]}, p_h), 201)
    after_second = validate_success(api.get_credit(credit["id"], p_h), 200)
    assert after_second["credit_status"] == "PARTIALLY_REDEEMED", (
        "a positive-remainder redemption keeps the credit PARTIALLY_REDEEMED")
    assert after_second["remaining_amount_cents"] == 10000

    validate_success(api.change_journey(
        j_new, {"new_flight_leg_id": sc["leg2"]["id"],
                "new_fare_class_id": sc["fare"]["id"],
                "new_base_fare_cents": 10000}, p_h), 200)

    restored = validate_success(api.get_credit(credit["id"], p_h), 200)
    assert restored["credit_status"] == "OPEN", (
        "the compensation back-edge returns the credit to OPEN")
    assert restored["remaining_amount_cents"] == 20000

    redemptions, _meta = validate_paginated(
        api.list_credit_redemptions(credit["id"], p_h))
    assert all(r["redemption_status"] == "VOIDED" for r in redemptions), (
        "the change voided every ACTIVE redemption on the journey")


def test_exact_redemption_consumes_the_credit_fully(api):
    """PRD §3.8: "The credit's status tracks the balance: a redemption that
    leaves a positive remainder moves `OPEN` to `PARTIALLY_REDEEMED` (or
    keeps it there), while a redemption that exactly consumes the remaining
    balance moves the credit to `REDEEMED`."

    Design: Difficulty/non_linear_state_machine/travel_credit_partial_redeem_cycle
    """
    sc = setup_credit_scenario(source_fare_cents=20000, new_fare_cents=10000)
    p_h = sc["passenger_headers"]
    credit = sc["credit"]

    validate_success(api.redeem_credit(
        credit["id"], {"journey_id": sc["j_new"], "amount_cents": 10000,
                       "expected_credit_version": credit["version"]}, p_h),
        201)
    mid = validate_success(api.get_credit(credit["id"], p_h), 200)
    assert mid["credit_status"] == "PARTIALLY_REDEEMED"
    assert mid["remaining_amount_cents"] == 10000

    validate_success(api.redeem_credit(
        credit["id"], {"journey_id": sc["j_new"], "amount_cents": 10000,
                       "expected_credit_version": mid["version"]}, p_h), 201)
    done = validate_success(api.get_credit(credit["id"], p_h), 200)
    assert done["credit_status"] == "REDEEMED", (
        "the exact-consumption redemption moves the credit to REDEEMED")
    assert done["remaining_amount_cents"] == 0
