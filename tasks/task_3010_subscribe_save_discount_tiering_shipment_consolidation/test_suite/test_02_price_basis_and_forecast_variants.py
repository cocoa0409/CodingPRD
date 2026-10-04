"""Dual-variant calculations: price-at-ship estimated vs final, and forecast
committed vs provisional (PRD §3.5, §3.6, §3.12)."""
from test_helpers import (
    ADMIN,
    add_price,
    api_client,
    create_customer,
    create_recompute_forecasts_payload,
    create_stocked_product,
    create_subscription,
    generate_plan_for,
    get_success_data,
    list_plan_lines,
    lock_plan,
    make_customer_headers,
    set_clock,
    setup_customer_with_plan,
)


class TestEstimatedVsChargedDivergence:
    def _setup_price_moved_plan(self):
        set_clock()
        customer = create_customer()
        product, placement = create_stocked_product(price_cents=1000, units=10)
        create_subscription(customer, product)
        plan = generate_plan_for(customer)
        add_price(product["id"], price_cents=1100,
                  effective_from="2026-09-02T00:00:00Z")
        set_clock("2026-09-03T00:00:00Z")
        return customer, plan

    def test_estimated_total_diverges_from_charged_total_after_price_move(self):
        """PRD §3.5: "Because the estimate uses prices effective at the
        generation instant while lock resolves prices effective at the lock
        instant, a price change landing between the two makes
        `estimated_total_cents` and `charged_total_cents` legitimately diverge
        for identical lines."

        Design: Difficulty/dual_variant_calc/plan_estimated_total_diverges_from_charged_total_after_price_move
        """
        customer, plan = self._setup_price_moved_plan()
        locked = lock_plan(plan, customer)
        assert locked["estimated_total_cents"] == 1000
        assert locked["charged_total_cents"] == 1100
        assert locked["gross_line_total_cents"] == 1100
        assert locked["estimated_total_cents"] != locked["charged_total_cents"]

    def test_lock_uses_price_effective_at_lock_instant(self):
        """PRD §3.6: "Each surviving line's `unit_price_cents` is resolved
        against the (possibly substituted) product's price history per §2.9,
        evaluated at the lock instant — the final variant of price
        resolution."

        Design: Difficulty/dual_variant_calc/plan_estimated_total_diverges_from_charged_total_after_price_move
        """
        customer, plan = self._setup_price_moved_plan()
        locked = lock_plan(plan, customer)
        lines = list_plan_lines(plan, as_customer=customer)
        assert len(lines) == 1
        assert lines[0]["unit_price_cents"] == 1100
        assert lines[0]["line_charged_cents"] == 1100
        assert locked["charged_total_cents"] == 1100


class TestForecastCommittedVsProvisional:
    def _setup_mixed_subscriptions(self):
        set_clock()
        customer = create_customer()
        product, placement = create_stocked_product(price_cents=500, units=50)
        create_subscription(customer, product, quantity=4)
        create_subscription(customer, product, quantity=2)
        paused = create_subscription(customer, product, quantity=5)
        headers = make_customer_headers(customer["id"])
        get_success_data(api_client.pause_subscription(paused["id"], headers))
        return customer, product

    def _recompute(self):
        return get_success_data(api_client.recompute_forecasts(
            create_recompute_forecasts_payload("US-WEST", "2026-09"), ADMIN))[0]

    def test_committed_sums_active_only_provisional_adds_half_weight_paused(self):
        """PRD §3.12: "`committed_units` is the sum of `quantity` over `ACTIVE`
        subscriptions in scope — the figure used for inventory placement buys.
        `provisional_units` is the planning view: the committed figure plus
        half of the summed quantity over `PAUSED` subscriptions in scope, with
        that half-weight contribution floored to a whole unit."

        Design: Difficulty/dual_variant_calc/forecast_committed_vs_provisional_half_weight_paused
        """
        customer, product = self._setup_mixed_subscriptions()
        forecast = self._recompute()
        assert forecast["committed_units"] == 6
        assert forecast["provisional_units"] == 8

    def test_paused_subscription_excluded_from_committed_variant(self):
        """PRD §3.4: "a paused subscription is excluded from future
        plan-generation runs and from the committed side of demand forecasts."
        PRD §3.12: "`provisional_units` is the planning view: the committed
        figure plus half of the summed quantity over `PAUSED` subscriptions in
        scope, with that half-weight contribution floored to a whole unit."

        Design: Difficulty/dual_variant_calc/forecast_committed_vs_provisional_half_weight_paused
        """
        customer, product = self._setup_mixed_subscriptions()
        forecast = self._recompute()
        # floor(0.5 * 5) == 2 joins the committed 6 for the provisional view.
        assert forecast["provisional_units"] - forecast["committed_units"] == 2
        assert forecast["committed_units"] == 6
