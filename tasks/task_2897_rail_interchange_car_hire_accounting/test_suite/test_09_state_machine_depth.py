"""State machines that loop, that run in parallel, and that read other aggregates.

The dispute negotiation alternates between two parties and caps itself; a car
carries three dimensions that never consult one another; and settling a cycle or
allowing an embargo reclaim both hinge on rows living in a different aggregate.
"""

from test_helpers import (
    ERR_DISPUTE_ROUNDS_EXHAUSTED,
    ERR_DISPUTE_TURN_VIOLATION,
    ERR_EMBARGO_DOES_NOT_COVER_WINDOW,
    ERR_OPEN_DISPUTES_BLOCK_SETTLEMENT,
    ApiClient,
    allow_reclaim,
    assert_hours,
    assert_instant_equals,
    assert_money,
    assert_error_envelope,
    closed_segment_world,
    exchanged_cycle,
    file_dispute,
    file_reclaim,
    issue_embargo,
    ledger_entries,
    read_cycle,
    read_movement,
    register_car,
    set_clock,
    standard_world,
    three_line_world,
    validate_success,
)
import test_helpers.factories as f


def _four_seven_hundred_dispute(api, amount: int = 4700):
    """A three-line exchanged cycle with a dispute standing on the 4700 line."""
    world, cars, movements = three_line_world(api, cars=3)
    target = next(c for c in cars if movements[c]["net_hire_cents"] == 4700)
    cycle, computed, exchanged = exchanged_cycle(api, world)
    dispute = file_dispute(api, world, exchanged, "HIRE_RATE_MISAPPLIED", amount,
                          movement_id=movements[target]["id"])
    return world, cycle, movements[target], dispute


