"""Difficulty rule combinatorial_formula.

Two multi-step compositions whose intermediate ordering is observable: nested
per-line rounding before summation, and the six-step payout assembly whose
guarantee floor is applied to a tip-inclusive subtotal.
"""

from test_helpers import fixtures as fx
from test_helpers.assertions import (
    assert_fields,
    assert_money_is_integer,
    assert_one_decimal,
    payout_for_batch,
    read_batch,
    read_line,
    read_order,
)
from test_helpers.constants import CLOCK_0800, PAYOUT_PROVISIONAL
from test_helpers.test_users import (
    ADMIN_HEADERS,
    make_customer_headers,
    make_shopper_headers,
)


def _two_weighted_lines_world(api):
    """Order O2 with two PER_LB lines of the same 689-cent/lb item at 2.5 lb."""
    fx.set_clock(api, CLOCK_0800)
    retailer = fx.make_retailer(api, catalog_markup_pct=0.15)
    r1 = retailer["id"]
    i2 = fx.make_catalog_item_per_lb(
        api, r1, sku="SKU-LB-EBT", name="Ground Coffee Bulk",
        in_store_price_cents=599, is_ebt_eligible=True, estimated_weight_lb=2.5,
    )
    customer = fx.make_customer(api, display_name="Ravi Menon", card_last4="1881")
    shopper = fx.make_shopper(api, service_area_code="SF-01", vehicle_capacity_units=10)
    c2 = customer["id"]
    order = fx.make_draft_order(
        api, c2, r1,
        delivery_distance_mi=5.0,
        delivery_deadline="2026-08-01T11:00:00Z",
        ebt_requested=False,
        tip_amount_cents=0,
    )
    m1 = fx.add_line_per_lb(api, order["id"], c2, i2["id"], 2.5)
    m2 = fx.add_line_per_lb(api, order["id"], c2, i2["id"], 2.5)
    placed = fx.submit_order(api, order["id"], c2)
    return {
        "item": i2,
        "customer": customer,
        "shopper": shopper,
        "order": order,
        "placed": placed,
        "lines": (m1, m2),
    }


def test_estimate_rounds_each_weighted_line_before_the_lines_are_added(api):
    """PRD 2.6: "**Per-line rounding is pinned before summation.** ... that
    single line's product is rounded half up to a whole cent *first*, and only
    then are the lines added together. Summing unrounded products and rounding
    the total once is explicitly wrong".

    689 * 2.5 = 1722.5 rounds to 1723 per line, so the subtotal is 3446 while
    rounding 689 * 2.5 * 2 = 3445.0 once would give 3445. The ceiling follows as
    round(3446 * 1.15) + 399 + 0 = 4362.

    Design: Difficulty/combinatorial_formula/weighted_line_round_per_line_then_sum
    """
    world = _two_weighted_lines_world(api)
    placed = world["placed"]
    assert_money_is_integer(
        placed, "estimated_subtotal_cents", "authorization_ceiling_cents"
    )
    assert placed["estimated_subtotal_cents"] == 3446, (
        "expected 3446 from round-per-line-then-sum, got "
        f"{placed['estimated_subtotal_cents']} (3445 means the sum was rounded once)"
    )
    assert_fields(placed, authorization_ceiling_cents=4362)


def test_checkout_repeats_the_per_line_rounding_and_bills_the_card_alone(api):
    """PRD 3.7: "each member order's `captured_subtotal_cents` is set to the sum
    of `final_price_cents` over all of its lines" and "`card_captured_cents` is
    then the grand total minus `ebt_captured_cents` - the service fee and the tip
    always ride on the card".

    Both lines scan at exactly 2.5 lb, so each is priced at 1723 and the captured
    subtotal is 3446, not 3445; with `ebt_requested` false the whole
    3446 + 399 + 0 rides on the card.

    Design: Difficulty/combinatorial_formula/weighted_line_round_per_line_then_sum
    """
    world = _two_weighted_lines_world(api)
    shopper_id = world["shopper"]["id"]
    batch = fx.make_batch(
        api, service_area_code="SF-01",
        shop_window_start="2026-08-01T08:00:00Z",
        shop_window_end="2026-08-01T11:00:00Z",
        tier_access_floor="PROBATION",
    )
    fx.attach_order(api, batch["id"], world["order"]["id"])
    fx.dispatch(api, batch["id"])
    fx.claim(api, batch["id"], shopper_id)
    fx.start_shopping(api, batch["id"], shopper_id)
    m1, m2 = world["lines"]
    fx.pick_weighted(api, m1["id"], shopper_id, 2.5)
    fx.pick_weighted(api, m2["id"], shopper_id, 2.5)
    fx.checkout(api, batch["id"], shopper_id)

    shopper_headers = make_shopper_headers(shopper_id)
    for line in (m1, m2):
        stored = read_line(api, line["id"], shopper_headers)
        assert_fields(stored, final_price_cents=1723)

    order = read_order(api, world["order"]["id"], make_customer_headers(world["customer"]["id"]))
    assert order["captured_subtotal_cents"] == 3446, (
        "expected 3446 from round-per-line-then-sum, got "
        f"{order['captured_subtotal_cents']}"
    )
    assert_fields(order, card_captured_cents=3845, ebt_captured_cents=0)


