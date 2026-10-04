"""Tier selection, pinned per-line rounding, and the cap-skip cascade through
the lock pipeline (PRD §3.6)."""
import pytest

from test_helpers import (
    ADMIN,
    ApiErrorId,
    add_price,
    create_customer,
    create_stocked_product,
    create_subscription,
    generate_plan_for,
    get_plan,
    list_notifications,
    list_plan_lines,
    lock_plan,
    make_customer_headers,
    set_clock,
    setup_customer_with_plan,
    validate_success,
)


class TestTierDiscountSelection:
    def test_five_lines_earn_top_tier_and_charge_900_each(self):
        """PRD §3.6: "With at least 5 such lines the tier is `0.10`; with at
        least 3 it is `0.05`; below that it is `0.00`."
        PRD §3.6: "For each `SCHEDULED` non-bonus line, `line_charged_cents` is
        the line's `unit_price_cents` multiplied by its `quantity`, discounted
        by the tier fraction, rounded half-up to whole cents".

        Design: Difficulty/combinatorial_formula/tier_discount_selects_rate_by_active_line_count
        """
        customer, product, placement, subs, plan = setup_customer_with_plan(
            num_subscriptions=5, price_cents=1000, units=100,
        )
        locked = lock_plan(plan, customer)
        assert locked["active_line_count"] == 5
        assert locked["tier_discount_pct"] == pytest.approx(0.10)
        assert locked["gross_line_total_cents"] == 4500
        assert locked["charged_total_cents"] == 4500
        lines = list_plan_lines(plan, as_customer=customer)
        non_bonus = [ln for ln in lines if not ln["is_bonus"]]
        assert len(non_bonus) == 5
        for line in non_bonus:
            assert line["line_charged_cents"] == 900, (
                f"line {line['id']} charged {line['line_charged_cents']}, "
                "expected 900 = 1000 * (1 - 0.10)")

    def test_four_lines_would_select_mid_tier_instead(self):
        """PRD §3.6: "With at least 5 such lines the tier is `0.10`; with at
        least 3 it is `0.05`; below that it is `0.00`. Boundaries are
        inclusive — exactly 3 lines earns `0.05` and exactly 5 earns `0.10`."

        Design: Difficulty/combinatorial_formula/tier_discount_selects_rate_by_active_line_count
        """
        customer, product, placement, subs, plan = setup_customer_with_plan(
            num_subscriptions=4, price_cents=1000, units=100,
        )
        locked = lock_plan(plan, customer)
        assert locked["active_line_count"] == 4
        assert locked["tier_discount_pct"] == pytest.approx(0.05)
        assert locked["gross_line_total_cents"] == 3800
        assert locked["charged_total_cents"] == 3800


class TestPerLineRoundingOrder:
    def test_per_line_rounding_then_sum_316_each_948_total(self):
        """PRD §2.8: "The rounding order for plan charges is pinned: each line
        is rounded to whole cents first, and only then are the rounded line
        values summed. Computing the discount over an unrounded sum and
        rounding once at the end is forbidden."

        Design: Difficulty/combinatorial_formula/per_line_rounding_then_sum_beats_sum_then_round
        """
        customer, product, placement, subs, plan = setup_customer_with_plan(
            num_subscriptions=3, price_cents=333, units=100,
        )
        locked = lock_plan(plan, customer)
        assert locked["tier_discount_pct"] == pytest.approx(0.05)
        lines = list_plan_lines(plan, as_customer=customer)
        non_bonus = [ln for ln in lines if not ln["is_bonus"]]
        assert len(non_bonus) == 3
        for line in non_bonus:
            assert line["line_charged_cents"] == 316, (
                f"line {line['id']} charged {line['line_charged_cents']}, "
                "expected round_half_up(333 * 0.95) == 316")
        assert locked["gross_line_total_cents"] == 948
        assert locked["charged_total_cents"] == 948

    def test_forbidden_sum_then_round_would_yield_949(self):
        """PRD §2.8: "Computing the discount over an unrounded sum and
        rounding once at the end is forbidden." (The forbidden order would
        produce round(999 * 0.95) == 949 for three 333-cent lines at the 0.05
        tier; the pinned order yields 948.)

        Design: Difficulty/combinatorial_formula/per_line_rounding_then_sum_beats_sum_then_round
        """
        customer, product, placement, subs, plan = setup_customer_with_plan(
            num_subscriptions=3, price_cents=333, units=100,
        )
        locked = lock_plan(plan, customer)
        assert locked["gross_line_total_cents"] == 948, (
            "sum-then-round would yield 949; the pinned per-line order yields "
            "3 * round_half_up(333 * 0.95) == 948")
        assert locked["charged_total_cents"] != 949


class TestCapSkipCascade:
    def _setup_capped_plan(self):
        set_clock()
        customer = create_customer()
        product, placement = create_stocked_product(price_cents=1000, units=100)
        capped = create_subscription(customer, product, price_cap_cents=1050)
        for _ in range(4):
            create_subscription(customer, product)
        plan = generate_plan_for(customer)
        add_price(product["id"], price_cents=1200,
                  effective_from="2026-09-02T00:00:00Z")
        set_clock("2026-09-03T00:00:00Z")
        return customer, product, plan

    def test_cap_skip_drops_tier_and_reprices_surviving_lines(self):
        """PRD §3.6: "If the line's subscription carries a non-null
        `price_cap_cents` and the resolved `unit_price_cents` is strictly
        greater than the cap, the line moves to `AUTO_SKIPPED` with
        `skip_reason` `PRICE_CAP`, and the customer receives a
        `PRICE_CAP_SKIP` notification. The cap compares the pre-tier unit
        price, and a price exactly equal to the cap passes."
        PRD §3.10: "Any change to the set of `SCHEDULED` lines recomputes
        `active_line_count`; the count change itself re-triggers tier
        selection; and the tier change re-triggers estimated per-line
        repricing and a fresh `estimated_total_cents`."

        Design: Difficulty/combinatorial_formula/cap_skip_drops_tier_and_reprices_surviving_lines
        """
        customer, product, plan = self._setup_capped_plan()
        locked = lock_plan(plan, customer)
        lines = list_plan_lines(plan, as_customer=customer)
        skipped = [ln for ln in lines if ln["line_status"] == "AUTO_SKIPPED"]
        assert len(skipped) == 1
        assert skipped[0]["skip_reason"] == "PRICE_CAP"
        assert locked["active_line_count"] == 4
        assert locked["tier_discount_pct"] == pytest.approx(0.05)
        # Price-at-ship resolves unit_price at the lock instant (1200, effective
        # 2026-09-02); tier 0.05 gives round_half_up(1200 * 0.95) = 1140 per
        # surviving line, 4 * 1140 = 4560.
        assert locked["gross_line_total_cents"] == 4560
        assert locked["charged_total_cents"] == 4560

    def test_cap_skip_emits_price_cap_skip_notification(self):
        """PRD §3.6: "If the line's subscription carries a non-null
        `price_cap_cents` and the resolved `unit_price_cents` is strictly
        greater than the cap, the line moves to `AUTO_SKIPPED` with
        `skip_reason` `PRICE_CAP`, and the customer receives a
        `PRICE_CAP_SKIP` notification."

        Design: Difficulty/combinatorial_formula/cap_skip_drops_tier_and_reprices_surviving_lines
        """
        customer, product, plan = self._setup_capped_plan()
        lock_plan(plan, customer)
        notifications = list_notifications(customer, "PRICE_CAP_SKIP")
        assert len(notifications) == 1
        assert notifications[0]["notification_type"] == "PRICE_CAP_SKIP"
