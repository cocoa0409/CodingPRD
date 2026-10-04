"""Transitive cascades: the skip ripple through tier and totals, and the
reship-dispatch cascade into inventory and derived availability
(PRD §3.10, §3.11, §2.10)."""
import pytest

from test_helpers import (
    ADMIN,
    SUPPORT,
    api_client,
    assert_inventory_conservation,
    get_placement,
    get_plan,
    get_product,
    get_success_data,
    list_notifications,
    list_plan_lines,
    make_customer_headers,
    setup_customer_with_plan,
    setup_reported_claim,
    validate_success,
)


class TestSkipCascade:
    def test_skip_cascades_line_count_tier_repricing_total(self):
        """PRD §3.10: "Both actions ripple through the plan's arithmetic. Any
        change to the set of `SCHEDULED` lines recomputes `active_line_count`;
        the count change itself re-triggers tier selection; and the tier
        change re-triggers estimated per-line repricing and a fresh
        `estimated_total_cents`."

        Design: Difficulty/transitive_cascade/skip_cascades_line_count_tier_repricing_total
        """
        customer, product, placement, subs, plan = setup_customer_with_plan(
            num_subscriptions=3, price_cents=1000,
        )
        assert plan["estimated_total_cents"] == 2850
        line = list_plan_lines(plan, as_customer=customer)[0]
        headers = make_customer_headers(customer["id"])
        skipped = validate_success(
            api_client.skip_line(plan["id"], line["id"], headers))
        assert skipped["line_status"] == "SKIPPED"
        plan_after = get_plan(plan["id"], as_customer=customer)
        assert plan_after["active_line_count"] == 2
        assert plan_after["tier_discount_pct"] == pytest.approx(0.00)
        assert plan_after["estimated_total_cents"] == 2000

    def test_surviving_lines_reprice_from_950_to_1000(self):
        """PRD §3.10: "the tier change re-triggers estimated per-line
        repricing and a fresh `estimated_total_cents`."
        PRD §3.6: "With at least 5 such lines the tier is `0.10`; with at
        least 3 it is `0.05`; below that it is `0.00`."

        Design: Difficulty/transitive_cascade/skip_cascades_line_count_tier_repricing_total
        """
        customer, product, placement, subs, plan = setup_customer_with_plan(
            num_subscriptions=3, price_cents=1000,
        )
        line = list_plan_lines(plan, as_customer=customer)[0]
        headers = make_customer_headers(customer["id"])
        validate_success(api_client.skip_line(plan["id"], line["id"], headers))
        plan_after = get_plan(plan["id"], as_customer=customer)
        # Two surviving lines at the 0.00 tier contribute 1000 each.
        assert plan_after["estimated_total_cents"] == 2000
        assert plan_after["tier_discount_pct"] == pytest.approx(0.00)


class TestReshipDispatchCascade:
    def test_reship_dispatch_cascades_inventory_to_product_availability(self):
        """PRD §3.11: "Dispatching requires `PENDING` status and re-verifies
        stock — every reshipped line's placement must still hold at least the
        line's quantity on hand, or the dispatch is rejected with
        `ERR_INSUFFICIENT_INVENTORY` — then moves each line's quantity from
        `on_hand_units` into `shipped_units`, flips any emptied product's
        availability per §2.10, sends the customer a `RESHIP_DISPATCHED`
        notification, and moves the reshipment to `DISPATCHED`."
        PRD §2.10: "Any mutation that takes a placement's `on_hand_units` to
        zero therefore flips the product to `OUT_OF_STOCK` immediately,
        including a lock-time reservation that consumes the last unit."

        Design: Difficulty/transitive_cascade/reship_dispatch_cascades_inventory_to_product_availability
        """
        customer, product, placement, subs, plan, line, claim = (
            setup_reported_claim(units=2, quantity=1))
        reviewed = validate_success(api_client.review_damage_claim(
            claim["id"], {"decision": "APPROVE_RESHIP"}, SUPPORT))
        assert reviewed["claim_status"] == "APPROVED_RESHIP"
        line_after = get_success_data(api_client.get_plan_line(
            line["id"], make_customer_headers(customer["id"])))
        assert line_after["line_status"] == "RESHIPPED"
        reshipments = get_success_data(
            api_client.list_claim_reshipments(claim["id"], SUPPORT))
        assert len(reshipments) == 1
        dispatched = validate_success(
            api_client.dispatch_reshipment(reshipments[0]["id"], ADMIN))
        assert dispatched["reshipment_status"] == "DISPATCHED"
        placement_after = get_placement(placement["id"])
        assert placement_after["on_hand_units"] == 0
        assert placement_after["shipped_units"] == 2
        assert_inventory_conservation(placement_after)
        product_after = get_product(product["id"])
        assert product_after["availability_status"] == "OUT_OF_STOCK"

    def test_reship_dispatch_emits_notification_and_tracks_counters(self):
        """PRD §3.11: "sends the customer a `RESHIP_DISPATCHED` notification,
        and moves the reshipment to `DISPATCHED`."
        PRD §2.10: "At all times, `received_total_units` equals the sum of
        `on_hand_units`, `reserved_units`, and `shipped_units`."

        Design: Difficulty/transitive_cascade/reship_dispatch_cascades_inventory_to_product_availability
        """
        customer, product, placement, subs, plan, line, claim = (
            setup_reported_claim(units=2, quantity=1))
        validate_success(api_client.review_damage_claim(
            claim["id"], {"decision": "APPROVE_RESHIP"}, SUPPORT))
        reshipments = get_success_data(
            api_client.list_claim_reshipments(claim["id"], SUPPORT))
        validate_success(api_client.dispatch_reshipment(reshipments[0]["id"], ADMIN))
        notifications = list_notifications(customer, "RESHIP_DISPATCHED")
        assert len(notifications) == 1
        placement_after = get_placement(placement["id"])
        assert_inventory_conservation(placement_after)
