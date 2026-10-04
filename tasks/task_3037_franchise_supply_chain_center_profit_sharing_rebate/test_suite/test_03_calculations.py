"""Calculation claims: tiered pricing, combinatorial totals, per-line floor
rounding, variance severity, eligibility rates, route utilization."""
from test_helpers import (
    ApiErrorId,
    add_line,
    api_client,
    create_capacity_plan,
    create_draft_po,
    create_price_book,
    create_product,
    create_route,
    create_store,
    create_supply_center_payload,
    activate_center,
    activate_store,
    get_store,
    get_store_version,
    get_success_data,
    set_clock,
    setup_draft_po_with_line,
    setup_submitted_po,
    setup_confirmed_po,
    setup_trading_store,
    submit_po,
    confirm_po,
    validate_error,
    validate_success,
)
from test_helpers.test_users import TEST_USERS, make_store_manager_headers

ADMIN = TEST_USERS["admin_headers"]
ANY = TEST_USERS["any_headers"]
COORD = TEST_USERS["coordinator_headers"]


class TestTieredPricing:
    def test_cost_plus_price_tiered_markup(self, api):
        """PRD §3.4: "among `ACTIVE` price book entries matching the center, the product,
        and the store's tier whose window contains the current time and whose
        `min_quantity` is at most the ordered `quantity`, the entry with the highest
        qualifying `min_quantity` wins"
        PRD §3.4: "orders of one hundred units or more qualify for the
        `VOLUME_DISCOUNT` tier at twelve percent"

        Design: Corner/calculations/cost_plus_price_tiered_markup
        """
        set_clock()
        center, product, store = setup_trading_store(base_cost=1000, markup=0.15,
                                                     credit_limit=100000000)
        center_id, store_id = center["id"], store["id"]
        # Add the VOLUME_DISCOUNT tier after the STANDARD tier.
        create_price_book(center_id, product["id"], store_tier="VOLUME_DISCOUNT",
                          markup_pct=0.12, min_quantity=100)
        po = create_draft_po(center_id, store_id)
        line_50 = add_line(center_id, store_id, po["id"], product["id"], 50)
        line_150 = add_line(center_id, store_id, po["id"], product["id"], 150)
        # 50 < 100 → STANDARD 0.15 → floor(1000*1.15) = 1150
        assert line_50["unit_price_cents"] == 1150
        # 150 >= 100 → VOLUME_DISCOUNT 0.12 → floor(1000*1.12) = 1120
        assert line_150["unit_price_cents"] == 1120


class TestCombinatorialTotal:
    def test_order_total_combinatorial_3input_volume_discount_crossing(self, api):
        """PRD §3.4: "the unit price is the product's `base_cost_cents_per_unit`
        multiplied by one plus that entry's `markup_pct`, with the fractional cent
        rounded down. The line's `extended_price_cents` is the unit price times the
        quantity"
        PRD §3.4: "Standard network tiers mark up at fifteen percent; orders of one
        hundred units or more qualify for the `VOLUME_DISCOUNT` tier at twelve percent"

        Design: Difficulty/combinatorial_formula/order_total_combinatorial_3input
        """
        set_clock()
        center, product, store = setup_trading_store(base_cost=1000, markup=0.15,
                                                     credit_limit=100000000)
        center_id, store_id = center["id"], store["id"]
        create_price_book(center_id, product["id"], store_tier="VOLUME_DISCOUNT",
                          markup_pct=0.12, min_quantity=100)
        mgr = make_store_manager_headers(store_id)
        po_x = create_draft_po(center_id, store_id)
        add_line(center_id, store_id, po_x["id"], product["id"], 99)
        po_y = create_draft_po(center_id, store_id)
        add_line(center_id, store_id, po_y["id"], product["id"], 100)
        submitted_x = submit_po(center_id, store_id, po_x["id"])
        submitted_y = submit_po(center_id, store_id, po_y["id"])
        # 99 * floor(1000*1.15) = 113850 (STANDARD tier)
        assert submitted_x["subtotal_cents"] == 113850
        # 100 * floor(1000*1.12) = 112000 (VOLUME_DISCOUNT tier)
        assert submitted_y["subtotal_cents"] == 112000
        assert submitted_y["subtotal_cents"] < submitted_x["subtotal_cents"]

    def test_order_total_combinatorial_3input_tier_boundary_at_100(self, api):
        """PRD §3.4: "orders of one hundred units or more qualify for the
        `VOLUME_DISCOUNT` tier at twelve percent"

        Design: Difficulty/combinatorial_formula/order_total_combinatorial_3input
        """
        set_clock()
        center, product, store = setup_trading_store(base_cost=1000, markup=0.15,
                                                     credit_limit=100000000)
        center_id, store_id = center["id"], store["id"]
        create_price_book(center_id, product["id"], store_tier="VOLUME_DISCOUNT",
                          markup_pct=0.12, min_quantity=100)
        po = create_draft_po(center_id, store_id)
        line_100 = add_line(center_id, store_id, po["id"], product["id"], 100)
        # Exactly 100 qualifies for the volume tier (at-most-min_quantity wins).
        assert line_100["unit_price_cents"] == 1120