class TestDisputeNegotiationLoop:
    """OPEN and COUNTERED name whose turn it is, and the third counter is the last."""

    def test_three_counters_alternate_then_the_fourth_is_refused(self, api: ApiClient):
        """CX, BN and CX counter to 1000, 2000 and 3000; BN's fourth attempt is refused.

        PRD: "`round_number` must be strictly below 3, so the third counter succeeds and the fourth is `ERR_DISPUTE_ROUNDS_EXHAUSTED`."

        Design: Difficulty/non_linear_state_machine/dispute_open_countered_loop_alternates_actor_and_caps_at_three_rounds
        """
        world, cycle, movement, dispute = _four_seven_hundred_dispute(api)
        assert dispute["status"] == "OPEN"
        assert dispute["round_number"] == 0
        assert dispute["counter_amount_cents"] is None
        assert dispute["filed_by_road_id"] == world.bn
        assert dispute["respondent_road_id"] == world.cx

        first = validate_success(api.counter_dispute(
            dispute["id"], {"counter_amount_cents": 1000}, world.accountant(world.cx)))
        assert first["status"] == "COUNTERED"
        assert first["round_number"] == 1
        assert_money(first["counter_amount_cents"], 1000, "counter_amount_cents")

        second = validate_success(api.counter_dispute(
            dispute["id"], {"counter_amount_cents": 2000}, world.accountant(world.bn)))
        assert second["status"] == "OPEN"
        assert second["round_number"] == 2
        assert_money(second["counter_amount_cents"], 2000, "counter_amount_cents")

        third = validate_success(api.counter_dispute(
            dispute["id"], {"counter_amount_cents": 3000}, world.accountant(world.cx)))
        assert third["status"] == "COUNTERED"
        assert third["round_number"] == 3
        assert_money(third["counter_amount_cents"], 3000, "counter_amount_cents")

        fourth = api.counter_dispute(dispute["id"], {"counter_amount_cents": 3500},
                                    world.accountant(world.bn))
        assert_error_envelope(fourth, ERR_DISPUTE_ROUNDS_EXHAUSTED, 409)

        stalled = validate_success(api.get_dispute(dispute["id"],
                                                  world.accountant(world.bn)))
        assert stalled["status"] == "COUNTERED"
        assert stalled["round_number"] == 3
        assert_money(stalled["counter_amount_cents"], 3000, "counter_amount_cents")

        accepted = validate_success(api.accept_dispute(dispute["id"], {},
                                                      world.accountant(world.bn)))
        assert accepted["status"] == "ACCEPTED"
        assert_money(accepted["resolution_amount_cents"], 3000,
                     "resolution_amount_cents")
        assert_instant_equals(accepted["resolved_at"], "2026-09-01T00:00:00Z",
                              "resolved_at")

        statement = validate_success(api.get_settlement_statement(
            cycle["id"], world.accountant(world.bn), params={"variant": "RECONCILED"}))
        assert_money(statement["dispute_adjustment_cents"], -3000, "adjustment")
        assert_money(statement["pre_fee_net_cents"], 15708, "pre_fee_net_cents")
        assert_money(statement["clearinghouse_fee_cents"], 79, "fee")
        assert_money(statement["net_settlement_cents"], 15629, "net_settlement_cents")

    def test_the_respondent_may_not_counter_twice_in_a_row(self, api: ApiClient):
        """After CX counters, the state is COUNTERED and only BN may move.

        PRD: "A party acting out of turn — the respondent countering twice in a row, for instance — is refused with `ERR_DISPUTE_TURN_VIOLATION` even though it is a party to the cycle."

        Design: Difficulty/non_linear_state_machine/dispute_open_countered_loop_alternates_actor_and_caps_at_three_rounds
        """
        world, cycle, movement, dispute = _four_seven_hundred_dispute(api)
        first = validate_success(api.counter_dispute(
            dispute["id"], {"counter_amount_cents": 1000}, world.accountant(world.cx)))
        assert first["status"] == "COUNTERED"
        assert first["round_number"] == 1

        again = api.counter_dispute(dispute["id"], {"counter_amount_cents": 1500},
                                   world.accountant(world.cx))
        assert_error_envelope(again, ERR_DISPUTE_TURN_VIOLATION, 403)

        unchanged = validate_success(api.get_dispute(dispute["id"],
                                                    world.accountant(world.bn)))
        assert unchanged["status"] == "COUNTERED"
        assert unchanged["round_number"] == 1
        assert_money(unchanged["counter_amount_cents"], 1000, "counter_amount_cents")


def _three_dimension_car(api):
    """A CX-owned car handed to BN so all three dimensions can be driven apart."""
    world = standard_world(api)
    car_id = register_car(api, "CX 100005", world.xm, world.cx, world=world)
    return world, car_id


def _dimensions(api, world, car_id):
    car = validate_success(api.get_car(car_id, world.owner(world.cx)))
    return car, (car["custody_status"], car["mechanical_status"], car["routing_status"])


