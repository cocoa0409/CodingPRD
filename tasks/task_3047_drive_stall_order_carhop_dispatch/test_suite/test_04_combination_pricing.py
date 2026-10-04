"""Combination pricing rounding order and offer evaluation order.

All prices here are exercised while the local check-in time is outside any
happy-hour window, so happy hour cannot contaminate the expected cents.
"""
from test_helpers import (
    TEST_DEFAULTS,
    add_line,
    assert_order,
    create_happy_hour_offer_payload,
    create_location,
    create_menu_item,
    create_offer_payload,
    create_service_target,
    create_stall,
    intercom_checkin,
    set_clock,
    TEST_USERS,
    validate_success,
)

ADMIN = TEST_USERS["platform_admin_headers"]
MANAGER = TEST_USERS["shift_manager_headers"]


def _setup_checkedin_order(code, item_price_cents, category="DRINK", half_price_eligible=False):
    """Location + target + one item + stall + DRAFT intercom order (no lines)."""
    set_clock(TEST_DEFAULTS["CLOCK_0800_LOCAL"])  # 08:00 local, outside 14:00-16:00
    location = create_location(code=code, stall_capacity=4)
    create_service_target(location["id"])
    item = create_menu_item(
        sku=f"DR-{code}", name=f"Drink {code}", category=category,
        base_price_cents=item_price_cents, half_price_eligible=half_price_eligible,
    )
    stall = create_stall(location["id"], stall_number=1)
    order = intercom_checkin(location["id"], stall["id"])
    return location, item, order


class TestCombinationPricingPerLineRoundingOrder:
    def test_per_line_rounding_pinned_before_sum_three_odd_priced_units(self, api):
        """PRD: "the second unit of each pair is discounted by half of its
        unit price, rounded half-up to the cent, and an unpaired leftover unit
        receives no discount. The discount for each half-price unit is folded
        back into its line's `extended_price_cents`, and the order's
        `subtotal_cents` is the sum of the adjusted extended prices — round
        per line first, then sum, always in that order."

        Three 155c drinks: the discounted unit loses round_half_up(155/2)=78,
        so the subtotal is 155 + (155-78) + 155 = 387.

        Design: Difficulty/combinatorial_formula/combination_pricing_per_line_rounding_order
        """
        location, item, order = _setup_checkedin_order("DIFF-COMBO1", 155)
        for _ in range(3):
            add_line(location["id"], order["id"], item["id"])

        read = validate_success(
            api.get_order(location["id"], order["id"], MANAGER), 200
        )
        assert_order(read)
        assert read["subtotal_cents"] == 387, (
            f"expected 387 (155 + 77 + 155), got {read['subtotal_cents']}"
        )

    def test_per_line_rounding_four_odd_priced_units_two_pairs(self, api):
        """PRD: "the second unit of each pair is discounted by half of its
        unit price, rounded half-up to the cent, and an unpaired leftover unit
        receives no discount."

        Four 155c drinks make two pairs; each pair's second unit loses 78, so
        the subtotal is 155 + 77 + 155 + 77 = 464.

        Design: Difficulty/combinatorial_formula/combination_pricing_per_line_rounding_order
        """
        location, item, order = _setup_checkedin_order("DIFF-COMBO2", 155)
        for _ in range(4):
            add_line(location["id"], order["id"], item["id"])

        read = validate_success(
            api.get_order(location["id"], order["id"], MANAGER), 200
        )
        assert read["subtotal_cents"] == 464, (
            f"expected 464 (155 + 77 + 155 + 77), got {read['subtotal_cents']}"
        )


class TestProvisionalPricingOutsideHappyHour:
    def test_provisional_subtotal_applies_combo_but_no_happy_hour(self, api):
        """PRD: "While the order remains in `DRAFT` this provisional pricing
        is what a cart preview shows: combination pricing applied, but no
        offers, no happy hour, and `tax_cents` estimated as 0."

        Two 400c half-price-eligible drinks, with a happy-hour offer defined
        but NOT active at the 08:00-local check-in: the provisional subtotal is
        600 (combination only) and placing outside the window changes nothing.

        Design: Difficulty/dual_variant_calc/order_pricing_provisional_vs_placed_final_diverge_on_happy_hour
        """
        location, item, order = _setup_checkedin_order(
            "DIFF-HH1", 400, category="DRINK", half_price_eligible=True
        )
        validate_success(
            api.create_offer(location["id"], create_happy_hour_offer_payload(), ADMIN), 201
        )
        add_line(location["id"], order["id"], item["id"])
        add_line(location["id"], order["id"], item["id"])

        preview = validate_success(api.get_order(location["id"], order["id"], MANAGER), 200)
        assert preview["subtotal_cents"] == 600, (
            f"provisional subtotal must be 600, got {preview['subtotal_cents']}"
        )
        assert preview["offer_discount_cents"] == 0
        assert preview["tax_cents"] == 0

        placed = validate_success(
            api.place_order(location["id"], order["id"], {}, MANAGER), 200
        )
        assert placed["status"] == "PLACED"
        assert placed["subtotal_cents"] == 600, (
            f"placed subtotal outside the window must be 600, got {placed['subtotal_cents']}"
        )
        assert placed["offer_discount_cents"] == 0

    def test_provisional_pricing_of_slush_lines_also_combos(self, api):
        """PRD: "While the order remains in `DRAFT` this provisional pricing
        is what a cart preview shows: combination pricing applied, but no
        offers, no happy hour, and `tax_cents` estimated as 0."

        Two 400c slushes (also a combination-eligible category) price to 600
        in the cart preview even though a happy-hour offer exists, because the
        08:00-local check-in is outside its 14:00-16:00 window.

        Design: Difficulty/dual_variant_calc/order_pricing_provisional_vs_placed_final_diverge_on_happy_hour
        """
        location, item, order = _setup_checkedin_order(
            "DIFF-HH2", 400, category="SLUSH", half_price_eligible=True
        )
        validate_success(
            api.create_offer(location["id"], create_happy_hour_offer_payload(), ADMIN), 201
        )
        add_line(location["id"], order["id"], item["id"])
        add_line(location["id"], order["id"], item["id"])

        preview = validate_success(api.get_order(location["id"], order["id"], MANAGER), 200)
        assert preview["subtotal_cents"] == 600
        assert preview["offer_discount_cents"] == 0

        placed = validate_success(
            api.place_order(location["id"], order["id"], {}, MANAGER), 200
        )
        assert placed["subtotal_cents"] == 600
        assert placed["offer_discount_cents"] == 0