def _guarantee_payout_world(api):
    """Batch B5: 20 units of a 0.5 lb item, tip 300, distance exactly 8.0 mi."""
    fx.set_clock(api, CLOCK_0800)
    retailer = fx.make_retailer(
        api, legal_name="Valley Grocers Inc", store_code="VG-03", catalog_markup_pct=0.15
    )
    r3 = retailer["id"]
    i5 = fx.make_catalog_item_each(
        api, r3, sku="SKU-SNACK", name="Granola Bar",
        in_store_price_cents=100, is_ebt_eligible=False, unit_weight_lb=0.5,
    )
    customer = fx.make_customer(api, display_name="Ana Whit", card_last4="7788")
    shopper = fx.make_shopper(
        api, display_name="Tess Nakamura", service_area_code="SF-03",
        vehicle_capacity_units=20,
    )
    c3 = customer["id"]
    s3 = shopper["id"]
    order = fx.make_draft_order(
        api, c3, r3,
        delivery_distance_mi=8.0,
        delivery_deadline="2026-08-01T11:00:00Z",
        ebt_requested=False,
        tip_amount_cents=300,
    )
    line = fx.add_line_each(api, order["id"], c3, i5["id"], 20)
    fx.submit_order(api, order["id"], c3)
    batch = fx.make_batch(
        api, service_area_code="SF-03",
        shop_window_start="2026-08-01T08:00:00Z",
        shop_window_end="2026-08-01T11:00:00Z",
        tier_access_floor="PROBATION",
    )
    fx.attach_order(api, batch["id"], order["id"])
    fx.dispatch(api, batch["id"])
    fx.claim(api, batch["id"], s3)
    fx.start_shopping(api, batch["id"], s3)
    fx.pick_each(api, line["id"], s3, 20)
    fx.checkout(api, batch["id"], s3)
    return {"batch": batch, "order": order, "line": line, "shopper": shopper}


def test_work_pay_components_are_computed_from_the_batch_composition(api):
    """PRD 3.8: "`base_pay_cents` is a flat 700 cents plus 25 cents for every
    unit in the batch's `total_units`", heavy pay pays "300 cents once it reaches
    50.0 pounds, otherwise 0", mileage "Subtract 8.0 miles from the batch's
    `total_distance_mi`; if the result is negative use 0.0 instead", and
    multi-store bonus "using 0 whenever `store_count` is 0 or 1".

    20 units at 0.5 lb each is 10.0 lb over 8.0 miles from one store, so
    base 700 + 500 = 1200 and every bonus is 0.

    Design: Difficulty/combinatorial_formula/payout_guarantee_topup_after_tip_protection_ordering
    """
    world = _guarantee_payout_world(api)
    shopper_id = world["shopper"]["id"]
    fx.deliver(api, world["batch"]["id"], shopper_id)

    batch = read_batch(api, world["batch"]["id"], ADMIN_HEADERS)
    assert_fields(batch, total_units=20, store_count=1)
    assert_one_decimal(batch["total_weight_lb"], 10.0, "total_weight_lb")
    assert_one_decimal(batch["total_distance_mi"], 8.0, "total_distance_mi")

    payout = payout_for_batch(api, world["batch"]["id"], ADMIN_HEADERS)
    assert_fields(
        payout,
        base_pay_cents=1200,
        heavy_pay_cents=0,
        mileage_bonus_cents=0,
        multi_store_bonus_cents=0,
    )


def test_guarantee_top_up_is_taken_after_tips_join_the_subtotal(api):
    """PRD 3.8: "Add the batch work pay, `tip_pass_through_cents`, and
    `tip_protection_cents` to form a subtotal. The guarantee floor is 80 cents
    multiplied by the batch's `total_units`. `guarantee_top_up_cents` is the
    guarantee floor minus that subtotal" and "Topping up from work pay alone and
    adding tips afterwards produces a different total for the same inputs and is
    wrong."

    Work pay 1200 + tip 300 + protection 0 = 1500 against a floor of 80 * 20 =
    1600, so the top-up is 100 and the total 1600; topping up 1200 to 1600 first
    and then adding the tip would read 1900.

    Design: Difficulty/combinatorial_formula/payout_guarantee_topup_after_tip_protection_ordering
    """
    world = _guarantee_payout_world(api)
    fx.deliver(api, world["batch"]["id"], world["shopper"]["id"])

    payout = payout_for_batch(api, world["batch"]["id"], ADMIN_HEADERS)
    assert_fields(
        payout,
        tip_pass_through_cents=300,
        tip_protection_cents=0,
        guarantee_top_up_cents=100,
        status=PAYOUT_PROVISIONAL,
    )
    assert payout["total_payout_cents"] == 1600, (
        "expected 1600 from a tip-inclusive guarantee subtotal, got "
        f"{payout['total_payout_cents']} (1900 means the floor was applied to work pay alone)"
    )
