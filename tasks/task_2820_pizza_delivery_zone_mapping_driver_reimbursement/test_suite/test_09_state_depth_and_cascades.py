"""Deep state-machine paths and multi-record cascades of the Store Operations API.

This module pins the behaviours that only appear once a record has been walked
several hops away from its birth state. It covers the two independent order
dimensions advancing in either interleaving, the bounded information-request loop
on an address dispute, a route cycling between committed and stacked so that the
second commitment must recompute the round trip and the mileage waterfall from
scratch, the four-hop cascade a door arrival drives into the driver's pouch and
the store's cash books, the four-hop cascade a failed motor-vehicle record drives
back down into logistics, and the three-hop cascade a granted dispute drives from
one address override into two parked orders and the store's backlog counter.
"""

import pytest

from prd_bench_local_runner.testing import (
    validate_success, validate_error, validate_paginated, get_success_data,
)

from test_helpers import api_client
from test_helpers.api_errors import ApiErrorId
from test_helpers import fixtures as fx
from test_helpers import factories as f
from test_helpers import assertions as a
from test_helpers.constants import DEFAULT_CLOCK, NOON_CLOCK
from test_helpers.test_users import (
    CARE_HEADERS,
    COMPLIANCE_HEADERS,
    DISPATCHER_HEADERS,
    make_compliance_headers,
    make_driver_headers,
    make_manager_headers,
)

# An address inside the ring whose modelled drive exceeds the 40-minute ceiling:
# 170100 micro-degrees due north is 11.34 grid miles, which models at 6 plus 35
# minutes and therefore reads EDGE rather than IN_ZONE.
EDGE_LAT_MICRO = 39170100
EDGE_LON_MICRO = -84000000


def _assert_instant_equals(actual, expected, field):
    """Compare a returned instant to an expected one without comparing string
    widths: every stored instant answers with exactly three fractional digits."""
    a.assert_iso_millis(actual, field)
    assert a.parse_instant(actual) == a.parse_instant(expected), (
        f"{field} should be {expected}, got {actual}"
    )


def test_disclosing_the_fee_before_production_reaches_ready_with_the_money_dimension_intact():
    """A ticket disclosed before the make line starts still reads DISCLOSED once
    production has driven the fulfillment dimension all the way to READY.

    PRD: "An order carries **two independent state dimensions** that advance on entirely different triggers."
    Design: Difficulty/non_linear_state_machine/order_fulfillment_and_settlement_dimensions_advance_in_either_interleaving
    """
    world = fx.setup_operational_store(
        clock=DEFAULT_CLOCK, address_keys=("A",), with_cost_model=False, with_driver=False
    )
    store_id = world["store"]["id"]

    order = fx.place_order(
        store_id,
        world["addresses"]["A"]["id"],
        customer_name="Xan",
        customer_phone="555-0120",
        food_subtotal_cents=2200,
        payment_method="CARD",
        tip_cents=500,
    )
    fx.decide_zone(order["id"], "CLEAR")
    fx.disclose_fee(order, 200, 500, True)
    fx.produce(order["id"], "START")

    data = validate_success(
        api_client.production(order["id"], f.production_payload("READY"), DISPATCHER_HEADERS), 200
    )

    a.assert_order(data)
    assert data["fulfillment_status"] == "READY"
    assert data["settlement_status"] == "DISCLOSED"
    _assert_instant_equals(data["ready_at"], DEFAULT_CLOCK, "ready_at")
    _assert_instant_equals(data["fee_disclosed_at"], DEFAULT_CLOCK, "fee_disclosed_at")
    assert data["delivery_fee_cents"] == 200
    assert data["total_charge_cents"] == 2900
    assert data["fee_disclosure_accurate"] is True

    store = get_success_data(api_client.get_store(store_id, make_manager_headers(store_id)), 200)
    assert store["unassigned_order_count"] == 1


