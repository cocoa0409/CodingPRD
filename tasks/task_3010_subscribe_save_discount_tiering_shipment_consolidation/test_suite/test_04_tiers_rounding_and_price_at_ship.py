"""Tier selection, pinned rounding order, price-at-ship divergence, and caps."""
from test_helpers import (
    ApiErrorId,
    create_customer,
    create_price_event_payload,
    create_product_payload,
    create_stocked_product,
    create_subscription,
    get_plan,
    list_notifications,
    list_plan_lines,
    lock_plan,
    make_customer_headers,
    make_platform_admin_headers,
    set_clock,
    setup_customer_with_plan,
    validate_success,
)

ADMIN = make_platform_admin_headers()


class TestTierBoundaries:
    def test_tier_boundary_two_lines_earns_no_discount(self, api):
        """PRD §3.6: "With at least 5 such lines the tier is `0.10`; with at
        least 3 it is `0.05`; below that it is `0.00`."

        Design: Difficulty/boundary_precision_check/tier_boundary_two_vs_three_lines
        """
        customer, product, placement, subs, plan = setup_customer_with_plan(
            num_subscriptions=2,
        )
        locked = lock_plan(plan, customer)
        assert locked["active_line_count"] == 2
        assert locked["tier_discount_pct"] == 0.00
        assert locked["charged_total_cents"] == 2000

    def test_tier_boundary_three_lines_earns_five_percent(self, api):
        """PRD §3.6: "Boundaries are inclusive — exactly 3 lines earns `0.05`
        and exactly 5 earns `0.10`."

        Design: Difficulty/boundary_precision_check/tier_boundary_two_vs_three_lines
        """
        customer, product, placement, subs, plan = setup_customer_with_plan(
            num_subscriptions=3,
        )
        locked = lock_plan(plan, customer)
        assert locked["active_line_count"] == 3
        assert locked["tier_discount_pct"] == 0.05
        assert locked["charged_total_cents"] == 2850


class TestTierAndCharges:
    def test_five_lines_select_ten_percent_tier(self, api):
        """PRD §3.6: "With at least 5 such lines the tier is `0.10`; with at
        least 3 it is `0.05`; below that it is `0.00`."

        Design: Difficulty/combinatorial_formula/tier_discount_selects_rate_by_active_line_count
        """
        customer, product, placement, subs, plan = setup_customer_with_plan(
            num_subscriptions=5, units=100,
        )
        locked = lock_plan(plan, customer)
        assert locked["active_line_count"] == 5
        assert locked["tier_discount_pct"] == 0.10

    def test_five_lines_charge_900_each_totaling_4500(self, api):
        """PRD §3.6: "For each `SCHEDULED` non-bonus line, `line_charged_cents`
        is the line's `unit_price_cents` multiplied by its `quantity`,
        discounted by the tier fraction, rounded half-up to whole cents".

        Design: Difficulty/combinatorial_formula/tier_discount_selects_rate_by_active_line_count
        """
        customer, product, placement, subs, plan = setup_customer_with_plan(
            num_subscriptions=5, units=100,
        )
        locked = lock_plan(plan, customer)
        assert locked["gross_line_total_cents"] == 4500
        assert locked["charged_total_cents"] == 4500
        lines = list_plan_lines(locked, as_customer=customer)
        non_bonus = [line for line in lines if not line["is_bonus"]]
        assert len(non_bonus) == 5
        for line in non_bonus:
            assert line["line_charged_cents"] == 900

    def test_per_line_rounding_applies_before_summing(self, api):
        """PRD §2.8: "The rounding order for plan charges is pinned: each line
        is rounded to whole cents first, and only then are the rounded line
        values summed. Computing the discount over an unrounded sum and rounding
        once at the end is forbidden."

        Design: Difficulty/combinatorial_formula/per_line_rounding_then_sum_beats_sum_then_round
        """
        customer, product, placement, subs, plan = setup_customer_with_plan(
            num_subscriptions=3, price_cents=333, units=100,
        )
        locked = lock_plan(plan, customer)
        assert locked["tier_discount_pct"] == 0.05
        lines = list_plan_lines(locked, as_customer=customer)
        non_bonus = [line for line in lines if not line["is_bonus"]]
        assert len(non_bonus) == 3
        # round_half_up(333 * 1 * 0.95) == round_half_up(316.35) == 316 per line
        for line in non_bonus:
            assert line["line_charged_cents"] == 316

    def test_per_line_rounding_then_sum_beats_sum_then_round_total(self, api):
        """PRD §2.8: "The rounding order for plan charges is pinned: each line
        is rounded to whole cents first, and only then are the rounded line
        values summed. Computing the discount over an unrounded sum and rounding
        once at the end is forbidden."

        Design: Difficulty/combinatorial_formula/per_line_rounding_then_sum_beats_sum_then_round
        """
        customer, product, placement, subs, plan = setup_customer_with_plan(
            num_subscriptions=3, price_cents=333, units=100,
        )
        locked = lock_plan(plan, customer)
        # 316 * 3 == 948 (the forbidden sum-then-round would give 949)
        assert locked["gross_line_total_cents"] == 948
        assert locked["charged_total_cents"] == 948


