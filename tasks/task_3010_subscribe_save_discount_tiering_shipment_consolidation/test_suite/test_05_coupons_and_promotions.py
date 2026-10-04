"""Coupon attachment rules, stacking limits, discount order; promotions."""
from test_helpers import (
    ApiErrorId,
    attach_coupon,
    create_coupon,
    create_promotion_payload,
    create_stocked_product,
    get_plan,
    list_plan_lines,
    lock_plan,
    make_platform_admin_headers,
    set_clock,
    setup_customer_with_plan,
    validate_error,
    validate_success,
)

ADMIN = make_platform_admin_headers()


class TestCouponWindows:
    def test_coupon_attach_before_valid_from_returns_not_yet_valid(self, api):
        """PRD §3.7: "a plan whose `delivery_date` falls before the coupon's
        `valid_from` is rejected with `ERR_COUPON_NOT_YET_VALID`".

        Design: Corner/validations/coupon_attach_before_valid_from_returns_not_yet_valid
        """
        customer, product, placement, subs, plan = setup_customer_with_plan(
            num_subscriptions=1,
        )
        create_coupon(
            "FUTURE", flat_off_cents=100,
            valid_from="2026-09-15", valid_to="2026-09-30",
        )
        resp = attach_coupon(plan, customer, "FUTURE")
        validate_error(resp, ApiErrorId.ERR_COUPON_NOT_YET_VALID.value, 422)
        refreshed = get_plan(plan["id"], as_customer=customer)
        assert refreshed["applied_coupon_codes"] == []

    def test_temporal_error_beats_fiscal_error_on_coupon_attach(self, api):
        """PRD §2.5: "(9) temporal rules — start-date lead time, coupon windows,
        price-event monotonicity, promotion window overlap, offer expiry; and
        finally (10) money and stock gates — coupon minimum subtotal, stacking
        limits, and reshipment stock sufficiency. A later check is only reached
        when every earlier check passes."

        Design: Difficulty/priority_pair_validation_conflict/temporal_error_beats_fiscal_error_on_coupon_attach
        """
        customer, product, placement, subs, plan = setup_customer_with_plan(
            num_subscriptions=1,
        )
        create_coupon(
            "OLD", flat_off_cents=100, min_subtotal_cents=999999,
            valid_from="2026-08-01", valid_to="2026-08-31",
        )
        resp = attach_coupon(plan, customer, "OLD")
        validate_error(resp, ApiErrorId.ERR_COUPON_EXPIRED.value, 422)


class TestCouponMinSubtotal:
    def test_coupon_min_subtotal_exact_equality_qualifies(self, api):
        """PRD §3.7: "a plan whose estimated subtotal is below the coupon's
        `min_subtotal_cents` — the floor is inclusive — is rejected with
        `ERR_SUBTOTAL_BELOW_COUPON_MIN`."

        Design: Difficulty/boundary_precision_check/coupon_min_subtotal_exact_equality_qualifies
        """
        customer, product, placement, subs, plan = setup_customer_with_plan(
            num_subscriptions=1,
        )
        create_coupon("MIN1K", flat_off_cents=50, min_subtotal_cents=1000)
        resp = attach_coupon(plan, customer, "MIN1K")
        data = validate_success(resp)
        assert data["applied_coupon_codes"] == ["MIN1K"]
        assert data["estimated_total_cents"] == 950

    def test_coupon_min_subtotal_one_cent_below_rejected(self, api):
        """PRD §3.7: "a plan whose estimated subtotal is below the coupon's
        `min_subtotal_cents` — the floor is inclusive — is rejected with
        `ERR_SUBTOTAL_BELOW_COUPON_MIN`."

        Design: Difficulty/boundary_precision_check/coupon_min_subtotal_exact_equality_qualifies
        """
        customer, product, placement, subs, plan = setup_customer_with_plan(
            num_subscriptions=1, price_cents=333, quantity=3,
        )
        create_coupon("MIN1K", flat_off_cents=50, min_subtotal_cents=1000)
        resp = attach_coupon(plan, customer, "MIN1K")
        validate_error(resp, ApiErrorId.ERR_SUBTOTAL_BELOW_COUPON_MIN.value, 422)