def test_disclosing_the_fee_after_the_order_is_ready_reaches_the_same_combined_state():
    """A ticket already sitting in READY may still be disclosed, and the disclosure
    leaves the fulfillment dimension exactly where production left it.

    PRD: "Because the two dimensions are independent, disclosure is legal while the order is `PLACED`, `ZONE_CLEARED`, `IN_PRODUCTION` or `READY`."
    Design: Difficulty/non_linear_state_machine/order_fulfillment_and_settlement_dimensions_advance_in_either_interleaving
    """
    world = fx.setup_operational_store(
        clock=DEFAULT_CLOCK, address_keys=("A", "A2"), with_cost_model=False, with_driver=False
    )
    store_id = world["store"]["id"]

    order_x = fx.place_order(
        store_id,
        world["addresses"]["A"]["id"],
        customer_name="Xan",
        customer_phone="555-0120",
        food_subtotal_cents=2200,
        payment_method="CARD",
        tip_cents=500,
    )
    order_y = fx.place_order(
        store_id,
        world["addresses"]["A2"]["id"],
        customer_name="Yuri",
        customer_phone="555-0121",
        food_subtotal_cents=2200,
        payment_method="CARD",
        tip_cents=500,
    )
    fx.decide_zone(order_x["id"], "CLEAR")
    fx.decide_zone(order_y["id"], "CLEAR")
    fx.disclose_fee(order_x, 200, 500, True)
    fx.produce(order_x["id"], "START")
    fx.produce(order_x["id"], "READY")
    fx.produce(order_y["id"], "START")
    fx.produce(order_y["id"], "READY")

    data = validate_success(
        api_client.disclose_fee(
            order_y["id"], f.disclose_fee_payload(200, 500, True), CARE_HEADERS
        ),
        200,
    )

    assert data["settlement_status"] == "DISCLOSED"
    assert data["fulfillment_status"] == "READY", (
        "the disclosure trigger must not move the fulfillment dimension past READY"
    )
    _assert_instant_equals(data["fee_disclosed_at"], DEFAULT_CLOCK, "fee_disclosed_at")
    _assert_instant_equals(data["ready_at"], DEFAULT_CLOCK, "ready_at")
    assert data["delivery_fee_cents"] == 200
    assert data["fee_disclosure_accurate"] is True

    reread_x = fx.read_order(order_x["id"])
    assert reread_x["fulfillment_status"] == "READY"
    assert reread_x["settlement_status"] == "DISCLOSED"
    assert reread_x["fee_disclosure_accurate"] is True

    store = get_success_data(api_client.get_store(store_id, make_manager_headers(store_id)), 200)
    assert store["unassigned_order_count"] == 2


def test_a_third_information_request_is_refused_once_the_round_count_has_reached_two():
    """A dispute back in UNDER_REVIEW for the third time refuses a further
    information request and keeps every field of the dispute exactly as it was.

    PRD: "The loop is bounded at two rounds: a `REQUEST_INFO` attempted when `review_round_count` has already reached 2 is rejected with `ERR_DISPUTE_ROUND_LIMIT`, so the second request for information is the last one and a third is refused."
    Design: Difficulty/non_linear_state_machine/dispute_info_request_cycle_caps_at_two_rounds
    """
    store, _zone_version = fx.bootstrap(DEFAULT_CLOCK)
    store_id = store["id"]
    manager = make_manager_headers(store_id)

    address = fx.add_address_at(store_id, EDGE_LAT_MICRO, EDGE_LON_MICRO)
    assert address["zone_state"] == "EDGE"
    dispute = fx.open_dispute(
        address["id"], evidence_note="Neighbour two doors down is delivered"
    )
    for action in ("START_REVIEW", "REQUEST_INFO", "START_REVIEW", "REQUEST_INFO", "START_REVIEW"):
        fx.review_dispute(dispute["id"], action, store_id)

    before = get_success_data(api_client.get_address_dispute(dispute["id"], manager), 200)
    assert before["status"] == "UNDER_REVIEW"
    assert before["review_round_count"] == 2

    validate_error(
        api_client.review_address_dispute(
            dispute["id"], f.review_dispute_payload("REQUEST_INFO"), manager
        ),
        ApiErrorId.ERR_DISPUTE_ROUND_LIMIT.value,
    )

    after = get_success_data(api_client.get_address_dispute(dispute["id"], manager), 200)
    a.assert_address_dispute(after)
    assert after["status"] == "UNDER_REVIEW"
    assert after["review_round_count"] == 2, "the refused request must not increment the counter"
    assert after["resolution"] is None
    assert after["version"] == before["version"], "a refused request applies no side effect"
    assert after["updated_at"] == before["updated_at"]

    granted = validate_success(
        api_client.review_address_dispute(
            dispute["id"],
            f.review_dispute_payload("GRANT", granted_until="2026-08-05T23:00:00Z"),
            manager,
        ),
        200,
    )
    assert granted["status"] == "GRANTED", "only the information-request edge is capped"
    assert granted["resolution"] == "GRANTED"
    assert granted["review_round_count"] == 2