class TestCarDimensionsAdvanceIndependently:
    """Custody, mechanical condition and routing move on their own tracks."""

    def test_five_steps_move_one_dimension_at_a_time(self, api: ApiClient):
        """Each action changes exactly one of the three dimensions and leaves the rest.

        PRD: "No transition on one dimension reads or constrains the value of another: a car may legitimately be `ON_FOREIGN_ROAD`, `UNDER_REPAIR` and `OBLIGATION_VIOLATED` at the same time, and clearing the mechanical dimension leaves custody and routing exactly as they were."

        Design: Difficulty/non_linear_state_machine/car_three_state_dimensions_advance_independently_not_as_one_status
        """
        world, car_id = _three_dimension_car(api)
        _, initial = _dimensions(api, world, car_id)
        assert initial == ("ON_HOME_ROAD", "SERVICEABLE", "NO_OBLIGATION")

        set_clock(api, "2026-08-26T00:00:00Z", world)
        validate_success(api.create_interchange_event(
            f.delivery_event_payload(car_id, world.jct, world.cx, world.bn,
                                     "2026-08-26T00:00:00Z", 1000, "LOADED"),
            world.clerk(world.cx)), 201)
        _, after_delivery = _dimensions(api, world, car_id)
        assert after_delivery == ("ON_FOREIGN_ROAD", "SERVICEABLE", "NO_OBLIGATION")

        set_clock(api, "2026-08-26T06:00:00Z", world)
        validate_success(api.report_bad_order(
            car_id,
            f.bad_order_payload("2026-08-26T06:00:00Z", "DOOR-TRACK",
                                "Left door track bent"),
            world.clerk(world.bn)))
        _, after_bad_order = _dimensions(api, world, car_id)
        assert after_bad_order == ("ON_FOREIGN_ROAD", "BAD_ORDER", "NO_OBLIGATION")

        set_clock(api, "2026-08-26T08:00:00Z", world)
        validate_success(api.issue_empty_routing_obligation(
            car_id,
            f.routing_obligation_payload(world.jct, "2026-08-26T08:00:00Z",
                                         "2026-08-30T00:00:00Z"),
            world.owner(world.cx)))
        obligated, after_obligation = _dimensions(api, world, car_id)
        assert after_obligation == ("ON_FOREIGN_ROAD", "BAD_ORDER", "OBLIGATION_ACTIVE")
        assert obligated["prescribed_return_junction_id"] == world.jct
        assert_instant_equals(obligated["obligation_issued_at"],
                              "2026-08-26T08:00:00Z", "obligation_issued_at")
        assert_instant_equals(obligated["obligation_due_at"],
                              "2026-08-30T00:00:00Z", "obligation_due_at")

        set_clock(api, "2026-08-26T18:00:00Z", world)
        validate_success(api.release_to_service(
            car_id, f.release_payload("2026-08-26T18:00:00Z"), world.clerk(world.bn)))
        _, after_release = _dimensions(api, world, car_id)
        assert after_release == ("ON_FOREIGN_ROAD", "SERVICEABLE", "OBLIGATION_ACTIVE")

    def test_clearing_the_defect_leaves_custody_and_routing_untouched(self, api: ApiClient):
        """Release restores SERVICEABLE while the car stays foreign and obligated.

        PRD: "The custody and mechanical dimensions are neither read nor written by this action."

        Design: Difficulty/non_linear_state_machine/car_three_state_dimensions_advance_independently_not_as_one_status
        """
        world, car_id = _three_dimension_car(api)
        set_clock(api, "2026-08-26T00:00:00Z", world)
        validate_success(api.create_interchange_event(
            f.delivery_event_payload(car_id, world.jct, world.cx, world.bn,
                                     "2026-08-26T00:00:00Z", 1000, "LOADED"),
            world.clerk(world.cx)), 201)
        set_clock(api, "2026-08-26T06:00:00Z", world)
        validate_success(api.report_bad_order(
            car_id, f.bad_order_payload("2026-08-26T06:00:00Z", "DOOR-TRACK"),
            world.clerk(world.bn)))
        set_clock(api, "2026-08-26T08:00:00Z", world)
        obligated = validate_success(api.issue_empty_routing_obligation(
            car_id,
            f.routing_obligation_payload(world.jct, "2026-08-26T08:00:00Z",
                                         "2026-08-30T00:00:00Z"),
            world.owner(world.cx)))
        assert obligated["mechanical_status"] == "BAD_ORDER"
        assert obligated["custody_status"] == "ON_FOREIGN_ROAD"
        assert_instant_equals(obligated["bad_order_since"], "2026-08-26T06:00:00Z",
                              "bad_order_since")

        set_clock(api, "2026-08-26T18:00:00Z", world)
        released = validate_success(api.release_to_service(
            car_id, f.release_payload("2026-08-26T18:00:00Z"), world.clerk(world.bn)))

        assert released["mechanical_status"] == "SERVICEABLE"
        assert released["custody_status"] == "ON_FOREIGN_ROAD"
        assert released["routing_status"] == "OBLIGATION_ACTIVE"
        assert released["current_handling_road_id"] == world.bn
        assert released["prescribed_return_junction_id"] == world.jct
        assert_instant_equals(released["obligation_due_at"], "2026-08-30T00:00:00Z",
                              "obligation_due_at")
        assert released["bad_order_since"] is None
        assert_instant_equals(released["bad_order_cleared_at"], "2026-08-26T18:00:00Z",
                              "bad_order_cleared_at")


