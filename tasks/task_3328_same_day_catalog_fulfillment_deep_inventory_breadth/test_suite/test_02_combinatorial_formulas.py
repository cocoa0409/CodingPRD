"""Combinatorial formulas: nested rounding order and pinned evaluation order."""

from test_helpers import (
    PICKER,
    confirm_cutoff,
    list_lines,
    setup_five_line_fee_order,
    setup_order_scenario,
    setup_released_order,
    validate_success,
)


class TestHandlingFeeNestedRoundingOrder:
    """Five eligible lines of 12000 cents: round the pool, then allocate."""

    PRICES = [12000, 24000, 36000, 48000, 60000]

    def _allocated(self, api):
        # Design recipe: five curated items each priced 12000 cents, with order-line
        # quantities 1..5, so the line subtotals are 12000/24000/36000/48000/60000.
        scenario = setup_five_line_fee_order(api, prices=[12000] * 5,
                                             quantities=[1, 2, 3, 4, 5])
        order = validate_success(
            api.allocate_order(scenario["order"]["id"],
                               {"expected_order_version": scenario["order"]["version"]},
                               scenario["acct_headers"])
        )
        lines = list_lines(api, scenario["acct"], scenario["order"])
        return scenario, order, lines

    def test_pool_is_rounded_once_and_equals_the_allocated_shares(self, api):
        """PRD §3.5: "the order-level pool `D` is the sum over eligible lines of the
        reduced raw fees".
        PRD §3.5: "an order-level discount is computed by multiplying `D` by 0.37 and
        rounding half up to the cent".
        PRD §3.5: "the order's `total_small_line_fee_cents` holds the total fee, and each
        eligible line's `allocated_small_line_fee_cents` holds its share".
        PRD §3.5: "if the number of eligible lines is at least 5 — the small-line count
        threshold — then each eligible line's raw fee is reduced by 250 cents, floored at
        0 so a fee never becomes negative".

        Design: Difficulty/combinatorial_formula/order_handling_fee_nested_rounding_order
        """
        scenario, order, lines = self._allocated(api)

        assert order["line_count"] == 5
        assert order["total_small_line_fee_cents"] == 10552, (
            f"expected 10552, got {order['total_small_line_fee_cents']}"
        )
        shares = [line["allocated_small_line_fee_cents"] for line in lines]
        assert sum(shares) == 10552, (
            f"the allocated shares must sum to the order total, got {sum(shares)}"
        )
        assert sorted(shares) == [2110, 2110, 2110, 2111, 2111]

    def test_leftover_cents_go_to_the_largest_subtotal_lines(self, api):
        """PRD §3.5: "The allocation order is by `line_subtotal_cents` descending, ties
        broken by `created_at` ascending; each line first receives an integer
        floor-division share of the total, and the leftover cents produced by the
        flooring are handed out one cent at a time to the lines at the front of that
        order."

        Design: Difficulty/combinatorial_formula/order_handling_fee_nested_rounding_order
        """
        scenario, order, lines = self._allocated(api)

        ranked = sorted(lines, key=lambda line: -line["line_subtotal_cents"])
        assert ranked[0]["line_subtotal_cents"] == 60000
        assert ranked[1]["line_subtotal_cents"] == 48000
        assert ranked[0]["allocated_small_line_fee_cents"] == 2111
        assert ranked[1]["allocated_small_line_fee_cents"] == 2111
        assert [line["allocated_small_line_fee_cents"] for line in ranked[2:]] == [2110, 2110, 2110]

        for line in lines:
            assert line["line_total_cents"] == (
                line["line_subtotal_cents"] + line["allocated_small_line_fee_cents"]
            ), "line_total_cents must be the subtotal plus the line's own fee share"