def test_returning_a_dispute_to_review_never_decrements_its_round_count():
    """Closing the information-request loop mutates the dispute — its version moves —
    but the round counter it consumed is never given back.

    PRD: "The same `START_REVIEW` action closes that loop from the other side, advancing `INFO_REQUESTED → UNDER_REVIEW` and re-stamping `reviewer_user_id`; note that returning to review does **not** decrement `review_round_count`, which only ever climbs."
    Design: Difficulty/non_linear_state_machine/dispute_info_request_cycle_caps_at_two_rounds
    """
    store, _zone_version = fx.bootstrap(DEFAULT_CLOCK)
    store_id = store["id"]
    manager = make_manager_headers(store_id)

    address = fx.add_address_at(store_id, EDGE_LAT_MICRO, EDGE_LON_MICRO)
    dispute = fx.open_dispute(
        address["id"], evidence_note="Neighbour two doors down is delivered"
    )
    assert dispute["review_round_count"] == 0

    fx.review_dispute(dispute["id"], "START_REVIEW", store_id)
    first_request = fx.review_dispute(dispute["id"], "REQUEST_INFO", store_id)
    assert first_request["status"] == "INFO_REQUESTED"
    assert first_request["review_round_count"] == 1

    reopened = validate_success(
        api_client.review_address_dispute(
            dispute["id"], f.review_dispute_payload("START_REVIEW"), manager
        ),
        200,
    )
    assert reopened["status"] == "UNDER_REVIEW"
    assert reopened["review_round_count"] == 1, "returning to review never gives a round back"
    assert reopened["version"] == first_request["version"] + 1

    second_request = fx.review_dispute(dispute["id"], "REQUEST_INFO", store_id)
    assert second_request["review_round_count"] == 2
    reopened_again = fx.review_dispute(dispute["id"], "START_REVIEW", store_id)
    assert reopened_again["status"] == "UNDER_REVIEW"
    assert reopened_again["review_round_count"] == 2, "the counter only ever climbs"


def test_re_locking_a_route_after_a_stop_is_added_recomputes_every_committed_figure():
    """A route committed, released and committed again over a larger stop set prices
    the new stop set from scratch rather than reusing the first commitment.

    PRD: "Committing a route therefore writes four fields at once: `route_minutes` and `expected_return_at` from the round-trip model, `resolved_cost_model_id` from the selector, and `estimated_reimbursement_cents` from the estimated variant of the waterfall."
    Design: Difficulty/non_linear_state_machine/dispatch_lock_unlock_relock_recomputes_route_from_scratch
    """
    world = fx.setup_operational_store(clock=DEFAULT_CLOCK, address_keys=("A", "A2"))
    store_id = world["store"]["id"]
    order_ann = fx.add_ready_order(
        store_id,
        world["addresses"]["A"]["id"],
        customer_name="Ann",
        customer_phone="555-0101",
        food_subtotal_cents=2200,
        payment_method="CARD",
        tip_cents=500,
    )
    order_ben = fx.add_ready_order(
        store_id,
        world["addresses"]["A2"]["id"],
        customer_name="Ben",
        customer_phone="555-0102",
        food_subtotal_cents=2200,
        payment_method="CARD",
        tip_cents=500,
    )

    dispatch = fx.open_dispatch(
        world["driver"]["id"], planned_depart_at="2026-08-05T18:00:00Z"
    )
    stop_one = fx.stack_stop(dispatch["id"], order_ann["id"], 1)
    first_commitment = fx.lock_route(dispatch["id"])
    assert first_commitment["route_minutes"] == 24
    assert first_commitment["estimated_reimbursement_cents"] == 336

    released = fx.unlock_route(dispatch["id"])
    assert released["status"] == "STACKED"
    assert released["route_minutes"] is None
    stop_two = fx.stack_stop(dispatch["id"], order_ben["id"], 1)

    recommitted = validate_success(
        api_client.lock_dispatch(dispatch["id"], DISPATCHER_HEADERS), 200
    )
    a.assert_dispatch(recommitted)
    assert recommitted["status"] == "LOCKED"
    assert recommitted["stop_count"] == 2
    assert recommitted["committed_hot_bag_slots"] == 2
    # Both doors sit 3.00 grid miles out: 9 + 9 outbound, 6 + 6 at the doors and a
    # 9-minute homeward leg repeating the last stop.
    assert recommitted["route_minutes"] == a.expected_route_minutes([3.00, 3.00], 3, 6) == 39
    _assert_instant_equals(
        recommitted["expected_return_at"], "2026-08-05T18:39:00Z", "expected_return_at"
    )
    assert (
        recommitted["estimated_reimbursement_cents"]
        == a.expected_reimbursement_from_model([3.00, 3.00], world["cost_model"])
        == 651
    ), "the second commitment prices both stops, not just the newly added one"
    assert recommitted["resolved_cost_model_id"] == world["cost_model"]["id"]

    sequences = {stop["id"]: stop["sequence"] for stop in fx.list_route_stops(dispatch["id"])}
    assert sequences[stop_one["id"]] == 1
    assert sequences[stop_two["id"]] == 2


