"""Compensating invariants: forward action + compensation conserve quantities.

Covers Difficulty/compensating_invariant instances:
- credit_balance_redeem_then_void_restores
- boarding_position_conservation_under_upgrade_refund
"""
from test_helpers import (
    TEST_USERS, api_client, get_success_data, validate_error,
    validate_paginated, validate_success,
    ApiErrorId,
    assert_credit_balance_invariant,
    book_journey, create_aircraft, create_fare_class, create_leg,
    create_passenger, create_station, leg_check_in, purchase_upgrade,
    set_clock, setup_basic_network, setup_credit_scenario,
)

OPS = TEST_USERS["ops_headers"]
GATE = TEST_USERS["gate_agent_headers"]


def test_redeem_then_change_restores_the_credit_balance_exactly(api):
    """PRD §3.8: "Step one: any `ACTIVE` `CreditRedemption` paying the
    journey is voided, and each source credit's `remaining_amount_cents` is
    restored by the redemption amount — this is the compensation path, and it
    can move a credit from `PARTIALLY_REDEEMED` back to `OPEN`."

    PRD §3.8: "A `TravelCredit` is minted with a `passenger_id` owner, a
    `source_journey_id` identifying the journey whose cancellation, no-show,
    or change produced it, an `initial_amount_cents` greater than zero, and a
    `remaining_amount_cents` that begins equal to the initial amount and is
    decremented by redemptions, never below zero."

    Design: Difficulty/compensating_invariant/credit_balance_redeem_then_void_restores
    """
    sc = setup_credit_scenario(source_fare_cents=20000, new_fare_cents=10000)
    p_h = sc["passenger_headers"]
    credit = sc["credit"]
    j_new = sc["j_new"]

    validate_success(api.redeem_credit(
        credit["id"], {"journey_id": j_new, "amount_cents": 5000,
                       "expected_credit_version": credit["version"]}, p_h),
        201)
    mid = validate_success(api.get_credit(credit["id"], p_h), 200)
    assert mid["remaining_amount_cents"] == 15000
    redemptions, _m = validate_paginated(
        api.list_credit_redemptions(credit["id"], p_h))
    assert_credit_balance_invariant(mid, redemptions)

    validate_success(api.change_journey(
        j_new, {"new_flight_leg_id": sc["leg2"]["id"],
                "new_fare_class_id": sc["fare"]["id"],
                "new_base_fare_cents": 10000}, p_h), 200)

    restored = validate_success(api.get_credit(credit["id"], p_h), 200)
    assert restored["remaining_amount_cents"] == 20000, (
        "the compensating void restores the balance with zero drift")
    assert restored["credit_status"] == "OPEN"
    redemptions, _m = validate_paginated(
        api.list_credit_redemptions(credit["id"], p_h))
    assert_credit_balance_invariant(restored, redemptions)
    assert all(r["redemption_status"] == "VOIDED" for r in redemptions)


def test_compensation_survives_two_partial_redemptions(api):
    """PRD §3.8: "When a journey change or cancellation voids an `ACTIVE`
    redemption, the redemption moves to `VOIDED` and the source credit's
    `remaining_amount_cents` is restored by the redemption amount, returning
    a `PARTIALLY_REDEEMED` credit to `OPEN` when the restoration covers all
    prior redemptions."

    Design: Difficulty/compensating_invariant/credit_balance_redeem_then_void_restores
    """
    sc = setup_credit_scenario(source_fare_cents=20000, new_fare_cents=10000)
    p_h = sc["passenger_headers"]
    credit = sc["credit"]
    j_new = sc["j_new"]

    v = credit["version"]
    for amount in (5000, 5000):
        validate_success(api.redeem_credit(
            credit["id"], {"journey_id": j_new, "amount_cents": amount,
                           "expected_credit_version": v}, p_h), 201)
        v = validate_success(api.get_credit(credit["id"], p_h),
                             200)["version"]

    mid = validate_success(api.get_credit(credit["id"], p_h), 200)
    assert mid["remaining_amount_cents"] == 10000
    assert mid["credit_status"] == "PARTIALLY_REDEEMED"

    validate_success(api.change_journey(
        j_new, {"new_flight_leg_id": sc["leg2"]["id"],
                "new_fare_class_id": sc["fare"]["id"],
                "new_base_fare_cents": 10000}, p_h), 200)

    restored = validate_success(api.get_credit(credit["id"], p_h), 200)
    assert restored["remaining_amount_cents"] == 20000, (
        "both redemptions are compensated: 20000 + 0 == 20000")
    assert restored["credit_status"] == "OPEN"