class TestSettleReadsTheDisputeAggregate:
    """A cycle's own status cannot tell it whether a dispute is still live."""

    def test_an_open_dispute_row_blocks_the_payer_from_remitting(self, api: ApiClient):
        """Settling an EXCHANGED cycle is refused while one dispute is unresolved.

        PRD: "The payer road — and only the payer road, never the payee — then settles, moving `EXCHANGED → SETTLED`, but only if no dispute on the cycle is still `OPEN` or `COUNTERED`; otherwise `ERR_OPEN_DISPUTES_BLOCK_SETTLEMENT`."

        Design: Difficulty/cross_entity_state_dependency/cycle_settle_blocked_by_a_dispute_row_in_another_aggregate
        """
        world, cycle, movement, dispute = _four_seven_hundred_dispute(api)
        assert dispute["status"] == "OPEN"

        refused = api.settle_settlement_cycle(cycle["id"], {},
                                             world.accountant(world.bn))
        assert_error_envelope(refused, ERR_OPEN_DISPUTES_BLOCK_SETTLEMENT, 409)

        stalled = read_cycle(api, world, cycle["id"])
        assert stalled["status"] == "EXCHANGED"
        assert stalled["settled_at"] is None
        assert_money(stalled["net_settlement_cents"], 18614, "net_settlement_cents")

    def test_resolving_the_dispute_releases_the_settlement(self, api: ApiClient):
        """Once the dispute is ACCEPTED the payer remits the reconciled 13938.

        PRD: "Settling stamps `settled_at`, sets `reopen_deadline_at` to 30 days after it, mints a `SETTLEMENT_PAYMENT` ledger entry for the negative of `net_settlement_cents`, and reduces the payer road's `per_diem_exposure_cents` by `net_settlement_cents`."

        Design: Difficulty/cross_entity_state_dependency/cycle_settle_blocked_by_a_dispute_row_in_another_aggregate
        """
        world, cycle, movement, dispute = _four_seven_hundred_dispute(api)
        accepted = validate_success(api.accept_dispute(dispute["id"], {},
                                                      world.accountant(world.cx)))
        assert accepted["status"] == "ACCEPTED"
        assert_money(accepted["resolution_amount_cents"], 4700,
                     "resolution_amount_cents")

        reconciled = read_cycle(api, world, cycle["id"])
        assert reconciled["status"] == "EXCHANGED"
        assert reconciled["variant_applied"] == "RECONCILED"
        assert_money(reconciled["dispute_adjustment_cents"], -4700, "adjustment")
        assert_money(reconciled["pre_fee_net_cents"], 14008, "pre_fee_net_cents")
        assert_money(reconciled["clearinghouse_fee_cents"], 70, "fee")
        assert_money(reconciled["net_settlement_cents"], 13938, "net_settlement_cents")

        settled = validate_success(api.settle_settlement_cycle(
            cycle["id"], {}, world.accountant(world.bn)))
        assert settled["status"] == "SETTLED"
        assert_instant_equals(settled["settled_at"], "2026-09-01T00:00:00Z",
                              "settled_at")
        assert_instant_equals(settled["reopen_deadline_at"], "2026-10-01T00:00:00Z",
                              "reopen_deadline_at")

        payments = [row for row in ledger_entries(api, world.accountant(world.bn),
                                                  settlement_cycle_id=cycle["id"])
                    if row["entry_type"] == "SETTLEMENT_PAYMENT"]
        assert len(payments) == 1
        assert_money(payments[0]["amount_cents"], -13938, "SETTLEMENT_PAYMENT amount")