def test_releasing_a_committed_route_returns_all_four_committed_figures_to_null():
    """Releasing a commitment does not merely change the route's status: it clears the
    whole priced snapshot, so no figure from the first commitment can survive.

    PRD: "Releasing a commitment reverses all of it: a `Dispatcher` may move a route `LOCKED → STACKED`, which returns `route_minutes`, `expected_return_at`, `resolved_cost_model_id` and `estimated_reimbursement_cents` all to null and frees both the driver's occupied interval and the store's bag reservation, so that stops can be added or removed and the route committed again."
    Design: Difficulty/non_linear_state_machine/dispatch_lock_unlock_relock_recomputes_route_from_scratch
    """
    world = fx.setup_operational_store(clock=DEFAULT_CLOCK, address_keys=("A",))
    store_id = world["store"]["id"]
    order_ann = fx.add_ready_order(
        store_id,
        world["addresses"]["A"]["id"],
        customer_name="Ann",
        customer_phone="555-0101",
        food_subtotal_cents=2200,
        payment_method="CARD",
        tip_cents=500,
    )
    dispatch = fx.open_dispatch(
        world["driver"]["id"], planned_depart_at="2026-08-05T18:00:00Z"
    )
    fx.stack_stop(dispatch["id"], order_ann["id"], 1)

    committed = fx.lock_route(dispatch["id"])
    # One door 3.00 grid miles out: 9 outbound, 6 at the door, 9 home.
    assert committed["route_minutes"] == a.expected_route_minutes([3.00], 3, 6) == 24
    assert committed["estimated_reimbursement_cents"] == 336
    assert committed["resolved_cost_model_id"] == world["cost_model"]["id"]
    assert committed["expected_return_at"] is not None

    released = validate_success(
        api_client.unlock_dispatch(dispatch["id"], DISPATCHER_HEADERS), 200
    )
    a.assert_dispatch(released)
    assert released["status"] == "STACKED"
    assert released["route_minutes"] is None
    assert released["expected_return_at"] is None
    assert released["resolved_cost_model_id"] is None
    assert released["estimated_reimbursement_cents"] is None
    assert released["stop_count"] == 1, "the stop itself stays stacked and can be added to"
    assert released["version"] == committed["version"] + 1


def test_one_cash_door_arrival_propagates_through_stop_order_driver_and_store():
    """A single handoff at a cash door moves the stop, both dimensions of its order,
    the driver's pouch and posture, and the owning store's cash totals and backlog.

    PRD: "Third, because the order is now charged and its `payment_method` is `CASH`, the driver's `cash_on_hand_cents` and the store's `cash_collected_total_cents` each rise by that order's `total_charge_cents`, and the driver's `version` and the store's `version` each increment by 1."
    Design: Difficulty/transitive_cascade/door_arrival_four_hop_cascade_to_store_cash_and_drop_posture
    """
    world = fx.setup_route(
        "EN_ROUTE",
        ("A",),
        clock=NOON_CLOCK,
        planned_depart_at="2026-08-05T12:05:00Z",
        store_overrides={"cash_limit_cents": 2900},
        order_overrides={
            "customer_name": "Ann",
            "customer_phone": "555-0101",
            "food_subtotal_cents": 2200,
            "payment_method": "CASH",
            "tip_cents": 500,
        },
    )
    store_id = world["store"]["id"]
    driver_id = world["driver"]["id"]
    dispatch_id = world["dispatch"]["id"]
    stop = world["stops"][0]
    order = world["orders"][0]
    assert order["total_charge_cents"] == 2900

    fx.set_clock("2026-08-05T12:36:00Z")
    driver_before = fx.read_driver(driver_id)
    store_before = fx.read_store(store_id)
    assert driver_before["cash_on_hand_cents"] == 0
    assert store_before["unassigned_order_count"] == 0, "a stacked order is already assigned"

    delivered_stop = validate_success(
        api_client.door_arrival(
            dispatch_id,
            stop["id"],
            f.door_arrival_payload(3.4, 2900),
            make_driver_headers(driver_id),
        ),
        200,
    )
    a.assert_dispatch_stop(delivered_stop)
    assert delivered_stop["status"] == "DELIVERED"
    _assert_instant_equals(delivered_stop["arrived_at"], "2026-08-05T12:36:00Z", "arrived_at")

    charged_order = fx.read_order(order["id"])
    a.assert_order(charged_order)
    assert charged_order["fulfillment_status"] == "DELIVERED"
    assert charged_order["settlement_status"] == "CHARGED"
    assert charged_order["total_charge_cents"] == 2900
    assert charged_order["cash_collected_cents"] == 2900
    assert charged_order["order_to_door_gross_minutes"] == 36
    assert charged_order["order_to_door_net_minutes"] == 36

    driver_after = fx.read_driver(driver_id)
    a.assert_driver(driver_after)
    assert driver_after["cash_on_hand_cents"] == 2900
    assert driver_after["cash_posture"] == "DROP_REQUIRED", "the pouch has reached the store limit"
    assert driver_after["version"] == driver_before["version"] + 1
    assert driver_after["reimbursement_accrued_cents"] == 0, "a provisional line is not accrued"

    store_after = fx.read_store(store_id)
    a.assert_store(store_after)
    assert store_after["cash_collected_total_cents"] == 2900
    assert store_after["safe_deposit_total_cents"] == 0
    assert store_after["unassigned_order_count"] == 0
    assert store_after["version"] == store_before["version"] + 1

    lines = fx.list_route_lines(dispatch_id)
    assert len(lines) == 1
    line = lines[0]
    a.assert_reimbursement_line(line)
    assert line["line_type"] == "PROVISIONAL_STOP"
    assert line["basis"] == "ESTIMATED"
    assert line["status"] == "PROVISIONAL"
    assert line["amount_cents"] == 336
    assert line["sequence_snapshot"] == 1

    route_after = fx.read_dispatch(dispatch_id)
    assert route_after["status"] == "EN_ROUTE", "one handoff does not close the route"