def _upgrade_refund_setup():
    """Two checked-in journeys; J1 buys and refunds an UPGRADED_BOARDING."""
    net = setup_basic_network(fare_overrides={"change_fee_cents": 0,
                                              "included_bags": 2})
    leg = net["leg"]
    set_clock("2026-09-30T12:00:00Z")
    p1, p1_h = create_passenger(full_name="P 1")
    p2, p2_h = create_passenger(full_name="P 2")
    _bk, j1 = book_journey(p1_h, p1["id"], leg["id"], net["fare"]["id"],
                           base_fare_cents=10000)
    _bk, j2 = book_journey(p2_h, p2["id"], leg["id"], net["fare"]["id"],
                           base_fare_cents=10000)
    leg_v = leg["version"]
    _j, leg_v = leg_check_in(leg["id"], j1, p1_h, expected_leg_version=leg_v)
    _j, leg_v = leg_check_in(leg["id"], j2, p2_h, expected_leg_version=leg_v)
    return net, leg, p1, p1_h, p2, p2_h, j1, j2, leg_v


def test_upgrade_purchase_and_refund_conserve_active_assignment_count(api):
    """PRD §3.5: "A successful refund moves the upgrade to `REFUNDED`, voids
    the granted assignment with `release_reason` `UPGRADE`, and reverts the
    journey's boarding assignment to its original `CHECKIN_TIME` position,
    re-issued with `assignment_source` `CHECKIN_TIME` (a retime-sourced
    position is not reused here). The freed A-position is **not** backfilled
    — later purchasers do not slide up."

    PRD §3.4: "The input set to the algorithm is the leg's journeys currently
    in `CHECKED_IN` holding `ACTIVE` assignments, plus the leg's `ACTIVE`
    `UPGRADED_BOARDING` upgrades; journeys that have reached `NO_SHOW` or
    `CANCELLED`, and assignments already `VOIDED` or `RETIMED`, are
    excluded."

    Design: Difficulty/compensating_invariant/boarding_position_conservation_under_upgrade_refund
    """
    _net, leg, _p1, p1_h, _p2, _p2_h, j1, _j2, leg_v = _upgrade_refund_setup()

    def active_count():
        _rows, meta = validate_paginated(
            api.list_leg_boarding_assignments(
                leg["id"], GATE, params={"assignment_status": "ACTIVE"}))
        return meta["total_count"]

    assert active_count() == 2, "two checked-in journeys, two assignments"

    upgrade, leg_v = purchase_upgrade(leg["id"], j1, p1_h,
                                      "UPGRADED_BOARDING",
                                      expected_leg_version=leg_v)
    assert upgrade["position_granted"] == 1
    assert active_count() == 2, (
        "the purchase re-points J1's assignment to A1 rather than adding a "
        "row")

    validate_success(api.refund_upgrade(upgrade["id"], p1_h), 200)
    assert active_count() == 2, (
        "the refund re-issues the original position: cardinality conserved "
        "across the forward+compensating pair")

    refunded = validate_success(api.get_upgrade(upgrade["id"], p1_h), 200)
    assert refunded["upgrade_status"] == "REFUNDED"

    rows, _m = validate_paginated(api.list_journey_assignments(j1, p1_h))
    active_rows = [r for r in rows if r["assignment_status"] == "ACTIVE"]
    assert len(active_rows) == 1
    assert active_rows[0]["assignment_source"] == "CHECKIN_TIME"
    voided = [r for r in rows if r["assignment_status"] == "VOIDED"]
    assert any(r["release_reason"] == "UPGRADE" for r in voided)


def test_the_refunded_a1_slot_is_never_backfilled(api):
    """PRD §3.5: "A successful refund moves the upgrade to `REFUNDED`, voids
    the granted assignment with `release_reason` `UPGRADE`, and reverts the
    journey's boarding assignment to its original `CHECKIN_TIME` position,
    re-issued with `assignment_source` `CHECKIN_TIME` (a retime-sourced
    position is not reused here). The freed A-position is **not** backfilled
    — later purchasers do not slide up."

    Design: Difficulty/compensating_invariant/boarding_position_conservation_under_upgrade_refund
    """
    _net, leg, _p1, p1_h, _p2, p2_h, j1, j2, leg_v = _upgrade_refund_setup()

    upgrade, leg_v = purchase_upgrade(leg["id"], j1, p1_h,
                                      "UPGRADED_BOARDING",
                                      expected_leg_version=leg_v)
    assert upgrade["position_granted"] == 1
    validate_success(api.refund_upgrade(upgrade["id"], p1_h), 200)

    second, _v = purchase_upgrade(leg["id"], j2, p2_h, "UPGRADED_BOARDING",
                                  expected_leg_version=leg_v)
    assert second["position_granted"] == 2, (
        "the refunded A1 slot is permanently consumed; the position counter "
        "is monotone")