class TestEstimatedVsCharged:
    def _setup_price_move(self, api):
        customer, product, placement, subs, plan = setup_customer_with_plan(
            num_subscriptions=1,
        )
        validate_success(api.create_price_event(
            product["id"],
            create_price_event_payload(1100, "2026-09-02T00:00:00Z"),
            ADMIN,
        ), 201)
        set_clock("2026-09-03T00:00:00Z")
        return customer, product, subs, plan

    def test_estimated_total_priced_at_generation_stays_1000(self, api):
        """PRD §3.5: "Because the estimate uses prices effective at the
        generation instant while lock resolves prices effective at the lock
        instant, a price change landing between the two makes
        `estimated_total_cents` and `charged_total_cents` legitimately diverge
        for identical lines."

        Design: Difficulty/dual_variant_calc/plan_estimated_total_diverges_from_charged_total_after_price_move
        """
        customer, product, subs, plan = self._setup_price_move(api)
        locked = lock_plan(plan, customer)
        assert locked["estimated_total_cents"] == 1000

    def test_charged_total_priced_at_lock_becomes_1100(self, api):
        """PRD §3.6: "Each surviving line's `unit_price_cents` is resolved
        against the (possibly substituted) product's price history per §2.9,
        evaluated at the lock instant — the final variant of price resolution."

        Design: Difficulty/dual_variant_calc/plan_estimated_total_diverges_from_charged_total_after_price_move
        """
        customer, product, subs, plan = self._setup_price_move(api)
        locked = lock_plan(plan, customer)
        assert locked["charged_total_cents"] == 1100
        assert locked["gross_line_total_cents"] == 1100
        assert locked["charged_total_cents"] != locked["estimated_total_cents"]


class TestPriceCapAutoSkip:
    def _setup_cap_scenario(self, api):
        customer, product, placement, subs, plan = setup_customer_with_plan(
            num_subscriptions=5,
            units=100,
            subscription_overrides_list=[{"price_cap_cents": 1050}] + [{}] * 4,
        )
        validate_success(api.create_price_event(
            product["id"],
            create_price_event_payload(1200, "2026-09-02T00:00:00Z"),
            ADMIN,
        ), 201)
        set_clock("2026-09-03T00:00:00Z")
        return customer, product, subs, plan

    def test_cap_skip_moves_line_to_auto_skipped_with_notification(self, api):
        """PRD §3.6: "If the line's subscription carries a non-null
        `price_cap_cents` and the resolved `unit_price_cents` is strictly
        greater than the cap, the line moves to `AUTO_SKIPPED` with
        `skip_reason` `PRICE_CAP`, and the customer receives a `PRICE_CAP_SKIP`
        notification."

        Design: Difficulty/combinatorial_formula/cap_skip_drops_tier_and_reprices_surviving_lines
        """
        customer, product, subs, plan = self._setup_cap_scenario(api)
        locked = lock_plan(plan, customer)
        lines = list_plan_lines(locked, as_customer=customer)
        auto_skipped = [
            line for line in lines if line["line_status"] == "AUTO_SKIPPED"
        ]
        assert len(auto_skipped) == 1
        assert auto_skipped[0]["skip_reason"] == "PRICE_CAP"
        notifications = list_notifications(customer, "PRICE_CAP_SKIP")
        assert len(notifications) == 1

    def test_cap_skip_drops_tier_and_reprices_surviving_lines(self, api):
        """PRD §3.6: "The cap compares the pre-tier unit price, and a price
        exactly equal to the cap passes."
        PRD §3.10: "Any change to the set of `SCHEDULED` lines recomputes
        `active_line_count`; the count change itself re-triggers tier selection;
        and the tier change re-triggers estimated per-line repricing and a fresh
        `estimated_total_cents`."

        Design: Difficulty/combinatorial_formula/cap_skip_drops_tier_and_reprices_surviving_lines
        """
        customer, product, subs, plan = self._setup_cap_scenario(api)
        locked = lock_plan(plan, customer)
        # Pre-tier price 1200 > cap 1050 skips one line: count 5 -> 4,
        # tier 0.10 -> 0.05, survivors reprice to round(1200*0.95) = 1140...
        # surviving lines priced 1200 with 0.05 tier: 4 * 1140 = 4560.
        assert locked["active_line_count"] == 4
        assert locked["tier_discount_pct"] == 0.05
        assert locked["gross_line_total_cents"] == 4560
        assert locked["charged_total_cents"] == 4560