def test_a_card_door_and_a_cash_door_on_one_route_take_different_money_branches():
    """Two handoffs on the same route charge their orders the same way but move money
    only for the cash one, so only the cash door touches the pouch and the store total.

    PRD: "Second, because the order has reached `DELIVERED`, its settlement dimension advances `DISCLOSED → CHARGED` and the order's own `cash_collected_cents` is fixed — equal to `total_charge_cents` for a cash order, 0 for a card order."
    Design: Difficulty/transitive_cascade/door_arrival_four_hop_cascade_to_store_cash_and_drop_posture
    """
    world = fx.setup_route(
        "EN_ROUTE",
        ("A", "A2"),
        clock=NOON_CLOCK,
        planned_depart_at="2026-08-05T12:05:00Z",
        store_overrides={"cash_limit_cents": 2900},
        order_overrides=[
            {
                "customer_name": "Ann",
                "customer_phone": "555-0101",
                "food_subtotal_cents": 2200,
                "payment_method": "CARD",
                "tip_cents": 500,
            },
            {
                "customer_name": "Ben",
                "customer_phone": "555-0102",
                "food_subtotal_cents": 2200,
                "payment_method": "CASH",
                "tip_cents": 500,
            },
        ],
    )
    store_id = world["store"]["id"]
    driver_id = world["driver"]["id"]
    dispatch_id = world["dispatch"]["id"]
    card_stop, cash_stop = world["stops"]
    card_order, cash_order = world["orders"]

    fx.set_clock("2026-08-05T12:36:00Z")
    fx.arrive_at_door(dispatch_id, card_stop["id"], driver_id, 3.4, 0)

    charged_card_order = fx.read_order(card_order["id"])
    assert charged_card_order["fulfillment_status"] == "DELIVERED"
    assert charged_card_order["settlement_status"] == "CHARGED"
    assert charged_card_order["total_charge_cents"] == 2900
    assert charged_card_order["cash_collected_cents"] == 0, "a card order collects nothing at the door"
    driver_after_card = fx.read_driver(driver_id)
    assert driver_after_card["cash_on_hand_cents"] == 0
    assert driver_after_card["cash_posture"] == "CLEAR"
    assert fx.read_store(store_id)["cash_collected_total_cents"] == 0

    delivered_cash_stop = validate_success(
        api_client.door_arrival(
            dispatch_id,
            cash_stop["id"],
            f.door_arrival_payload(3.4, 2900),
            make_driver_headers(driver_id),
        ),
        200,
    )
    assert delivered_cash_stop["status"] == "DELIVERED"

    charged_cash_order = fx.read_order(cash_order["id"])
    assert charged_cash_order["settlement_status"] == "CHARGED"
    assert charged_cash_order["cash_collected_cents"] == 2900
    assert fx.read_order(card_order["id"])["cash_collected_cents"] == 0, (
        "the card order's fixed figure is not disturbed by the later cash door"
    )

    driver_after_cash = fx.read_driver(driver_id)
    assert driver_after_cash["cash_on_hand_cents"] == 2900
    assert driver_after_cash["cash_posture"] == "DROP_REQUIRED"
    store_after = fx.read_store(store_id)
    assert store_after["cash_collected_total_cents"] == 2900, "only the cash door raised the total"
    assert store_after["safe_deposit_total_cents"] == 0