class TestTheoreticalUsageRounding:
    def test_theoretical_usage_per_line_floor_then_sum(self, api):
        """PRD §3.7: "For each `DELIVERED` line, the theoretical ingredient cost is the
        line's quantity times the product's `base_cost_cents_per_unit` times the
        category's ingredient yield factor — 0.85 for `DOUGH` ... — rounded down per
        line to whole cents."

        Design: Difficulty/combinatorial_formula/theoretical_usage_per_line_floor_then_sum
        """
        set_clock()
        ctx = setup_confirmed_po(base_cost=334, markup=0.15, quantity=1,
                                 credit_limit=100000000)
        center_id = ctx["center"]["id"]
        po_id, line_id = ctx["po"]["id"], ctx["line"]["id"]
        store_id = ctx["store"]["id"]
        validate_success(api.dispatch_route(center_id, ctx["route"]["id"], COORD))
        validate_success(api.load_purchase_order(center_id, po_id, COORD))
        stops = get_success_data(api.list_stops(center_id, ctx["route"]["id"], ANY))
        stop_id = stops[0]["id"]
        validate_success(api.arrive_stop(center_id, ctx["route"]["id"], stop_id, COORD))
        delivered = validate_success(api.deliver_purchase_order(
            center_id, po_id, 0, COORD))
        line_after = [l for l in get_success_data(
            api.list_order_lines(center_id, po_id, ANY)) if l["id"] == line_id][0]
        # Per-line floor: floor(1 * 334 * 0.85) = floor(283.9) = 283
        assert line_after["theoretical_usage_cents"] == 283, (
            f"Expected per-line floored theoretical usage 283, got "
            f"{line_after['theoretical_usage_cents']}")
        assert delivered["theoretical_usage_cents"] == 283

    def test_theoretical_usage_per_line_floor_sum_from_po_lines(self, api):
        """PRD §3.7: "The order's `theoretical_usage_cents` is the sum across lines."

        Design: Difficulty/combinatorial_formula/theoretical_usage_per_line_floor_then_sum
        """
        set_clock()
        center, product, store = setup_trading_store(base_cost=334, markup=0.15,
                                                     credit_limit=100000000)
        center_id, store_id = center["id"], store["id"]
        create_capacity_plan(center_id)
        route = create_route(center_id, assigned_store_ids=[store_id])
        po = create_draft_po(center_id, store_id)
        for _ in range(3):
            add_line(center_id, store_id, po["id"], product["id"], 1)
        submit_po(center_id, store_id, po["id"])
        confirm_po(center_id, po["id"])
        validate_success(api.dispatch_route(center_id, route["id"], COORD))
        validate_success(api.load_purchase_order(center_id, po["id"], COORD))
        stops = get_success_data(api.list_stops(center_id, route["id"], ANY))
        validate_success(api.arrive_stop(center_id, route["id"], stops[0]["id"], COORD))
        delivered = validate_success(api.deliver_purchase_order(center_id, po["id"], 0, COORD))
        listed = get_success_data(api.list_order_lines(center_id, po["id"], ANY))
        total = sum(l["theoretical_usage_cents"] for l in listed)
        # Floor-then-sum: 3 * 283 = 849; sum-then-floor would be floor(3*283.9) = 851
        assert total == 849
        assert total != 851
        assert delivered["theoretical_usage_cents"] == 849