class TestCouponStacking:
    def test_third_coupon_attach_returns_stack_limit(self, api):
        """PRD §3.7: "Stacking is limited: a plan carries at most 2 coupons, so
        attaching a third is rejected with `ERR_COUPON_STACK_LIMIT`".

        Design: Corner/validations/third_coupon_attach_returns_stack_limit
        """
        customer, product, placement, subs, plan = setup_customer_with_plan(
            num_subscriptions=1,
        )
        for code in ("A1", "A2", "A3"):
            create_coupon(code, flat_off_cents=10, stackable=True)
        validate_success(attach_coupon(plan, customer, "A1"))
        validate_success(attach_coupon(plan, customer, "A2"))
        resp = attach_coupon(plan, customer, "A3")
        validate_error(resp, ApiErrorId.ERR_COUPON_STACK_LIMIT.value, 422)
        refreshed = get_plan(plan["id"], as_customer=customer)
        assert refreshed["applied_coupon_codes"] == ["A1", "A2"]

    def test_second_coupon_after_non_stackable_returns_not_stackable(self, api):
        """PRD §3.7: "a non-stackable coupon may never be combined with any
        other coupon in either direction, so attaching a non-stackable coupon to
        a plan that already holds one, or attaching any coupon to a plan already
        holding a non-stackable one, is rejected with
        `ERR_COUPON_NOT_STACKABLE`."

        Design: Corner/validations/second_coupon_after_non_stackable_returns_not_stackable
        """
        customer, product, placement, subs, plan = setup_customer_with_plan(
            num_subscriptions=1,
        )
        create_coupon("SOLO", flat_off_cents=10, stackable=False)
        create_coupon("OTHER", flat_off_cents=10, stackable=True)
        validate_success(attach_coupon(plan, customer, "SOLO"))
        resp = attach_coupon(plan, customer, "OTHER")
        validate_error(resp, ApiErrorId.ERR_COUPON_NOT_STACKABLE.value, 422)
        refreshed = get_plan(plan["id"], as_customer=customer)
        assert refreshed["applied_coupon_codes"] == ["SOLO"]


class TestCouponApplicationOrder:
    def test_stacked_coupons_record_attach_order_and_gross(self, api):
        """PRD §3.7: "A successful attach appends the code to the plan's
        `applied_coupon_codes` and recomputes the estimated totals."
        PRD §3.7: "When charges are computed — at lock in the charged variant,
        at generation and refresh in the estimated variant — coupons apply to
        the gross line total in the order they were attached (ties broken by
        coupon creation time, earliest first)."

        Design: Corner/calculations/stacked_coupons_apply_in_attach_order_with_per_step_rounding
        """
        customer, product, placement, subs, plan = setup_customer_with_plan(
            num_subscriptions=3, price_cents=333, units=100,
        )
        create_coupon("PCT10", discount_type="PERCENT", percent_off=0.10,
                      stackable=True, flat_off_cents=None)
        create_coupon("FLAT50", flat_off_cents=50, stackable=True)
        validate_success(attach_coupon(plan, customer, "PCT10"))
        validate_success(attach_coupon(plan, customer, "FLAT50"))
        locked = lock_plan(plan, customer)
        assert locked["gross_line_total_cents"] == 948
        assert locked["applied_coupon_codes"] == ["PCT10", "FLAT50"]

    def test_stacked_coupons_apply_in_attach_order_with_per_step_rounding(self, api):
        """PRD §3.7: "A `PERCENT` step multiplies the running total by one minus
        `percent_off` and rounds the result half-up to whole cents before the
        next step; a `FLAT` step subtracts `flat_off_cents` but never takes the
        total below zero."

        Design: Corner/calculations/stacked_coupons_apply_in_attach_order_with_per_step_rounding
        """
        customer, product, placement, subs, plan = setup_customer_with_plan(
            num_subscriptions=3, price_cents=333, units=100,
        )
        create_coupon("PCT10", discount_type="PERCENT", percent_off=0.10,
                      stackable=True, flat_off_cents=None)
        create_coupon("FLAT50", flat_off_cents=50, stackable=True)
        validate_success(attach_coupon(plan, customer, "PCT10"))
        validate_success(attach_coupon(plan, customer, "FLAT50"))
        locked = lock_plan(plan, customer)
        # round_half_up(948 * 0.9) = 853; 853 - 50 = 803.
        assert locked["charged_total_cents"] == 803