def test_a_failed_record_check_mid_route_unwinds_the_route_stops_orders_and_backlog():
    """A failed record check on a driver who is out on the road reaches down through
    the route, its pending stop, that stop's order and its ledger line to the store.

    PRD: "The driver is driven straight to `DISQUALIFIED` from whichever of `APPLICANT`, `PENDING_CHECKS`, `QUALIFIED` or `SUSPENDED` they occupied, with `disqualified_reason` recorded as `MVR_FAILED`, and a four-hop cascade unwinds everything that driver was in the middle of."
    Design: Difficulty/transitive_cascade/mvr_failure_four_hop_cascade_recalls_route_and_restores_backlog
    """
    world = fx.setup_route(
        "EN_ROUTE",
        ("A", "A2"),
        clock=NOON_CLOCK,
        planned_depart_at="2026-08-05T12:05:00Z",
        order_overrides=[
            {
                "customer_name": "Ann",
                "customer_phone": "555-0101",
                "food_subtotal_cents": 2200,
                "payment_method": "CARD",
                "tip_cents": 500,
            },
            {
                "customer_name": "Ben",
                "customer_phone": "555-0102",
                "food_subtotal_cents": 2200,
                "payment_method": "CARD",
                "tip_cents": 500,
            },
        ],
    )
    store_id = world["store"]["id"]
    driver_id = world["driver"]["id"]
    dispatch_id = world["dispatch"]["id"]
    first_stop, second_stop = world["stops"]
    first_order, second_order = world["orders"]
    fx.arrive_at_door(dispatch_id, first_stop["id"], driver_id, 3.4, 0)

    failed_check = validate_success(
        api_client.create_mvr_check(
            driver_id,
            f.create_mvr_check_payload(
                result="FAILED", violation_points=9, checked_on="2026-08-05T11:00:00Z"
            ),
            make_compliance_headers("officer-3"),
        ),
        201,
    )
    a.assert_mvr_check(failed_check)

    driver_after = fx.read_driver(driver_id)
    assert driver_after["qualification_status"] == "DISQUALIFIED"
    assert driver_after["disqualified_reason"] == "MVR_FAILED"
    assert driver_after["mvr_points_latest"] == 9
    assert driver_after["reimbursement_accrued_cents"] == 0, "an aborted route accrues nothing"

    route_after = fx.read_dispatch(dispatch_id)
    assert route_after["status"] == "RECALLED"
    assert route_after["recalled_reason"] == "DRIVER_DISQUALIFIED"

    assert fx.read_stop(second_stop["id"])["status"] == "RELEASED"
    assert fx.read_stop(first_stop["id"])["status"] == "DELIVERED", "a delivered door stays delivered"

    assert fx.read_order(second_order["id"])["fulfillment_status"] == "READY"
    reread_first_order = fx.read_order(first_order["id"])
    assert reread_first_order["fulfillment_status"] == "DELIVERED"
    assert reread_first_order["settlement_status"] == "CHARGED"

    lines = fx.list_route_lines(dispatch_id)
    assert len(lines) == 1
    assert lines[0]["sequence_snapshot"] == 1
    assert lines[0]["status"] == "VOIDED", "the aborted route pays nothing out"

    assert fx.read_store(store_id)["unassigned_order_count"] == 1

    checks, _meta = validate_paginated(
        api_client.list_mvr_checks(COMPLIANCE_HEADERS, {"driver_id": driver_id, "limit": 100})
    )
    assert len(checks) == 2
    for record in checks:
        a.assert_append_only_common_fields(record)
        assert "version" not in record


