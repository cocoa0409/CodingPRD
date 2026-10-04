"""Cross-entity state dependencies: lock-time substitution through a second
product, and plan generation gated on customer and subscription state
(PRD §3.6, §3.5, §3.2)."""
from test_helpers import (
    ADMIN,
    api_client,
    create_customer,
    create_product,
    create_stocked_product,
    create_subscription,
    generate_plan_for,
    get_placement,
    get_subscription_by_id,
    get_success_data,
    list_plan_lines,
    lock_plan,
    make_customer_headers,
    set_clock,
    validate_paginated,
)


class TestLockSubstitution:
    def _setup(self):
        set_clock()
        customer = create_customer()
        substitute, sub_placement = create_stocked_product(price_cents=700,
                                                           units=10)
        original = create_product(substitute_product_id=substitute["id"])
        from test_helpers import add_price
        add_price(original["id"], price_cents=1000)
        # placement for the original with no stock received (stays empty)
        placement = get_success_data(api_client.create_inventory_placement(
            {"product_id": original["id"], "region": original["region"]}, ADMIN))
        create_subscription(customer, original)
        plan = generate_plan_for(customer)
        return customer, original, substitute, sub_placement, plan

    def test_lock_rewrites_line_to_in_stock_substitute(self):
        """PRD §3.6: "If it does not, the product's designated substitute is
        considered: when a `substitute_product_id` is set, the substitute is
        `IN_STOCK` in the region with enough on hand, and the substitute's
        price passes the step-3 cap check, the line's `product_id` is
        rewritten to the substitute and `was_substituted` becomes true."

        Design: Difficulty/cross_entity_state_dependency/lock_substitution_requires_substitute_product_in_stock
        """
        customer, original, substitute, sub_placement, plan = self._setup()
        locked = lock_plan(plan, customer)
        lines = list_plan_lines(plan, as_customer=customer)
        assert len(lines) == 1
        line = lines[0]
        assert line["product_id"] == substitute["id"]
        assert line["was_substituted"] is True
        assert line["unit_price_cents"] == 700
        assert locked["charged_total_cents"] == 700

    def test_substitution_reserves_on_the_substitutes_placement(self):
        """PRD §3.6: "Locking also reserves inventory: for every remaining
        `SCHEDULED` non-bonus line, the placement's `on_hand_units` decreases
        and its `reserved_units` increases by the line's `quantity`".

        Design: Difficulty/cross_entity_state_dependency/lock_substitution_requires_substitute_product_in_stock
        """
        customer, original, substitute, sub_placement, plan = self._setup()
        lock_plan(plan, customer)
        placement_after = get_placement(sub_placement["id"])
        assert placement_after["reserved_units"] == 1
        assert placement_after["on_hand_units"] == 9


class TestPlanGenerationExclusions:
    def _setup(self):
        set_clock()
        customer_x = create_customer()
        customer_y = create_customer()
        product, placement = create_stocked_product(price_cents=1000, units=50)
        included = create_subscription(customer_x, product)
        paused = create_subscription(customer_x, product)
        headers_x = make_customer_headers(customer_x["id"])
        get_success_data(api_client.pause_subscription(paused["id"], headers_x))
        create_subscription(customer_y, product)
        get_success_data(api_client.suspend_customer(customer_y["id"], ADMIN))
        return customer_x, customer_y, product, included, paused

    def test_paused_subscriptions_and_suspended_customers_are_excluded(self):
        """PRD §3.5: "For each customer whose `account_status` is `ACTIVE` and
        who does not already have a plan for that month, the system collects
        the customer's `ACTIVE` subscriptions whose `next_delivery_date` falls
        within the calendar month, both endpoints of the window inclusive."
        PRD §3.2: "Suspending an `ACTIVE` customer moves `account_status` to
        `SUSPENDED` and excludes the customer from all future plan-generation
        runs".

        Design: Difficulty/cross_entity_state_dependency/plan_generation_excludes_paused_subscriptions_and_suspended_customers
        """
        customer_x, customer_y, product, included, paused = self._setup()
        generated = get_success_data(api_client.generate_plans(
            {"delivery_month": "2026-09"}, ADMIN))
        assert len(generated) == 1
        assert generated[0]["customer_id"] == customer_x["id"]
        lines = list_plan_lines(generated[0], as_customer=customer_x)
        assert len(lines) == 1
        plans_y, _meta = validate_paginated(api_client.list_customer_plans(
            customer_y["id"], ADMIN))
        assert plans_y == []

    def test_included_subscription_advances_while_paused_one_does_not(self):
        """PRD §3.5: "Every subscription consolidated into the plan
        immediately has its `next_delivery_date` advanced by its cadence per
        the clamped arithmetic of §3.3."

        Design: Difficulty/cross_entity_state_dependency/plan_generation_excludes_paused_subscriptions_and_suspended_customers
        """
        customer_x, customer_y, product, included, paused = self._setup()
        get_success_data(api_client.generate_plans(
            {"delivery_month": "2026-09"}, ADMIN))
        included_after = get_subscription_by_id(included["id"], customer_x)
        paused_after = get_subscription_by_id(paused["id"], customer_x)
        assert included_after["next_delivery_date"] == "2026-10-10"
        assert paused_after["next_delivery_date"] == "2026-09-10"
