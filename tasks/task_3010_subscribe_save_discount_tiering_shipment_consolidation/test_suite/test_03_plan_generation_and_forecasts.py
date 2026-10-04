"""Monthly consolidation (generate-plans) and demand forecasts."""
from test_helpers import (
    ApiErrorId,
    create_customer,
    create_stocked_product,
    create_subscription,
    get_subscription_by_id,
    list_plan_lines,
    make_customer_headers,
    make_platform_admin_headers,
    set_clock,
    validate_paginated,
    validate_success,
)

ADMIN = make_platform_admin_headers()


class TestPlanGenerationEligibility:
    def test_paused_subscription_contributes_no_line(self, api):
        """PRD §3.5: "For each customer whose `account_status` is `ACTIVE` and
        who does not already have a plan for that month, the system collects the
        customer's `ACTIVE` subscriptions whose `next_delivery_date` falls
        within the calendar month, both endpoints of the window inclusive."
        PRD §3.4: "a paused subscription is excluded from future plan-generation
        runs and from the committed side of demand forecasts."

        Design: Difficulty/cross_entity_state_dependency/plan_generation_excludes_paused_subscriptions_and_suspended_customers
        """
        set_clock()
        customer = create_customer()
        product, _ = create_stocked_product()
        create_subscription(customer, product, quantity=1)
        paused = create_subscription(customer, product, quantity=1)
        validate_success(
            api.pause_subscription(paused["id"], make_customer_headers(customer["id"])),
        )
        resp = api.generate_plans({"delivery_month": "2026-09"}, ADMIN)
        plans = validate_success(resp, expected_status=201)
        assert len(plans) == 1
        plan = plans[0]
        assert plan["customer_id"] == customer["id"]
        lines = list_plan_lines(plan, as_customer=customer)
        assert len(lines) == 1

    def test_suspended_customer_gets_no_plan_and_paused_does_not_advance(self, api):
        """PRD §3.2: "Suspending an `ACTIVE` customer moves `account_status` to
        `SUSPENDED` and excludes the customer from all future plan-generation
        runs".
        PRD §3.5: "Every subscription consolidated into the plan immediately has
        its `next_delivery_date` advanced by its cadence per the clamped
        arithmetic of §3.3."

        Design: Difficulty/cross_entity_state_dependency/plan_generation_excludes_paused_subscriptions_and_suspended_customers
        """
        set_clock()
        active_customer = create_customer()
        suspended_customer = create_customer()
        product, _ = create_stocked_product()
        included = create_subscription(active_customer, product, quantity=1)
        paused = create_subscription(active_customer, product, quantity=1)
        validate_success(
            api.pause_subscription(paused["id"], make_customer_headers(active_customer["id"])),
        )
        create_subscription(suspended_customer, product, quantity=1)
        validate_success(api.suspend_customer(suspended_customer["id"], ADMIN))

        resp = api.generate_plans({"delivery_month": "2026-09"}, ADMIN)
        plans = validate_success(resp, expected_status=201)
        assert len(plans) == 1

        suspended_plans, _ = validate_paginated(
            api.list_customer_plans(suspended_customer["id"], ADMIN),
        )
        assert suspended_plans == []

        assert get_subscription_by_id(included["id"], active_customer)[
            "next_delivery_date"
        ] == "2026-10-10"
        assert get_subscription_by_id(paused["id"], active_customer)[
            "next_delivery_date"
        ] == "2026-09-10"


class TestDemandForecasts:
    def test_forecast_committed_sums_active_subscriptions(self, api):
        """PRD §3.12: "`committed_units` is the sum of `quantity` over `ACTIVE`
        subscriptions in scope — the figure used for inventory placement buys."

        Design: Difficulty/dual_variant_calc/forecast_committed_vs_provisional_half_weight_paused
        """
        set_clock()
        customer = create_customer()
        product, _ = create_stocked_product(price_cents=500)
        create_subscription(customer, product, quantity=4)
        create_subscription(customer, product, quantity=2)
        paused = create_subscription(customer, product, quantity=5)
        validate_success(
            api.pause_subscription(paused["id"], make_customer_headers(customer["id"])),
        )
        resp = api.recompute_forecasts(
            {"region": "US-WEST", "forecast_month": "2026-09"}, ADMIN,
        )
        forecasts = validate_success(resp)
        assert len(forecasts) == 1
        assert forecasts[0]["committed_units"] == 6

    def test_forecast_provisional_adds_floored_half_weight_paused(self, api):
        """PRD §3.12: "`provisional_units` is the planning view: the committed
        figure plus half of the summed quantity over `PAUSED` subscriptions in
        scope, with that half-weight contribution floored to a whole unit."

        Design: Difficulty/dual_variant_calc/forecast_committed_vs_provisional_half_weight_paused
        """
        set_clock()
        customer = create_customer()
        product, _ = create_stocked_product(price_cents=500)
        create_subscription(customer, product, quantity=4)
        create_subscription(customer, product, quantity=2)
        paused = create_subscription(customer, product, quantity=5)
        validate_success(
            api.pause_subscription(paused["id"], make_customer_headers(customer["id"])),
        )
        resp = api.recompute_forecasts(
            {"region": "US-WEST", "forecast_month": "2026-09"}, ADMIN,
        )
        forecasts = validate_success(resp)
        assert len(forecasts) == 1
        # 6 committed + floor(0.5 * 5) == 6 + 2
        assert forecasts[0]["provisional_units"] == 8

    def test_forecast_excludes_pending_cancel_and_cancelled_subscriptions(self, api):
        """PRD §3.12: "Subscriptions in `PENDING_CANCEL` or `CANCELLED` status
        are excluded from both figures."

        Design: Corner/calculations/forecast_excludes_pending_cancel_and_cancelled_subscriptions
        """
        set_clock()
        customer = create_customer()
        product, _ = create_stocked_product(price_cents=500)
        create_subscription(customer, product, quantity=4)
        pending = create_subscription(customer, product, quantity=7)
        validate_success(
            api.cancel_subscription(pending["id"], make_customer_headers(customer["id"])),
        )
        resp = api.recompute_forecasts(
            {"region": "US-WEST", "forecast_month": "2026-09"}, ADMIN,
        )
        forecasts = validate_success(resp)
        assert len(forecasts) == 1
        assert forecasts[0]["committed_units"] == 4
        assert forecasts[0]["provisional_units"] == 4