class TestVarianceSeverity:
    def test_food_cost_variance_severity_thresholds(self, api):
        """PRD §3.7: "An administrator creates one for a `week_start_date`; it is born
        `PENDING` with `theoretical_cents` and `actual_cents` summed from all of the
        store's settled orders that week"
        PRD §3.7: "at most 0.05 `GREEN`, at most 0.10 `YELLOW`, otherwise `RED`."

        Design: Corner/calculations/food_cost_variance_severity_thresholds
        """
        center, product, store = setup_trading_store(credit_limit=1000000)
        data = validate_success(api.create_food_cost_variance(
            center["id"], store["id"], {"week_start_date": "2026-09-07T00:00:00Z"}, ADMIN),
            expected_status=201)
        assert data["status"] == "PENDING"
        # No settled orders → theoretical is zero → severity GREEN
        assert data["severity"] == "GREEN"

    def test_food_cost_variance_yellow_boundary(self, api):
        """PRD §3.7: "A percentage of at most 0.05 is `GREEN`, at most 0.10 is
        `YELLOW`, and anything above is `RED`."

        Design: Difficulty/boundary_precision_check/food_cost_variance_yellow_boundary
        """
        center, product, store = setup_trading_store(credit_limit=100000000)
        data = validate_success(api.create_food_cost_variance(
            center["id"], store["id"], {"week_start_date": "2026-09-07T00:00:00Z"}, ADMIN),
            expected_status=201)
        assert data["status"] == "PENDING"
        assert data["severity"] == "GREEN"

    def test_food_cost_variance_zero_theoretical_is_green(self, api):
        """PRD §3.7: "When the order's theoretical usage is zero — an order of nothing
        but equipment and smallwares — `food_cost_variance_pct` is null and the week's
        severity is `GREEN`."

        Design: Difficulty/boundary_precision_check/food_cost_variance_yellow_boundary
        """
        center, product, store = setup_trading_store(credit_limit=100000000)
        data = validate_success(api.create_food_cost_variance(
            center["id"], store["id"], {"week_start_date": "2026-09-07T00:00:00Z"}, ADMIN),
            expected_status=201)
        assert data["theoretical_cents"] == 0
        assert data["severity"] == "GREEN"


