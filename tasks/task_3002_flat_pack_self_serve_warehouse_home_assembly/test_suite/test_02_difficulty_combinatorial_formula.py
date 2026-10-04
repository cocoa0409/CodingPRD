"""Difficulty rule: combinatorial_formula — food discount rounding and the
multi-input delivery fee."""
from test_helpers import (
    create_booking,
    create_customer,
    create_delivery_slot,
    cust_headers,
    get_success_data,
    setup_article_with_stock,
    setup_delivery_paid_order,
    setup_paid_order,
    setup_store_and_customer,
    validate_success,
)


class TestFoodDiscountRoundedPerLineThenSummed:
    """Instance: food_discount_rounded_per_line_then_summed."""

    def test_two_115_cent_food_lines_discount_24_not_23(self, api):
        """PRD §3.3: "the order's `subtotal_cents` is the sum of line grosses
        and `discount_cents` the sum of the per-line discounts — the rounded
        per-line discounts are summed, never recomputed from the summed
        grosses, so two `FOOD` lines grossing 115 cents each yield 12 plus 12,
        that is 24 cents of discount, not the 23 a sum-then-round would
        produce."

        Design: Difficulty/combinatorial_formula/food_discount_rounded_per_line_then_summed
        """
        store, member = setup_store_and_customer(member=True)
        f1, _, _ = setup_article_with_stock(
            store, on_hand=10, price_cents=115, category="FOOD")
        f2, _, _ = setup_article_with_stock(
            store, on_hand=10, price_cents=115, category="FOOD")

        order, order_lines = setup_paid_order(member, store, [(f1, 1), (f2, 1)])

        assert order["status"] == "PAID"
        assert order["subtotal_cents"] == 230
        assert order["discount_cents"] == 24, (
            "per-line rounding: round_half_up(115 x 0.10) = 12 per line, "
            f"summed to 24 (sum-then-round would give 23); got {order['discount_cents']}"
        )
        assert order["total_cents"] == 206
        assert order["points_discount_cents"] == 0
        for line in order_lines:
            fetched = get_success_data(api.get_order_line(line["id"], cust_headers(member)))
            assert fetched["line_discount_cents"] == 12

    def test_single_food_line_discount_rounds_half_up(self, api):
        """PRD §3.3: "when the customer is an `ACTIVE` member and the
        article's `category` is `FOOD`, the line earns a `line_discount_cents`
        of 10 percent of its gross, rounded half-up per line; every other
        line's discount is 0."
        PRD §2.5: "per-line rounding, where each line's amount is rounded
        half-up before the rounded amounts are summed (order pricing and
        return refunds work this way)"

        Design: Difficulty/combinatorial_formula/food_discount_rounded_per_line_then_summed
        """
        store, member = setup_store_and_customer(member=True)
        food, _, _ = setup_article_with_stock(
            store, on_hand=10, price_cents=115, category="FOOD")
        order, order_lines = setup_paid_order(member, store, [(food, 1)])

        assert order["subtotal_cents"] == 115
        assert order["discount_cents"] == 12, (
            f"round_half_up(115 x 0.10) = round_half_up(11.5) = 12; got {order['discount_cents']}"
        )
        assert order["total_cents"] == 103


class TestDeliveryFeeTierZoneWeightAccessMembership:
    """Instance: delivery_fee_tier_zone_weight_access_membership."""

    def _heavy_article_and_slot(self, api, store):
        article, _, _ = setup_article_with_stock(
            store, on_hand=4, price_cents=5000, category="FURNITURE",
            pick_policy="FULL_SERVE", cartons=[(160, 0.5, 4)],
        )
        slot = create_delivery_slot(
            store["id"], zone="ZONE_B", capacity_weight_kg=500,
            capacity_volume_m3=10, service_date="2026-09-10",
        )
        return article, slot

    def test_non_member_tiered_fee_with_overage(self, api):
        """PRD §3.5: "The gross fee starts from a zone base of 4900 cents for
        `ZONE_A`, 7900 cents for `ZONE_B`, or 12900 cents for `ZONE_C`. A
        weight surcharge follows: nothing while the booking weighs at most 50
        kilograms; a flat 2500 cents once it exceeds 50 kilograms up to and
        including 150; and beyond 150 kilograms the flat 2500 plus 15
        additional cents per kilogram of overage, with any fractional overage
        rounded up to a whole kilogram."

        Design: Difficulty/combinatorial_formula/delivery_fee_tier_zone_weight_access_membership
        """
        store, non_member = setup_store_and_customer(member=False)
        article, slot = self._heavy_article_and_slot(api, store)

        order, _ = setup_delivery_paid_order(non_member, store, article, qty=1)
        booking = create_booking(
            non_member, order["id"], slot["id"],
            expected_slot_version=slot["version"],
            access_type="WALKUP_LOW", floor=2,
        )
        # 7900 base + 2500 tier-2 flat + ceil(160 - 150) x 15 = 10550
        assert booking["status"] == "CONFIRMED"
        assert booking["fee_cents"] == 10550, (
            f"ZONE_B 160 kg WALKUP_LOW non-member fee must be 10550, got {booking['fee_cents']}"
        )
        slot_after = get_success_data(api.get_delivery_slot(slot["id"], cust_headers(non_member)))
        assert slot_after["used_weight_kg"] == 160

    def test_member_pays_eighty_percent_rounded_half_up_once(self, api):
        """PRD §3.5: "Finally, an `ACTIVE` family member pays 80 percent of
        the gross, the 20 percent discount applied with a single rounding
        half-up at the end; non-members pay the gross as computed."
        PRD §2.5: "terminal rounding, where a single rounding half-up happens
        once at the end of a calculation (the member delivery-fee discount and
        the no-receipt refund basis work this way)"

        Design: Difficulty/combinatorial_formula/delivery_fee_tier_zone_weight_access_membership
        """
        store, non_member = setup_store_and_customer(member=False)
        member = create_customer(member=True)
        article, slot = self._heavy_article_and_slot(api, store)

        order_n, _ = setup_delivery_paid_order(non_member, store, article, qty=1)
        booking_n = create_booking(
            non_member, order_n["id"], slot["id"],
            expected_slot_version=slot["version"],
            access_type="WALKUP_LOW", floor=2,
        )
        assert booking_n["fee_cents"] == 10550

        slot_now = get_success_data(api.get_delivery_slot(slot["id"], cust_headers(member)))
        order_m, _ = setup_delivery_paid_order(member, store, article, qty=1)
        booking_m = create_booking(
            member, order_m["id"], slot["id"],
            expected_slot_version=slot_now["version"],
            access_type="WALKUP_LOW", floor=2,
        )
        # round_half_up(10550 x 0.80) = 8440
        assert booking_m["status"] == "CONFIRMED"
        assert booking_m["fee_cents"] == 8440, (
            f"member fee must be round_half_up(10550 x 0.80) = 8440, got {booking_m['fee_cents']}"
        )
        slot_final = get_success_data(api.get_delivery_slot(slot["id"], cust_headers(member)))
        assert slot_final["used_weight_kg"] == 320