class TestOrderTotalFactorFirstEvaluationOrder:
    """Two 1000-cent lines: the fee is sized on the raw line, never the discounted one."""

    def _shipped(self, api):
        scenario = setup_released_order(
            api,
            lines_spec=[
                {"price": 1000, "qty": 1, "bundle": 8, "on_hand": 4, "sku": "SKU-2101"},
                {"price": 1000, "qty": 1, "bundle": 8, "on_hand": 4, "sku": "SKU-2102"},
            ],
            # The PRD's 798/1160 freight illustration is a cross-zone shipment: it is
            # the 450 base plus the 275 zone surcharge, times the urgency multiplier.
            account_overrides={"delivery_zone": "America/Chicago"},
        )
        order = validate_success(
            api.allocate_order(scenario["order"]["id"],
                               {"expected_order_version": scenario["order"]["version"]},
                               scenario["acct_headers"])
        )
        for line in list_lines(api, scenario["acct"], scenario["order"]):
            api.pick_line(scenario["order"]["id"], line["id"], {"requested_units": 1}, PICKER)
            api.complete_pick(scenario["order"]["id"], line["id"], {"actual_units": 1}, PICKER)
        shipment = confirm_cutoff(api, order=scenario["order"], account=scenario["acct"])
        after = validate_success(api.get_order(scenario["order"]["id"],
                                               scenario["acct_headers"]))
        return scenario, after, shipment

    def test_fee_is_keyed_on_the_raw_line_not_the_discounted_line(self, api):
        """PRD §3.5: "Take two eligible lines of 1000 cents each."
        PRD §3.5: "Each line's own-precision fee is 1000 multiplied by 0.03 — exactly 30
        cents, no rounding needed — for a fee term of 60 cents and an order total of 2000
        cents."
        PRD §3.5: "the fee is computed on the line's own `line_subtotal_cents`, before the
        discount, and rounding half up is applied once per eligible line and once on the
        discounted material base, never on the sum".

        Design: Difficulty/combinatorial_formula/order_total_factor_first_evaluation_order
        """
        scenario, order, shipment = self._shipped(api)

        assert order["line_count"] == 2
        # PRD 3.5: "Each line's own-precision fee is 1000 multiplied by 0.03 — exactly
        # 30 cents, no rounding needed — for a fee term of 60 cents and an order total
        # of 2000 cents." Two eligible lines are below the count threshold of 5, so no
        # order-level pool reduction applies.
        assert order["total_small_line_fee_cents"] == 60, (
            f"raw-basis fee term expected 60, got {order['total_small_line_fee_cents']}"
        )
        assert order["order_total_cents"] == 2000, (
            f"order total expected 2000, got {order['order_total_cents']}"
        )

    def test_evaluating_the_discount_first_is_not_the_implementation(self, api):
        """PRD §3.5: "Had the fee instead been sized off the already-discounted line, the
        arithmetic would have been 0.97 multiplied by 0.03 and then by 1000, giving 29.1
        cents per line, which rounds half up to 29 cents, for a fee term of 58 cents and
        a total of 1998 cents — a two-cent error introduced purely by evaluating the
        discount before the fee."

        Design: Difficulty/combinatorial_formula/order_total_factor_first_evaluation_order
        """
        scenario, order, shipment = self._shipped(api)

        assert order["order_total_cents"] != 1998, (
            "a total of 1998 would mean the fee was sized on the discounted line "
            "(0.97 * 0.03 * 1000 = 29.1) instead of the raw line"
        )
        assert order["total_small_line_fee_cents"] != 58
        assert order["fulfillment_status"] == "SHIPPED"
        # PRD 3.7: on identical weight, zone and account the estimate variant gives 798
        # cents where the certified figure gives 1160. The order is certified while the
        # center is still ahead of its cutoff by more than the 120-minute threshold, so
        # the urgency multiplier is the 1.1 figure: (450 + 275) * 1.1 = 797.5 -> 798.
        assert shipment["freight_rate_cents"] == 798, (
            f"certified freight rate expected 798, got {shipment['freight_rate_cents']}"
        )
        assert shipment["freight_surcharge_cents"] == 0
        assert shipment["freight_charge_cents"] == 798
        assert order["freight_charge_cents"] == shipment["freight_charge_cents"]