class TestSubstitution:
    def _setup_substitution_scenario(self, api):
        set_clock()
        customer = create_customer()
        substitute, sub_placement = create_stocked_product(price_cents=700, units=10)
        original_payload = create_product_payload(substitute_product_id=substitute["id"])
        original = validate_success(
            api.create_product(original_payload, ADMIN), expected_status=201,
        )
        validate_success(api.create_price_event(
            original["id"],
            create_price_event_payload(1000, "2026-09-01T00:00:00Z"),
            ADMIN,
        ), 201)
        # Placement exists but is never stocked: on_hand stays 0.
        orig_placement = validate_success(api._request(
            "POST", "/sns/inventory-placements",
            {"product_id": original["id"], "region": "US-WEST"}, ADMIN,
        ), expected_status=201)
        sub = create_subscription(customer, original, quantity=1)
        plans = validate_success(
            api.generate_plans({"delivery_month": "2026-09"}, ADMIN), 201,
        )
        return customer, original, substitute, sub_placement, orig_placement, plans[0]

    def test_lock_substitution_rewrites_line_to_substitute(self, api):
        """PRD §3.6: "when a `substitute_product_id` is set, the substitute is
        `IN_STOCK` in the region with enough on hand, and the substitute's price
        passes the step-3 cap check, the line's `product_id` is rewritten to the
        substitute and `was_substituted` becomes true."

        Design: Difficulty/cross_entity_state_dependency/lock_substitution_requires_substitute_product_in_stock
        """
        (customer, original, substitute, sub_placement,
         orig_placement, plan) = self._setup_substitution_scenario(api)
        locked = lock_plan(plan, customer)
        lines = list_plan_lines(locked, as_customer=customer)
        assert len(lines) == 1
        assert lines[0]["product_id"] == substitute["id"]
        assert lines[0]["was_substituted"] is True

    def test_lock_substitution_prices_at_substitute_and_reserves_there(self, api):
        """PRD §3.6: "Each surviving line's `unit_price_cents` is resolved
        against the (possibly substituted) product's price history per §2.9,
        evaluated at the lock instant — the final variant of price resolution."
        PRD §3.6: "Locking also reserves inventory: for every remaining
        `SCHEDULED` non-bonus line, the placement's `on_hand_units` decreases
        and its `reserved_units` increases by the line's `quantity`".

        Design: Difficulty/cross_entity_state_dependency/lock_substitution_requires_substitute_product_in_stock
        """
        (customer, original, substitute, sub_placement,
         orig_placement, plan) = self._setup_substitution_scenario(api)
        locked = lock_plan(plan, customer)
        lines = list_plan_lines(locked, as_customer=customer)
        assert lines[0]["unit_price_cents"] == 700
        assert locked["charged_total_cents"] == 700
        refreshed = validate_success(
            api.get_inventory_placement(sub_placement["id"], ADMIN),
        )
        assert refreshed["reserved_units"] == 1
        assert refreshed["on_hand_units"] == 9


class TestPriceIncreaseNotice:
    def test_price_increase_notice_threshold_is_strictly_greater(self, api):
        """PRD §3.6: "for every charged non-bonus line whose locked
        `unit_price_cents` is strictly greater than the round-half-up of the
        subscription's `subscribe_price_cents` multiplied by 1.10, the customer
        receives a `PRICE_INCREASE` notification; a locked price sitting exactly
        at 110 percent of the subscribe price does not notify."

        Design: Corner/calculations/price_increase_notice_threshold_is_strictly_greater
        """
        customer, product, placement, subs, plan = setup_customer_with_plan(
            num_subscriptions=1,
        )
        validate_success(api.create_price_event(
            product["id"],
            create_price_event_payload(1100, "2026-09-02T00:00:00Z"),
            ADMIN,
        ), 201)
        set_clock("2026-09-03T00:00:00Z")
        locked = lock_plan(plan, customer)
        assert locked["charged_total_cents"] == 1100
        notifications = list_notifications(customer, "PRICE_INCREASE")
        assert notifications == []
