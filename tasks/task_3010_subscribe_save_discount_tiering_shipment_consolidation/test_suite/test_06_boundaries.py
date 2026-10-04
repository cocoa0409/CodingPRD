"""Boundary-precision probes: the inclusive tier-count boundary and the
inclusive coupon minimum-subtotal boundary (PRD §3.6, §3.7)."""
import pytest

from test_helpers import (
    ApiErrorId,
    attach_coupon,
    create_coupon,
    create_customer,
    create_stocked_product,
    create_subscription,
    generate_plan_for,
    get_plan,
    lock_plan,
    set_clock,
    setup_customer_with_plan,
    validate_error,
    validate_success,
)


class TestTierBoundaryTwoVsThree:
    def _two_customer_setup(self, count_a, count_b):
        set_clock()
        customer_a = create_customer()
        customer_b = create_customer()
        product, placement = create_stocked_product(price_cents=1000, units=100)
        for _ in range(count_a):
            create_subscription(customer_a, product)
        for _ in range(count_b):
            create_subscription(customer_b, product)
        plan_a = generate_plan_for(customer_a)
        plan_b = generate_plan_for(customer_b)
        return customer_a, plan_a, customer_b, plan_b

    def test_two_lines_earn_no_discount_three_lines_earn_five_percent(self):
        """PRD §3.6: "With at least 5 such lines the tier is `0.10`; with at
        least 3 it is `0.05`; below that it is `0.00`. Boundaries are
        inclusive — exactly 3 lines earns `0.05` and exactly 5 earns `0.10`."

        Design: Difficulty/boundary_precision_check/tier_boundary_two_vs_three_lines
        """
        customer_a, plan_a, customer_b, plan_b = self._two_customer_setup(2, 3)
        locked_a = lock_plan(plan_a, customer_a)
        locked_b = lock_plan(plan_b, customer_b)
        assert locked_a["active_line_count"] == 2
        assert locked_a["tier_discount_pct"] == pytest.approx(0.00)
        assert locked_a["charged_total_cents"] == 2000
        assert locked_b["active_line_count"] == 3
        assert locked_b["tier_discount_pct"] == pytest.approx(0.05)
        assert locked_b["charged_total_cents"] == 2850

    def test_boundary_is_inclusive_at_three(self):
        """PRD §3.6: "Boundaries are inclusive — exactly 3 lines earns `0.05`
        and exactly 5 earns `0.10`."

        Design: Difficulty/boundary_precision_check/tier_boundary_two_vs_three_lines
        """
        customer_a, plan_a, customer_b, plan_b = self._two_customer_setup(2, 3)
        locked_a = lock_plan(plan_a, customer_a)
        locked_b = lock_plan(plan_b, customer_b)
        assert locked_a["tier_discount_pct"] == pytest.approx(0.00)
        assert locked_b["tier_discount_pct"] == pytest.approx(0.05)


class TestCouponMinSubtotalBoundary:
    def _setup(self):
        set_clock()
        customer_a = create_customer()
        customer_b = create_customer()
        product_a, _ = create_stocked_product(price_cents=1000, units=10)
        product_b, _ = create_stocked_product(price_cents=333, units=10)
        create_subscription(customer_a, product_a, quantity=1)
        create_subscription(customer_b, product_b, quantity=3)
        plan_a = generate_plan_for(customer_a)
        plan_b = generate_plan_for(customer_b)
        create_coupon("MIN1K", discount_type="FLAT", flat_off_cents=50,
                      stackable=False, min_subtotal_cents=1000,
                      valid_from="2026-09-01", valid_to="2026-09-30")
        return customer_a, plan_a, customer_b, plan_b

    def test_exact_equality_qualifies_and_one_cent_below_fails(self):
        """PRD §3.7: "a plan whose estimated subtotal is below the coupon's
        `min_subtotal_cents` — the floor is inclusive — is rejected with
        `ERR_SUBTOTAL_BELOW_COUPON_MIN`."

        Design: Difficulty/boundary_precision_check/coupon_min_subtotal_exact_equality_qualifies
        """
        customer_a, plan_a, customer_b, plan_b = self._setup()
        resp_a = attach_coupon(plan_a, customer_a, "MIN1K")
        attached = validate_success(resp_a)
        assert attached["applied_coupon_codes"] == ["MIN1K"]
        assert attached["estimated_total_cents"] == 950
        resp_b = attach_coupon(plan_b, customer_b, "MIN1K")
        validate_error(resp_b, ApiErrorId.ERR_SUBTOTAL_BELOW_COUPON_MIN)

    def test_inclusive_floor_error_carries_422(self):
        """PRD §5: `ERR_SUBTOTAL_BELOW_COUPON_MIN` maps to 422 Unprocessable
        Entity.
        PRD §3.7: "a plan whose estimated subtotal is below the coupon's
        `min_subtotal_cents` — the floor is inclusive — is rejected with
        `ERR_SUBTOTAL_BELOW_COUPON_MIN`."

        Design: Difficulty/boundary_precision_check/coupon_min_subtotal_exact_equality_qualifies
        """
        customer_a, plan_a, customer_b, plan_b = self._setup()
        resp_b = attach_coupon(plan_b, customer_b, "MIN1K")
        assert resp_b.status_code == 422
        assert resp_b.json()["data"]["error_id"] == "ERR_SUBTOTAL_BELOW_COUPON_MIN"