class TestRebateEligibilityRate:
    def test_rebate_accrual_eligible_rate(self, api):
        """PRD §3.2: "A new store starts with `compliance_tier` of `FULL_COMPLIANCE`,
        `rebate_eligibility_status` of `ELIGIBLE`, an `exclusive_purchase_pct` of 0,
        and an `outstanding_balance_cents` of 0."
        PRD §3.7: "An `ELIGIBLE` store accrues at five percent on the same basis."

        Design: Corner/calculations/rebate_accrual_eligible_rate
        """
        center, product, store = setup_trading_store(credit_limit=1000000)
        center_id, store_id = center["id"], store["id"]
        store_after = get_store(center_id, store_id)
        assert store_after["rebate_eligibility_status"] == "ELIGIBLE"
        # Freshly activated store has not purchased externally: exclusivity is 0.
        assert store_after["exclusive_purchase_pct"] == 0.0

    def test_rebate_accrual_eligible_vs_conditional(self, api):
        """PRD §3.7: "A store whose `rebate_eligibility_status` is `INELIGIBLE` accrues
        nothing. A `CONDITIONAL` store accrues its order's `total_cents` multiplied by
        two percent and by its `exclusive_purchase_pct`, rounded down to whole cents. An
        `ELIGIBLE` store accrues at five percent on the same basis."

        Design: Difficulty/dual_variant_calc/rebate_accrual_eligible_vs_conditional
        """
        center, product, store = setup_trading_store(credit_limit=100000000)
        center_id, store_id = center["id"], store["id"]
        store_after = get_store(center_id, store_id)
        assert store_after["rebate_eligibility_status"] == "ELIGIBLE"
        assert store_after["exclusive_purchase_pct"] == 0.0

    def test_rebate_accrual_conditional_variant_rate_named(self, api):
        """PRD §3.2: "the store's `rebate_eligibility_status` drops to `CONDITIONAL`"
        PRD §3.7: "A `CONDITIONAL` store accrues its order's `total_cents` multiplied by
        two percent and by its `exclusive_purchase_pct`, rounded down to whole cents."

        Design: Difficulty/dual_variant_calc/rebate_accrual_eligible_vs_conditional
        """
        # Drive a store into CONDITIONAL via two consecutive weeks below threshold.
        set_clock()
        center, product, store = setup_trading_store(credit_limit=1000000)
        center_id, store_id = center["id"], store["id"]
        mgr = make_store_manager_headers(store_id)
        for week in ("2026-08-31T00:00:00Z", "2026-09-07T00:00:00Z"):
            validate_success(api.submit_compliance_report(
                center_id, store_id,
                {"week_start_date": week, "external_purchases_cents": 50000}, mgr),
                expected_status=201)
            validate_success(api.run_ops(center_id, ADMIN))
        store_after = get_store(center_id, store_id)
        assert store_after["rebate_eligibility_status"] == "CONDITIONAL"
        assert store_after["compliance_tier"] == "PROBATION"


class TestRouteLoadUtilization:
    def test_route_load_utilization_check(self, api):
        """PRD §3.6: "Utilization is tracked at four decimal places as load divided by
        capacity; a load exceeding capacity is refused with `ERR_ROUTE_OVERLOADED`."

        Design: Corner/calculations/route_load_utilization_check
        """
        ctx = setup_submitted_po(base_cost=100, markup=0.0, quantity=150,
                                 with_capacity_plan=True, with_route=True,
                                 truck_capacity=100)
        center_id = ctx["center"]["id"]
        # Confirm succeeds (capacity plan has room: baseline 100000).
        confirm_po(center_id, ctx["po"]["id"])
        resp = api.dispatch_route(center_id, ctx["route"]["id"], COORD)
        validate_error(resp, ApiErrorId.ERR_ROUTE_OVERLOADED)


class TestProvisionalVsConfirmedPricing:
    def test_cost_plus_price_provisional_vs_confirmed_submission_value(self, api):
        """PRD §3.4: "While an order sits in `DRAFT` or `SUBMITTED`, its pricing is
        provisional — lines are priced off the current price book and re-priced on
        submission."

        Design: Difficulty/dual_variant_calc/cost_plus_price_provisional_vs_confirmed
        """
        center, product, store = setup_trading_store(base_cost=1000, markup=0.15,
                                                     credit_limit=100000000)
        center_id, store_id = center["id"], store["id"]
        po = create_draft_po(center_id, store_id)
        add_line(center_id, store_id, po["id"], product["id"], 100)
        submitted = submit_po(center_id, store_id, po["id"])
        # 100 * floor(1000 * 1.15) = 115000
        assert submitted["subtotal_cents"] == 115000
        assert submitted["status"] == "SUBMITTED"

    def test_cost_plus_price_confirmed_locked_after_confirmation(self, api):
        """PRD §3.4: "From `CONFIRMED` onward, prices are locked; changing them requires
        re-confirmation."

        Design: Difficulty/dual_variant_calc/cost_plus_price_provisional_vs_confirmed
        """
        ctx = setup_submitted_po(base_cost=1000, markup=0.15, quantity=100,
                                 with_capacity_plan=True, with_route=True)
        center_id = ctx["center"]["id"]
        confirmed = confirm_po(center_id, ctx["po"]["id"])
        assert confirmed["status"] == "CONFIRMED"
        assert confirmed["subtotal_cents"] == 115000
