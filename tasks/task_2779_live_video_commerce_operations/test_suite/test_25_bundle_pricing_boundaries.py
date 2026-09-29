"""Bundle-tier thresholds, the locked line price, and repricing on recovery."""

from test_helpers import (
    assert_cart_item,
    assert_order,
    build_scenario,
    checkout,
    hold_line,
    read_cart,
    read_line,
    read_offer,
    read_show,
    validate_success,
)

_ROBE = {"title": "Silk Wrap Robe", "base_price_cents": 4000, "unit_cost_cents": 1500, "on_hand_qty": 50}
_BELT = {
    "title": "Obi Belt",
    "base_price_cents": 4000,
    "unit_cost_cents": 1200,
    "on_hand_qty": 50,
    "evidence_ref": "LAB-91",
}

_WINDOW = {
    "window_start_at": "2026-08-10T18:00:00Z",
    "window_end_at": "2026-08-10T19:00:00Z",
}


def _two_offer_show(price_a, max_qty_a, price_b, max_qty_b, num_carts=2):
    """A LIVE show selling two different products at two flash prices."""
    return build_scenario(
        num_viewers=2,
        products=[dict(_ROBE), dict(_BELT)],
        slots=[
            {
                "product_index": 0,
                "slot_sequence": 1,
                "planned_start_at": "2026-08-10T18:05:00Z",
                "planned_end_at": "2026-08-10T18:35:00Z",
                "planned_qty": 20,
            },
            {
                "product_index": 1,
                "slot_sequence": 2,
                "planned_start_at": "2026-08-10T18:40:00Z",
                "planned_end_at": "2026-08-10T19:00:00Z",
                "planned_qty": 20,
            },
        ],
        offers=[
            dict(_WINDOW, slot_index=0, offer_price_cents=price_a, max_qty=max_qty_a),
            dict(_WINDOW, slot_index=1, offer_price_cents=price_b, max_qty=max_qty_b),
        ],
        take_live=True,
        activate=True,
        num_carts=num_carts,
    )


def test_a_basket_of_exactly_fifty_dollars_earns_the_lower_bundle_tier(api):
    """Fifty dollars of undiscounted flash pricing is enough to earn the five
    percent bundle: the shopper pays 23.75 a unit and the order carries flat
    shipping.

    PRD 3.6: "A subtotal of at least 150 dollars takes the upper tier of `0.10`;
    otherwise a subtotal of at least 50 dollars takes the lower tier of `0.05`;
    otherwise the discount is `0.00`. Both comparisons are inclusive at the floor —
    a subtotal of exactly 50 dollars is in the lower tier"
    PRD 3.6: "The line's `effective_unit_price_cents` is the line's
    `offer_unit_price_cents` multiplied by one minus `bundle_discount_pct`, rounded
    half up to a whole cent."
    PRD 3.7: "`shipping_cents` is a flat 5.99 dollars, except that it is zero when
    `merchandise_cents` reaches at least 75 dollars"

    Design: Corner/calculations/bundle_tier_first_threshold_at_exactly_5000_cents
    """
    scenario = _two_offer_show(2500, 20, 2499, 20)
    line = hold_line(scenario, 2, cart_index=0, offer_index=0)

    cart = read_cart(scenario.carts[0]["id"], scenario.viewers[0]["id"])
    assert cart["pre_discount_subtotal_cents"] == 5000
    assert cart["bundle_discount_pct"] == 0.05, "exactly fifty dollars is in the tier"

    assert_cart_item(line)
    assert line["effective_unit_price_cents"] == 2375
    assert line["line_gross_cents"] == 4750
    assert line["line_tax_cents"] == 416, "8.75 percent of 4750 is 415.625, rounded up"

    order = checkout(scenario.carts[0]["id"], scenario.viewers[0]["id"])
    assert_order(order)
    assert order["merchandise_cents"] == 4750
    assert order["tax_cents"] == 416
    assert order["shipping_cents"] == 599, "the basket is short of the free-ship floor"
    assert order["total_cents"] == 5765


