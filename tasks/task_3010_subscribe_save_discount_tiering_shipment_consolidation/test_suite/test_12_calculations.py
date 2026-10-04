"""Calculation claims: stacked coupon order, the strict price-increase
threshold, promotion bonus lines, and forecast input filtering
(PRD §3.7, §3.6, §3.8, §3.12)."""
import pytest

from test_helpers import (
    ADMIN,
    api_client,
    attach_coupon,
    create_coupon,
    create_customer,
    create_promotion_payload,
    create_recompute_forecasts_payload,
    create_stocked_product,
    create_subscription,
    generate_plan_for,
    get_success_data,
    list_notifications,
    list_plan_lines,
    lock_plan,
    make_customer_headers,
    set_clock,
    setup_customer_with_plan,
    validate_success,
)


class TestStackedCouponOrder:
    def _setup(self):
        customer, product, placement, subs, plan = setup_customer_with_plan(
            num_subscriptions=3, price_cents=333, units=100,
        )
        create_coupon("PCT10", discount_type="PERCENT", percent_off=0.10,
                      stackable=True, flat_off_cents=None)
        create_coupon("FLAT50", discount_type="FLAT", flat_off_cents=50,
                      stackable=True)
        return customer, plan

    def test_stacked_coupons_apply_in_attach_order_with_per_step_rounding(self):
        """PRD §3.7: "coupons apply to the gross line total in the order they
        were attached (ties broken by coupon creation time, earliest first). A
        `PERCENT` step multiplies the running total by one minus `percent_off`
        and rounds the result half-up to whole cents before the next step; a
        `FLAT` step subtracts `flat_off_cents` but never takes the total below
        zero."

        Design: Corner/calculations/stacked_coupons_apply_in_attach_order_with_per_step_rounding
        """
        customer, plan = self._setup()
        validate_success(attach_coupon(plan, customer, "PCT10"))
        validate_success(attach_coupon(plan, customer, "FLAT50"))
        locked = lock_plan(plan, customer)
        assert locked["gross_line_total_cents"] == 948
        assert locked["applied_coupon_codes"] == ["PCT10", "FLAT50"]
        # round(948 * 0.9) == 853; 853 - 50 == 803 (reversed order: 808).
        assert locked["charged_total_cents"] == 803


class TestPriceIncreaseNoticeThreshold:
    def _setup(self):
        customer, product, placement, subs, plan = setup_customer_with_plan(
            num_subscriptions=1, price_cents=1000,
        )
        from test_helpers import add_price
        add_price(product["id"], price_cents=1100,
                  effective_from="2026-09-02T00:00:00Z")
        set_clock("2026-09-03T00:00:00Z")
        return customer, plan

    def test_price_increase_notice_threshold_is_strictly_greater(self):
        """PRD §3.6: "for every charged non-bonus line whose locked
        `unit_price_cents` is strictly greater than the round-half-up of the
        subscription's `subscribe_price_cents` multiplied by 1.10, the
        customer receives a `PRICE_INCREASE` notification; a locked price
        sitting exactly at 110 percent of the subscribe price does not
        notify."

        Design: Corner/calculations/price_increase_notice_threshold_is_strictly_greater
        """
        customer, plan = self._setup()
        locked = lock_plan(plan, customer)
        assert locked["charged_total_cents"] == 1100
        notifications = list_notifications(customer, "PRICE_INCREASE")
        assert notifications == []


class TestPromotionBonusLine:
    def _setup(self):
        customer, product, placement, subs, plan = setup_customer_with_plan(
            num_subscriptions=3, price_cents=1000,
        )
        bonus, _bplacement = create_stocked_product(price_cents=500, units=10)
        validate_success(api_client.create_promotion(
            create_promotion_payload(
                bonus["id"], min_line_count=3,
                starts_on="2026-09-01", ends_on="2026-10-01"),
            ADMIN), expected_status=201)
        return customer, plan, bonus

    def test_promotion_bonus_line_added_after_tier_without_affecting_it(self):
        """PRD §3.8: "At lock, after tier and charges are fixed, every
        `ACTIVE` promotion whose window contains the plan's `delivery_date` —
        the lower bound inclusive, the upper bound exclusive — is tested
        against the plan's final `active_line_count`: when the count is at
        least the promotion's `min_line_count` (the threshold inclusive), one
        bonus line is appended to the plan carrying the promotion's
        `bonus_product_id`, `is_bonus` true, `quantity` 1, `unit_price_cents`
        0, `line_charged_cents` 0, `subscription_id` null, and `line_status`
        `SCHEDULED`. Bonus lines are excluded from the tier count and receive
        no discount, so they never change the outcome they qualified under."

        Design: Corner/calculations/promotion_bonus_line_added_after_tier_without_affecting_it
        """
        customer, plan, bonus = self._setup()
        locked = lock_plan(plan, customer)
        lines = list_plan_lines(plan, as_customer=customer)
        assert len(lines) == 4
        bonus_lines = [ln for ln in lines if ln["is_bonus"]]
        assert len(bonus_lines) == 1
        bonus_line = bonus_lines[0]
        assert bonus_line["product_id"] == bonus["id"]
        assert bonus_line["quantity"] == 1
        assert bonus_line["unit_price_cents"] == 0
        assert bonus_line["line_charged_cents"] == 0
        assert locked["active_line_count"] == 3
        assert locked["tier_discount_pct"] == pytest.approx(0.05)
        assert locked["charged_total_cents"] == 2850


class TestForecastInputFiltering:
    def test_forecast_excludes_pending_cancel_and_cancelled_subscriptions(self):
        """PRD §3.12: "Subscriptions in `PENDING_CANCEL` or `CANCELLED` status
        are excluded from both figures."

        Design: Corner/calculations/forecast_excludes_pending_cancel_and_cancelled_subscriptions
        """
        from test_helpers import cancel_subscription_and_get_offer
        set_clock()
        customer = create_customer()
        product, _placement = create_stocked_product(price_cents=500, units=50)
        create_subscription(customer, product, quantity=4)
        cancelling = create_subscription(customer, product, quantity=7)
        cancel_subscription_and_get_offer(cancelling, customer)
        forecast = get_success_data(api_client.recompute_forecasts(
            create_recompute_forecasts_payload("US-WEST", "2026-09"), ADMIN))[0]
        assert forecast["committed_units"] == 4
        assert forecast["provisional_units"] == 4
