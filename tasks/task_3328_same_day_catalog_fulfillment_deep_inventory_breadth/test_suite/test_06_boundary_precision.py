"""Boundary precision: inclusive thresholds on the SKU census and the line count."""

from test_helpers import (
    DCM,
    add_stock_row,
    account_headers,
    setup_account,
    setup_center,
    setup_clock,
    setup_curated_items,
    validate_paginated,
    validate_success,
)


class TestDcPositioningSkuCountBoundaryInclusive:
    """The in-stock SKU census decides the flag, and the count is inclusive at 2."""

    def _census(self, api):
        setup_clock(api)
        bos = setup_center(api, code="BOS", region="NORTHEAST")
        dal = setup_center(api, code="DAL", region="SOUTHWEST", local_zone="America/Chicago",
                           utc_offset_minutes=-300, transit_seconds=43200)
        sea = setup_center(api, code="SEA", region="WEST", local_zone="America/Los_Angeles",
                           utc_offset_minutes=-420, transit_seconds=36000)
        acct = setup_account(api)
        catalog = setup_curated_items(
            api,
            specs=[
                {"sku": "DD-1001", "price": 3000, "bundle": 8, "long_tail": False},
                {"sku": "DD-1002", "price": 3200, "bundle": 8, "long_tail": False},
                {"sku": "DD-1003", "price": 9000, "bundle": 4, "long_tail": True},
            ],
            account=acct, dc=None, with_stock=False, sku_prefix="DD")
        non_lt, non_lt2, lt = catalog["items"]
        add_stock_row(api, item=non_lt, dc=bos, account=acct, on_hand=10)
        add_stock_row(api, item=lt, dc=bos, account=acct, on_hand=5)
        add_stock_row(api, item=lt, dc=dal, account=acct, on_hand=5)
        add_stock_row(api, item=non_lt, dc=sea, account=acct, on_hand=7)
        add_stock_row(api, item=non_lt2, dc=sea, account=acct, on_hand=0)
        for dc in (bos, dal, sea):
            validate_success(api.roll_cutoff(dc["id"], DCM))
        return {"bos": bos, "dal": dal, "sea": sea}

    def _rows(self, api, dc):
        rows, _meta = validate_paginated(api.list_stock(
            DCM, {"dc_id": dc["id"], "limit": 100, "offset": 0}))
        return rows

    def test_two_in_stock_skus_satisfy_the_threshold_inclusively(self, api):
        """PRD §3.8: "If that count is at least the positioning threshold of 2, the
        classification is `OK`."
        PRD §3.8: "The stock rows eligible for the count are those whose `on_hand_units` is
        at least 1".

        Design: Difficulty/boundary_precision_check/dc_positioning_sku_count_boundary_inclusive
        """
        context = self._census(api)
        rows = self._rows(api, context["bos"])

        assert len(rows) == 2
        assert all(row["positioning_flag"] == "OK" for row in rows), (
            "exactly two distinct in-stock SKUs already satisfy the inclusive threshold"
        )

    def test_one_in_stock_long_tail_sku_lands_in_the_long_tail_deficit_branch(self, api):
        """PRD §3.8: "If the count is greater than 0 but every one of the ordered rows
        belongs to an item with `long_tail` true, the classification is
        `LONG_TAIL_DEFICIT`."

        Design: Difficulty/boundary_precision_check/dc_positioning_sku_count_boundary_inclusive
        """
        context = self._census(api)
        rows = self._rows(api, context["dal"])

        assert len(rows) == 1
        assert rows[0]["positioning_flag"] == "LONG_TAIL_DEFICIT"

    def test_a_zero_on_hand_row_is_excluded_from_the_census(self, api):
        """PRD §3.8: "The stock rows eligible for the count are those whose `on_hand_units`
        is at least 1 — no status filter applies, and an item with zero on hand is simply
        not counted."
        PRD §3.8: "In every other case — including the case where the count is 0 — the
        classification is `UNDERSTOCKED`."

        Design: Difficulty/boundary_precision_check/dc_positioning_sku_count_boundary_inclusive
        """
        context = self._census(api)
        rows = self._rows(api, context["sea"])

        assert len(rows) == 2
        assert all(row["positioning_flag"] == "UNDERSTOCKED" for row in rows), (
            "the zero on-hand row does not count, so the census stays at 1 and the center "
            "is UNDERSTOCKED rather than OK"
        )


class TestSmallLineReductionCountBoundaryFiveVersusFour:
    """One extra eligible line crosses the count threshold and changes the fee."""

    def _pair(self, api):
        setup_clock(api)
        dc = setup_center(api)
        acct = setup_account(api)
        catalog = setup_curated_items(
            api,
            specs=[{"sku": f"BL-{2000 + i}", "price": 12000, "bundle": 8, "on_hand": 20}
                   for i in range(1, 6)],
            account=acct, dc=dc, sku_prefix="BL")
        items = catalog["items"]
        headers = account_headers(acct)

        def build(item_count):
            lines = [{"item_id": item["id"], "quantity": 1} for item in items[:item_count]]
            order = validate_success(api.create_order(
                {"account_id": acct["id"], "lines": lines}, headers), 201)
            released = validate_success(api.release_order(order["id"], headers))
            return validate_success(api.allocate_order(
                order["id"], {"expected_order_version": released["version"]}, headers))

        return build(4), build(5), headers

    def test_four_lines_keep_the_flat_fee_while_five_trigger_the_reduction(self, api):
        """PRD §3.5: "Step two applies an order-level threshold reduction: if the number of
        eligible lines is at least 5 — the small-line count threshold — then each eligible
        line's raw fee is reduced by 250 cents, floored at 0 so a fee never becomes
        negative."

        Design: Difficulty/boundary_precision_check/small_line_reduction_count_boundary_five_versus_four
        """
        four, five, _headers = self._pair(api)

        assert four["line_count"] == 4
        assert four["total_small_line_fee_cents"] == 1440, (
            "four eligible lines never trigger the count reduction, so each keeps its "
            "full flat 360-cent fee and the handling total is 1440"
        )
        assert five["line_count"] == 5
        assert five["total_small_line_fee_cents"] == 2992, (
            "five eligible lines lose 250 cents each before the pool is discounted"
        )

    def test_one_more_line_moves_the_handling_fee_by_32_cents(self, api):
        """PRD §3.5: "Step four distributes that total across the eligible lines by largest
        remainder."
        PRD §3.5: "the order's total handling fee is `D` minus that discount. The pool is
        rounded once, at this point, and never again."

        Design: Difficulty/boundary_precision_check/small_line_reduction_count_boundary_five_versus_four
        """
        four, five, headers = self._pair(api)
        four_lines, _meta = validate_paginated(api.list_order_lines(
            four["id"], headers, {"limit": 10, "offset": 0}))
        five_lines, _meta = validate_paginated(api.list_order_lines(
            five["id"], headers, {"limit": 10, "offset": 0}))

        assert four["total_small_line_fee_cents"] == 1440
        assert five["total_small_line_fee_cents"] == 2992
        assert four["total_small_line_fee_cents"] - five["total_small_line_fee_cents"] == -1552, (
            "the fifth line applies the 250-cent reduction to every line, so the "
            "five-line order pays 1552 cents less than the four-line order"
        )
        assert all(line["allocated_small_line_fee_cents"] == 360 for line in four_lines)
        assert sorted(line["allocated_small_line_fee_cents"] for line in five_lines) == [
            598, 598, 598, 599, 599
        ], "the five-line fee is spread as 598/599 across the five eligible lines"