def test_a_basket_one_cent_short_of_fifty_dollars_earns_nothing(api):
    """One cent below the floor there is no bundle at all, so the cheaper flash
    price produces the dearer order.

    PRD 3.6: "otherwise a subtotal of at least 50 dollars takes the lower tier of
    `0.05`; otherwise the discount is `0.00`."
    PRD 3.7: "`tax_cents` is the sum, across those same lines, of each line's gross
    multiplied by the 8.75 percent tax rate and rounded half up **per line**"
    PRD 3.7: "`total_cents` is `merchandise_cents` plus `tax_cents` plus
    `shipping_cents`."

    Design: Corner/calculations/bundle_tier_first_threshold_at_exactly_5000_cents
    """
    scenario = _two_offer_show(2500, 20, 2499, 20)
    line = hold_line(scenario, 2, cart_index=1, offer_index=1)

    cart = read_cart(scenario.carts[1]["id"], scenario.viewers[1]["id"])
    assert cart["pre_discount_subtotal_cents"] == 4998
    assert cart["bundle_discount_pct"] == 0.0, "one cent short of the floor"

    assert line["effective_unit_price_cents"] == 2499, "no discount is applied"
    assert line["line_gross_cents"] == 4998
    assert line["line_tax_cents"] == 437, "8.75 percent of 4998 is 437.325"

    order = checkout(scenario.carts[1]["id"], scenario.viewers[1]["id"])
    assert order["merchandise_cents"] == 4998
    assert order["tax_cents"] == 437
    assert order["shipping_cents"] == 599
    assert order["total_cents"] == 6034


def test_a_basket_of_exactly_one_hundred_fifty_dollars_earns_the_upper_tier_and_free_shipping(api):
    """At exactly a hundred and fifty dollars the shopper reaches the ten percent
    bundle, and the resulting merchandise total also clears the free-shipping floor.

    PRD 3.6: "A subtotal of at least 150 dollars takes the upper tier of `0.10`" and
    "Both comparisons are inclusive at the floor — a subtotal of exactly 50 dollars
    is in the lower tier, and exactly 150 dollars is in the upper."
    PRD 3.6: "The line's `line_gross_cents` is `effective_unit_price_cents`
    multiplied by `qty`, computed from the already-rounded per-unit figure"
    PRD 3.7: "`shipping_cents` is a flat 5.99 dollars, except that it is zero when
    `merchandise_cents` reaches at least 75 dollars"

    Design: Corner/calculations/bundle_tier_second_threshold_at_exactly_15000_cents
    """
    scenario = _two_offer_show(3000, 20, 2999, 20)
    line = hold_line(scenario, 5, cart_index=0, offer_index=0)

    cart = read_cart(scenario.carts[0]["id"], scenario.viewers[0]["id"])
    assert cart["pre_discount_subtotal_cents"] == 15000
    assert cart["bundle_discount_pct"] == 0.10

    assert line["effective_unit_price_cents"] == 2700
    assert line["line_gross_cents"] == 13500
    assert line["line_tax_cents"] == 1181, "8.75 percent of 13500 is 1181.25"

    order = checkout(scenario.carts[0]["id"], scenario.viewers[0]["id"])
    assert order["merchandise_cents"] == 13500
    assert order["tax_cents"] == 1181
    assert order["shipping_cents"] == 0, "the merchandise total ships free"
    assert order["total_cents"] == 14681


def test_five_cents_below_the_upper_floor_costs_the_shopper_more_overall(api):
    """A flash price a cent cheaper can cost the shopper more: missing the ten
    percent bundle by five cents of subtotal leaves the order eight hundred and ten
    cents dearer than the pricier offer's.

    PRD 3.6: "A subtotal of at least 150 dollars takes the upper tier of `0.10`;
    otherwise a subtotal of at least 50 dollars takes the lower tier of `0.05`"
    PRD 3.6: "The line's `effective_unit_price_cents` is the line's
    `offer_unit_price_cents` multiplied by one minus `bundle_discount_pct`, rounded
    half up to a whole cent."
    PRD 3.6: "The tier is **never** re-derived from the discounted subtotal."

    Design: Corner/calculations/bundle_tier_second_threshold_at_exactly_15000_cents
    """
    scenario = _two_offer_show(3000, 20, 2999, 20)
    hold_line(scenario, 5, cart_index=0, offer_index=0)
    dearer_order = checkout(scenario.carts[0]["id"], scenario.viewers[0]["id"])

    line = hold_line(scenario, 5, cart_index=1, offer_index=1)
    cart = read_cart(scenario.carts[1]["id"], scenario.viewers[1]["id"])
    assert cart["pre_discount_subtotal_cents"] == 14995
    assert cart["bundle_discount_pct"] == 0.05, "five cents short of the upper tier"

    assert line["effective_unit_price_cents"] == 2849, (
        "2999 less five percent is 2849.05, which rounds half up to 2849"
    )
    assert line["line_gross_cents"] == 14245
    assert line["line_tax_cents"] == 1246, "8.75 percent of 14245 is 1246.4375"

    order = checkout(scenario.carts[1]["id"], scenario.viewers[1]["id"])
    assert order["merchandise_cents"] == 14245
    assert order["tax_cents"] == 1246
    assert order["shipping_cents"] == 0
    assert order["total_cents"] == 15491
    assert order["total_cents"] - dearer_order["total_cents"] == 810, (
        "the cheaper flash price yields the larger order because it misses the tier"
    )