class TestPromotions:
    def test_promotion_window_overlap_rejected(self, api):
        """PRD §3.8: "Two `ACTIVE` promotions for the same bonus product may not
        have overlapping half-open windows; a conflicting creation is rejected
        with `ERR_PROMOTION_WINDOW_OVERLAP` (HTTP 409)."

        Design: Difficulty/resource_temporal_overlap/promotion_windows_half_open_overlap_but_adjacency_allowed
        """
        set_clock()
        bonus, _ = create_stocked_product(units=0)
        validate_success(api.create_promotion(
            create_promotion_payload(
                bonus["id"], min_line_count=3,
                starts_on="2026-09-01", ends_on="2026-10-01",
            ), ADMIN,
        ), 201)
        resp = api.create_promotion(
            create_promotion_payload(
                bonus["id"], min_line_count=2,
                starts_on="2026-09-15", ends_on="2026-11-01",
            ), ADMIN,
        )
        validate_error(resp, ApiErrorId.ERR_PROMOTION_WINDOW_OVERLAP.value, 409)

    def test_promotion_window_adjacency_at_exclusive_bound_allowed(self, api):
        """PRD §3.8: "Two `ACTIVE` promotions for the same bonus product may not
        have overlapping half-open windows; a conflicting creation is rejected
        with `ERR_PROMOTION_WINDOW_OVERLAP` (HTTP 409)."
        PRD §3.8: "every `ACTIVE` promotion whose window contains the plan's
        `delivery_date` — the lower bound inclusive, the upper bound exclusive".

        Design: Difficulty/resource_temporal_overlap/promotion_windows_half_open_overlap_but_adjacency_allowed
        """
        set_clock()
        bonus, _ = create_stocked_product(units=0)
        validate_success(api.create_promotion(
            create_promotion_payload(
                bonus["id"], min_line_count=3,
                starts_on="2026-09-01", ends_on="2026-10-01",
            ), ADMIN,
        ), 201)
        resp = api.create_promotion(
            create_promotion_payload(
                bonus["id"], min_line_count=2,
                starts_on="2026-10-01", ends_on="2026-11-01",
            ), ADMIN,
        )
        data = validate_success(resp, expected_status=201)
        assert data["promotion_status"] == "ACTIVE"

    def test_promotion_bonus_line_added_after_tier_without_affecting_it(self, api):
        """PRD §3.8: "At lock, after tier and charges are fixed, every `ACTIVE`
        promotion whose window contains the plan's `delivery_date` — the lower
        bound inclusive, the upper bound exclusive — is tested against the
        plan's final `active_line_count`: when the count is at least the
        promotion's `min_line_count` (the threshold inclusive), one bonus line
        is appended to the plan carrying the promotion's `bonus_product_id`,
        `is_bonus` true, `quantity` 1, `unit_price_cents` 0,
        `line_charged_cents` 0, `subscription_id` null, and `line_status`
        `SCHEDULED`. Bonus lines are excluded from the tier count and receive no
        discount, so they never change the outcome they qualified under."

        Design: Corner/calculations/promotion_bonus_line_added_after_tier_without_affecting_it
        """
        bonus, _ = create_stocked_product(price_cents=500, units=10)
        customer, product, placement, subs, plan = setup_customer_with_plan(
            num_subscriptions=3,
        )
        validate_success(api.create_promotion(
            create_promotion_payload(
                bonus["id"], min_line_count=3,
                starts_on="2026-09-01", ends_on="2026-10-01",
            ), ADMIN,
        ), 201)
        locked = lock_plan(plan, customer)
        lines = list_plan_lines(locked, as_customer=customer)
        bonus_lines = [line for line in lines if line["is_bonus"]]
        assert len(lines) == 4
        assert len(bonus_lines) == 1
        bonus_line = bonus_lines[0]
        assert bonus_line["product_id"] == bonus["id"]
        assert bonus_line["quantity"] == 1
        assert bonus_line["unit_price_cents"] == 0
        assert bonus_line["line_charged_cents"] == 0
        assert bonus_line["subscription_id"] is None
        assert bonus_line["line_status"] == "SCHEDULED"
        assert locked["active_line_count"] == 3
        assert locked["tier_discount_pct"] == 0.05
        assert locked["charged_total_cents"] == 2850