def test_recalling_a_route_for_a_failed_check_leaves_the_delivered_door_and_its_cash_alone():
    """The unwind is selective: the stop already handed over keeps its status, its
    order stays charged and the cash taken there stays on the driver's pouch.

    PRD: "Stops already `DELIVERED` keep their status and the cash already collected at those doors stays on the driver's pouch, exactly where the conservation identity says it is."
    Design: Difficulty/transitive_cascade/mvr_failure_four_hop_cascade_recalls_route_and_restores_backlog
    """
    world = fx.setup_route(
        "EN_ROUTE",
        ("A", "A2"),
        clock=NOON_CLOCK,
        planned_depart_at="2026-08-05T12:05:00Z",
        order_overrides=[
            {
                "customer_name": "Ann",
                "customer_phone": "555-0101",
                "food_subtotal_cents": 2200,
                "payment_method": "CASH",
                "tip_cents": 500,
            },
            {
                "customer_name": "Ben",
                "customer_phone": "555-0102",
                "food_subtotal_cents": 2200,
                "payment_method": "CARD",
                "tip_cents": 500,
            },
        ],
    )
    store_id = world["store"]["id"]
    driver_id = world["driver"]["id"]
    dispatch_id = world["dispatch"]["id"]
    cash_stop, pending_stop = world["stops"]
    cash_order, pending_order = world["orders"]
    fx.arrive_at_door(dispatch_id, cash_stop["id"], driver_id, 3.4, 2900)
    assert fx.read_driver(driver_id)["cash_on_hand_cents"] == 2900

    validate_success(
        api_client.create_mvr_check(
            driver_id,
            f.create_mvr_check_payload(
                result="FAILED", violation_points=9, checked_on="2026-08-05T11:00:00Z"
            ),
            make_compliance_headers("officer-3"),
        ),
        201,
    )

    driver_after = fx.read_driver(driver_id)
    assert driver_after["qualification_status"] == "DISQUALIFIED"
    assert driver_after["cash_on_hand_cents"] == 2900, "the pouch is not emptied by the recall"
    assert driver_after["reimbursement_accrued_cents"] == 0

    kept_stop = fx.read_stop(cash_stop["id"])
    assert kept_stop["status"] == "DELIVERED"
    assert kept_stop["cash_collected_cents"] == 2900
    kept_order = fx.read_order(cash_order["id"])
    assert kept_order["fulfillment_status"] == "DELIVERED"
    assert kept_order["settlement_status"] == "CHARGED"
    assert kept_order["cash_collected_cents"] == 2900

    assert fx.read_stop(pending_stop["id"])["status"] == "RELEASED"
    assert fx.read_order(pending_order["id"])["fulfillment_status"] == "READY"

    store_after = fx.read_store(store_id)
    assert store_after["cash_collected_total_cents"] == 2900
    assert store_after["safe_deposit_total_cents"] == 0
    assert store_after["unassigned_order_count"] == 1
    a.assert_cash_conservation(fx.read_cash_reconciliation(store_id))

    lines = fx.list_route_lines(dispatch_id)
    assert len(lines) == 1
    assert lines[0]["status"] == "VOIDED"


def test_granting_an_address_dispute_clears_both_parked_orders_with_their_own_hold_minutes():
    """One grant writes an override on one address and from that single write releases
    every order parked on it, each accruing the minutes it personally spent parked.

    PRD: "Second, because the address now reads as in-zone, every order on that address whose fulfillment status is `ZONE_HELD` is automatically advanced `ZONE_HELD → ZONE_CLEARED`, processed in `created_at` ascending order across those orders; each such order accrues into its `zone_hold_minutes` the whole minutes it spent parked, computed as the difference between the logical clock and its `zone_held_at` in whole seconds, divided by 60 and truncated downward."
    Design: Difficulty/transitive_cascade/dispute_grant_three_hop_cascade_clears_two_held_orders_with_distinct_holds
    """
    store, _zone_version = fx.bootstrap(DEFAULT_CLOCK)
    store_id = store["id"]
    manager = make_manager_headers(store_id)
    address = fx.add_address_at(
        store_id, EDGE_LAT_MICRO, EDGE_LON_MICRO, line1="77 Far Ridge"
    )
    assert address["zone_state"] == "EDGE"
    assert address["grid_miles"] == 11.34
    assert address["drive_time_estimate_minutes"] == 41

    fx.set_clock(NOON_CLOCK)
    order_hana = fx.place_order(
        store_id,
        address["id"],
        customer_name="Hana",
        customer_phone="555-0108",
        food_subtotal_cents=2200,
        payment_method="CARD",
        tip_cents=500,
    )
    held_hana = fx.decide_zone(order_hana["id"], "HOLD")
    assert held_hana["fulfillment_status"] == "ZONE_HELD"

    fx.set_clock("2026-08-05T12:02:00Z")
    order_ivo = fx.place_order(
        store_id,
        address["id"],
        customer_name="Ivo",
        customer_phone="555-0109",
        food_subtotal_cents=2200,
        payment_method="CARD",
        tip_cents=500,
    )
    held_ivo = fx.decide_zone(order_ivo["id"], "HOLD")

    dispute = fx.open_dispute(
        address["id"],
        claimed_state="IN_ZONE",
        evidence_note="Driveway is on our side of the creek",
    )
    fx.review_dispute(dispute["id"], "START_REVIEW", store_id)

    fx.set_clock("2026-08-05T12:08:00Z")
    address_before = fx.read_address(address["id"])
    assert fx.read_store(store_id)["unassigned_order_count"] == 0, "parked orders need no route"

    granted = validate_success(
        api_client.review_address_dispute(
            dispute["id"],
            f.review_dispute_payload("GRANT", granted_until="2026-08-05T23:00:00Z"),
            manager,
        ),
        200,
    )
    a.assert_address_dispute(granted)
    assert granted["status"] == "GRANTED"
    assert granted["resolution"] == "GRANTED"
    _assert_instant_equals(granted["decided_at"], "2026-08-05T12:08:00Z", "decided_at")

    address_after = fx.read_address(address["id"])
    a.assert_service_address(address_after)
    assert address_after["override_state"] == "IN_ZONE"
    _assert_instant_equals(
        address_after["override_until"], "2026-08-05T23:00:00Z", "override_until"
    )
    assert address_after["effective_zone_state"] == "IN_ZONE"
    assert address_after["zone_state"] == "EDGE", "the classification itself is not rewritten"
    assert address_after["grid_miles"] == 11.34
    assert address_after["drive_time_estimate_minutes"] == 41
    assert address_after["version"] == address_before["version"] + 1

    cleared_hana = fx.read_order(order_hana["id"])
    cleared_ivo = fx.read_order(order_ivo["id"])
    assert cleared_hana["fulfillment_status"] == "ZONE_CLEARED"
    assert cleared_ivo["fulfillment_status"] == "ZONE_CLEARED"
    assert cleared_hana["zone_hold_minutes"] == 8
    assert cleared_ivo["zone_hold_minutes"] == 6, "each order accrues its own parked minutes"
    assert cleared_hana["version"] == held_hana["version"] + 1
    assert cleared_ivo["version"] == held_ivo["version"] + 1

    assert fx.read_store(store_id)["unassigned_order_count"] == 2