def test_recovering_a_basket_reprices_the_surviving_line_at_the_smaller_tier(api):
    """Recovery is not a restoration of the old prices: a shopper who loses one of
    two lines while away gets the survivor re-priced at whatever tier the smaller
    basket earns, which here is none at all.

    PRD 3.7: "each line is re-priced as it is re-held: the line returns to state
    `HELD` with `released_reason` and `released_at` cleared, and its
    `effective_unit_price_cents`, `line_gross_cents` and `line_tax_cents` are
    re-locked at the **current** bundle tier using the same pinned four-step
    procedure of §3.6."
    PRD 3.7: "Because the subtotal that selects the tier counts only the lines
    already re-held plus the line being re-held, an early line can land in a lower
    tier than it originally enjoyed and a late line in a higher one"
    PRD 3.7: "A released line is recoverable when the offer it names is currently
    `ACTIVE`, that offer's `remaining_qty` is at least the line's `qty`, and the
    product's `available_qty` is at least the line's `qty`."
    PRD 3.7: "The cart's `recovered_count` is incremented by one, `abandoned_at` and
    `recovery_deadline_at` are cleared back to null, the show's
    `abandoned_cart_count` is decremented"

    Design: Corner/calculations/recovery_relock_reprices_the_surviving_line_at_the_current_tier
    """
    scenario = _two_offer_show(2000, 1, 3600, 5)
    cart_id = scenario.carts[0]["id"]

    line_a = hold_line(scenario, 1, cart_index=0, offer_index=0)
    line_b = hold_line(scenario, 1, cart_index=0, offer_index=1)
    assert line_a["effective_unit_price_cents"] == 2000, "a 20 dollar basket earns no tier"
    assert line_b["effective_unit_price_cents"] == 3420, "56 dollars held earns five percent"
    assert line_b["line_tax_cents"] == 299

    abandoned = validate_success(
        api.abandon_cart(cart_id, scenario.viewer_headers_for(0))
    )
    assert abandoned["status"] == "ABANDONED"
    assert read_line(line_a["id"])["released_reason"] == "CART_ABANDONED"
    assert read_line(line_b["id"])["released_reason"] == "CART_ABANDONED"
    offer_a = read_offer(scenario.offers[0]["id"])
    assert offer_a["status"] == "ACTIVE", "the walked-away unit reopens the offer"
    assert offer_a["remaining_qty"] == 1
    assert read_show(scenario.show_id)["abandoned_cart_count"] == 1

    rival = hold_line(scenario, 1, cart_index=1, offer_index=0)
    assert rival["state"] == "HELD"
    offer_a = read_offer(scenario.offers[0]["id"])
    assert offer_a["status"] == "EXHAUSTED", "the rival took the last unit"
    assert offer_a["remaining_qty"] == 0
    assert offer_a["held_qty"] == 1

    recovered = validate_success(api.recover_cart(cart_id, scenario.viewer_headers_for(0)))

    assert read_line(line_a["id"])["state"] == "RELEASED", (
        "the line whose offer is exhausted is left behind"
    )
    survivor = read_line(line_b["id"])
    assert survivor["state"] == "HELD"
    assert survivor["released_reason"] is None
    assert survivor["effective_unit_price_cents"] == 3600, (
        "re-held alone, the line earns no bundle at all"
    )
    assert survivor["line_gross_cents"] == 3600
    assert survivor["line_tax_cents"] == 315
    assert survivor["effective_unit_price_cents"] > 3420, (
        "the recovered price is strictly higher than the price it held before"
    )

    assert recovered["status"] == "OPEN"
    assert recovered["pre_discount_subtotal_cents"] == 3600
    assert recovered["bundle_discount_pct"] == 0.0
    assert recovered["recovered_count"] == 1
    assert recovered["abandoned_at"] is None
    assert recovered["recovery_deadline_at"] is None
    assert read_show(scenario.show_id)["abandoned_cart_count"] == 0
