"""Non-linear state machines: parallel order axes and the pick-task cycle."""

from test_helpers import (
    PICKER,
    DCM,
    list_lines,
    open_pick,
    setup_order_scenario,
    validate_success,
)


class TestOrderParallelStatusDimensionsMoveIndependently:
    """order_status and fulfillment_status are two axes on one row."""

    def _allocated(self, api):
        return setup_order_scenario(
            api,
            lines_spec=[{"price": 8000, "qty": 4, "bundle": 8, "on_hand": 12,
                         "sku": "SM-3001"}],
            target="ALLOCATED",
        )

    def test_allocation_pairs_released_with_allocated_and_holds_the_units(self, api):
        """PRD §2.10: "An order's `order_status` is `DRAFT`, `RELEASED` or `CANCELLED`,
        and its `fulfillment_status` is one of `AWAITING_RELEASE`, `ALLOCATED`, `PICKED`,
        `SHIPPED` or `RETURNED` — the two dimensions evolve independently".
        PRD §3.4: "At the center, each affected stock row has `reserved_units` increased by
        the units allocated to it and `available_units` recomputed as the difference
        between `on_hand_units` and `reserved_units`".

        Design: Difficulty/non_linear_state_machine/order_parallel_status_dimensions_move_independently
        """
        scenario = self._allocated(api)
        stock_id = scenario["stock_rows"][0]["id"]

        order = validate_success(api.get_order(scenario["order"]["id"],
                                               scenario["acct_headers"]))
        stock = validate_success(api.get_stock(stock_id, DCM))

        assert order["order_status"] == "RELEASED"
        assert order["fulfillment_status"] == "ALLOCATED"
        assert stock["reserved_units"] == 4
        assert stock["available_units"] == 8

    def test_cancelling_while_allocated_rolls_the_fulfillment_axis_back(self, api):
        """PRD §3.3: "Every line then returns to `line_status` `PENDING` with
        `allocated_units` reset to 0, `fulfillment_status` returns to `AWAITING_RELEASE`,
        `order_status` becomes `CANCELLED`, and the order's `version` increments by 1."
        PRD §3.3: "for every line still in `line_status` `ALLOCATED`, the units reserved at
        that line's distribution center are released, so the stock row's `reserved_units` is
        decremented by `allocated_units` and its `available_units` recomputed".

        Design: Difficulty/non_linear_state_machine/order_parallel_status_dimensions_move_independently
        """
        scenario = self._allocated(api)
        stock_id = scenario["stock_rows"][0]["id"]

        validate_success(api.cancel_order(scenario["order"]["id"],
                                          scenario["acct_headers"]))

        after = validate_success(api.get_order(scenario["order"]["id"],
                                               scenario["acct_headers"]))
        assert after["order_status"] == "CANCELLED"
        assert after["fulfillment_status"] == "AWAITING_RELEASE", (
            "the fulfillment axis rolled back independently of the order axis"
        )

        stock = validate_success(api.get_stock(stock_id, DCM))
        assert stock["reserved_units"] == 0
        assert stock["available_units"] == 12

        lines = list_lines(api, scenario["acct"], scenario["order"])
        assert lines[0]["line_status"] == "PENDING"
        assert lines[0]["allocated_units"] == 0


class TestPickTaskReopensAfterAShortClosedPick:
    """A short-closed pick is re-entered on the same task row while the order holds."""

    def _short_closed(self, api):
        scenario = setup_order_scenario(
            api,
            lines_spec=[
                {"price": 6000, "qty": 5, "bundle": 8, "on_hand": 10, "sku": "SM-3101"},
                {"price": 6000, "qty": 1, "bundle": 8, "on_hand": 10, "sku": "SM-3102"},
            ],
            target="ALLOCATED",
        )
        line = list_lines(api, scenario["acct"], scenario["order"])[0]
        task = open_pick(api, order=scenario["order"], line=line, requested_units=5)
        task = validate_success(api.complete_pick(
            scenario["order"]["id"], line["id"], {"actual_units": 3}, PICKER))
        return scenario, line, task

    def test_a_short_pick_closes_the_task_and_records_the_shortage(self, api):
        """PRD §3.6: "The picker reports the units actually pulled as `actual_units`, and
        the task records `picked_units` as that value and computes `shortage_units` as
        `requested_units` minus `actual_units` when the pick fell short, and as 0
        otherwise."
        PRD §3.6: "a task whose picked units equal the requested units lands in `PICKED`,
        and one that came up short lands in `SHORT_CLOSED`."

        Design: Difficulty/non_linear_state_machine/pick_task_reopens_after_a_short_closed_pick
        """
        scenario, line, task = self._short_closed(api)

        current = validate_success(api.get_pick_task(task["id"], PICKER))
        assert current["pick_status"] == "SHORT_CLOSED"
        assert current["picked_units"] == 3
        assert current["shortage_units"] == 2

        order = validate_success(api.get_order(scenario["order"]["id"],
                                               scenario["acct_headers"]))
        assert order["fulfillment_status"] == "ALLOCATED", (
            "another line is still unpicked, so the order never left ALLOCATED"
        )

    def test_a_second_pick_reopens_the_same_task_to_picking(self, api):
        """PRD §3.6: "While the order's `fulfillment_status` is still `ALLOCATED` and the
        line's damage claim is still `OPEN`, the picker may start a fresh pick on the same
        line, which moves the line's `line_status` back to `ALLOCATED`, returns the task
        from `SHORT_CLOSED` to `PICKING`, and increments the order's `version` by 1."

        Design: Difficulty/non_linear_state_machine/pick_task_reopens_after_a_short_closed_pick
        """
        scenario, line, task = self._short_closed(api)

        validate_success(api.pick_line(scenario["order"]["id"], line["id"],
                                       {"requested_units": 2}, PICKER))

        reopened = validate_success(api.get_pick_task(task["id"], PICKER))
        assert reopened["id"] == task["id"], "the same task row is reused, not a new one"
        assert reopened["pick_status"] == "PICKING"

        lines = list_lines(api, scenario["acct"], scenario["order"])
        assert lines[0]["line_status"] == "ALLOCATED"

        order = validate_success(api.get_order(scenario["order"]["id"],
                                               scenario["acct_headers"]))
        assert order["fulfillment_status"] == "ALLOCATED"