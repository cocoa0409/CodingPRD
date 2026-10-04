"""Combinatorial formulas: nested-min route-day capacity and per-line rounding."""
from test_helpers import (
    api_client,
    create_assignment,
    create_order,
    create_product,
    create_rep,
    create_route,
    create_route_day,
    create_store,
    get_route_day,
    load_route_day,
    lot_entry,
    make_rep_headers,
    make_supervisor_headers,
    order_line,
    set_clock,
    start_route_day,
    validate_paginated,
    validate_success,
)


def list_order_lines(params):
    return validate_paginated(
        api_client.list_order_lines(make_supervisor_headers(), params=params)
    )


class TestEventDayCapacityNestedMin:
    def test_truck_cap_binds_over_base_plus_surge(self, api):
        """PRD §3.2: "the day's capacity_cases is computed as the route's
        base_capacity_cases plus the surge — where the surge is event_surge_cases
        on an event day and zero on a standard day regardless of any payload
        value (a positive event_surge_cases on a non-event day is ERR_VALIDATION)
        — capped at the route's truck_cap_cases; equality with the cap is
        permitted."

        Design: Difficulty/combinatorial_formula/event_day_capacity_nested_min_with_surge_branch
        """
        set_clock()
        rep = create_rep()
        store = create_store()
        product = create_product(case_price_cents=300)
        route = create_route(rep["id"], base_capacity_cases=100, truck_cap_cases=120)
        create_assignment(route["id"], store["id"], service_weekdays=["TUE", "WED"])

        event_day = create_route_day(
            route["id"],
            service_date="2026-09-01",
            is_event_day=True,
            event_surge_cases=50,
        )
        plain_day = create_route_day(route["id"], service_date="2026-09-02")

        # min(100 + 50, 120) — the truck ceiling binds, not 150.
        assert event_day["capacity_cases"] == 120
        # Surge branch not taken on a standard day.
        assert plain_day["capacity_cases"] == 100

    def test_load_at_exact_capped_capacity_succeeds(self, api):
        """PRD §3.3: "The summed loaded_cases across the payload may not exceed
        the day's capacity_cases — ERR_CAPACITY_EXCEEDED when it does."
        PRD §3.2: "equality with the cap is permitted."

        Design: Difficulty/combinatorial_formula/event_day_capacity_nested_min_with_surge_branch
        """
        set_clock()
        rep = create_rep()
        store = create_store()
        p1 = create_product(sku="P-1", case_price_cents=300)
        p2 = create_product(sku="P-2", name="Dips", case_price_cents=400, shelf_life_days=45)
        route = create_route(rep["id"], base_capacity_cases=100, truck_cap_cases=120)
        create_assignment(route["id"], store["id"], service_weekdays=["TUE"])
        event_day = create_route_day(
            route["id"],
            service_date="2026-09-01",
            is_event_day=True,
            event_surge_cases=50,
        )

        # Load exactly 70 + 50 == 120 == capacity: accepted.
        resp = api.load_route_day(
            event_day["id"],
            {
                "lots": [
                    lot_entry(p1["id"], "L-1", "2026-09-20", 70),
                    lot_entry(p2["id"], "L-2", "2026-09-20", 50),
                ]
            },
            make_rep_headers(rep["id"]),
        )
        day = validate_success(resp)
        assert day["status"] == "LOADED"
        assert day["loaded_cases"] == 120
        assert day["capacity_cases"] == 120


class TestPerLineRoundingThenSum:
    def _setup_started_day_with_335_product(self):
        set_clock()
        rep = create_rep()
        store = create_store()
        product = create_product(case_price_cents=335)
        route = create_route(rep["id"])
        create_assignment(route["id"], store["id"])
        day = create_route_day(route["id"])
        load_route_day(
            day["id"], [lot_entry(product["id"], "L-1", "2026-09-20", 10)], rep
        )
        start_route_day(day["id"], rep)
        return rep, store, product, day

    def test_three_discounted_lines_round_per_line_then_sum(self, api):
        """PRD §2.6: "Order line pricing rounds each line's total to whole cents
        individually and only then sums the rounded line totals into the order's
        gross_total_cents — rounding the unrounded sum is not equivalent and is
        not permitted."

        Design: Difficulty/combinatorial_formula/per_line_rounding_then_sum_beats_sum_then_round
        """
        rep, store, product, day = self._setup_started_day_with_335_product()

        resp = api.create_order(
            {
                "route_day_id": day["id"],
                "store_id": store["id"],
                "lines": [
                    {"product_id": product["id"], "qty_ordered_cases": 1, "line_discount_pct": 0.05},
                    {"product_id": product["id"], "qty_ordered_cases": 1, "line_discount_pct": 0.05},
                    {"product_id": product["id"], "qty_ordered_cases": 1, "line_discount_pct": 0.05},
                ],
            },
            make_rep_headers(rep["id"]),
        )
        order = validate_success(resp, expected_status=201)

        # 3 x round_half_up(335 * 0.95) = 3 x 318 = 954; the forbidden
        # sum-then-round outcome would be 955.
        assert order["gross_total_cents"] == 954
        assert order["gross_total_cents"] != 955

        lines, _ = list_order_lines({"order_id": order["id"]})
        assert len(lines) == 3
        for line in lines:
            assert line["line_total_cents"] == 318

    def test_gross_total_equals_sum_of_rounded_line_totals(self, api):
        """PRD §3.4: "Each line's line_total_cents is the line's qty_ordered_cases
        multiplied by the product's case_price_cents, multiplied by one minus
        the line_discount_pct, rounded half up to whole cents; the order's
        gross_total_cents is the sum of those per-line rounded totals."

        Design: Difficulty/combinatorial_formula/per_line_rounding_then_sum_beats_sum_then_round
        """
        rep, store, product, day = self._setup_started_day_with_335_product()

        resp = api.create_order(
            {
                "route_day_id": day["id"],
                "store_id": store["id"],
                "lines": [
                    {"product_id": product["id"], "qty_ordered_cases": 1, "line_discount_pct": 0.05},
                    {"product_id": product["id"], "qty_ordered_cases": 2},
                ],
            },
            make_rep_headers(rep["id"]),
        )
        order = validate_success(resp, expected_status=201)

        lines, _ = list_order_lines({"order_id": order["id"]})
        # Per-line: 318 + round_half_up(2 * 335 * 1) = 318 + 670 = 988.
        assert order["gross_total_cents"] == sum(l["line_total_cents"] for l in lines)
        assert order["gross_total_cents"] == 988