class TestEmbargoReclaimNeedsAThirdEntity:
    """An EMBARGO reclaim is decided by an order living in another aggregate."""

    def test_an_order_covering_the_window_grounds_the_claim(self, api: ApiClient):
        """A closed order over 2026-08-25 to 2026-08-26 credits the full 2843.

        PRD: "The `split_pct_applied` depends on the ground: 1.0 for `BAD_ORDER` and 1.0 for `EMBARGO`, but only 0.5 for `CUSTOMER_DETENTION`, because the two roads share the cost of a shipper holding the car."

        Design: Difficulty/cross_entity_state_dependency/reclaim_embargo_reason_depends_on_a_third_entity_covering_the_window
        """
        world, movement = closed_segment_world(api)
        assert_money(movement["time_component_cents"], 10900, "time_component_cents")
        assert_hours(movement["chargeable_hours"], 92.00, "chargeable_hours")

        order = issue_embargo(api, world, world.cx, world.jct,
                             "2026-08-25T00:00:00Z", "2026-08-26T00:00:00Z",
                             car_type_id=world.xm)
        assert order["status"] == "ACTIVE"

        claim = file_reclaim(api, world, movement, "EMBARGO",
                            "2026-08-25T00:00:00Z", "2026-08-26T00:00:00Z",
                            supporting_embargo_id=order["id"])
        assert claim["status"] == "FILED"
        assert claim["supporting_embargo_id"] == order["id"]
        assert_hours(claim["claimed_hours"], 24.00, "claimed_hours")

        allowed = allow_reclaim(api, world, claim)
        assert allowed["status"] == "ALLOWED"
        assert_hours(allowed["allowed_hours"], 24.00, "allowed_hours")
        assert float(allowed["split_pct_applied"]) == 1.0
        assert_money(allowed["credit_cents"], 2843, "credit_cents")

        repriced = read_movement(api, world, movement["id"])
        assert_money(repriced["reclaim_credit_cents"], 2843, "reclaim_credit_cents")
        assert_money(repriced["net_hire_cents"], 8621, "net_hire_cents")

    def test_a_window_beyond_the_order_coverage_is_refused(self, api: ApiClient):
        """A claim running to 2026-08-27 is refused against an order ending 2026-08-26.

        PRD: "An embargo-grounded claim additionally requires the cited order to genuinely cover the claim: the order's `car_type_id` must equal the car's `car_type_id`, its `junction_id` must be the junction of either the event that opened the segment or the event that closed it, and the claimed window must lie inside the order's effective coverage as described above; failure is `ERR_EMBARGO_DOES_NOT_COVER_WINDOW`."

        Design: Difficulty/cross_entity_state_dependency/reclaim_embargo_reason_depends_on_a_third_entity_covering_the_window
        """
        world, movement = closed_segment_world(api)
        order = issue_embargo(api, world, world.cx, world.jct,
                             "2026-08-25T00:00:00Z", "2026-08-26T00:00:00Z",
                             car_type_id=world.xm)

        refused = api.create_reclaim_claim(
            f.reclaim_payload(movement["id"], "EMBARGO", "2026-08-26T00:00:00Z",
                              "2026-08-27T00:00:00Z", movement["version"],
                              supporting_embargo_id=order["id"]),
            world.accountant(world.bn),
        )
        assert_error_envelope(refused, ERR_EMBARGO_DOES_NOT_COVER_WINDOW, 422)

        rows = validate_success(api.list_reclaim_claims(
            world.accountant(world.bn), params={"movement_id": movement["id"]}))
        rows = rows if isinstance(rows, list) else rows["items"]
        assert rows == []

        untouched = read_movement(api, world, movement["id"])
        assert_money(untouched["reclaim_credit_cents"], 0, "reclaim_credit_cents")
        assert_money(untouched["net_hire_cents"], 11464, "net_hire_cents")
