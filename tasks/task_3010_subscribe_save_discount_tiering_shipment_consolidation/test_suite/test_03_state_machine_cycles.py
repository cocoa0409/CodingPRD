"""Cyclic state machines: the subscription cancel/accept loop and the plan
line skip/unskip loop (PRD §3.4, §3.10)."""
import pytest

from test_helpers import (
    ADMIN,
    ApiErrorId,
    api_client,
    cancel_subscription_and_get_offer,
    create_customer,
    create_stocked_product,
    create_subscription,
    generate_plan_for,
    get_customer_by_id,
    get_plan,
    get_subscription_by_id,
    get_success_data,
    list_plan_lines,
    make_customer_headers,
    set_clock,
    setup_customer_with_plan,
    validate_error,
    validate_success,
)


class TestSubscriptionCancelAcceptCycle:
    def test_offer_accept_returns_subscription_to_active_and_grants_credit(self):
        """PRD §3.4: "Accepting — which additionally requires the logical today
        to be on or before `expires_on` — moves the offer to `ACCEPTED`,
        returns the subscription to `ACTIVE`, and adds 500 cents to the
        customer's `credit_balance_cents`."

        Design: Difficulty/non_linear_state_machine/subscription_cancel_offer_accept_cycle_returns_to_active
        """
        set_clock()
        customer = create_customer()
        product, _placement = create_stocked_product()
        sub = create_subscription(customer, product)
        offer = cancel_subscription_and_get_offer(sub, customer)
        headers = make_customer_headers(customer["id"])
        accepted = validate_success(
            api_client.accept_retention_offer(offer["id"], headers))
        assert accepted["offer_status"] == "ACCEPTED"
        refreshed_sub = get_subscription_by_id(sub["id"], customer)
        assert refreshed_sub["status"] == "ACTIVE"
        refreshed_customer = get_customer_by_id(customer["id"])
        assert refreshed_customer["credit_balance_cents"] == 500

    def test_cycle_is_reentrant_pause_succeeds_after_accept(self):
        """PRD §3.4: "A subscriber may pause an `ACTIVE` subscription, moving
        its `status` to `PAUSED`".
        PRD §3.4: "Accepting — which additionally requires the logical today
        to be on or before `expires_on` — moves the offer to `ACCEPTED`,
        returns the subscription to `ACTIVE`, and adds 500 cents to the
        customer's `credit_balance_cents`."

        Design: Difficulty/non_linear_state_machine/subscription_cancel_offer_accept_cycle_returns_to_active
        """
        set_clock()
        customer = create_customer()
        product, _placement = create_stocked_product()
        sub = create_subscription(customer, product)
        offer = cancel_subscription_and_get_offer(sub, customer)
        headers = make_customer_headers(customer["id"])
        validate_success(api_client.accept_retention_offer(offer["id"], headers))
        paused = validate_success(
            api_client.pause_subscription(sub["id"], headers))
        assert paused["status"] == "PAUSED"


class TestPlanLineSkipUnskipCycle:
    def test_skip_then_unskip_restores_tier_and_estimate(self):
        """PRD §3.10: "A customer-skip can be walked back: unskipping requires
        the line to be `SKIPPED` with `skip_reason` `CUSTOMER` and its
        subscription to be `ACTIVE` — a line whose subscription has since
        moved on is rejected with `ERR_SUBSCRIPTION_NOT_ACTIVE` — and returns
        the line to `SCHEDULED` with `skip_reason` cleared."
        PRD §3.10: "Any change to the set of `SCHEDULED` lines recomputes
        `active_line_count`; the count change itself re-triggers tier
        selection; and the tier change re-triggers estimated per-line
        repricing and a fresh `estimated_total_cents`."

        Design: Difficulty/non_linear_state_machine/planline_skip_unskip_cycle_restores_tier
        """
        customer, product, placement, subs, plan = setup_customer_with_plan(
            num_subscriptions=3, price_cents=1000,
        )
        headers = make_customer_headers(customer["id"])
        line = list_plan_lines(plan, as_customer=customer)[0]
        skipped = validate_success(
            api_client.skip_line(plan["id"], line["id"], headers))
        assert skipped["line_status"] == "SKIPPED"
        assert skipped["skip_reason"] == "CUSTOMER"
        plan_after_skip = get_plan(plan["id"], as_customer=customer)
        assert plan_after_skip["active_line_count"] == 2
        assert plan_after_skip["tier_discount_pct"] == pytest.approx(0.00)
        assert plan_after_skip["estimated_total_cents"] == 2000
        restored = validate_success(
            api_client.unskip_line(plan["id"], line["id"], headers))
        assert restored["line_status"] == "SCHEDULED"
        assert restored["skip_reason"] is None
        plan_after_unskip = get_plan(plan["id"], as_customer=customer)
        assert plan_after_unskip["active_line_count"] == 3
        assert plan_after_unskip["tier_discount_pct"] == pytest.approx(0.05)
        assert plan_after_unskip["estimated_total_cents"] == 2850

    def test_skip_drops_tier_and_unskip_restores_line_count(self):
        """PRD §3.10: "While a plan is `OPEN`, the customer may curate it line
        by line. Skipping a `SCHEDULED` non-bonus line moves it to `SKIPPED`
        with `skip_reason` `CUSTOMER`".
        PRD §3.6: "With at least 5 such lines the tier is `0.10`; with at
        least 3 it is `0.05`; below that it is `0.00`."

        Design: Difficulty/non_linear_state_machine/planline_skip_unskip_cycle_restores_tier
        """
        customer, product, placement, subs, plan = setup_customer_with_plan(
            num_subscriptions=3, price_cents=1000,
        )
        headers = make_customer_headers(customer["id"])
        line = list_plan_lines(plan, as_customer=customer)[0]
        validate_success(api_client.skip_line(plan["id"], line["id"], headers))
        plan_after_skip = get_plan(plan["id"], as_customer=customer)
        assert plan_after_skip["active_line_count"] == 2
        validate_success(api_client.unskip_line(plan["id"], line["id"], headers))
        plan_after_unskip = get_plan(plan["id"], as_customer=customer)
        assert plan_after_unskip["active_line_count"] == 3