def test_a_grant_raises_the_backlog_by_exactly_the_orders_it_released():
    """The release reaches only orders parked on the disputed address: an order on that
    address that was never parked, and an order parked on a different address, are left
    alone, so the backlog rises by exactly two.

    PRD: "Third, because those orders have left `ZONE_HELD` and entered a status the unassigned filter counts, the owning store's `unassigned_order_count` re-derives upward by exactly the number of orders cleared in the previous hop."
    Design: Difficulty/transitive_cascade/dispute_grant_three_hop_cascade_clears_two_held_orders_with_distinct_holds
    """
    store, _zone_version = fx.bootstrap(DEFAULT_CLOCK)
    store_id = store["id"]
    manager = make_manager_headers(store_id)
    disputed = fx.add_address_at(
        store_id, EDGE_LAT_MICRO, EDGE_LON_MICRO, line1="77 Far Ridge"
    )
    other_edge = fx.add_address(store_id, "E")
    assert other_edge["zone_state"] == "EDGE"

    fx.set_clock(NOON_CLOCK)
    order_hana = fx.place_order(
        store_id, disputed["id"], customer_name="Hana", customer_phone="555-0108"
    )
    fx.decide_zone(order_hana["id"], "HOLD")

    fx.set_clock("2026-08-05T12:02:00Z")
    order_ivo = fx.place_order(
        store_id, disputed["id"], customer_name="Ivo", customer_phone="555-0109"
    )
    fx.decide_zone(order_ivo["id"], "HOLD")

    untouched_same_address = fx.place_order(
        store_id, disputed["id"], customer_name="Jo", customer_phone="555-0110"
    )
    assert untouched_same_address["fulfillment_status"] == "PLACED"
    order_on_other_address = fx.place_order(
        store_id, other_edge["id"], customer_name="Kai", customer_phone="555-0111"
    )
    held_elsewhere = fx.decide_zone(order_on_other_address["id"], "HOLD")
    assert held_elsewhere["fulfillment_status"] == "ZONE_HELD"

    dispute = fx.open_dispute(
        disputed["id"],
        claimed_state="IN_ZONE",
        evidence_note="Driveway is on our side of the creek",
    )
    fx.review_dispute(dispute["id"], "START_REVIEW", store_id)

    fx.set_clock("2026-08-05T12:08:00Z")
    validate_success(
        api_client.review_address_dispute(
            dispute["id"],
            f.review_dispute_payload("GRANT", granted_until="2026-08-05T23:00:00Z"),
            manager,
        ),
        200,
    )

    assert fx.read_order(order_hana["id"])["fulfillment_status"] == "ZONE_CLEARED"
    assert fx.read_order(order_ivo["id"])["fulfillment_status"] == "ZONE_CLEARED"

    still_placed = fx.read_order(untouched_same_address["id"])
    assert still_placed["fulfillment_status"] == "PLACED", "only parked orders are released"
    assert still_placed["zone_hold_minutes"] == 0
    assert still_placed["version"] == untouched_same_address["version"]

    still_held = fx.read_order(order_on_other_address["id"])
    assert still_held["fulfillment_status"] == "ZONE_HELD", "another address keeps its own hold"
    assert still_held["zone_hold_minutes"] == 0
    assert still_held["version"] == held_elsewhere["version"]
    assert fx.read_address(other_edge["id"])["override_state"] is None

    assert fx.read_store(store_id)["unassigned_order_count"] == 2
